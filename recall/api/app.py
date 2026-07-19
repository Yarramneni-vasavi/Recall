from __future__ import annotations

from pathlib import Path
from collections import deque
import asyncio
import time

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field

# Load .env (OPENAI_API_KEY etc.) before importing any future agent stack.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from recall.agent.service import continue_quiz, current_quiz, handle_input, quiz_summary, review_quiz, start_quiz, submit_quiz
from recall.agent.scorecard import get_score, list_scores, topic_key
from recall.api.ui_state import load_ui_state, save_ui_state
from recall.api.tasks import (
  get_task,
  new_task,
  set_task_done,
  set_task_error,
  set_task_running,
  set_task_stage,
)
from recall.observability.logger import configure_logging
from recall.db import postgres as pg

import logging

configure_logging(log_file_name="recall-api.log", console_level=logging.INFO)


class RateLimitMiddleware(BaseHTTPMiddleware):
  def __init__(self, app: FastAPI, *, max_per_minute: int = 10):
    super().__init__(app)
    self._max = max(1, int(max_per_minute))
    self._lock = asyncio.Lock()
    self._hits: dict[str, deque[float]] = {}

  async def dispatch(self, request, call_next):
    # Basic per-IP sliding window. Good enough for local dev / single process.
    client = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - 60.0
    async with self._lock:
      q = self._hits.get(client)
      if q is None:
        q = deque()
        self._hits[client] = q
      while q and q[0] < cutoff:
        q.popleft()
      if len(q) >= self._max:
        retry_after = max(1, int(60 - (now - q[0]))) if q else 60
        return JSONResponse(
          status_code=429,
          content={"error": "rate_limited", "message": "Too many requests. Limit is 10 per minute."},
          headers={"Retry-After": str(retry_after)},
        )
      q.append(now)
    return await call_next(request)


class ChatRequest(BaseModel):
  session_id: str | None = None
  text: str = Field(min_length=1, max_length=4000)


class QuizStartRequest(BaseModel):
  input: str = Field(min_length=1, max_length=4000)


class QuizSubmitAnswer(BaseModel):
  q_id: str = Field(min_length=1, max_length=100)
  answer: str = Field(min_length=0, max_length=4000)


class QuizSubmitRequest(BaseModel):
  answers: list[QuizSubmitAnswer] = Field(default_factory=list, max_length=16)


class QuizContinueRequest(BaseModel):
  action: str = Field(min_length=1, max_length=20)


class UiStateRequest(BaseModel):
  conversations: list[dict] = Field(default_factory=list)


app = FastAPI(title="RECALL API", version="0.1.0")

app.add_middleware(RateLimitMiddleware, max_per_minute=10)

app.add_middleware(
  CORSMiddleware,
  allow_origins=[
        "https://recall-ui.pages.dev",       # your Cloudflare frontend
        "http://localhost:5173",              # keep for local dev
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],            # don't allow "*" — be explicit
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/health")
def health():
  return {"ok": True}


@app.on_event("startup")
def _startup():
  # If DATABASE_URL/memory.postgres_url is set, fail fast if Postgres can't be used.
  pg.startup_check()


@app.get("/ui/state")
def ui_get_state():
  return load_ui_state()


@app.put("/ui/state")
def ui_put_state(body: UiStateRequest):
  save_ui_state({"conversations": body.conversations})
  return {"ok": True}


@app.get("/tasks/{task_id}")
def tasks_get(task_id: str):
  t = get_task(task_id)
  if t is None:
    raise HTTPException(status_code=404, detail="Unknown task_id")
  return t


@app.post("/chat")
def chat(body: ChatRequest):
  import uuid

  session_id = (body.session_id or "").strip() or str(uuid.uuid4())
  return handle_input(session_id=session_id, text=body.text)


@app.post("/quiz/{session_id}/start")
def quiz_start(session_id: str, body: QuizStartRequest):
  return start_quiz(session_id=session_id, input_text=body.input)


@app.post("/quiz/{session_id}/start_task")
def quiz_start_task(session_id: str, body: QuizStartRequest, background: BackgroundTasks):
  task_id = new_task(stage="queued")

  def run():
    try:
      set_task_running(task_id, stage="parsing")
      set_task_stage(task_id, stage="generating")
      result = start_quiz(session_id=session_id, input_text=body.input)
      set_task_done(task_id, result=result)
    except Exception as e:
      set_task_error(task_id, stage="error", error=str(e))

  background.add_task(run)
  return {"task_id": task_id}


@app.post("/quiz/{session_id}/submit")
def quiz_submit(session_id: str, body: QuizSubmitRequest):
  return submit_quiz(session_id=session_id, answers=[a.model_dump() for a in body.answers])


@app.post("/quiz/{session_id}/submit_task")
def quiz_submit_task(session_id: str, body: QuizSubmitRequest, background: BackgroundTasks):
  task_id = new_task(stage="queued")

  def run():
    try:
      set_task_running(task_id, stage="judging")
      result = submit_quiz(session_id=session_id, answers=[a.model_dump() for a in body.answers])
      set_task_done(task_id, result=result)
    except Exception as e:
      set_task_error(task_id, stage="error", error=str(e))

  background.add_task(run)
  return {"task_id": task_id}


@app.post("/quiz/{session_id}/continue")
def quiz_continue(session_id: str, body: QuizContinueRequest):
  return continue_quiz(session_id=session_id, action=body.action)


@app.get("/quiz/{session_id}/summary")
def quiz_get_summary(session_id: str):
  return quiz_summary(session_id=session_id)


@app.get("/quiz/{session_id}/current")
def quiz_get_current(session_id: str):
  return current_quiz(session_id=session_id)


@app.get("/quiz/{session_id}/review")
def quiz_get_review(session_id: str):
  return review_quiz(session_id=session_id)


@app.get("/scorecard")
def scorecard_list(limit: int = 50):
  items = [s.to_dict() for s in list_scores(limit=limit)]
  return {"items": items}


@app.get("/scorecard/{topic}")
def scorecard_get(topic: str):
  s = get_score(topic=topic)
  if s is None:
    return {"topic": topic_key(topic), "item": None}
  return {"topic": topic_key(topic), "item": s.to_dict()}
