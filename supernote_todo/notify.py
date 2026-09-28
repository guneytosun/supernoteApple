"""macOS notifications for tasks that just arrived from Supernote."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import macapp

TITLE = "Supernote"
#: How many titles to spell out before summarising the rest.
SHOWN = 3


def _quote(text: str) -> str:
    """An AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def message_for(titles: Sequence[str]) -> str:
    if len(titles) == 1:
        return f"Yeni görev: {titles[0]}"
    shown = ", ".join(titles[:SHOWN])
    rest = len(titles) - SHOWN
    more = f" ve {rest} görev daha" if rest > 0 else ""
    return f"{len(titles)} yeni görev: {shown}{more}"


def notify_new_tasks(titles: Sequence[str],
                     run: Callable[..., object] = subprocess.run,
                     notifier: Optional[Path] = None,
                     message_file: Optional[Path] = None) -> None:
    """Show one notification for the tasks just created. Never raises: a
    notification that cannot be shown must not stop a sync.

    Goes through the small notifier app `install-app` builds (notifier.swift),
    so it is shown as "Supernote Bildirim" and a click opens Reminders;
    without it, falls back to osascript, which macOS shows as Script Editor.
    """
    if not titles or (sys.platform != "darwin" and run is subprocess.run):
        return
    message = message_for(titles)
    notifier = notifier or macapp.notifier_path()
    message_file = message_file or macapp.message_path()
    try:
        if notifier.exists():
            message_file.parent.mkdir(parents=True, exist_ok=True)
            message_file.write_text(message, encoding="utf-8")
            run(["open", "-g", str(notifier)], capture_output=True, timeout=10)
        else:
            script = (f"display notification {_quote(message)} "
                      f"with title {_quote(TITLE)} subtitle {_quote('Anımsatıcılar')}")
            run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
