from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from recall.config.config import config
from recall.db import postgres as pg


Level = Literal["beginner", "intermediate", "advanced"]
QuizQuestionType = Literal["mcq", "fill_blank"]


@dataclass
class Question:
  q_id: str
  question_text: str
  type: QuizQuestionType
  options: list[str] | None = None
  correct_answer: str | None = None
  difficulty: float | None = None
  batch_num: int = 1
  user_answer: str | None = None
  correct: bool | None = None
  explanation: str | None = None


@dataclass
class SessionStats:
  total_correct: int = 0
  total_questions: int = 0
  current_accuracy: float = 0.0


@dataclass
class SessionState:
  session_id: str
  topic: str
  stated_level: Level
  question_count: int = 0
  current_batch: int = 1
  target_difficulty: float = 5.0
  awaiting_continue: bool = False
  next_prompt_at: int = 20
  max_questions: int = 20
  ended: bool = False
  pending_questions: list[Question] = field(default_factory=list)
  pending_index: int = 0
  all_questions: list[Question] = field(default_factory=list)
  session_stats: SessionStats = field(default_factory=SessionStats)
  review_summary: dict | None = None


def _state_dir() -> Path:
  # Keep state under the memory directory so it's portable/configurable.
  base = Path(config["memory"]["db_path"]).parent
  d = base / "sessions"
  d.mkdir(parents=True, exist_ok=True)
  return d


def state_path(session_id: str) -> Path:
  return _state_dir() / f"{session_id}.json"


def load_state(session_id: str) -> SessionState | None:
  if pg.enabled():
    raw = pg.get_pg_store().session_get(session_id)
    if not raw:
      return None
    stats = SessionStats(**(raw.get("session_stats") or {}))
    pending = [Question(**q) for q in (raw.get("pending_questions") or [])]
    all_q = [Question(**q) for q in (raw.get("all_questions") or [])]
    return SessionState(
      session_id=raw["session_id"],
      topic=raw["topic"],
      stated_level=raw["stated_level"],
      question_count=int(raw.get("question_count", 0)),
      current_batch=int(raw.get("current_batch", 1)),
      target_difficulty=float(raw.get("target_difficulty", 5.0)),
      awaiting_continue=bool(raw.get("awaiting_continue", False)),
      next_prompt_at=int(raw.get("next_prompt_at", 20)),
      max_questions=int(raw.get("max_questions", 20)),
      ended=bool(raw.get("ended", False)),
      pending_questions=pending,
      pending_index=int(raw.get("pending_index", 0)),
      all_questions=all_q,
      session_stats=stats,
      review_summary=raw.get("review_summary"),
    )
  p = state_path(session_id)
  if not p.exists():
    return None
  raw = json.loads(p.read_text(encoding="utf-8"))
  stats = SessionStats(**(raw.get("session_stats") or {}))
  pending = [Question(**q) for q in (raw.get("pending_questions") or [])]
  all_q = [Question(**q) for q in (raw.get("all_questions") or [])]
  return SessionState(
    session_id=raw["session_id"],
    topic=raw["topic"],
    stated_level=raw["stated_level"],
    question_count=int(raw.get("question_count", 0)),
    current_batch=int(raw.get("current_batch", 1)),
    target_difficulty=float(raw.get("target_difficulty", 5.0)),
    awaiting_continue=bool(raw.get("awaiting_continue", False)),
    next_prompt_at=int(raw.get("next_prompt_at", 20)),
    max_questions=int(raw.get("max_questions", 20)),
    ended=bool(raw.get("ended", False)),
    pending_questions=pending,
    pending_index=int(raw.get("pending_index", 0)),
    all_questions=all_q,
    session_stats=stats,
    review_summary=raw.get("review_summary"),
  )


def save_state(state: SessionState) -> None:
  if pg.enabled():
    pg.get_pg_store().session_put(session_id=state.session_id, state=asdict(state), updated_at=time.time())
    return
  p = state_path(state.session_id)
  payload: dict[str, Any] = asdict(state)
  p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_state(session_id: str) -> None:
  if pg.enabled():
    pg.get_pg_store().session_delete(session_id)
    return
  p = state_path(session_id)
  if p.exists():
    p.unlink()
