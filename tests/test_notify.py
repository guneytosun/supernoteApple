from supernote_todo.notify import message_for, notify_new_tasks


def test_messages():
    assert message_for(["Fatura"]) == "Yeni görev: Fatura"
    assert message_for(["A", "B"]) == "2 yeni görev: A, B"
    assert message_for(["A", "B", "C", "D", "E"]) == "5 yeni görev: A, B, C ve 2 görev daha"


def test_osascript_call_is_quoted():
    calls = []
    notify_new_tasks(['Say "hi" \\ bye'], run=lambda cmd, **kw: calls.append(cmd))
    (cmd,) = calls
    assert cmd[:2] == ["osascript", "-e"]
    assert 'display notification "Yeni görev: Say \\"hi\\" \\\\ bye"' in cmd[2]


def test_nothing_new_means_no_notification():
    calls = []
    notify_new_tasks([], run=lambda cmd, **kw: calls.append(cmd))
    assert calls == []


def test_failures_are_swallowed():
    def boom(cmd, **kw):
        raise OSError("no osascript")
    notify_new_tasks(["A"], run=boom)
