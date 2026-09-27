"""Apple Reminders through EventKit (macOS only, via PyObjC).

iCloud's current Reminders format is not reachable over CalDAV, so the only
dependable way in is the local EventKit store on a Mac signed in to iCloud;
whatever is written there syncs to the iPhone/iPad (and to anything else that
shows your Reminders) on its own.

Every reminder this tool creates carries ``supernote-todo://task/<id>`` in its
URL field. Reminders are found by that marker rather than by EventKit's
``calendarItemIdentifier``, which Apple documents can change after a full
resync with the server.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Optional

from .target import Target, TargetAuthError, TargetError, TargetList, TargetNotFound

URL_PREFIX = "supernote-todo://task/"

_TIMEOUT = 60
#: EKAuthorizationStatus: 3 is "authorized" before macOS 14, "fullAccess" after.
FULL_ACCESS = 3


def _load_eventkit():
    try:
        import EventKit  # type: ignore
        import Foundation  # type: ignore
    except ImportError:
        raise TargetError(
            "Apple Reminders yalnızca macOS'ta çalışır ve PyObjC gerektirir: "
            "pip install pyobjc-framework-EventKit"
        ) from None
    return EventKit, Foundation


class RemindersTarget(Target):
    name = "Apple Reminders"

    def __init__(self, eventkit=None, foundation=None):
        if eventkit is None:
            eventkit, foundation = _load_eventkit()
        self.ek = eventkit
        self.ns = foundation
        self.store = eventkit.EKEventStore.alloc().init()
        self._request_access()
        self._index: Optional[dict] = None

    def _wait(self, start) -> tuple:
        """Run an EventKit call that answers through a completion block.

        The main run loop is spun while waiting: some EventKit callbacks (the
        permission prompt in particular) are delivered through it.
        """
        done = threading.Event()
        result: list = []

        def callback(*args):
            result.extend(args)
            done.set()

        start(callback)
        deadline = time.monotonic() + _TIMEOUT
        run_loop = self.ns.NSRunLoop.currentRunLoop()
        while not done.is_set():
            if time.monotonic() > deadline:
                raise TargetError("Apple Reminders yanıt vermedi.")
            run_loop.runUntilDate_(self.ns.NSDate.dateWithTimeIntervalSinceNow_(0.1))
        return tuple(result)

    # -- access --------------------------------------------------------------

    def _request_access(self) -> None:
        """Ask for access, or explain why it cannot be had.

        macOS grants Reminders access per *app*: run from Terminal, the prompt
        is for Terminal; run by launchd there is no app to ask on behalf of,
        so the request is refused without a prompt and nothing shows up in
        System Settings. `supernote-todo install-app` exists for that case.
        """
        ek, store = self.ek, self.store
        status = ek.EKEventStore.authorizationStatusForEntityType_(ek.EKEntityTypeReminder)
        if status == FULL_ACCESS:
            return
        if hasattr(store, "requestFullAccessToRemindersWithCompletion_"):  # macOS 14+
            granted, *_ = self._wait(store.requestFullAccessToRemindersWithCompletion_)
        else:
            granted, *_ = self._wait(
                lambda cb: store.requestAccessToEntityType_completion_(ek.EKEntityTypeReminder, cb))
        if not granted:
            raise TargetAuthError(
                "Anımsatıcılar'a erişim izni yok. Terminal'den çalıştırıyorsanız: Sistem "
                "Ayarları → Gizlilik ve Güvenlik → Anımsatıcılar → Terminal'i açın. Arka "
                "planda çalıştırmak için `supernote-todo install-app` kullanın (launchd "
                "ile çalışan bir süreç bu izni alamaz)."
            )

    # -- helpers -------------------------------------------------------------

    def _calendars(self) -> list:
        return list(self.store.calendarsForEntityType_(self.ek.EKEntityTypeReminder) or [])

    def _calendar(self, list_id: str):
        cal = self.store.calendarWithIdentifier_(list_id)
        if cal is None:
            raise TargetNotFound(f"Anımsatıcı listesi bulunamadı: {list_id}")
        return cal

    def _all_reminders(self) -> list:
        predicate = self.store.predicateForRemindersInCalendars_(None)
        reminders, *_ = self._wait(
            lambda cb: self.store.fetchRemindersMatchingPredicate_completion_(predicate, cb))
        return list(reminders or [])

    def _by_sn_id(self) -> dict:
        if self._index is None:
            self._index = {}
            for reminder in self._all_reminders():
                url = reminder.URL()
                text = str(url.absoluteString()) if url is not None else ""
                if text.startswith(URL_PREFIX):
                    self._index[text[len(URL_PREFIX):]] = reminder
        return self._index

    def _find(self, sn_id: str):
        reminder = self._by_sn_id().get(sn_id)
        if reminder is None:
            raise TargetNotFound(sn_id)
        return reminder

    def _save(self, reminder) -> None:
        ok, error = self.store.saveReminder_commit_error_(reminder, True, None)
        if not ok:
            raise TargetError(f"Anımsatıcı kaydedilemedi: {error}")

    def _apply(self, reminder, changes: dict) -> None:
        if "title" in changes:
            reminder.setTitle_(changes["title"])
        if "body" in changes:
            reminder.setNotes_(changes["body"] or None)
        if "due" in changes:
            reminder.setDueDateComponents_(self._components(changes["due"]))
        if "completed" in changes:
            reminder.setCompleted_(bool(changes["completed"]))

    def _components(self, value: Optional[str]):
        if not value:
            return None
        day = date.fromisoformat(value)
        comps = self.ns.NSDateComponents.alloc().init()
        comps.setCalendar_(self.ns.NSCalendar.currentCalendar())
        comps.setYear_(day.year)
        comps.setMonth_(day.month)
        comps.setDay_(day.day)
        return comps

    # -- Target --------------------------------------------------------------

    def lists(self) -> list[TargetList]:
        default = self.store.defaultCalendarForNewReminders()
        default_id = str(default.calendarIdentifier()) if default is not None else None
        return [
            TargetList(id=str(cal.calendarIdentifier()), name=str(cal.title()),
                       is_default=str(cal.calendarIdentifier()) == default_id)
            for cal in self._calendars()
        ]

    def create_list(self, name: str) -> TargetList:
        cal = self.ek.EKCalendar.calendarForEntityType_eventStore_(
            self.ek.EKEntityTypeReminder, self.store)
        cal.setTitle_(name)
        # Same account as the default list, so it lands in iCloud rather than
        # "On My Mac" and shows up on every device.
        default = self.store.defaultCalendarForNewReminders()
        if default is None:
            raise TargetError("Varsayılan Anımsatıcılar listesi bulunamadı.")
        cal.setSource_(default.source())
        ok, error = self.store.saveCalendar_commit_error_(cal, True, None)
        if not ok:
            raise TargetError(f"'{name}' listesi oluşturulamadı: {error}")
        return TargetList(id=str(cal.calendarIdentifier()), name=name)

    def create(self, list_id: str, sn_id: str, fields: dict) -> str:
        reminder = self.ek.EKReminder.reminderWithEventStore_(self.store)
        reminder.setCalendar_(self._calendar(list_id))
        reminder.setURL_(self.ns.NSURL.URLWithString_(URL_PREFIX + sn_id))
        self._apply(reminder, fields)
        self._save(reminder)
        self._by_sn_id()[sn_id] = reminder
        return str(reminder.calendarItemIdentifier())

    def update(self, list_id: str, task_id: str, sn_id: str, changes: dict) -> None:
        reminder = self._find(sn_id)
        self._apply(reminder, changes)
        self._save(reminder)

    def is_completed(self, list_id: str, task_id: str, sn_id: str) -> Optional[bool]:
        reminder = self._by_sn_id().get(sn_id)
        return None if reminder is None else bool(reminder.isCompleted())

    def delete(self, list_id: str, task_id: str, sn_id: str) -> None:
        reminder = self._find(sn_id)
        ok, error = self.store.removeReminder_commit_error_(reminder, True, None)
        if not ok:
            raise TargetError(f"Anımsatıcı silinemedi: {error}")
        self._by_sn_id().pop(sn_id, None)

    def refresh(self) -> None:
        self._index = None

    def on_change(self, callback) -> bool:
        """EventKit posts EKEventStoreChangedNotification on every change,
        whether made in the Reminders app, on another device via iCloud, or by
        this tool itself."""
        self._observer = self.ns.NSNotificationCenter.defaultCenter() \
            .addObserverForName_object_queue_usingBlock_(
                self.ek.EKEventStoreChangedNotification, self.store, None,
                lambda _note: callback())
        return True

    def idle(self, seconds: float) -> None:
        # Notifications are delivered through the run loop, so spin it rather
        # than sleeping.
        self.ns.NSRunLoop.currentRunLoop().runUntilDate_(
            self.ns.NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def recover(self) -> dict[str, dict]:
        return {
            sn_id: {"list": str(r.calendar().calendarIdentifier()),
                    "id": str(r.calendarItemIdentifier())}
            for sn_id, r in self._by_sn_id().items()
        }
