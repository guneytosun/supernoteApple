import plistlib
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
    notifier = tmp_path / "Applications" / "Supernote Bildirim.app"
    assert [c[2] for c in calls if c[0] == "osacompile"] == [str(app)]
    (swiftc,) = [c for c in calls if c[:2] == ["xcrun", "swiftc"]]
    assert swiftc[4] == str(notifier / "Contents/MacOS/SupernoteBildirim")
    assert swiftc[5].endswith("main.swift")
    assert ["codesign", "--force", "--sign", "-", str(notifier)] in calls
    with (notifier / "Contents/Info.plist").open("rb") as fh:
        info = plistlib.load(fh)
    assert info["CFBundleIdentifier"] == "com.supernote-todo.notifier"
    assert info["CFBundleExecutable"] == "SupernoteBildirim"
    assert info["SupernoteMessageFile"].endswith("notification.txt")
    assert info["LSUIElement"] is True


def test_notifier_compile_failure_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(macapp.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(macapp, "LAUNCH_AGENT", tmp_path / "none.plist")
    messages = []

    def run(cmd):
        if cmd[:2] == ["xcrun", "swiftc"]:
            return subprocess.CompletedProcess(cmd, 1, "", "no swiftc")
        return ok(cmd)

    macapp.install("/venv/bin/python", run=run, log=messages.append)
    assert any("Script Editor" in m for m in messages)
    assert not (tmp_path / "Applications" / "Supernote Bildirim.app").exists()


def test_swift_source_is_shipped():
    source = macapp.NOTIFIER_SOURCE.read_text(encoding="utf-8")
    assert "UNUserNotificationCenter" in source
    assert '"SupernoteMessageFile"' in source
    assert '"com.apple.reminders"' in source


def test_install_stops_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(macapp.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(macapp, "LAUNCH_AGENT", tmp_path / "none.plist")

    def run(cmd):
        if cmd[0] == "osacompile":
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        return ok(cmd)

    with pytest.raises(RuntimeError, match="boom"):
        macapp.install("/venv/bin/python", run=run, log=lambda _: None)
