"""Where settings, tokens and sync state live on disk."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # Supernote account e-mail, remembered after the first login.
    "supernote_email": "",
    # Supernote Cloud session token (a JWT, valid for ~30 days).
    "supernote_token": "",
    # Where tasks go: "reminders" (Apple Reminders, macOS) or "microsoft"
    # (Microsoft To Do, needs an Azure app registration).
    "target": "reminders",
    # Application (client) ID of your own Azure app registration.
    "ms_client_id": "",
    # "consumers" for personal Microsoft accounts (outlook.com, hotmail, ...),
    # "organizations" for work/school, "common" if the app accepts both.
    "ms_authority": "consumers",
    # "mirror": one target list per Supernote list (created on demand).
    # "single": everything goes into the list named by `target_list`.
    "list_mode": "mirror",
    "target_list": "Supernote",
    # Prefix for the names of mirrored lists, e.g. "SN - " -> "SN - Work".
    "list_prefix": "",
    # Also copy tasks that are already completed on Supernote the first time
    # they are seen.
    "include_completed": False,
    # Tasks ticked off in Microsoft To Do are also ticked off on Supernote.
    "complete_back": False,
    # Tasks deleted on Supernote are deleted from Microsoft To Do as well.
    "delete_removed": False,
}


def home() -> Path:
    override = os.environ.get("SUPERNOTE_TODO_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "supernote-todo"


def config_path() -> Path:
    return home() / "config.json"


def state_path(target: str) -> Path:
    # One file per target: the task ids in it only mean something there.
    return home() / f"state-{target}.json"


def ms_cache_path() -> Path:
    return home() / "msal_cache.json"


def _read_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def write_private(path: Path, text: str) -> None:
    """Write a file readable only by the current user (it holds tokens)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def load_config() -> dict:
    config = dict(DEFAULTS)
    config.update(_read_json(config_path()))
    if os.environ.get("MS_CLIENT_ID"):
        config["ms_client_id"] = os.environ["MS_CLIENT_ID"]
    return config


def save_config(config: dict) -> None:
    write_private(config_path(), json.dumps(config, indent=2, ensure_ascii=False))


def load_state(target: str) -> dict:
    state = _read_json(state_path(target))
    state.setdefault("lists", {})
    state.setdefault("tasks", {})
    return state


def save_state(target: str, state: dict) -> None:
    write_private(state_path(target), json.dumps(state, indent=2, ensure_ascii=False))
