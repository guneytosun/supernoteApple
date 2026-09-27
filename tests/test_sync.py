import base64
import hashlib
import json
from datetime import datetime


from supernote_todo.mstodo import MicrosoftTarget, ToDoError, ToDoNotFound
from supernote_todo.supernote import (SupernoteList, decode_source, parse_task,
                                      password_digest, token_expiry)
from supernote_todo.sync import Syncer


def ms(y, m, d):
    return int(datetime(y, m, d).timestamp() * 1000)


def row(task_id, title, list_id="L1", status="needsAction", **extra):
    base = {"taskId": task_id, "title": title, "taskListId": list_id, "status": status,
            "isDeleted": "N", "dueTime": 0, "detail": None, "completedTime": ms(2026, 1, 1)}
    base.update(extra)
    return base


class FakeSupernote:
    def __init__(self, rows, lists=(("L1", "İş"),)):
        self.rows = rows
        self._lists = [SupernoteList(i, t) for i, t in lists]
        self.truncated = False
        self.completed = []

    def lists(self):
        return self._lists

    def tasks(self):
        return [parse_task(r) for r in self.rows]

    def complete(self, task):
        self.completed.append(task.id)
        next(r for r in self.rows if r["taskId"] == task.id)["status"] = "completed"


class FakeToDo:
    def __init__(self):
        self.lists_ = [{"id": "default", "displayName": "Tasks", "wellknownListName": "defaultList"}]
        self.tasks_ = {}  # list id -> {task id -> task}
        self.calls = []
        self._n = 0

    def lists(self):
        return list(self.lists_)

    def create_list(self, name):
        entry = {"id": f"list-{name}", "displayName": name, "wellknownListName": "none"}
        self.lists_.append(entry)
        return entry

    def tasks(self, list_id, expand_links=False):
        return list(self.tasks_.get(list_id, {}).values())

    def create_task(self, list_id, fields):
        self._n += 1
        task = dict(fields, id=f"t{self._n}", status=fields.get("status", "notStarted"))
        self.tasks_.setdefault(list_id, {})[task["id"]] = task
        self.calls.append(("create", list_id, fields))
        return task

    def update_task(self, list_id, task_id, fields):
        if task_id not in self.tasks_.get(list_id, {}):
            raise ToDoNotFound(task_id)
        self.tasks_[list_id][task_id].update(fields)
        self.calls.append(("update", task_id, fields))
        return self.tasks_[list_id][task_id]

    def delete_task(self, list_id, task_id):
        self.tasks_.get(list_id, {}).pop(task_id, None)
        self.calls.append(("delete", task_id))


CONFIG = {"list_mode": "mirror", "list_prefix": "", "target_list": "Supernote",
          "include_completed": False, "complete_back": False, "delete_removed": False}


def run(sn, todo, state, **overrides):
    config = dict(CONFIG, **overrides)
    return Syncer(sn, MicrosoftTarget(todo), config, state, log=lambda _: None).run()


def fresh_state():
    return {"lists": {}, "tasks": {}}


def test_creates_tasks_in_mirrored_lists():
    sn = FakeSupernote([row("a", "Rapor yaz", dueTime=ms(2026, 10, 3)),
                        row("b", "Kutusuz", list_id=None)])
    todo, state = FakeToDo(), fresh_state()
    stats = run(sn, todo, state)

    assert stats.created == 2
    work = todo.tasks_["list-İş"]
    (task,) = work.values()
    assert task["title"] == "Rapor yaz"
    assert task["dueDateTime"]["dateTime"].startswith("2026-10-03")
    assert task["linkedResources"][0]["externalId"] == "a"
    # A task outside every list lands in the default "Tasks" list.
    assert [t["title"] for t in todo.tasks_["default"].values()] == ["Kutusuz"]


def test_second_run_is_a_noop_and_changes_are_patched():
    sn = FakeSupernote([row("a", "Rapor yaz")])
    todo, state = FakeToDo(), fresh_state()
    run(sn, todo, state)
    stats = run(sn, todo, state)
    assert (stats.created, stats.updated) == (0, 0)

    sn.rows[0]["title"] = "Raporu bitir"
    sn.rows[0]["status"] = "completed"
    stats = run(sn, todo, state)
    assert stats.updated == 1
    assert todo.calls[-1] == ("update", "t1", {"title": "Raporu bitir", "status": "completed"})


def test_completed_tasks_skipped_unless_requested():
    sn = FakeSupernote([row("a", "Eski", status="completed")])
    assert run(sn, FakeToDo(), fresh_state()).created == 0
    assert run(sn, FakeToDo(), fresh_state(), include_completed=True).created == 1


def test_single_list_mode():
    sn = FakeSupernote([row("a", "Bir"), row("b", "İki", list_id=None)])
    todo = FakeToDo()
    run(sn, todo, fresh_state(), list_mode="single", target_list="Supernote")
    assert len(todo.tasks_["list-Supernote"]) == 2


def test_task_deleted_in_microsoft_is_not_recreated():
    sn = FakeSupernote([row("a", "Bir")])
    todo, state = FakeToDo(), fresh_state()
    run(sn, todo, state)
    todo.tasks_["list-İş"].clear()
    sn.rows[0]["title"] = "Bir (değişti)"
    stats = run(sn, todo, state)
    assert state["tasks"]["a"]["gone"] is True
    assert stats.created == 0


def test_complete_back_marks_supernote_task_done():
    sn = FakeSupernote([row("a", "Bir")])
    todo, state = FakeToDo(), fresh_state()
    run(sn, todo, state, complete_back=True)
    todo.tasks_["list-İş"]["t1"]["status"] = "completed"
    stats = run(sn, todo, state, complete_back=True)
    assert stats.completed_back == 1
    assert sn.completed == ["a"]
    # The next pass sees Supernote completed and has nothing left to send.
    sn.rows[0]["status"] = "completed"
    assert run(sn, todo, state, complete_back=True).updated == 0


def test_removed_tasks_deleted_only_when_enabled():
    sn = FakeSupernote([row("a", "Bir")])
    todo, state = FakeToDo(), fresh_state()
    run(sn, todo, state)
    sn.rows[0]["isDeleted"] = "Y"
    run(sn, todo, state)
    assert "t1" in todo.tasks_["list-İş"] and "a" not in state["tasks"]

    sn2 = FakeSupernote([row("b", "İki")])
    todo2, state2 = FakeToDo(), fresh_state()
    run(sn2, todo2, state2)
    sn2.rows.clear()
    assert run(sn2, todo2, state2, delete_removed=True).deleted == 1
    assert todo2.tasks_["list-İş"] == {}


def test_truncated_read_never_deletes():
    sn = FakeSupernote([row("a", "Bir")])
    todo, state = FakeToDo(), fresh_state()
    run(sn, todo, state)
    sn.rows.clear()
    sn.truncated = True
    assert run(sn, todo, state, delete_removed=True).deleted == 0
    assert "a" in state["tasks"]


def test_lost_state_is_recovered_from_linked_resources():
    sn = FakeSupernote([row("a", "Bir")])
    todo = FakeToDo()
    run(sn, todo, fresh_state())
    stats = run(sn, todo, fresh_state())
    assert stats.created == 0
    assert len(todo.tasks_["list-İş"]) == 1


def test_errors_are_collected_not_fatal():
    class Broken(FakeToDo):
        def create_task(self, list_id, fields):
            if fields["title"] == "Kötü":
                raise ToDoError("boom")
            return super().create_task(list_id, fields)

    sn = FakeSupernote([row("a", "Kötü"), row("b", "İyi")])
    stats = run(sn, Broken(), fresh_state())
    assert stats.created == 1 and len(stats.errors) == 1


def test_dry_run_changes_nothing():
    sn = FakeSupernote([row("a", "Bir")])
    todo, state = FakeToDo(), fresh_state()
    config = dict(CONFIG)
    Syncer(sn, MicrosoftTarget(todo), config, state, dry_run=True, log=lambda _: None).run()
    assert todo.calls == [] and state["tasks"] == {} and len(todo.lists_) == 1


def test_helpers():
    md5 = hashlib.md5(b"secret").hexdigest()
    assert password_digest("secret", "abc") == hashlib.sha256((md5 + "abc").encode()).hexdigest()
    links = base64.b64encode(json.dumps(
        {"filePath": "/storage/Note/Toplantı.note", "page": 3}).encode()).decode()
    assert decode_source(links) == "Toplantı.note, sayfa 3"
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1893456000}).encode()).decode().rstrip("=")
    assert token_expiry(f"x.{payload}.y").year == 2030
    assert token_expiry("garbage") is None


def test_created_titles_collected_for_notification():
    sn = FakeSupernote([row("a", "Bir"), row("b", "İki")])
    todo, state = FakeToDo(), fresh_state()
    assert run(sn, todo, state).created_titles == ["Bir", "İki"]
    assert run(sn, todo, state).created_titles == []
