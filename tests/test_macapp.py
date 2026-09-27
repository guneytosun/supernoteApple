import subprocess

import pytest

from supernote_todo import macapp


def ok(cmd):
    return subprocess.CompletedProcess(cmd, 0, "", "")


def test_applet_source_runs_watch_in_a_restart_loop(tmp_path):
    src = macapp.applet_source("/Users/me/.venvs/supernote-todo/bin/python",
                               tmp_path / "log file.log")
    assert src.startswith('do shell script "while true; do ')
    assert "/Users/me/.venvs/supernote-todo/bin/python -m supernote_todo watch" in src
    assert f"'{tmp_path}/log file.log'" in src  # spaces quoted for the shell
    assert src.count('"') == 2


def test_applet_source_rejects_quotes():
    with pytest.raises(ValueError):
        macapp.applet_source('/Users/a"b/python', macapp.log_path())


def test_install_builds_signs_and_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(macapp.Path, "home", lambda: tmp_path)
    agent = tmp_path / "agent.plist"
    agent.write_text("x")
    monkeypatch.setattr(macapp, "LAUNCH_AGENT", agent)
    calls = []

    def run(cmd):
        calls.append(list(cmd))
        return ok(cmd)

    app = macapp.install("/venv/bin/python", run=run, log=lambda _: None)
    names = [c[0] for c in calls]
    assert names.index("osacompile") < names.index("codesign") < names.index("open")
    assert ["launchctl", "unload", str(agent)] in calls and not agent.exists()
    keys = {c[2] for c in calls if c[0] == "plutil"}
    assert {"NSRemindersFullAccessUsageDescription", "LSUIElement", "CFBundleIdentifier"} <= keys
    assert app == tmp_path / "Applications" / "Supernote ToDo.app"
    compiled = [c[2] for c in calls if c[0] == "osacompile"]
    assert compiled == [str(app), str(tmp_path / "Applications" / "Supernote Bildirim.app")]
    ids = [c[4] for c in calls if c[0] == "plutil" and c[2] == "CFBundleIdentifier"]
    assert ids == ["com.supernote-todo.agent", "com.supernote-todo.notifier"]


def test_notifier_source_opens_reminders_when_clicked(tmp_path):
    src = macapp.notifier_source(tmp_path / "notification.txt")
    assert src.isascii()
    assert 'tell application "Reminders" to activate' in src
    assert "display notification msg" in src


def test_install_stops_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(macapp.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(macapp, "LAUNCH_AGENT", tmp_path / "none.plist")

    def run(cmd):
        if cmd[0] == "osacompile":
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        return ok(cmd)

    with pytest.raises(RuntimeError, match="boom"):
        macapp.install("/venv/bin/python", run=run, log=lambda _: None)
