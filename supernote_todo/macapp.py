"""Run `watch` in the background inside a tiny app of its own (macOS).

macOS grants Reminders access to an *app*. A process started by launchd has
none, so it is refused without ever being asked. Wrapping the watcher in a
minimal AppleScript applet gives macOS something to ask about: the applet
declares why it wants Reminders in its Info.plist, is signed ad hoc so the
grant sticks, and starts the watcher as its child, which inherits the grant.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

APP_NAME = "Supernote ToDo"
BUNDLE_ID = "com.supernote-todo.agent"
USAGE = "Supernote görevlerini Anımsatıcılar'a aktarmak için."
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents/com.supernote-todo.sync.plist"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def log_path() -> Path:
    return Path.home() / "Library/Logs/supernote-todo.log"


def applet_source(python: str, log: Path) -> str:
    """AppleScript that keeps the watcher running, restarting it if it exits."""
    for text in (python, str(log)):
        if '"' in text or "\\" in text or "'" in text:
            raise ValueError(f"Desteklenmeyen karakter içeren yol: {text}")
    shell = (f"while true; do PYTHONUNBUFFERED=1 {shlex.quote(python)} -m supernote_todo watch "
             f">> {shlex.quote(str(log))} 2>&1; sleep 60; done")
    return f'do shell script "{shell}"\n'


def _check(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{what} başarısız: {(result.stderr or result.stdout).strip()}")


def stop(run: Runner = _run) -> None:
    # The applet first, then its shell loop and the watcher (both carry this
    # text on their command line); otherwise the loop restarts the watcher.
    run(["pkill", "-f", f"{APP_NAME}.app/Contents/MacOS"])
    run(["pkill", "-f", "supernote_todo watch"])


def install(python: str = sys.executable, run: Runner = _run,
            log: Callable[[str], None] = print) -> Path:
    if sys.platform != "darwin" and run is _run:
        raise RuntimeError("Bu komut yalnızca macOS'ta çalışır.")
    app = app_path()
    app.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)

    if LAUNCH_AGENT.exists():
        # It can never get Reminders access, and would fight the app.
        run(["launchctl", "unload", str(LAUNCH_AGENT)])
        LAUNCH_AGENT.unlink()
        log(f"launchd görevi kaldırıldı: {LAUNCH_AGENT}")
    stop(run)

    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as fh:
        fh.write(applet_source(python, log_path()))
        source = fh.name
    _check(run(["osacompile", "-o", str(app), source]), "Uygulama oluşturma (osacompile)")

    plist = str(app / "Contents/Info.plist")
    for key, kind, value in [
        ("CFBundleIdentifier", "-string", BUNDLE_ID),
        ("CFBundleName", "-string", APP_NAME),
        ("NSRemindersUsageDescription", "-string", USAGE),
        ("NSRemindersFullAccessUsageDescription", "-string", USAGE),
        ("LSUIElement", "-bool", "true"),  # no Dock icon
    ]:
        _check(run(["plutil", "-replace", key, kind, value, plist]), f"Info.plist ({key})")
    _check(run(["codesign", "--force", "--deep", "--sign", "-", str(app)]), "İmzalama (codesign)")
    log(f"Uygulama oluşturuldu: {app}")

    login = run(["osascript", "-e",
                 'tell application "System Events" to make login item at end with properties '
                 f'{{path:"{app}", hidden:true, name:"{APP_NAME}"}}'])
    if login.returncode == 0:
        log("Giriş öğelerine eklendi: oturum açınca kendiliğinden başlayacak.")
    else:
        log("Giriş öğelerine eklenemedi. Elle ekleyin: Sistem Ayarları → Genel → "
            f"Giriş Öğeleri → + → {app}")

    _check(run(["open", str(app)]), "Uygulamayı başlatma")
    log("Başlatıldı. macOS Anımsatıcılar izni isterse izin verin.")
    log(f"Günlük: tail -f {log_path()}")
    return app


def uninstall(run: Runner = _run, log: Callable[[str], None] = print) -> None:
    stop(run)
    run(["osascript", "-e",
         f'tell application "System Events" to delete login item "{APP_NAME}"'])
    app = app_path()
    if app.exists():
        run(["rm", "-rf", str(app)])
    log(f"{APP_NAME} durduruldu ve kaldırıldı.")
