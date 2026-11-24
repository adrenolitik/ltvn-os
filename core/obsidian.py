"""
Frame OS Core — работа с Obsidian vault как с FS-хранилищем.
Markdown + YAML frontmatter = единая источник правды.
"""
from __future__ import annotations
import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from datetime import datetime, date
import frontmatter


@dataclass
class VaultConfig:
    vault_path: Path
    structure: dict[str, str]

    def get_path(self, key: str) -> Path:
        """Получить абсолютный путь к секции vault."""
        rel = self.structure.get(key, f"FrameOS/{key.title()}")
        return self.vault_path / rel

    def ensure_dirs(self):
        for p in self.structure.values():
            (self.vault_path / p).mkdir(parents=True, exist_ok=True)


class ObsidianVault:
    """Обёртка над файловой системой vault: CRUD для markdown-файлов с frontmatter."""

    def __init__(self, config: VaultConfig):
        self.config = config
        self.config.ensure_dirs()

    # ─── Low-level ───

    def _read_raw(self, path: Path) -> tuple[dict, str]:
        """Прочитать файл → (frontmatter_dict, body)."""
        if not path.exists():
            return {}, ""
        post = frontmatter.load(path)
        return post.metadata, post.content

    def _write_raw(self, path: Path, metadata: dict, content: str):
        """Записать файл с frontmatter."""
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(content, **metadata)
        frontmatter.dump(post, path)

    # ─── High-level: generic CRUD ───

    def create(self, section: str, slug: str, metadata: dict, content: str = "") -> Path:
        """Создать новый файл в секции."""
        path = self.config.get_path(section) / f"{slug}.md"
        if path.exists():
            raise FileExistsError(f"Файл уже существует: {path}")
        metadata.setdefault("created", datetime.now().isoformat())
        metadata.setdefault("updated", datetime.now().isoformat())
        metadata.setdefault("slug", slug)
        metadata.setdefault("section", section)
        self._write_raw(path, metadata, content)
        return path

    def read(self, section: str, slug: str) -> tuple[dict, str] | None:
        path = self.config.get_path(section) / f"{slug}.md"
        if not path.exists():
            return None
        return self._read_raw(path)

    def update(self, section: str, slug: str, metadata: dict | None = None, content: str | None = None) -> Path:
        path = self.config.get_path(section) / f"{slug}.md"
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        meta, body = self._read_raw(path)
        if metadata:
            meta.update(metadata)
        meta["updated"] = datetime.now().isoformat()
        new_content = content if content is not None else body
        self._write_raw(path, meta, new_content)
        return path

    def delete(self, section: str, slug: str) -> bool:
        path = self.config.get_path(section) / f"{slug}.md"
        if path.exists():
            path.unlink()
            return True
        return False

    def list(self, section: str, pattern: str = "*.md") -> list[Path]:
        return sorted(self.config.get_path(section).glob(pattern))

    def list_with_meta(self, section: str, pattern: str = "*.md") -> list[dict]:
        """Список файлов с их frontmatter (для дашбордов)."""
        results = []
        for path in self.list(section, pattern):
            meta, _ = self._read_raw(path)
            meta["_path"] = str(path)
            meta["_slug"] = path.stem
            results.append(meta)
        return results

    # ─── Поиск ───

    def search(self, section: str, query: str, fields: list[str] | None = None) -> list[dict]:
        """Простой полнотекстовый поиск по frontmatter + body."""
        query_lower = query.lower()
        results = []
        for path in self.list(section):
            meta, body = self._read_raw(path)
            haystack = " ".join([
                str(meta.get(f, "")) for f in (fields or list(meta.keys()))
            ] + [body]).lower()
            if query_lower in haystack:
                meta["_path"] = str(path)
                meta["_slug"] = path.stem
                results.append(meta)
        return results


# ─── Специализированные модели для Frame OS ───

@dataclass
class Goal:
    slug: str
    title: str
    description: str = ""
    category: str = "general"  # health, career, learning, finance, etc.
    status: str = "active"     # active, done, archived
    target_date: str | None = None
    metrics: dict = field(default_factory=dict)  # KPI для отслеживания
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_meta(cls, meta: dict, content: str) -> "Goal":
        return cls(
            slug=meta.get("slug", ""),
            title=meta.get("title", ""),
            description=content.strip(),
            category=meta.get("category", "general"),
            status=meta.get("status", "active"),
            target_date=meta.get("target_date"),
            metrics=meta.get("metrics", {}),
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
        )

    def to_meta(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("slug", "description")}

    def to_markdown(self) -> tuple[dict, str]:
        return self.to_meta(), self.description


@dataclass
class Cycle:
    """PABO 12-недельный цикл."""
    slug: str
    number: int
    title: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    main_goal: str = ""
    additional_goals: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    status: str = "planning"  # planning, execution, review, done
    phase: str = "planning"
    week: int = 1
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def current_week(self) -> int:
        start = datetime.fromisoformat(self.start_date).date()
        today = date.today()
        delta = (today - start).days
        return max(1, min(12, delta // 7 + 1))

    @property
    def is_active(self) -> bool:
        return self.status in ("planning", "execution")

    @classmethod
    def from_meta(cls, meta: dict, content: str) -> "Cycle":
        return cls(
            slug=meta.get("slug", ""),
            number=meta.get("number", 0),
            title=meta.get("title", ""),
            start_date=meta.get("start_date", ""),
            end_date=meta.get("end_date", ""),
            main_goal=meta.get("main_goal", ""),
            additional_goals=meta.get("additional_goals", []),
            hypotheses=meta.get("hypotheses", []),
            actions=meta.get("actions", []),
            status=meta.get("status", "planning"),
            phase=meta.get("phase", "planning"),
            week=meta.get("week", 1),
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
        )

    def to_meta(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("slug",)}

    def to_markdown(self) -> tuple[dict, str]:
        body = []
        if self.main_goal:
            body.append(f"## Главная цель\n{self.main_goal}\n")
        if self.additional_goals:
            body.append("## Дополнительные направления\n" + "\n".join(f"- {g}" for g in self.additional_goals) + "\n")
        if self.hypotheses:
            body.append("## Гипотезы\n" + "\n".join(f"- {h}" for h in self.hypotheses) + "\n")
        if self.actions:
            body.append("## Конкретные действия\n" + "\n".join(f"- [ ] {a}" for a in self.actions) + "\n")
        return self.to_meta(), "\n".join(body)


@dataclass
class JournalEntry:
    slug: str
    cycle_slug: str
    week: int
    date: str
    content: str = ""
    mood: int | None = None          # 1-10
    energy: int | None = None        # 1-10
    focus: int | None = None         # 1-10
    tags: list[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_meta(cls, meta: dict, content: str) -> "JournalEntry":
        return cls(
            slug=meta.get("slug", ""),
            cycle_slug=meta.get("cycle_slug", ""),
            week=meta.get("week", 1),
            date=meta.get("date", ""),
            content=content.strip(),
            mood=meta.get("mood"),
            energy=meta.get("energy"),
            focus=meta.get("focus"),
            tags=meta.get("tags", []),
            created=meta.get("created", ""),
        )

    def to_meta(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("slug", "content")}

    def to_markdown(self) -> tuple[dict, str]:
        return self.to_meta(), self.content


@dataclass
class ContentItem:
    """Единица контент-плана (видео, пост, тред)."""
    slug: str
    platform: str  # youtube, telegram, shorts, reel
    title: str
    status: str = "idea"  # idea, research, script, filming, editing, scheduled, published
    stage: str = "idea"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    publish_date: str | None = None
    stats: dict = field(default_factory=dict)  # views, likes, etc. после публикации
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_meta(cls, meta: dict, content: str) -> "ContentItem":
        return cls(
            slug=meta.get("slug", ""),
            platform=meta.get("platform", "youtube"),
            title=meta.get("title", ""),
            status=meta.get("status", "idea"),
            stage=meta.get("stage", "idea"),
            description=content.strip(),
            tags=meta.get("tags", []),
            publish_date=meta.get("publish_date"),
            stats=meta.get("stats", {}),
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
        )

    def to_meta(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("slug", "description")}

    def to_markdown(self) -> tuple[dict, str]:
        return self.to_meta(), self.description


# ─── Фабрика ───

def create_vault(vault_path: str, structure: dict[str, str]) -> ObsidianVault:
    config = VaultConfig(Path(vault_path), structure)
    return ObsidianVault(config)