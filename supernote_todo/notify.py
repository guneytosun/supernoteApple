"""macOS notifications for tasks that just arrived from Supernote."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Sequence

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
                     run: Callable[..., object] = subprocess.run) -> None:
    """Show one notification for the tasks just created. Never raises: a
    notification that cannot be shown must not stop a sync."""
    if not titles or (sys.platform != "darwin" and run is subprocess.run):
        return
    script = (f"display notification {_quote(message_for(titles))} "
              f"with title {_quote(TITLE)} subtitle {_quote('Anımsatıcılar')}")
    try:
        run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
