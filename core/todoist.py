"""
Двусторонняя синхронизация с Todoist.
Использует Todoist REST API v2.
"""
from __future__ import annotations
import httpx
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from core.obsidian import ObsidianVault


TODOIST_API = "https://api.todoist.com/rest/v2"


@dataclass
class TodoistConfig:
    api_token: str
    sync_interval_seconds: int = 60
    project_filter: list[str] = field(default_factory=list)  # пусто = все


@dataclass
class TodoistTask:
    id: str
    content: str
    description: str = ""
    project_id: str = ""
    labels: list[str] = field(default_factory=list)
    priority: int = 1
    due: dict | None = None  # {"date": "2024-01-15", "recurring": false}
    completed: bool = False
    created_at: str = ""
    updated_at: str = ""


class TodoistSync:
    def __init__(self, config: TodoistConfig, vault: ObsidianVault):
        self.config = config
        self.vault = vault
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {config.api_token}"},
            timeout=30.0,
        )

    # ─── API wrappers ───

    async def _get(self, path: str, params: dict | None = None):
        resp = await self.client.get(f"{TODOIST_API}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: dict):
        resp = await self.client.post(f"{TODOIST_API}{path}", json=json)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str):
        resp = await self.client.delete(f"{TODOIST_API}{path}")
        resp.raise_for_status()

    # ─── Read ───

    async def get_tasks(self, filter: str = "") -> list[TodoistTask]:
        params = {}
        if filter:
            params["filter"] = filter
        elif self.config.project_filter:
            # фильтр по проектам: ##project_name
            params["filter"] = " | ".join(f"##{p}" for p in self.config.project_filter)
        data = await self._get("/tasks", params)
        return [self._parse_task(t) for t in data]

    async def get_projects(self) -> list[dict]:
        return await self._get("/projects")

    def _parse_task(self, data: dict) -> TodoistTask:
        return TodoistTask(
            id=data["id"],
            content=data["content"],
            description=data.get("description", ""),
            project_id=data.get("project_id", ""),
            labels=data.get("labels", []),
            priority=data.get("priority", 1),
            due=data.get("due"),
            completed=data.get("is_completed", False),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    # ─── Write ───

    async def create_task(self, content: str, **kwargs) -> TodoistTask:
        data = await self._post("/tasks", {"content": content, **kwargs})
        return self._parse_task(data)

    async def update_task(self, task_id: str, **kwargs) -> TodoistTask:
        data = await self._post(f"/tasks/{task_id}", kwargs)
        return self._parse_task(data)

    async def complete_task(self, task_id: str) -> None:
        await self._post(f"/tasks/{task_id}/close", {})

    async def reopen_task(self, task_id: str) -> None:
        await self._post(f"/tasks/{task_id}/reopen", {})

    async def delete_task(self, task_id: str) -> None:
        await self._delete(f"/tasks/{task_id}")

    # ─── Sync with Obsidian ───

    async def push_to_obsidian(self) -> dict:
        """Todoist → Obsidian (mirror задач в vault)."""
        tasks = await self.get_tasks()
        results = {"created": 0, "updated": 0, "skipped": 0}

        for task in tasks:
            slug = f"todoist-{task.id}"
            meta = {
                "source": "todoist",
                "todoist_id": task.id,
                "content": task.content,
                "description": task.description,
                "project_id": task.project_id,
                "labels": task.labels,
                "priority": task.priority,
                "due": task.due,
                "completed": task.completed,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "synced_at": datetime.now().isoformat(),
            }
            content = task.description or ""

            try:
                existing = self.vault.read("tasks", slug)
                if existing:
                    self.vault.update("tasks", slug, meta, content)
                    results["updated"] += 1
                else:
                    self.vault.create("tasks", slug, meta, content)
                    results["created"] += 1
            except Exception:
                results["skipped"] += 1

        return results

    async def pull_from_obsidian(self) -> dict:
        """Obsidian → Todoist (создать задачи из vault, помеченные для синка)."""
        # Ищем задачи в vault с флагом sync_to_todoist=true
        tasks_meta = self.vault.list_with_meta("tasks")
        results = {"created": 0, "updated": 0, "errors": 0}

        for meta in tasks_meta:
            if not meta.get("sync_to_todoist"):
                continue

            slug = meta["_slug"]
            _, content = self.vault.read("tasks", slug)

            try:
                if meta.get("todoist_id"):
                    # Обновить существующую
                    await self.update_task(meta["todoist_id"], content=meta.get("content", slug))
                    results["updated"] += 1
                else:
                    # Создать новую
                    task = await self.create_task(
                        content=meta.get("content", slug),
                        description=content,
                        project_id=meta.get("project_id"),
                        labels=meta.get("labels", []),
                        priority=meta.get("priority", 1),
                    )
                    # Обновить vault с новым ID
                    self.vault.update("tasks", slug, {"todoist_id": task.id, "synced_at": datetime.now().isoformat()})
                    results["created"] += 1
            except Exception:
                results["errors"] += 1

        return results

    async def full_sync(self) -> dict:
        """Полная двусторонняя синхронизация."""
        push = await self.push_to_obsidian()
        pull = await self.pull_from_obsidian()
        return {"push": push, "pull": pull}

    async def close(self):
        await self.client.aclose()


# ─── Sync wrapper ───

import asyncio

def full_sync_sync(config: TodoistConfig, vault: ObsidianVault) -> dict:
    sync = TodoistSync(config, vault)
    try:
        return asyncio.run(sync.full_sync())
    finally:
        asyncio.run(sync.close())