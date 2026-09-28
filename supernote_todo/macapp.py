"""Run `watch` in the background inside a tiny app of its own (macOS).

macOS grants Reminders access to an *app*. A process started by launchd has
none, so it is refused without ever being asked. Wrapping the watcher in a
minimal AppleScript applet gives macOS something to ask about: the applet
declares why it wants Reminders in its Info.plist, is signed ad hoc so the
grant sticks, and starts the watcher as its child, which inherits the grant.
"""

from __future__ import annotations

import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from .config import home

APP_NAME = "Supernote ToDo"
BUNDLE_ID = "com.supernote-todo.agent"
#: A second, tiny app that only shows notifications. AppleScript's `display
#: notification` is attributed to Script Editor even from a saved applet (and a
#: click opens Script Editor), so this one is a small Swift program -- see
#: notifier.swift -- compiled on the Mac at install time.
NOTIFIER_NAME = "Supernote Bildirim"
NOTIFIER_EXE = "SupernoteBildirim"
NOTIFIER_SOURCE = Path(__file__).with_name("notifier.swift")
NOTIFIER_ID = "com.supernote-todo.notifier"
USAGE = "Supernote görevlerini Anımsatıcılar'a aktarmak için."
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents/com.supernote-todo.sync.plist"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def app_path() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def notifier_path() -> Path:
    return Path.home() / "Applications" / f"{NOTIFIER_NAME}.app"


def message_path() -> Path:
    """Where the watcher leaves the text for the notifier applet to show."""
    return home() / "notification.txt"


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


def _build_applet(app: Path, source_text: str, bundle_id: str, name: str,
                  extra: list, run: Runner) -> None:
    """Compile an AppleScript applet, give it an identity and sign it ad hoc
    (so permissions granted to it survive until it is rebuilt)."""
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as fh:
        fh.write(source_text)
        source = fh.name
    _check(run(["osacompile", "-o", str(app), source]), "Uygulama oluşturma (osacompile)")
    plist = str(app / "Contents/Info.plist")
    for key, kind, value in [
        ("CFBundleIdentifier", "-string", bundle_id),
        ("CFBundleName", "-string", name),
        ("LSUIElement", "-bool", "true"),  # no Dock icon
        *extra,
    ]:
        _check(run(["plutil", "-replace", key, kind, value, plist]), f"Info.plist ({key})")
    _check(run(["codesign", "--force", "--deep", "--sign", "-", str(app)]), "İmzalama (codesign)")


def notifier_info(message_file: Path) -> dict:
    return {
        "CFBundleIdentifier": NOTIFIER_ID,
        "CFBundleName": NOTIFIER_NAME,
        "CFBundleDisplayName": NOTIFIER_NAME,
        "CFBundleExecutable": NOTIFIER_EXE,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSUIElement": True,  # no Dock icon
        "SupernoteMessageFile": str(message_file),
    }


def _build_swift_notifier(app: Path, message_file: Path, run: Runner) -> None:
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents/MacOS").mkdir(parents=True)
    with (app / "Contents/Info.plist").open("wb") as fh:
        plistlib.dump(notifier_info(message_file), fh)
    # swiftc wants a file called main.swift for top-level code.
    build_dir = Path(tempfile.mkdtemp())
    source = build_dir / "main.swift"
    shutil.copyfile(NOTIFIER_SOURCE, source)
    _check(run(["xcrun", "swiftc", "-O", "-o", str(app / "Contents/MacOS" / NOTIFIER_EXE),
                str(source)]), "Bildirim uygulamasını derleme (swiftc)")
    _check(run(["codesign", "--force", "--sign", "-", str(app)]), "İmzalama (codesign)")


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

    _build_applet(app, applet_source(python, log_path()), BUNDLE_ID, APP_NAME, [
        ("NSRemindersUsageDescription", "-string", USAGE),
        ("NSRemindersFullAccessUsageDescription", "-string", USAGE),
    ], run)
    try:
        _build_swift_notifier(notifier_path(), message_path(), run)
    except RuntimeError as exc:
        # Notifications still work without it, only under Script Editor's name.
        log(f"Uyarı: bildirim uygulaması derlenemedi ({exc}); bildirimler "
            "Script Editor adıyla gösterilecek.")
        if notifier_path().exists():
            shutil.rmtree(notifier_path())
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
    for app in (app_path(), notifier_path()):
        if app.exists():
            run(["rm", "-rf", str(app)])
    log(f"{APP_NAME} durduruldu ve kaldırıldı.")
