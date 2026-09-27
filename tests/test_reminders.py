"""RemindersTarget against a stand-in for PyObjC's EventKit/Foundation.

The fake mirrors the selector names the adapter calls, so a typo in one of
them fails here rather than only on a Mac.
"""

import types
from datetime import datetime

from supernote_todo.reminders import URL_PREFIX, RemindersTarget
from supernote_todo.supernote import SupernoteList, parse_task
from supernote_todo.sync import Syncer


class Obj:
    """Minimal NSObject: `alloc().init()` and generated setters/getters."""

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self


class NSURL(Obj):
    def __init__(self, text=""):
        self.text = text

    @classmethod
    def URLWithString_(cls, text):
        return cls(text)

    def absoluteString(self):
        return self.text


class NSDateComponents(Obj):
    def setCalendar_(self, cal): self.calendar = cal
    def setYear_(self, v): self.y = v
    def setMonth_(self, v): self.m = v
    def setDay_(self, v): self.d = v


class Source:
    pass


class EKCalendar(Obj):
    _n = 0

    def __init__(self, title="", source=None):
        EKCalendar._n += 1
        self._id = f"cal{EKCalendar._n}"
        self._title, self._source = title, source

    @classmethod
    def calendarForEntityType_eventStore_(cls, entity, store):
        assert entity == EventKit.EKEntityTypeReminder
        return cls()

    def calendarIdentifier(self): return self._id
    def title(self): return self._title
    def setTitle_(self, t): self._title = t
    def source(self): return self._source
    def setSource_(self, s): self._source = s


class EKReminder(Obj):
    _n = 0

    @classmethod
    def reminderWithEventStore_(cls, store):
        r = cls()
        r._title = r._notes = r._url = r._due = r._calendar = None
        r._completed = False
        EKReminder._n += 1
        r._id = f"rem{EKReminder._n}"
        return r

    def setTitle_(self, v): self._title = v
    def title(self): return self._title
    def setNotes_(self, v): self._notes = v
    def setURL_(self, v): self._url = v
    def URL(self): return self._url
    def setDueDateComponents_(self, v): self._due = v
    def setCompleted_(self, v): self._completed = v
    def isCompleted(self): return self._completed
    def setCalendar_(self, v): self._calendar = v
    def calendar(self): return self._calendar
    def calendarItemIdentifier(self): return self._id


class EKEventStore(Obj):
    granted = True

    @classmethod
    def authorizationStatusForEntityType_(cls, entity):
        return 0  # not determined: always go through the request

    def init(self):
        self.source = Source()
        self.cals = [EKCalendar("Anımsatıcılar", self.source)]
        self.saved = []
        return self

    def requestFullAccessToRemindersWithCompletion_(self, cb):
        cb(self.granted, None)

    def calendarsForEntityType_(self, entity):
        return self.cals

    def calendarWithIdentifier_(self, ident):
        return next((c for c in self.cals if c.calendarIdentifier() == ident), None)

    def defaultCalendarForNewReminders(self):
        return self.cals[0]

    def saveCalendar_commit_error_(self, cal, commit, err):
        self.cals.append(cal)
        return True, None

    def predicateForRemindersInCalendars_(self, cals):
        return "all"

    def fetchRemindersMatchingPredicate_completion_(self, pred, cb):
        cb(list(self.saved))

    def saveReminder_commit_error_(self, r, commit, err):
        if r not in self.saved:
            self.saved.append(r)
        return True, None

    def removeReminder_commit_error_(self, r, commit, err):
        self.saved.remove(r)
        return True, None


class NSRunLoop:
    @classmethod
    def currentRunLoop(cls):
        return cls()

    def runUntilDate_(self, d):
        pass


class NSNotificationCenter:
    observers = []

    @classmethod
    def defaultCenter(cls):
        return cls()

    def addObserverForName_object_queue_usingBlock_(self, name, obj, queue, block):
        assert name == EventKit.EKEventStoreChangedNotification
        NSNotificationCenter.observers.append(block)
        return object()


EventKit = types.SimpleNamespace(
    EKEventStore=EKEventStore, EKCalendar=EKCalendar, EKReminder=EKReminder,
    EKEntityTypeReminder=1, EKEventStoreChangedNotification="EKEventStoreChangedNotification")
Foundation = types.SimpleNamespace(
    NSURL=NSURL, NSDateComponents=NSDateComponents, NSRunLoop=NSRunLoop,
    NSNotificationCenter=NSNotificationCenter,
    NSDate=types.SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda s: s),
    NSCalendar=types.SimpleNamespace(currentCalendar=lambda: "gregorian"))


class FakeSupernote:
    truncated = False

    def __init__(self, rows):
        self.rows = rows
        self.completed = []

    def lists(self):
        return [SupernoteList("L1", "İş")]

    def tasks(self):
        return [parse_task(r) for r in self.rows]

    def complete(self, task):
        self.completed.append(task.id)
        next(r for r in self.rows if r["taskId"] == task.id)["status"] = "completed"


def row(task_id, title, list_id="L1", **extra):
    base = {"taskId": task_id, "title": title, "taskListId": list_id,
            "status": "needsAction", "isDeleted": "N", "dueTime": 0}
    base.update(extra)
    return base


CONFIG = {"list_mode": "mirror", "list_prefix": "", "include_completed": False,
          "complete_back": True, "delete_removed": True}


def run(target, sn, state):
    return Syncer(sn, target, CONFIG, state, log=lambda _: None).run()


def test_round_trip_through_reminders():
    target = RemindersTarget(EventKit, Foundation)
    due = int(datetime(2026, 10, 3).timestamp() * 1000)
    sn = FakeSupernote([row("a", "Rapor yaz", dueTime=due, detail="ayrıntı"),
                        row("b", "Kutusuz", list_id=None)])
    state = {"lists": {}, "tasks": {}}

    assert run(target, sn, state).created == 2
    store = target.store
    by_title = {r.title(): r for r in store.saved}
    work = by_title["Rapor yaz"]
    assert work.calendar().title() == "İş"
    assert work.calendar().source() is store.source  # same (iCloud) account
    assert (work._due.y, work._due.m, work._due.d) == (2026, 10, 3)
    assert work._notes == "ayrıntı"
    assert work.URL().absoluteString() == URL_PREFIX + "a"
    assert by_title["Kutusuz"].calendar().title() == "Anımsatıcılar"

    # Edited on the tablet -> updated in place.
    sn.rows[0]["title"] = "Raporu bitir"
    assert run(target, sn, state).updated == 1
    assert work.title() == "Raporu bitir"

    # Ticked off on the phone -> ticked off on Supernote.
    work.setCompleted_(True)
    assert run(target, sn, state).completed_back == 1
    assert sn.completed == ["a"]

    # Nothing left to do once both sides agree.
    stats = run(target, sn, state)
    assert (stats.updated, stats.completed_back) == (0, 0) and work.isCompleted()

    # Deleted on Supernote -> removed from Reminders.
    sn.rows.pop(1)
    assert run(target, sn, state).deleted == 1
    assert [r.title() for r in store.saved] == ["Raporu bitir"]


def test_lost_state_does_not_duplicate():
    target = RemindersTarget(EventKit, Foundation)
    sn = FakeSupernote([row("a", "Bir")])
    run(target, sn, {"lists": {}, "tasks": {}})
    fresh = RemindersTarget(EventKit, Foundation)
    fresh.store = target.store
    stats = run(fresh, sn, {"lists": {}, "tasks": {}})
    assert stats.created == 0 and len(target.store.saved) == 1


def test_access_denied():
    import pytest
    from supernote_todo.target import TargetAuthError

    EKEventStore.granted = False
    try:
        with pytest.raises(TargetAuthError):
            RemindersTarget(EventKit, Foundation)
    finally:
        EKEventStore.granted = True


def test_change_notifications_and_idle():
    target = RemindersTarget(EventKit, Foundation)
    fired = []
    assert target.on_change(lambda: fired.append(1))
    NSNotificationCenter.observers[-1](object())
    assert fired == [1]
    target.idle(0.5)  # spins the run loop instead of sleeping


def test_refresh_sees_changes_made_elsewhere():
    target = RemindersTarget(EventKit, Foundation)
    sn = FakeSupernote([row("a", "Bir")])
    state = {"lists": {}, "tasks": {}}
    run(target, sn, state)
    # Deleted in the Reminders app between passes: the next pass must notice.
    target.store.saved.clear()
    sn.rows[0]["title"] = "Bir (değişti)"
    run(target, sn, state)
    assert state["tasks"]["a"]["gone"] is True
