from supernote_todo.notify import message_for, notify_new_tasks


def test_messages():
    assert message_for(["Fatura"]) == "Yeni görev: Fatura"
    assert message_for(["A", "B"]) == "2 yeni görev: A, B"
    assert message_for(["A", "B", "C", "D", "E"]) == "5 yeni görev: A, B, C ve 2 görev daha"


def test_osascript_call_is_quoted(tmp_path):
    calls = []
    notify_new_tasks(['Say "hi" \\ bye'], run=lambda cmd, **kw: calls.append(cmd),
                     notifier=tmp_path / "missing.app")
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


def test_notifier_applet_is_used_when_installed(tmp_path):
    app = tmp_path / "Supernote Bildirim.app"
    app.mkdir()
    message = tmp_path / "cfg" / "notification.txt"
    calls = []
    notify_new_tasks(["Fatura", "Kira"], run=lambda cmd, **kw: calls.append(cmd),
                     notifier=app, message_file=message)
    assert calls == [["open", "-g", str(app)]]
    assert message.read_text(encoding="utf-8") == "2 yeni görev: Fatura, Kira"


def test_falls_back_to_osascript_without_applet(tmp_path):
    calls = []
    notify_new_tasks(["A"], run=lambda cmd, **kw: calls.append(cmd),
                     notifier=tmp_path / "missing.app", message_file=tmp_path / "m.txt")
    assert calls[0][0] == "osascript"
