# LTVN OS

Персональная операционная система для продуктивности, построенная на Obsidian, FastAPI и ИИ.

Вдохновлено [Frame OS](https://www.youtube.com/watch?v=l_LL52QZz-E) — подходом, где Obsidian выступает не просто хранилищем заметок, а backend'ом для всей системы управления жизнью.

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                      LTVN OS (FastAPI)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │  Cycles  │ │ Journal  │ │  Tasks   │ │    Content     │  │
│  │  (PABO)  │ │ (metrics)│ │(Todoist) │ │ (YT/TG/Shorts) │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘  │
└──────────────────────────┬────────────────────────────────────┘
                           │ Markdown + YAML frontmatter
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Obsidian Vault (Source of Truth)         │
│  /FrameOS/Goals      /FrameOS/Cycles      /FrameOS/Tasks    │
│  /FrameOS/Journal    /FrameOS/Content       /FrameOS/Analytics
└─────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
      ┌─────────┐    ┌───────────┐    ┌──────────┐
      │ Todoist │    │  OpenRouter│    │ YouTube/ │
      │   API   │    │ (nemotron) │    │ Telegram │
      └─────────┘    └───────────┘    └──────────┘
```

## Возможности

- **PABO циклы** — 12-недельное планирование: цель → гипотезы → действия → рефлексия
- **Журнал с метриками** — mood/energy/focus (1-10) + теги для ИИ-анализа
- **ИИ-рефлексия** — автоматический разбор цикла/недели через LLM (OpenRouter)
- **Двусторонний Todoist sync** — задачи в Obsidian ↔ Todoist в реальном времени
- **Контент-конвейер** — канбан для YouTube/Telegram/Shorts: идея → публикация
- **Цели** — долгосрочные цели с категориями, метриками, дедлайнами
- **Локальный UI** — FastAPI + HTMX + Alpine.js, работает через Cloudflare Tunnel

## Быстрый старт

```bash
# 1. Клонировать
git clone https://github.com/yourusername/ltvn-os.git
cd ltvn-os

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Настроить config.yaml (скопируй из config.example.yaml)
cp config.yaml config.local.yaml
# Отредактируй: vault_path, токены API

# 4. Запустить
python -c "import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8767, reload=False)"

# 5. Открыть http://127.0.0.1:8767
```

## Конфигурация (`config.yaml`)

```yaml
app:
  host: "127.0.0.1"
  port: 8767

obsidian:
  vault_path: "C:/Users/.../Obsidian Vault"
  structure:
    goals: "FrameOS/Goals"
    cycles: "FrameOS/Cycles"
    tasks: "FrameOS/Tasks"
    journal: "FrameOS/Journal"
    content: "FrameOS/Content"
    tracking: "FrameOS/Tracking"
    analytics: "FrameOS/Analytics"

todoist:
  api_token: ""  # https://todoist.com/prefs/integrations

youtube:
  api_key: ""
  channel_id: ""

telegram:
  bot_token: ""
  channel_id: ""

ai:
  provider: "openrouter"
  model: "nvidia/nemotron-3-ultra-550b-a55b:free"
  api_key: ""
```

## Структура проекта

```
ltvn-os/
├── config.yaml              # Настройки (токены не коммить!)
├── main.py                  # FastAPI приложение
├── requirements.txt
├── core/
│   ├── obsidian.py          # Vault CRUD, модели
│   ├── pabo.py              # PABO циклы + журнал
│   ├── reflection.py        # ИИ-рефлексия
│   ├── todoist.py           # Todoist sync
│   └── content.py           # Контент-план
├── templates/               # Jinja2 + HTMX
│   ├── base.html
│   ├── dashboard.html
│   ├── cycles/
│   ├── journal/
│   ├── tasks/
│   ├── content/
│   └── goals/
└── static/style.css         # UI (dark/light, responsive)
```

## Деплой через Cloudflare Tunnel

```bash
# Установить cloudflared
# Добавить в config.yml:
ingress:
  - hostname: ltvn-os.yourdomain.com
    service: http://localhost:8767
  - service: http_status:404

# Запустить
cloudflared tunnel run --config config.yml your-tunnel-name
```

## Лицензия

MIT — используй, меняй, делай свою ОС.