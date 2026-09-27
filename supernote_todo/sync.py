"""One sync pass: Supernote To-Do -> a target (Apple Reminders, Microsoft To Do).

Supernote is the source of truth for a task's title, note, due date and
completion. A snapshot of what was last sent is kept per task in the state
file, so a task is only touched when it changed on Supernote -- edits made on
the other side survive until the same task is edited on the tablet again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .supernote import SupernoteClient, SupernoteError, SupernoteTask
from .target import FIELDS, Target, TargetError, TargetNotFound

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

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.completed_back
                    or self.deleted or self.errors)

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
    """What the copy of this task should look like on the other side."""
    body = task.detail
    if task.source:
        body = f"{body}\n\nNot: {task.source}" if body else f"Not: {task.source}"
    return {
        "title": task.title or "(başlıksız görev)",
        "body": body,
        "due": task.due.isoformat() if task.due else None,
        "completed": task.completed,
    }


class Syncer:
    def __init__(self, supernote: SupernoteClient, target: Target, config: dict,
                 state: dict, dry_run: bool = False,
                 log: Callable[[str], None] = print):
        self.sn = supernote
        self.target = target
        self.config = config
        self.state = state
        self.dry_run = dry_run
        self.log = log
        self.stats = Stats()
        self._lists: list = []

    # -- lists ---------------------------------------------------------------

    def _destination(self, task: SupernoteTask, sn_names: dict[str, str]) -> tuple[str, Optional[str]]:
        """(state key, list name) for the list this task belongs in.

        A name of None means the target's default list.
        """
        if self.config.get("list_mode") == "single":
            return SINGLE_KEY, self.config.get("target_list") or "Supernote"
        if task.list_id and task.list_id in sn_names:
            return task.list_id, f"{self.config.get('list_prefix', '')}{sn_names[task.list_id]}"
        return INBOX_KEY, None

    def _resolve_list(self, key: str, name: Optional[str]) -> str:
        cached = self.state["lists"].get(key)
        if cached in {l.id for l in self._lists}:
            return cached
        if name is None:
            match = next((l for l in self._lists if l.is_default), None)
            if match is None:
                raise TargetError(f"{self.target.name} içinde varsayılan liste bulunamadı.")
        else:
            match = next((l for l in self._lists if l.name == name), None)
        if match is None:
            if self.dry_run:
                self.log(f"  [deneme] '{name}' listesi oluşturulacak")
                return f"dry-run:{key}"
            self.log(f"  {self.target.name} içinde '{name}' listesi oluşturuluyor")
            match = self.target.create_list(name)
            self._lists.append(match)
        self.state["lists"][key] = match.id
        return match.id

    # -- the pass ------------------------------------------------------------

    def run(self) -> Stats:
        sn_names = {l.id: l.title for l in self.sn.lists()}
        sn_tasks = self.sn.tasks()
        if self.sn.truncated:
            self.log("Uyarı: Supernote hesabın yalnızca bir kısmını döndürdü; "
                     "silme işlemleri bu tur atlanacak.")
        self.target.refresh()
        self._lists = self.target.lists()
        if not self.state["tasks"]:
            # A lost state file must not turn into a second copy of everything.
            try:
                for sn_id, link in self.target.recover().items():
                    self.state["tasks"][sn_id] = dict(link, synced={})
            except TargetError as exc:
                self.log(f"  Uyarı: önceki eşleşmeler aranamadı ({exc})")

        seen: set[str] = set()
        for task in sn_tasks:
            if task.deleted:
                continue
            seen.add(task.id)
            try:
                self._sync_task(task, sn_names)
            except (TargetError, SupernoteError) as exc:
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
            list_id = self._resolve_list(*self._destination(task, sn_names))
            self.log(f"+ {want['title']}")
            if not self.dry_run:
                task_id = self.target.create(list_id, task.id, want)
                self.state["tasks"][task.id] = {"list": list_id, "id": task_id, "synced": want}
            self.stats.created += 1
            return

        if record.get("gone"):
            return

        changes = {k: want[k] for k in FIELDS if want[k] != record["synced"].get(k)}
        if changes:
            self.log(f"~ {want['title']} ({', '.join(changes)})")
            if not self.dry_run:
                try:
                    self.target.update(record["list"], record["id"], task.id, changes)
                except TargetNotFound:
                    # Deleted on the other side on purpose: do not bring it back.
                    record["gone"] = True
                    return
                record["synced"] = want
            self.stats.updated += 1
            return

        if self.config.get("complete_back") and not task.completed:
            done = self.target.is_completed(record["list"], record["id"], task.id)
            if done is None:
                record["gone"] = True
            elif done:
                self.log(f"✓ {want['title']} (Supernote'ta tamamlandı olarak işaretleniyor)")
                if not self.dry_run:
                    self.sn.complete(task)
                    record["synced"] = dict(want, completed=True)
                self.stats.completed_back += 1

    def _handle_removed(self, seen: set[str]) -> None:
        for sn_id in [i for i in self.state["tasks"] if i not in seen]:
            record = self.state["tasks"][sn_id]
            if self.config.get("delete_removed") and not record.get("gone"):
                self.log(f"- {record.get('synced', {}).get('title', sn_id)}")
                if not self.dry_run:
                    try:
                        self.target.delete(record["list"], record["id"], sn_id)
                    except TargetNotFound:
                        pass
                    except TargetError as exc:
                        self.stats.errors.append(str(exc))
                        continue
                self.stats.deleted += 1
            if not self.dry_run:
                del self.state["tasks"][sn_id]
