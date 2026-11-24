"""
PABO Framework — 12-недельные циклы планирования.
Цель → Гипотезы → Действия → Рефлексия.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from core.obsidian import ObsidianVault, Cycle, JournalEntry, Goal


@dataclass
class PABOManager:
    vault: ObsidianVault
    cycle_weeks: int = 12

    # ─── Cycles ───

    def create_cycle(
        self,
        number: int,
        title: str,
        start_date: date | None = None,
        main_goal: str = "",
        additional_goals: list[str] | None = None,
        hypotheses: list[str] | None = None,
        actions: list[str] | None = None,
    ) -> Cycle:
        """Создать новый 12-недельный цикл."""
        if start_date is None:
            start_date = date.today()
        end_date = start_date + timedelta(weeks=self.cycle_weeks)

        slug = f"cycle-{number:02d}-{start_date.isoformat()}"
        cycle = Cycle(
            slug=slug,
            number=number,
            title=title,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            main_goal=main_goal,
            additional_goals=additional_goals or [],
            hypotheses=hypotheses or [],
            actions=actions or [],
            status="planning",
            phase="planning",
            week=1,
        )
        meta, content = cycle.to_markdown()
        self.vault.create("cycles", slug, meta, content)
        return cycle

    def get_cycle(self, slug: str) -> Cycle | None:
        result = self.vault.read("cycles", slug)
        if not result:
            return None
        meta, content = result
        return Cycle.from_meta(meta, content)

    def get_current_cycle(self) -> Cycle | None:
        """Найти активный цикл (по датам или статусу)."""
        cycles_meta = self.vault.list_with_meta("cycles")
        today = date.today().isoformat()
        for meta in cycles_meta:
            cycle = Cycle.from_meta(meta, "")
            if cycle.start_date <= today <= cycle.end_date:
                return self.get_cycle(cycle.slug)
        # fallback: последний planning/execution
        for meta in reversed(cycles_meta):
            if meta.get("status") in ("planning", "execution"):
                return self.get_cycle(meta["_slug"])
        return None

    def update_cycle_phase(self, slug: str):
        """Авто-переключение фаз по неделям."""
        cycle = self.get_cycle(slug)
        if not cycle:
            return
        week = cycle.current_week
        if week == 1:
            phase, status = "planning", "planning"
        elif week <= 11:
            phase, status = "execution", "execution"
        else:
            phase, status = "review", "review"
        if phase != cycle.phase:
            self.vault.update("cycles", slug, {"phase": phase, "status": status, "week": week})
        else:
            self.vault.update("cycles", slug, {"week": week})

    def add_action_to_cycle(self, slug: str, action: str) -> Cycle | None:
        cycle = self.get_cycle(slug)
        if not cycle:
            return None
        cycle.actions.append(action)
        meta, content = cycle.to_markdown()
        self.vault.update("cycles", slug, meta, content)
        return cycle

    def link_todoist_task(self, slug: str, task_id: str, task_content: str) -> Cycle | None:
        """Связать Todoist-задачу с действием цикла (в метаданных)."""
        cycle = self.get_cycle(slug)
        if not cycle:
            return None
        linked = cycle.__dict__.setdefault("linked_tasks", [])
        linked.append({"id": task_id, "content": task_content, "linked_at": datetime.now().isoformat()})
        meta, content = cycle.to_markdown()
        meta["linked_tasks"] = linked
        self.vault.update("cycles", slug, meta, content)
        return cycle

    # ─── Journal / Reflection ───

    def create_journal_entry(
        self,
        cycle_slug: str,
        week: int,
        content: str = "",
        mood: int | None = None,
        energy: int | None = None,
        focus: int | None = None,
        tags: list[str] | None = None,
    ) -> JournalEntry:
        today = date.today().isoformat()
        slug = f"journal-{cycle_slug}-w{week:02d}-{today}"
        entry = JournalEntry(
            slug=slug,
            cycle_slug=cycle_slug,
            week=week,
            date=today,
            content=content,
            mood=mood,
            energy=energy,
            focus=focus,
            tags=tags or [],
        )
        meta, body = entry.to_markdown()
        self.vault.create("journal", slug, meta, body)
        return entry

    def get_journal_entries(self, cycle_slug: str, week: int | None = None) -> list[JournalEntry]:
        entries = []
        for meta in self.vault.list_with_meta("journal"):
            if meta.get("cycle_slug") == cycle_slug:
                if week is None or meta.get("week") == week:
                    _, content = self.vault.read("journal", meta["_slug"])
                    entries.append(JournalEntry.from_meta(meta, content))
        return sorted(entries, key=lambda e: e.date)

    # ─── Goals ───

    def create_goal(self, goal: Goal) -> Goal:
        meta, content = goal.to_markdown()
        self.vault.create("goals", goal.slug, meta, content)
        return goal

    def get_goal(self, slug: str) -> Goal | None:
        result = self.vault.read("goals", slug)
        if not result:
            return None
        meta, content = result
        return Goal.from_meta(meta, content)

    def list_goals(self, status: str | None = None) -> list[Goal]:
        goals = []
        for meta in self.vault.list_with_meta("goals"):
            if status is None or meta.get("status") == status:
                _, content = self.vault.read("goals", meta["_slug"])
                goals.append(Goal.from_meta(meta, content))
        return goals

    # ─── Context for AI reflection ───

    def build_reflection_context(self, cycle_slug: str) -> dict:
        """Собрать полный контекст цикла для ИИ-рефлексии."""
        cycle = self.get_cycle(cycle_slug)
        if not cycle:
            return {}

        entries = self.get_journal_entries(cycle_slug)
        goals = self.list_goals("active")

        return {
            "cycle": {
                "number": cycle.number,
                "title": cycle.title,
                "phase": cycle.phase,
                "week": cycle.week,
                "main_goal": cycle.main_goal,
                "additional_goals": cycle.additional_goals,
                "hypotheses": cycle.hypotheses,
                "actions": cycle.actions,
                "start_date": cycle.start_date,
                "end_date": cycle.end_date,
            },
            "journal": [
                {
                    "date": e.date,
                    "week": e.week,
                    "content": e.content,
                    "mood": e.mood,
                    "energy": e.energy,
                    "focus": e.focus,
                    "tags": e.tags,
                }
                for e in entries
            ],
            "active_goals": [
                {
                    "title": g.title,
                    "category": g.category,
                    "metrics": g.metrics,
                }
                for g in goals
            ],
            "generated_at": datetime.now().isoformat(),
        }


# ─── Helpers ───

def next_cycle_number(vault: ObsidianVault) -> int:
    """Определить номер следующего цикла."""
    cycles = vault.list_with_meta("cycles")
    if not cycles:
        return 1
    return max(c.get("number", 0) for c in cycles) + 1