"""
ИИ-рефлексия циклов через OpenRouter / Hermes.
Получает контекст цикла → просит модель дать глубокий анализ.
"""
from __future__ import annotations
import json
import httpx
from dataclasses import dataclass
from typing import Optional
from core.pabo import PABOManager
from core.obsidian import ObsidianVault, JournalEntry


@dataclass
class AIConfig:
    provider: str = "openrouter"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    api_base: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    max_tokens: int = 4000
    temperature: float = 0.3


REFLECTION_PROMPT = """Ты — стратегический коуч и аналитик. Твоя задача — провести глубокую рефлексию завершённого периода (недели/цикла) на основе личных данных пользователя.

ДАННЫЕ ЦИКЛА:
{cycle_json}

ДНЕВНИК ЗА ПЕРИОД:
{journal_json}

АКТИВНЫЕ ЦЕЛИ:
{goals_json}

ИНСТРУКЦИЯ:
Проанализируй и верни JSON со структурой:
{{
  "summary": "Краткое резюме периода (3-5 предложений)",
  "achievements": ["Что удалось сделать", "..."],
  "failures": ["Что не получилось и почему", "..."],
  "patterns": ["Наблюдаемые паттерны поведения/мышления", "..."],
  "hypothesis_check": [
    {{"hypothesis": "Гипотеза из цикла", "verdict": "confirmed/refuted/partial", "evidence": "Доказательства из дневника/метрик"}}
  ],
  "metrics_trend": {{
    "mood": "trend description",
    "energy": "trend description",
    "focus": "trend description"
  }},
  "insights": ["Ключевые инсайты", "..."],
  "adjustments": ["Корректировки на следующий период", "..."],
  "next_actions": ["Конкретные следующие шаги", "..."]
}}

Будь честным, конкретным, без воды. Используй данные из дневника как доказательную базу."""


WEEKLY_REFLECTION_PROMPT = """Ты — коуч для еженедельного обзора. Данные за неделю {week} цикла {cycle_number}.

ДНЕВНИК ЗА НЕДЕЛЮ:
{journal_json}

ЦЕЛИ НЕДЕЛИ (из действий цикла):
{actions_json}

Верни JSON:
{{
  "week_summary": "Резюме недели",
  "completed": ["Что сделано"],
  "blocked": ["Что застряло и почему"],
  "mood_energy_focus": {{"mood": N, "energy": N, "focus": N}},
  "key_insight": "Главный инсайт недели",
  "adjustment": "Что изменить на следующей неделе"
}}"""


class ReflectionEngine:
    def __init__(self, config: AIConfig, pabo: PABOManager):
        self.config = config
        self.pabo = pabo
        self.client = httpx.AsyncClient(timeout=60.0)

    async def _call_llm(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        resp = await self.client.post(
            f"{self.config.api_base}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Вытащить JSON из ответа (модель может обернуть в ```json)."""
        # Попробуем найти ```json ... ```
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
        return json.loads(text)

    async def reflect_cycle(self, cycle_slug: str) -> dict:
        """Полная рефлексия цикла (в конце 12 недель)."""
        context = self.pabo.build_reflection_context(cycle_slug)
        if not context:
            return {"error": "Cycle not found"}

        prompt = REFLECTION_PROMPT.format(
            cycle_json=json.dumps(context["cycle"], ensure_ascii=False, indent=2),
            journal_json=json.dumps(context["journal"], ensure_ascii=False, indent=2),
            goals_json=json.dumps(context["active_goals"], ensure_ascii=False, indent=2),
        )
        raw = await self._call_llm(prompt)
        result = self._extract_json(raw)

        # Сохранить рефлексию в vault
        reflection_entry = {
            "type": "cycle_reflection",
            "cycle_slug": cycle_slug,
            "content": result,
            "raw_response": raw,
        }
        self.pabo.vault.create(
            "journal",
            f"reflection-{cycle_slug}-{context['cycle']['number']:02d}",
            reflection_entry,
            json.dumps(result, ensure_ascii=False, indent=2),
        )
        return result

    async def reflect_week(self, cycle_slug: str, week: int) -> dict:
        """Еженедельная рефлексия."""
        cycle = self.pabo.get_cycle(cycle_slug)
        if not cycle:
            return {"error": "Cycle not found"}

        entries = self.pabo.get_journal_entries(cycle_slug, week)
        journal_data = [
            {
                "date": e.date,
                "content": e.content,
                "mood": e.mood,
                "energy": e.energy,
                "focus": e.focus,
                "tags": e.tags,
            }
            for e in entries
        ]

        prompt = WEEKLY_REFLECTION_PROMPT.format(
            week=week,
            cycle_number=cycle.number,
            journal_json=json.dumps(journal_data, ensure_ascii=False, indent=2),
            actions_json=json.dumps(cycle.actions, ensure_ascii=False, indent=2),
        )
        raw = await self._call_llm(prompt)
        result = self._extract_json(raw)

        # Сохранить
        self.pabo.vault.create(
            "journal",
            f"weekly-reflection-{cycle_slug}-w{week:02d}",
            {"type": "weekly_reflection", "cycle_slug": cycle_slug, "week": week, "content": result},
            json.dumps(result, ensure_ascii=False, indent=2),
        )
        return result

    async def close(self):
        await self.client.aclose()


# ─── Sync wrapper для синхронного вызова из FastAPI ───

import asyncio

def reflect_cycle_sync(config: AIConfig, pabo: PABOManager, cycle_slug: str) -> dict:
    engine = ReflectionEngine(config, pabo)
    try:
        return asyncio.run(engine.reflect_cycle(cycle_slug))
    finally:
        asyncio.run(engine.close())

def reflect_week_sync(config: AIConfig, pabo: PABOManager, cycle_slug: str, week: int) -> dict:
    engine = ReflectionEngine(config, pabo)
    try:
        return asyncio.run(engine.reflect_week(cycle_slug, week))
    finally:
        asyncio.run(engine.close())