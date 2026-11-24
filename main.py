"""
Frame OS — FastAPI + HTMX + Alpine.js локальный дашборд.
"""
from __future__ import annotations
import os
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.obsidian import create_vault, Goal, Cycle, JournalEntry, ContentItem
from core.pabo import PABOManager, next_cycle_number
from core.todoist import TodoistConfig, TodoistSync, full_sync_sync
from core.reflection import AIConfig, reflect_cycle_sync, reflect_week_sync
from core.content import ContentManager, AnalyticsManager


# ─── Config & State ───

class AppState:
    vault = None
    pabo = None
    todoist_config = None
    ai_config = None
    content_mgr = None
    analytics_mgr = None

state = AppState()


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cfg = load_config()
    vault = create_vault(cfg["obsidian"]["vault_path"], cfg["obsidian"]["structure"])
    state.vault = vault
    state.pabo = PABOManager(vault, cycle_weeks=cfg["pabo"]["cycle_weeks"])
    state.todoist_config = TodoistConfig(**cfg["todoist"])
    state.ai_config = AIConfig(**cfg["ai"])
    state.content_mgr = ContentManager(vault)
    state.analytics_mgr = AnalyticsManager(vault)
    print(f"[Frame OS] Vault: {cfg['obsidian']['vault_path']}")
    print(f"[Frame OS] Ready on http://127.0.0.1:8765")
    yield
    # Shutdown
    print("[Frame OS] Shutdown")


app = FastAPI(title="Frame OS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 environment (workaround for Starlette/Jinja2 cache key bug)
jinja_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

# Custom Jinja2 filters
def date_to_days(date_str: str) -> int:
    """Convert YYYY-MM-DD to days since epoch for arithmetic."""
    try:
        return (datetime.fromisoformat(date_str).date() - date(1970, 1, 1)).days
    except Exception:
        return 0

jinja_env.filters["date_to_days"] = date_to_days


def render_template(name: str, context: dict) -> HTMLResponse:
    """Render template with Jinja2 directly (sync)."""
    template = jinja_env.get_template(name)
    return HTMLResponse(content=template.render(context))


# ─── Helpers ───

def current_cycle():
    return state.pabo.get_current_cycle()


def today_iso():
    return date.today().isoformat()


# ─── API Models ───

class CycleCreate(BaseModel):
    title: str
    main_goal: str = ""
    additional_goals: list[str] = []
    hypotheses: list[str] = []
    actions: list[str] = []


class JournalCreate(BaseModel):
    cycle_slug: str
    week: int
    content: str = ""
    mood: Optional[int] = None
    energy: Optional[int] = None
    focus: Optional[int] = None
    tags: list[str] = []


class ContentCreate(BaseModel):
    platform: str
    title: str
    description: str = ""
    tags: list[str] = []
    publish_date: Optional[str] = None


# ─── Routes: Main Dashboard ───

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    cycle = current_cycle()
    tasks_meta = state.vault.list_with_meta("tasks")
    today_tasks = [t for t in tasks_meta if t.get("due", {}).get("date") == today_iso() or not t.get("due")]
    overdue_tasks = [t for t in tasks_meta if t.get("due", {}).get("date", "") < today_iso() and not t.get("completed")]

    return render_template("dashboard.html", {
        "request": request,
        "cycle": cycle,
        "today_tasks": today_tasks[:10],
        "overdue_tasks": overdue_tasks[:10],
        "today": today_iso(),
    })


# ─── Routes: Cycles (PABO) ───

@app.get("/cycles", response_class=HTMLResponse)
async def cycles_list(request: Request):
    cycles_meta = state.vault.list_with_meta("cycles")
    cycles = []
    for meta in cycles_meta:
        c = state.pabo.get_cycle(meta["_slug"])
        if c:
            cycles.append(c)
    return render_template("cycles/list.html", {
        "request": request,
        "cycles": sorted(cycles, key=lambda x: x.number, reverse=True),
    })


@app.get("/cycles/new", response_class=HTMLResponse)
async def cycle_new_form(request: Request):
    next_num = next_cycle_number(state.vault)
    return render_template("cycles/new.html", {
        "request": request,
        "next_number": next_num,
        "today": today_iso(),
    })


@app.post("/cycles/new")
async def cycle_create(
    title: str = Form(...),
    main_goal: str = Form(""),
    additional_goals: str = Form(""),
    hypotheses: str = Form(""),
    actions: str = Form(""),
    start_date: str = Form(...),
):
    next_num = next_cycle_number(state.vault)
    cycle = state.pabo.create_cycle(
        number=next_num,
        title=title,
        start_date=date.fromisoformat(start_date),
        main_goal=main_goal,
        additional_goals=[g.strip() for g in additional_goals.split("\n") if g.strip()],
        hypotheses=[h.strip() for h in hypotheses.split("\n") if h.strip()],
        actions=[a.strip() for a in actions.split("\n") if a.strip()],
    )
    return RedirectResponse(f"/cycles/{cycle.slug}", status_code=303)


@app.get("/cycles/{slug}", response_class=HTMLResponse)
async def cycle_detail(request: Request, slug: str):
    cycle = state.pabo.get_cycle(slug)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    # Обновить фазу/неделю
    state.pabo.update_cycle_phase(slug)
    cycle = state.pabo.get_cycle(slug)  # re-fetch

    entries = state.pabo.get_journal_entries(slug)
    return render_template("cycles/detail.html", {
        "request": request,
        "cycle": cycle,
        "entries": entries,
        "today": today_iso(),
    })


@app.post("/cycles/{slug}/action")
async def cycle_add_action(slug: str, action: str = Form(...)):
    state.pabo.add_action_to_cycle(slug, action)
    return RedirectResponse(f"/cycles/{slug}", status_code=303)


# ─── Routes: Journal / Reflection ───

@app.get("/journal", response_class=HTMLResponse)
async def journal_list(request: Request):
    cycle = current_cycle()
    entries = []
    if cycle:
        entries = state.pabo.get_journal_entries(cycle.slug)
    return render_template("journal/list.html", {
        "request": request,
        "cycle": cycle,
        "entries": entries,
    })


@app.get("/journal/new", response_class=HTMLResponse)
async def journal_new_form(request: Request):
    cycle = current_cycle()
    return render_template("journal/new.html", {
        "request": request,
        "cycle": cycle,
        "today": today_iso(),
    })


@app.post("/journal/new")
async def journal_create(
    cycle_slug: str = Form(...),
    week: int = Form(...),
    content: str = Form(""),
    mood: Optional[int] = Form(None),
    energy: Optional[int] = Form(None),
    focus: Optional[int] = Form(None),
    tags: str = Form(""),
):
    state.pabo.create_journal_entry(
        cycle_slug=cycle_slug,
        week=week,
        content=content,
        mood=mood,
        energy=energy,
        focus=focus,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    return RedirectResponse(f"/cycles/{cycle_slug}", status_code=303)


@app.post("/reflect/cycle/{slug}")
async def reflect_cycle_endpoint(slug: str):
    if not state.ai_config.api_key:
        return {"error": "AI API key not configured"}
    result = reflect_cycle_sync(state.ai_config, state.pabo, slug)
    return result


@app.post("/reflect/week/{slug}/{week}")
async def reflect_week_endpoint(slug: str, week: int):
    if not state.ai_config.api_key:
        return {"error": "AI API key not configured"}
    result = reflect_week_sync(state.ai_config, state.pabo, slug, week)
    return result


# ─── Routes: Tasks (Todoist mirror) ───

@app.get("/tasks", response_class=HTMLResponse)
async def tasks_list(request: Request):
    tasks_meta = state.vault.list_with_meta("tasks")
    # Сортировка: overdue → today → future → no date → completed
    def sort_key(t):
        due = t.get("due", {}).get("date", "9999-99-99")
        completed = t.get("completed", False)
        return (completed, due)
    tasks = sorted(tasks_meta, key=sort_key)
    return render_template("tasks/list.html", {
        "request": request,
        "tasks": tasks,
        "today": today_iso(),
    })


@app.post("/tasks/sync")
async def tasks_sync():
    if not state.todoist_config.api_token:
        return {"error": "Todoist token not configured"}
    result = full_sync_sync(state.todoist_config, state.vault)
    return result


@app.post("/tasks/{slug}/toggle")
async def task_toggle(slug: str):
    meta = state.vault.read("tasks", slug)
    if not meta:
        raise HTTPException(404, "Task not found")
    meta, content = meta
    todoist_id = meta.get("todoist_id")
    completed = not meta.get("completed", False)

    # Обновить в vault
    state.vault.update("tasks", slug, {"completed": completed, "synced_at": datetime.now().isoformat()})

    # Если есть todoist_id — синхронизировать
    if todoist_id and state.todoist_config.api_token:
        sync = TodoistSync(state.todoist_config, state.vault)
        try:
            if completed:
                await sync.complete_task(todoist_id)
            else:
                await sync.reopen_task(todoist_id)
        finally:
            await sync.close()

    return {"ok": True, "completed": completed}


# ─── Routes: Content ───

@app.get("/content", response_class=HTMLResponse)
async def content_list(request: Request, platform: str = ""):
    items = state.content_mgr.list_content(platform=platform or None)
    pipeline = {}
    if platform:
        pipeline = state.content_mgr.get_pipeline(platform)
    return render_template("content/list.html", {
        "request": request,
        "items": items,
        "platform": platform,
        "pipeline": pipeline,
    })


@app.get("/content/new", response_class=HTMLResponse)
async def content_new_form(request: Request):
    return render_template("content/new.html", {"request": request})


@app.post("/content/new")
async def content_create(
    platform: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    publish_date: str = Form(""),
):
    item = state.content_mgr.create_content(ContentItem(
        slug=f"{platform[:2]}-{title.lower().replace(' ', '-')[:40]}-{today_iso()}",
        platform=platform,
        title=title,
        description=description,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        publish_date=publish_date or None,
    ))
    return RedirectResponse(f"/content?platform={platform}", status_code=303)


# ─── Routes: Goals ───

@app.get("/goals", response_class=HTMLResponse)
async def goals_list(request: Request):
    goals = state.pabo.list_goals()
    return render_template("goals/list.html", {
        "request": request,
        "goals": goals,
    })


# ─── Static files check ───

@app.get("/health")
async def health():
    return {"status": "ok", "vault": str(state.vault.config.vault_path) if state.vault else "not initialized"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8766, reload=True)