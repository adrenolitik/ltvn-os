"""
Контент-планирование (YouTube, Telegram, Shorts) + аналитика.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from core.obsidian import ObsidianVault, ContentItem


@dataclass
class ContentManager:
    vault: ObsidianVault

    # ─── Content CRUD ───

    def create_content(self, item: ContentItem) -> ContentItem:
        meta, content = item.to_markdown()
        self.vault.create("content", item.slug, meta, content)
        return item

    def get_content(self, slug: str) -> ContentItem | None:
        result = self.vault.read("content", slug)
        if not result:
            return None
        meta, content = result
        return ContentItem.from_meta(meta, content)

    def update_content(self, slug: str, **kwargs) -> ContentItem | None:
        item = self.get_content(slug)
        if not item:
            return None
        for k, v in kwargs.items():
            if hasattr(item, k):
                setattr(item, k, v)
        item.updated = datetime.now().isoformat()
        meta, content = item.to_markdown()
        self.vault.update("content", slug, meta, content)
        return item

    def list_content(
        self,
        platform: str | None = None,
        status: str | None = None,
    ) -> list[ContentItem]:
        items = []
        for meta in self.vault.list_with_meta("content"):
            if platform and meta.get("platform") != platform:
                continue
            if status and meta.get("status") != status:
                continue
            _, content = self.vault.read("content", meta["_slug"])
            items.append(ContentItem.from_meta(meta, content))
        return sorted(items, key=lambda x: x.created, reverse=True)

    def get_pipeline(self, platform: str) -> dict[str, list[ContentItem]]:
        """Канбан-доска по стадиям для платформы."""
        stages = ["idea", "research", "script", "filming", "editing", "scheduled", "published"]
        result = {stage: [] for stage in stages}
        for item in self.list_content(platform=platform):
            result[item.stage].append(item)
        return result

    # ─── YouTube specific ───

    def create_youtube_video(
        self,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        publish_date: str | None = None,
    ) -> ContentItem:
        slug = f"yt-{title.lower().replace(' ', '-')[:50]}-{date.today().isoformat()}"
        return self.create_content(ContentItem(
            slug=slug,
            platform="youtube",
            title=title,
            description=description,
            tags=tags or [],
            publish_date=publish_date,
            stage="idea",
            status="idea",
        ))

    def update_youtube_stats(self, slug: str, views: int, likes: int, comments: int, subscribers: int) -> ContentItem | None:
        return self.update_content(slug, stats={
            "views": views,
            "likes": likes,
            "comments": comments,
            "subscribers_gained": subscribers,
            "updated_at": datetime.now().isoformat(),
        })

    # ─── Telegram specific ───

    def create_telegram_post(
        self,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
        publish_date: str | None = None,
    ) -> ContentItem:
        slug = f"tg-{title.lower().replace(' ', '-')[:50]}-{date.today().isoformat()}"
        return self.create_content(ContentItem(
            slug=slug,
            platform="telegram",
            title=title,
            description=content,
            tags=tags or [],
            publish_date=publish_date,
            stage="idea",
            status="idea",
        ))

    def update_telegram_stats(self, slug: str, views: int, forwards: int, reactions: dict) -> ContentItem | None:
        return self.update_content(slug, stats={
            "views": views,
            "forwards": forwards,
            "reactions": reactions,
            "updated_at": datetime.now().isoformat(),
        })


# ─── Analytics (placeholder — подключим API позже) ───

@dataclass
class AnalyticsManager:
    vault: ObsidianVault

    def export_youtube_analytics(self, channel_id: str, api_key: str) -> dict:
        """Заглушка — подключить YouTube Data API v3."""
        return {
            "channel_id": channel_id,
            "note": "Требует YouTube Data API v3 ключ. Реализуй в core/analytics.py",
            "metrics": {},
        }

    def export_telegram_analytics(self, channel_id: str, bot_token: str) -> dict:
        """Заглушка — подключить Telegram Bot API / TDLib."""
        return {
            "channel_id": channel_id,
            "note": "Требует Telegram Bot API. Реализуй в core/analytics.py",
            "metrics": {},
        }

    def save_analytics_snapshot(self, platform: str, data: dict) -> str:
        """Сохранить снапшот аналитики в vault."""
        slug = f"analytics-{platform}-{date.today().isoformat()}"
        self.vault.create("analytics", slug, {"platform": platform, "date": date.today().isoformat()}, "")
        # Обновим с реальными данными
        self.vault.update("analytics", slug, data, json.dumps(data, ensure_ascii=False, indent=2))
        return slug

    def get_analytics_history(self, platform: str, days: int = 30) -> list[dict]:
        """История аналитики за N дней."""
        import json
        from datetime import timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        results = []
        for meta in self.vault.list_with_meta("analytics"):
            if meta.get("platform") == platform and meta.get("date", "") >= cutoff:
                _, content = self.vault.read("analytics", meta["_slug"])
                try:
                    results.append(json.loads(content))
                except Exception:
                    pass
        return sorted(results, key=lambda x: x.get("date", ""))

import json