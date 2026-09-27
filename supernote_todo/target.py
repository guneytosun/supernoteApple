"""The interface every destination (Apple Reminders, Microsoft To Do) implements.

The sync engine speaks in neutral task fields::

    {"title": str, "body": str, "due": "YYYY-MM-DD" | None, "completed": bool}

and each target translates them into its own model. A target keeps a link from
every task it creates back to the Supernote task id, so a lost state file can
be rebuilt with :meth:`Target.recover` instead of duplicating everything.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

FIELDS = ("title", "body", "due", "completed")


class TargetError(Exception):
    pass


class TargetAuthError(TargetError):
    pass


class TargetNotFound(TargetError):
    pass


@dataclass
class TargetList:
    id: str
    name: str
    is_default: bool = False


class Target:
    #: Shown to the user, e.g. in "3 tasks created in Apple Reminders".
    name = "hedef"

    def lists(self) -> list[TargetList]:
        raise NotImplementedError

    def create_list(self, name: str) -> TargetList:
        raise NotImplementedError

    def create(self, list_id: str, sn_id: str, fields: dict) -> str:
        """Create a task and return the target's id for it."""
        raise NotImplementedError

    def update(self, list_id: str, task_id: str, sn_id: str, changes: dict) -> None:
        """Apply only the given fields. Raise TargetNotFound if it is gone."""
        raise NotImplementedError

    def is_completed(self, list_id: str, task_id: str, sn_id: str) -> Optional[bool]:
        """Completion state, or None when the task no longer exists."""
        raise NotImplementedError

    def delete(self, list_id: str, task_id: str, sn_id: str) -> None:
        raise NotImplementedError

    def recover(self) -> dict[str, dict]:
        """{supernote id: {"list": ..., "id": ...}} for tasks made by this tool."""
        return {}

    # -- long-running (watch) support ---------------------------------------

    def refresh(self) -> None:
        """Forget anything cached, so the next pass sees the current state."""

    def on_change(self, callback: Callable[[], None]) -> bool:
        """Call ``callback`` whenever tasks change on this side.

        Returns False when the target cannot notify, in which case the watcher
        falls back to periodic full passes.
        """
        return False

    def idle(self, seconds: float) -> None:
        """Wait, while letting change notifications arrive."""
        time.sleep(seconds)
