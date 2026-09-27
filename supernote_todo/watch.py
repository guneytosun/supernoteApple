"""Keep running and sync as soon as either side changes.

Supernote Cloud offers no push channel, so its side is polled -- but cheaply:
one task listing every ``interval`` seconds, and a full pass only when that
listing actually differs from the last one. The target side is event driven
where the target supports it (Apple Reminders posts a notification on every
change), so ticking a reminder off on the phone reaches Supernote within
seconds. A full pass also runs every ``full_every`` seconds as a safety net.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Callable, Optional

from .supernote import SupernoteAuthError, SupernoteClient, SupernoteError, SupernoteTask
from .sync import Stats
from .target import Target, TargetError

#: Wait this long after a change notification before syncing, so a burst of
#: edits (or an iCloud sync delivering many at once) becomes one pass.
DEBOUNCE = 2.0
MAX_BACKOFF = 600.0
AUTH_RETRY = 1800.0


def fingerprint(tasks: list[SupernoteTask]) -> str:
    """A digest of everything a pass could act on."""
    keys = ("taskId", "taskListId", "title", "detail", "status", "dueTime",
            "isDeleted", "lastModified")
    rows = sorted(
        (tuple(str(t.raw.get(k)) for k in keys) for t in tasks), key=lambda r: r[0])
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()


class Watcher:
    def __init__(self, supernote: SupernoteClient, target: Target,
                 run_pass: Callable[[], Stats], interval: float = 30.0,
                 full_every: float = 600.0, log: Callable[[str], None] = print,
                 clock: Callable[[], float] = time.monotonic):
        self.sn = supernote
        self.target = target
        self.run_pass = run_pass
        self.interval = interval
        self.full_every = full_every
        self.log = log
        self.clock = clock

        self._last_fp: Optional[str] = None
        self._dirty = True  # always start with a full pass
        self._changed_at: Optional[float] = None
        self._next_poll = 0.0
        self._next_full = 0.0
        self._blocked_until = 0.0
        self._backoff = 0.0
        self.passes = 0
        self.live = target.on_change(self._target_changed)

    def _target_changed(self) -> None:
        # Our own writes notify too. That costs one extra pass which finds
        # nothing to do and writes nothing, so it cannot loop -- cheaper than
        # risking a real change being ignored as an echo.
        self._changed_at = self.clock()

    def _fail(self, exc: Exception) -> None:
        if isinstance(exc, SupernoteAuthError):
            delay = AUTH_RETRY
        else:
            delay = self._backoff = min(MAX_BACKOFF, max(self.interval, self._backoff * 2))
        self.log(f"Hata: {exc} — {int(delay)} sn sonra tekrar denenecek.")
        self._blocked_until = self._next_poll = self.clock() + delay

    def step(self) -> None:
        """One tick of the loop; ``run`` calls it once a second."""
        now = self.clock()
        if now < self._blocked_until:
            return

        if now >= self._next_poll:
            self._next_poll = now + self.interval
            try:
                fp = fingerprint(self.sn.tasks())
            except (SupernoteError, TargetError) as exc:
                self._fail(exc)
                return
            if fp != self._last_fp:
                self._dirty = True
                self._last_fp = fp

        if self._changed_at is not None and now - self._changed_at >= DEBOUNCE:
            self._changed_at = None
            self._dirty = True

        if now >= self._next_full:
            self._dirty = True

        if not self._dirty:
            return

        try:
            stats = self.run_pass()
        except (SupernoteError, TargetError) as exc:
            self._fail(exc)
            return
        self.passes += 1
        self._backoff = 0.0
        self._dirty = False
        self._next_full = now + self.full_every
        if stats.changed:
            self.log(f"[{time.strftime('%H:%M:%S')}] {stats.summary()}")

    def run(self) -> None:
        mode = "anında" if self.live else f"en geç {int(self.full_every)} sn içinde"
        self.log(f"İzleniyor: Supernote {int(self.interval)} sn'de bir yoklanıyor, "
                 f"{self.target.name} değişiklikleri {mode} aktarılıyor. "
                 "Durdurmak için Ctrl+C.")
        while True:
            self.step()
            self.target.idle(1.0)
