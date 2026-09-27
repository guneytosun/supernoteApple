import hashlib
import pytest

from supernote_todo.supernote import (BASE_URL, SupernoteAuthError, SupernoteClient,
                                      SupernoteError)


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, answers):
        self.answers = answers
        self.sent = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        path = url[len(BASE_URL):]
        self.sent.append((method, path, json, headers))
        answer = self.answers[path]
        return answer if isinstance(answer, Resp) else Resp(answer)


def test_login_with_emailed_code():
    session = FakeSession({
        "/official/user/query/random/code": {"randomCode": "nonce", "timestamp": 123},
        "/official/user/account/login/new": {"success": False, "errorCode": "E1760"},
        "/user/validcode/pre-auth": {"token": "aa-bb-cc-1"},
        "/user/mail/validcode/send": {"validCodeKey": "key"},
        "/official/user/sms/login": {"token": "jwt"},
    })
    client = SupernoteClient(session=session)
    assert client.login("me@example.com", "pw", lambda _: " abc123 ") == "jwt"
    final = session.sent[-1][2]
    assert final["validCode"] == "ABC123" and final["validCodeKey"] == "key"


def test_wrong_password():
    session = FakeSession({
        "/official/user/query/random/code": {"randomCode": "nonce", "timestamp": 1},
        "/official/user/account/login/new": {"success": False, "errorMsg": "bad"},
    })
    with pytest.raises(SupernoteAuthError):
        SupernoteClient(session=session).login("me@example.com", "pw", lambda _: "")


def test_listing_asks_for_everything_and_detects_truncation():
    session = FakeSession({"/file/schedule/task/all": {
        "success": True, "nextPageToken": "2",
        "scheduleTask": [{"taskId": "a", "title": "Bir", "status": "needsAction"}],
    }})
    client = SupernoteClient("tok", session=session)
    tasks = client.tasks()
    assert [t.title for t in tasks] == ["Bir"] and client.truncated
    method, _, payload, headers = session.sent[0]
    assert payload["maxResults"] >= 1000 and headers["x-access-token"] == "tok"


def test_errors():
    with pytest.raises(SupernoteAuthError):
        SupernoteClient("tok", session=FakeSession({"/file/schedule/group/all": Resp({}, 401)})).lists()
    with pytest.raises(SupernoteError):
        SupernoteClient("tok", session=FakeSession(
            {"/file/schedule/group/all": {"success": False, "errorMsg": "nope"}})).lists()
    with pytest.raises(SupernoteAuthError):
        SupernoteClient("").lists()


def test_complete_sends_full_row_with_last_modified():
    session = FakeSession({
        "/file/schedule/task/all": {"scheduleTask": [
            {"taskId": "a", "title": "Bir", "status": "needsAction", "sort": 7}]},
        "/file/schedule/task": {"success": True},
    })
    client = SupernoteClient("tok", session=session)
    client.complete(client.tasks()[0])
    method, path, payload, _ = session.sent[-1]
    assert method == "PUT" and payload["status"] == "completed"
    assert payload["sort"] == 7 and payload["lastModified"] > 0


def test_login_with_phone_and_sms_code():
    session = FakeSession({
        "/official/user/query/random/code": {"randomCode": "nonce", "timestamp": 123},
        "/official/user/account/login/new": {"success": False, "errorCode": "E1760"},
        "/user/validcode/pre-auth": {"token": "aa-bb-cc-1"},
        "/user/sms/validcode/send": {"success": True},
        "/official/user/sms/login": {"token": "jwt"},
    })
    asked = []
    client = SupernoteClient(session=session)
    token = client.login("5321234567", "pw", lambda where: asked.append(where) or "1234",
                         country_code=90)
    assert token == "jwt" and asked == ["+90 5321234567"]
    sent = {path: body for _, path, body, _ in session.sent}
    assert sent["/official/user/query/random/code"] == {"countryCode": "90", "account": "5321234567"}
    assert sent["/official/user/account/login/new"]["countryCode"] == 90
    assert sent["/user/validcode/pre-auth"] == {"account": "905321234567"}
    sms = sent["/user/sms/validcode/send"]
    assert sms["telephone"] == "5321234567" and sms["nationcode"] == 90
    assert sms["sign"] == hashlib.sha256(b"905321234567bb").hexdigest()
    final = sent["/official/user/sms/login"]
    assert final["telephone"] == "5321234567" and final["countryCode"] == 90
    assert final["validCodeKey"] == "90-5321234567_validCode"
    assert "email" not in final


def test_phone_login_without_verification():
    session = FakeSession({
        "/official/user/query/random/code": {"randomCode": "nonce", "timestamp": 1},
        "/official/user/account/login/new": {"token": "jwt"},
    })
    assert SupernoteClient(session=session).login(
        "5321234567", "pw", lambda _: "", country_code=90) == "jwt"


def test_error_message_carries_server_code():
    session = FakeSession({
        "/official/user/query/random/code": {"randomCode": "nonce", "timestamp": 1},
        "/official/user/account/login/new": {"success": False, "errorCode": "E0018",
                                             "errorMsg": "Account or password error"},
    })
    with pytest.raises(SupernoteAuthError, match="E0018"):
        SupernoteClient(session=session).login("5321234567", "pw", lambda _: "",
                                               country_code=90)
