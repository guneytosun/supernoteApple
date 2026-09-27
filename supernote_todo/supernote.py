"""Client for the Supernote Cloud To-Do API.

Ratta does not publish this API. The endpoints below are the ones the Supernote
Partner app uses and could change without notice. Notable quirks:

* The to-do routes live on viewer.supernote.com, not cloud.supernote.com.
* Lists are "schedule task groups", tasks are "schedule tasks", booleans are
  the strings "Y"/"N" and timestamps are epoch milliseconds.
* Without ``maxResults`` the listing endpoints silently return only the
  oldest 20 rows.
* ``completedTime`` is set on open tasks too; only ``status`` says whether a
  task is done ("needsAction" / "completed").
* Updating a task is a PUT of the whole row and requires ``lastModified``.
* Errors usually come back as HTTP 200 with ``success: false``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional

import requests

BASE_URL = "https://viewer.supernote.com/api"
MAX_RESULTS = 8000
USER_AGENT = "supernote-todo/0.1"


class SupernoteError(Exception):
    pass


class SupernoteAuthError(SupernoteError):
    pass


@dataclass
class SupernoteList:
    id: str
    title: str


@dataclass
class SupernoteTask:
    id: str
    list_id: Optional[str]
    title: str
    detail: str
    status: str  # "needsAction" | "completed"
    due: Optional[date]
    deleted: bool
    source: Optional[str]  # "Notebook.note, page 3" for tasks written in a note
    raw: dict

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def is_yes(value: object) -> bool:
    return str(value or "").strip().upper() == "Y"


def epoch_ms_to_date(value: object) -> Optional[date]:
    """Supernote stores due dates as an instant; read it in the local timezone.

    A due date picked on the tablet is local midnight, so converting in UTC
    would move it to the previous day for anyone east of Greenwich.
    """
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000).date()
    except (OverflowError, OSError, ValueError):
        return None


def now_ms() -> int:
    return int(time.time() * 1000)


def password_digest(password: str, random_code: str) -> str:
    """sha256(md5_hex(password) + server nonce), as the Partner app sends it."""
    md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    return hashlib.sha256((md5 + random_code).encode("utf-8")).hexdigest()


def decode_source(links: object) -> Optional[str]:
    """Tasks circled in a notebook carry base64 JSON pointing at the page."""
    if not isinstance(links, str) or not links.strip():
        return None
    try:
        data = json.loads(base64.b64decode(links + "=" * (-len(links) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("filePath"):
        return None
    name = str(data["filePath"]).rsplit("/", 1)[-1]
    page = data.get("page")
    return f"{name}, sayfa {page}" if page else name


def token_expiry(token: str) -> Optional[datetime]:
    """Read the ``exp`` claim out of the session JWT, if there is one."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = float(claims["exp"])
    except (ValueError, TypeError, KeyError):
        return None
    if exp > 1e11:  # milliseconds
        exp /= 1000
    return datetime.fromtimestamp(exp, timezone.utc)


def _needs_code(result: dict) -> bool:
    """E1760 is "verification code required" for e-mail accounts; accept the
    wording too, in case phone accounts answer with another code."""
    message = str(result.get("errorMsg") or "").lower()
    return result.get("errorCode") == "E1760" or "verification" in message


def _explain(body: dict, fallback: str) -> str:
    """The server's own message, with its error code for troubleshooting."""
    message = body.get("errorMsg") or fallback
    code = body.get("errorCode")
    return f"{message} (kod: {code})" if code else message


def parse_task(row: dict) -> SupernoteTask:
    list_id = row.get("taskListId")
    return SupernoteTask(
        id=str(row.get("taskId") or "").strip(),
        list_id=str(list_id).strip() if list_id not in (None, "") else None,
        title=(row.get("title") or "").strip(),
        detail=(row.get("detail") or "").strip(),
        status="completed" if row.get("status") == "completed" else "needsAction",
        due=epoch_ms_to_date(row.get("dueTime")),
        deleted=is_yes(row.get("isDeleted")),
        source=decode_source(row.get("links")),
        raw=row,
    )


class SupernoteClient:
    def __init__(self, token: str = "", session: Optional[requests.Session] = None):
        self.token = token
        self.session = session or requests.Session()
        self.truncated = False

    # -- transport -----------------------------------------------------------

    def _call(self, method: str, path: str, payload: Optional[dict] = None,
              auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if auth:
            if not self.token:
                raise SupernoteAuthError(
                    "Supernote oturumu yok. Önce `supernote-todo login-supernote` çalıştırın."
                )
            headers["x-access-token"] = self.token
        try:
            resp = self.session.request(method, BASE_URL + path, json=payload,
                                        headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise SupernoteError(f"Supernote Cloud'a ulaşılamadı: {exc}") from exc
        if resp.status_code in (401, 403):
            raise SupernoteAuthError(
                "Supernote oturumu geçersiz veya süresi dolmuş (30 gün). "
                "`supernote-todo login-supernote` ile tekrar giriş yapın."
            )
        try:
            body = resp.json()
        except ValueError:
            raise SupernoteError(
                f"Supernote Cloud beklenmeyen bir yanıt verdi (HTTP {resp.status_code})."
            ) from None
        if not isinstance(body, dict):
            raise SupernoteError("Supernote Cloud beklenmeyen bir yanıt verdi.")
        if auth and body.get("success") is False:
            message = body.get("errorMsg") or f"{path} isteği reddedildi"
            if "token" in str(message).lower():
                raise SupernoteAuthError(f"Supernote oturumu reddedildi: {message}")
            raise SupernoteError(f"Supernote: {message}")
        return body

    # -- login ---------------------------------------------------------------

    def login(self, account: str, password: str,
              ask_code: Callable[[str], str],
              country_code: Optional[int] = None) -> str:
        """Sign in with an e-mail address or a phone number; return the token.

        ``country_code`` (e.g. 90) marks ``account`` as a phone number without
        it (e.g. "5321234567"). New devices must confirm with a code Supernote
        sends by e-mail or SMS; ``ask_code`` is called with where it went and
        must return what the user typed.

        The e-mail flow is the one the Partner app uses and has been confirmed
        against a live account. The phone flow follows the same endpoints with
        the fields the allenporter/supernote project documents for phones.
        """
        account = account.strip()
        phone = country_code is not None
        challenge = self._call("POST", "/official/user/query/random/code", {
            "countryCode": str(country_code) if phone else "1",
            "account": account,
        }, auth=False)
        random_code = challenge.get("randomCode")
        timestamp = challenge.get("timestamp")
        if not random_code:
            raise SupernoteAuthError(_explain(challenge, "Giriş başlatılamadı."))

        result = self._call("POST", "/official/user/account/login/new", {
            "countryCode": country_code if phone else 1,
            "account": account,
            "password": password_digest(password, random_code),
            "browser": "Chrome107",
            "equipment": "1",
            # "1" is what the Partner app sends for e-mail accounts too.
            "loginMethod": "1",
            "timestamp": timestamp,
            "language": "en",
        }, auth=False)
        if result.get("token"):
            self.token = result["token"]
            return self.token
        if not _needs_code(result):
            raise SupernoteAuthError(_explain(result, "Hesap bilgileri veya şifre hatalı."))

        # The code-sending endpoints are signed with a key hidden in a pre-auth
        # token: its last character indexes into its own dash-separated parts.
        signed = f"{country_code}{account}" if phone else account
        pre_token = self._call("POST", "/user/validcode/pre-auth",
                               {"account": signed}, auth=False).get("token") or ""
        try:
            key = pre_token.split("-")[int(pre_token[-1])]
        except (ValueError, IndexError):
            raise SupernoteError("Doğrulama kodu isteği tanınmayan bir biçimde döndü.") from None
        sign = hashlib.sha256(f"{signed}{key}".encode("utf-8")).hexdigest()

        if phone:
            sent = self._call("POST", "/user/sms/validcode/send", {
                "telephone": account,
                "timestamp": timestamp,
                "token": pre_token,
                "sign": sign,
                "nationcode": country_code,
            }, auth=False)
            if sent.get("success") is False:
                raise SupernoteError(_explain(sent, "SMS kodu gönderilemedi."))
            valid_code_key = sent.get("validCodeKey") or f"{country_code}-{account}_validCode"
            where = f"+{country_code} {account}"
        else:
            sent = self._call("POST", "/user/mail/validcode/send", {
                "email": account,
                "timestamp": timestamp,
                "token": pre_token,
                "sign": sign,
            }, auth=False)
            valid_code_key = sent.get("validCodeKey")
            if not valid_code_key:
                raise SupernoteError(_explain(sent, "Doğrulama kodu gönderilemedi."))
            where = account

        code = ask_code(where)
        payload = {
            "validCode": code.strip().upper(),
            "validCodeKey": valid_code_key,
            "timestamp": timestamp,
            "browser": "Chrome107",
            "equipment": "4",
        }
        if phone:
            payload.update(telephone=account, countryCode=country_code)
        else:
            payload["email"] = account
        result = self._call("POST", "/official/user/sms/login", payload, auth=False)
        if not result.get("token"):
            raise SupernoteAuthError(_explain(result, "Doğrulama kodu kabul edilmedi."))
        self.token = result["token"]
        return self.token

    # -- to-do ---------------------------------------------------------------

    @staticmethod
    def _is_truncated(body: dict) -> bool:
        token = str(body.get("nextPageToken") or "").strip()
        return token not in ("", "null", "undefined", "0")

    def lists(self) -> list[SupernoteList]:
        body = self._call("POST", "/file/schedule/group/all", {"maxResults": MAX_RESULTS})
        result = []
        for row in body.get("scheduleTaskGroup") or []:
            if is_yes(row.get("isDeleted")) or row.get("taskListId") in (None, ""):
                continue
            result.append(SupernoteList(
                id=str(row["taskListId"]).strip(),
                title=(row.get("title") or "").strip() or "Adsız liste",
            ))
        return result

    def tasks(self) -> list[SupernoteTask]:
        body = self._call("POST", "/file/schedule/task/all", {"maxResults": MAX_RESULTS})
        self.truncated = self._is_truncated(body)
        return [parse_task(row) for row in body.get("scheduleTask") or []
                if str(row.get("taskId") or "").strip()]

    def complete(self, task: SupernoteTask) -> None:
        """Mark a task done, sending back the server's own row otherwise intact."""
        row = dict(task.raw)
        row["status"] = "completed"
        row["completedTime"] = now_ms()
        row["lastModified"] = now_ms()
        self._call("PUT", "/file/schedule/task", row)
