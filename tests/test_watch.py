from supernote_todo.supernote import SupernoteAuthError, SupernoteError, parse_task
from supernote_todo.sync import Stats
from supernote_todo.target import Target
from supernote_todo.watch import DEBOUNCE, Watcher


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeSupernote:
    def __init__(self):
        self.rows = [{"taskId": "a", "title": "Bir", "status": "needsAction"}]
        self.polls = 0
        self.error = None

    def tasks(self):
        self.polls += 1
        if self.error:
            raise self.error
        return [parse_task(r) for r in self.rows]


class LiveTarget(Target):
    name = "fake"

    def on_change(self, callback):
        self.fire = callback
        return True


def make(target=None, interval=30, full_every=600):
    clock, sn, passes = Clock(), FakeSupernote(), []
    watcher = Watcher(sn, target or LiveTarget(), lambda: passes.append(clock.now) or Stats(),
                      interval=interval, full_every=full_every, log=lambda _: None,
                      clock=clock)
    return watcher, clock, sn, passes


def tick(watcher, clock, seconds):
    for _ in range(int(seconds)):
        watcher.step()
        clock.now += 1


def test_first_tick_syncs_then_stays_quiet():
    watcher, clock, sn, passes = make()
    tick(watcher, clock, 120)
    assert len(passes) == 1
    assert sn.polls == 4  # one cheap listing per 30 s


def test_supernote_change_triggers_pass_on_next_poll():
    watcher, clock, sn, passes = make()
    tick(watcher, clock, 5)
    sn.rows[0]["title"] = "İki"
    tick(watcher, clock, 30)
    assert len(passes) == 2


def test_target_notification_syncs_after_debounce():
    target = LiveTarget()
    watcher, clock, sn, passes = make(target)
    tick(watcher, clock, 5)
    target.fire()
    tick(watcher, clock, DEBOUNCE)
    assert len(passes) == 1
    tick(watcher, clock, 2)
    assert len(passes) == 2
    assert watcher.live


def test_periodic_full_pass_without_notifications():
    watcher, clock, sn, passes = make(Target(), full_every=100)
    tick(watcher, clock, 250)
    assert len(passes) == 3 and not watcher.live


def test_errors_back_off():
    watcher, clock, sn, passes = make()
    sn.error = SupernoteError("down")
    tick(watcher, clock, 100)
    # 30 s, then 60 s: three attempts in 100 s, not one per second.
    assert sn.polls == 3 and passes == []
    sn.error = None
    tick(watcher, clock, 200)
    assert len(passes) == 1


def test_auth_error_waits_long():
    watcher, clock, sn, passes = make()
    sn.error = SupernoteAuthError("expired")
    tick(watcher, clock, 1000)
    assert sn.polls == 1


def test_new_login_is_picked_up_without_restart():
    clock, sn = Clock(), FakeSupernote()
    sn.error = SupernoteAuthError("expired")
    tokens = []
    watcher = Watcher(sn, LiveTarget(), lambda: Stats(), log=lambda _: None, clock=clock,
                      before_poll=lambda: tokens.append(clock.now))
    tick(watcher, clock, 5)
    sn.error = None  # the user logged in again
    tick(watcher, clock, 1900)
    assert len(tokens) >= 2 and watcher.passes == 1


def test_new_login_ends_auth_wait_immediately():
    clock, sn = Clock(), FakeSupernote()
    sn.error = SupernoteAuthError("expired")
    fresh = []
    watcher = Watcher(sn, LiveTarget(), lambda: Stats(), log=lambda _: None, clock=clock,
                      before_poll=lambda: bool(fresh))
    tick(watcher, clock, 5)
    assert sn.polls == 1
    sn.error = None
    fresh.append("new token")  # the user ran login-supernote
    tick(watcher, clock, 2)
    assert sn.polls == 2 and watcher.passes == 1
