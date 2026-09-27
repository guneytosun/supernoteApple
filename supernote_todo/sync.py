"""One sync pass: Supernote To-Do -> Microsoft To Do.

Supernote is the source of truth for a task's title, note, due date and
completion. A snapshot of what was last sent is kept per task in the state
file, so a task is only patched when it changed on Supernote -- edits made in
Microsoft To Do survive until the same task is edited on the tablet again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from .mstodo import ToDoClient, ToDoError, ToDoNotFound, due_field
from .supernote import SupernoteClient, SupernoteError, SupernoteTask

APP_NAME = "Supernote"
INBOX_KEY = "__inbox__"
SINGLE_KEY = "__single__"


@dataclass
class Stats:
    created: int = 0
    updated: int = 0
    completed_back: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.created} yeni",
            f"{self.updated} güncellendi",
            f"{self.completed_back} Supernote'ta tamamlandı",
            f"{self.deleted} silindi",
            f"{self.skipped} atlandı",
        ]
        if self.errors:
            parts.append(f"{len(self.errors)} hata")
        return ", ".join(parts)


def desired_fields(task: SupernoteTask) -> dict:
    """What the Microsoft To Do copy of this task should look like."""
    body = task.detail
    if task.source:
        body = f"{body}\n\nNot: {task.source}" if body else f"Not: {task.source}"
    return {
        "title": task.title or "(başlıksız görev)",
        "body": body,
        "due": task.due.isoformat() if task.due else None,
        "status": "completed" if task.completed else "notStarted",
    }


def graph_payload(fields: dict, keys) -> dict:
    """Translate the snapshot format into a Graph todoTask body."""
    payload: dict = {}
    for key in keys:
        value = fields[key]
        if key == "title":
            payload["title"] = value
        elif key == "body":
            payload["body"] = {"content": value or "", "contentType": "text"}
        elif key == "due":
            payload["dueDateTime"] = due_field(date.fromisoformat(value)) if value else None
        elif key == "status":
            payload["status"] = value
    return payload


class Syncer:
    def __init__(self, supernote: SupernoteClient, todo: ToDoClient, config: dict,
                 state: dict, dry_run: bool = False,
                 log: Callable[[str], None] = print):
        self.sn = supernote
        self.todo = todo
        self.config = config
        self.state = state
        self.dry_run = dry_run
        self.log = log
        self.stats = Stats()
        self._ms_lists: list[dict] = []
        self._ms_tasks: dict[str, dict[str, dict]] = {}

    # -- lists ---------------------------------------------------------------

    def _target(self, task: SupernoteTask, sn_names: dict[str, str]) -> tuple[str, Optional[str]]:
        """(state key, list name to create) for the list this task belongs in.

        A name of None means Microsoft To Do's default "Tasks" list.
        """
        if self.config.get("list_mode") == "single":
            return SINGLE_KEY, self.config.get("target_list") or "Supernote"
        if task.list_id and task.list_id in sn_names:
            return task.list_id, f"{self.config.get('list_prefix', '')}{sn_names[task.list_id]}"
        return INBOX_KEY, None

    def _resolve_list(self, key: str, name: Optional[str]) -> str:
        known = {entry["id"] for entry in self._ms_lists}
        cached = self.state["lists"].get(key)
        if cached in known:
            return cached
        if name is None:
            match = next((l for l in self._ms_lists if l.get("wellknownListName") == "defaultList"), None)
        else:
            match = next((l for l in self._ms_lists if l.get("displayName") == name), None)
        if match is None:
            if self.dry_run:
                self.log(f"  [deneme] '{name}' listesi oluşturulacak")
                return f"dry-run:{key}"
            self.log(f"  Microsoft To Do'da '{name}' listesi oluşturuluyor")
            match = self.todo.create_list(name)
            self._ms_lists.append(match)
        self.state["lists"][key] = match["id"]
        return match["id"]

    def _ms_task_index(self, list_id: str) -> dict[str, dict]:
        if list_id not in self._ms_tasks:
            self._ms_tasks[list_id] = {t["id"]: t for t in self.todo.tasks(list_id)}
        return self._ms_tasks[list_id]

    def _recover_state(self) -> None:
        """Re-link tasks created by an earlier run whose state file was lost.

        Every task this tool creates carries a linked resource naming the
        Supernote task id, so nothing is duplicated after a reinstall.
        """
        for ms_list in self._ms_lists:
            try:
                tasks = self.todo.tasks(ms_list["id"], expand_links=True)
            except ToDoError as exc:
                self.log(f"  Uyarı: eski eşleşmeler aranamadı ({exc})")
                return
            for task in tasks:
                for link in task.get("linkedResources") or []:
                    if link.get("applicationName") == APP_NAME and link.get("externalId"):
                        self.state["tasks"][link["externalId"]] = {
                            "list": ms_list["id"], "id": task["id"], "synced": {},
                        }

    # -- the pass ------------------------------------------------------------

    def run(self) -> Stats:
        sn_names = {l.id: l.title for l in self.sn.lists()}
        sn_tasks = self.sn.tasks()
        if self.sn.truncated:
            self.log("Uyarı: Supernote hesabın yalnızca bir kısmını döndürdü; "
                     "silme işlemleri bu tur atlanacak.")
        self._ms_lists = self.todo.lists()
        if not self.state["tasks"]:
            self._recover_state()

        seen: set[str] = set()
        for task in sn_tasks:
            if task.deleted:
                continue
            seen.add(task.id)
            try:
                self._sync_task(task, sn_names)
            except (ToDoError, SupernoteError) as exc:
                self.stats.errors.append(f"{task.title!r}: {exc}")
                self.log(f"  HATA '{task.title}': {exc}")

        if not self.sn.truncated:
            self._handle_removed(seen)
        return self.stats

    def _sync_task(self, task: SupernoteTask, sn_names: dict[str, str]) -> None:
        want = desired_fields(task)
        record = self.state["tasks"].get(task.id)

        if record is None:
            if task.completed and not self.config.get("include_completed"):
                self.stats.skipped += 1
                return
            key, name = self._target(task, sn_names)
            list_id = self._resolve_list(key, name)
            self.log(f"+ {want['title']}")
            if self.dry_run:
                self.stats.created += 1
                return
            payload = graph_payload(want, [k for k in want if want[k] is not None])
            payload["linkedResources"] = [{
                "applicationName": APP_NAME,
                "externalId": task.id,
                "displayName": "Supernote To-Do",
            }]
            created = self.todo.create_task(list_id, payload)
            self.state["tasks"][task.id] = {"list": list_id, "id": created["id"], "synced": want}
            self.stats.created += 1
            return

        if record.get("gone"):
            return

        changed = [k for k in want if want[k] != record["synced"].get(k)]
        if changed:
            self.log(f"~ {want['title']} ({', '.join(changed)})")
            if self.dry_run:
                self.stats.updated += 1
                return
            try:
                self.todo.update_task(record["list"], record["id"], graph_payload(want, changed))
            except ToDoNotFound:
                # Deleted in Microsoft To Do on purpose: do not bring it back.
                record["gone"] = True
                return
            record["synced"] = want
            self.stats.updated += 1
            return

        if self.config.get("complete_back") and not task.completed:
            ms_task = self._ms_task_index(record["list"]).get(record["id"])
            if ms_task is None:
                record["gone"] = True
            elif ms_task.get("status") == "completed":
                self.log(f"✓ {want['title']} (Supernote'ta tamamlandı olarak işaretleniyor)")
                self.stats.completed_back += 1
                if not self.dry_run:
                    self.sn.complete(task)
                    record["synced"] = dict(want, status="completed")

    def _handle_removed(self, seen: set[str]) -> None:
        for sn_id in [i for i in self.state["tasks"] if i not in seen]:
            record = self.state["tasks"][sn_id]
            if self.config.get("delete_removed") and not record.get("gone"):
                self.log(f"- {record.get('synced', {}).get('title', sn_id)}")
                self.stats.deleted += 1
                if self.dry_run:
                    continue
                try:
                    self.todo.delete_task(record["list"], record["id"])
                except ToDoNotFound:
                    pass
                except ToDoError as exc:
                    self.stats.errors.append(str(exc))
                    continue
            if not self.dry_run:
                del self.state["tasks"][sn_id]
