# RECALL — revise smarter, not longer

RECALL is a quiz-first learning assistant:
- You give a topic (ex: “revise python, I’m intermediate”)
- It parses topic + level, generates a batch of questions, judges your answers, and adapts difficulty
- UI shows chat + quiz + scorecard across sessions

## Project Structure

Backend (`recall/`):
- `recall/api/app.py`: FastAPI app + CORS + rate limiting + task endpoints
- `recall/agent/`: core “agent chain” (parser → questions → ranker → judge → review)
- `recall/agent/state.py`: session state persistence (Postgres if enabled, else `.memory/sessions/*.json`)
- `recall/agent/pending_parse.py`: “topic/level missing” follow-ups persistence
- `recall/memory/long_term.py`: long-term scorecard store (Postgres if enabled, else `.memory/long_term.db`)
- `recall/api/tasks.py`: in-memory DB for async task status (Postgres if enabled, else `.memory/memory.db`)
- `recall/api/ui_state.py`: conversation list store for UI (Postgres if enabled, else `.memory/ui_state.json`)
- `recall/db/postgres.py`: Postgres schema + persistence helpers (uses `DATABASE_URL`)

Frontend (`recall-ui/`):
- Vite + React UI (3 columns: conversations, chat, quiz + review)

## Architecture (brief)

Session flow (see `ARCHITECTURE.md`):
1. **Parser** runs once per new session to extract `topic` and `level` (or asks for missing level).
2. **Question Generator** creates a batch (internally 8, UI shows best 4).
3. **Ranker/Validator** picks the best 4 questions for the stated level.
4. **AI Judge** evaluates answers, updates accuracy, adjusts difficulty, and prepares the next batch.

Limits:
- Per-session max questions is configurable (`recall/config.yaml` → `quiz.max_questions_per_session`, default 20).

## Run Backend (FastAPI)

Prereqs:
- Python 3.11+
- `OPENAI_API_KEY` in `.env` (or environment)

Install + run:

```bash
poetry install
poetry run uvicorn recall.api.app:app --reload --port 8000
```

Health check:
- `GET http://localhost:8000/health`

API reference:
- See `API.md`

## Run Frontend (UI)

Prereqs:
- Node 18+

Configure API base URL (optional):
- `VITE_API_BASE_URL` (defaults to `http://localhost:8000`)

Run:

```bash
cd recall-ui
npm install
npm run dev
```

## Persistence (Local vs Render/Postgres)

By default (local dev), state persists under `.memory/`:
- `.memory/memory.db`: SQLite task/status DB (and any short-term bits still using sqlite)
- `.memory/long_term.db`: long-term scorecard store (per-topic accuracy/attempts/level)
- `.memory/sessions/*.json`: per-session quiz state
- `.memory/pending_parse/*.json`: “missing level/topic” follow-up state
- `.memory/ui_state.json`: UI conversation list

For hosting (Render), enable Postgres-backed persistence:
- Set `memory.use_postgres: true` in `recall/config.yaml`
- Set `DATABASE_URL` in environment (Render Postgres provides this)
- Ensure `psycopg[binary]` is installed in the runtime (use Poetry build/run commands)

Recommended Render commands:
- Build: `pip install poetry && poetry install --only main --no-interaction --no-ansi`
- Start: `poetry run uvicorn recall.api.app:app --host 0.0.0.0 --port $PORT`
