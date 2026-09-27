"""Microsoft To Do through Microsoft Graph, signed in with the device-code flow."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import msal
import requests

from .config import write_private

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Tasks.ReadWrite"]


class ToDoError(Exception):
    pass


class ToDoAuthError(ToDoError):
    pass


class ToDoNotFound(ToDoError):
    pass


class MicrosoftAuth:
    """MSAL public client with a token cache persisted to disk."""

    def __init__(self, client_id: str, authority: str, cache_path: Path):
        if not client_id:
            raise ToDoAuthError(
                "Microsoft uygulama kimliği (client ID) ayarlı değil. README'deki "
                "'Microsoft uygulaması kaydı' adımını izleyip "
                "`supernote-todo setup` ile girin."
            )
        self.cache_path = cache_path
        self.cache = msal.SerializableTokenCache()
        if cache_path.exists():
            self.cache.deserialize(cache_path.read_text(encoding="utf-8"))
        self.app = msal.PublicClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{authority}",
            token_cache=self.cache,
        )

    def _persist(self) -> None:
        if self.cache.has_state_changed:
            write_private(self.cache_path, self.cache.serialize())

    def login(self, show: Callable[[str], None]) -> str:
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise ToDoAuthError(f"Microsoft girişi başlatılamadı: {flow.get('error_description', flow)}")
        show(flow["message"])
        result = self.app.acquire_token_by_device_flow(flow)
        self._persist()
        if "access_token" not in result:
            raise ToDoAuthError(f"Microsoft girişi başarısız: {result.get('error_description', result)}")
        claims = result.get("id_token_claims") or {}
        return claims.get("preferred_username") or claims.get("name") or "Microsoft hesabı"

    def token(self) -> str:
        accounts = self.app.get_accounts()
        result = self.app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        self._persist()
        if not result or "access_token" not in result:
            raise ToDoAuthError(
                "Microsoft oturumu yok veya süresi dolmuş. "
                "`supernote-todo login-microsoft` çalıştırın."
            )
        return result["access_token"]


class ToDoClient:
    def __init__(self, token_provider: Callable[[], str],
                 session: Optional[requests.Session] = None):
        self.token_provider = token_provider
        self.session = session or requests.Session()

    def _call(self, method: str, url: str, payload: Optional[dict] = None) -> dict:
        if not url.startswith("http"):
            url = GRAPH + url
        for attempt in range(4):
            resp = self.session.request(
                method, url, json=payload, timeout=30,
                headers={"Authorization": f"Bearer {self.token_provider()}"},
            )
            if resp.status_code in (429, 503, 504) and attempt < 3:
                time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                continue
            break
        if resp.status_code == 401:
            raise ToDoAuthError("Microsoft Graph oturumu reddetti; tekrar giriş yapın.")
        if resp.status_code == 404:
            raise ToDoNotFound(url)
        if resp.status_code >= 400:
            raise ToDoError(f"Microsoft Graph {method} {url} -> {resp.status_code}: {resp.text[:300]}")
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _paged(self, url: str) -> list[dict]:
        items: list[dict] = []
        while url:
            body = self._call("GET", url)
            items.extend(body.get("value") or [])
            url = body.get("@odata.nextLink") or ""
        return items

    # -- lists ---------------------------------------------------------------

    def lists(self) -> list[dict]:
        return self._paged("/me/todo/lists")

    def create_list(self, name: str) -> dict:
        return self._call("POST", "/me/todo/lists", {"displayName": name})

    # -- tasks ---------------------------------------------------------------

    def tasks(self, list_id: str, expand_links: bool = False) -> list[dict]:
        query = "?$top=100&$expand=linkedResources" if expand_links else "?$top=100"
        return self._paged(f"/me/todo/lists/{list_id}/tasks{query}")

    def create_task(self, list_id: str, fields: dict) -> dict:
        return self._call("POST", f"/me/todo/lists/{list_id}/tasks", fields)

    def update_task(self, list_id: str, task_id: str, fields: dict) -> dict:
        return self._call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", fields)

    def delete_task(self, list_id: str, task_id: str) -> None:
        self._call("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}")


def due_field(due: Optional[date]) -> Optional[dict]:
    if due is None:
        return None
    return {"dateTime": f"{due.isoformat()}T00:00:00.0000000", "timeZone": "UTC"}
