from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

try:
  import psycopg  # type: ignore
except Exception:  # pragma: no cover
  psycopg = None  # type: ignore

from recall.config.config import config
from recall.observability.logger import get_logger


logger = get_logger(__name__)


def postgres_dsn() -> str | None:
  # Render uses DATABASE_URL by default (and we only support env-based DSN to avoid
  # storing credentials in config files).
  dsn = (os.getenv("DATABASE_URL") or "").strip()
  return dsn or None


def configured() -> bool:
  mem_cfg = dict(config.get("memory") or {})
  if not bool(mem_cfg.get("use_postgres", False)):
    return False
  return postgres_dsn() is not None


def enabled() -> bool:
  return psycopg is not None and configured()


def connect() -> psycopg.Connection:
  if psycopg is None:
    raise RuntimeError("psycopg is not installed (add/install psycopg[binary]).")
  dsn = postgres_dsn()
  if not dsn:
    raise RuntimeError("Postgres is not configured (set DATABASE_URL).")
  return psycopg.connect(dsn, autocommit=False)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS long_term_memories (
  id            BIGSERIAL PRIMARY KEY,
  project       TEXT NOT NULL,
  category      TEXT NOT NULL,
  memory_key    TEXT NOT NULL,
  value_json    TEXT NOT NULL,
  tags_json     TEXT NOT NULL DEFAULT '[]',
  source        TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  pinned        BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(project, category, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_ltm_project_updated ON long_term_memories(project, updated_at);
CREATE INDEX IF NOT EXISTS idx_ltm_category ON long_term_memories(category);

CREATE TABLE IF NOT EXISTS tasks (
  task_id     TEXT PRIMARY KEY,
  status      TEXT NOT NULL,
  stage       TEXT NOT NULL,
  result_json TEXT,
  error       TEXT,
  updated_at  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);

CREATE TABLE IF NOT EXISTS ui_state (
  id INTEGER PRIMARY KEY,
  conversations_json TEXT NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS session_states (
  session_id TEXT PRIMARY KEY,
  state_json TEXT NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_parse (
  session_id TEXT PRIMARY KEY,
  pending_json TEXT NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

-- Minimal replacement for sqlite checkpointer usage (if any).
CREATE TABLE IF NOT EXISTS checkpoints (
  thread_id TEXT PRIMARY KEY,
  checkpoint_json TEXT NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
"""


def _json_loads(value: Any, default: Any) -> Any:
  if not isinstance(value, str) or not value:
    return default
  try:
    return json.loads(value)
  except Exception:
    return default


@dataclass(frozen=True)
class PgStore:
  def init_schema(self) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(_SCHEMA)
    finally:
      conn.close()

  # ----- UI state -----
  def put_ui_state(self, *, conversations: list[dict], updated_at: float) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(
          """
          INSERT INTO ui_state(id, conversations_json, updated_at)
          VALUES (1, %s, %s)
          ON CONFLICT (id) DO UPDATE SET conversations_json=EXCLUDED.conversations_json, updated_at=EXCLUDED.updated_at
          """,
          (json.dumps(conversations, ensure_ascii=False), float(updated_at)),
        )
    finally:
      conn.close()

  def get_ui_state(self) -> dict[str, Any]:
    conn = connect()
    try:
      row = conn.execute("SELECT conversations_json FROM ui_state WHERE id=1").fetchone()
    finally:
      conn.close()
    if not row:
      return {"conversations": []}
    conversations = _json_loads(row[0], [])
    if not isinstance(conversations, list):
      conversations = []
    return {"conversations": conversations}

  # ----- Tasks -----
  def task_create(self, *, task_id: str, status: str, stage: str, result: Any, error: str | None, updated_at: float) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(
          """
          INSERT INTO tasks(task_id,status,stage,result_json,error,updated_at)
          VALUES (%s,%s,%s,%s,%s,%s)
          ON CONFLICT (task_id) DO UPDATE SET
            status=EXCLUDED.status,
            stage=EXCLUDED.stage,
            result_json=EXCLUDED.result_json,
            error=EXCLUDED.error,
            updated_at=EXCLUDED.updated_at
          """,
          (
            task_id,
            status,
            stage,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            float(updated_at),
          ),
        )
    finally:
      conn.close()

  def task_get(self, task_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
      row = conn.execute(
        "SELECT task_id,status,stage,result_json,error,updated_at FROM tasks WHERE task_id=%s",
        (task_id,),
      ).fetchone()
    finally:
      conn.close()
    if not row:
      return None
    tid, status, stage, result_json, error, updated_at = row
    return {
      "task_id": tid,
      "status": status,
      "stage": stage,
      "result": _json_loads(result_json, None),
      "error": error,
      "updated_at": updated_at,
    }

  # ----- Session state -----
  def session_put(self, *, session_id: str, state: dict[str, Any], updated_at: float) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(
          """
          INSERT INTO session_states(session_id,state_json,updated_at)
          VALUES (%s,%s,%s)
          ON CONFLICT (session_id) DO UPDATE SET state_json=EXCLUDED.state_json, updated_at=EXCLUDED.updated_at
          """,
          (session_id, json.dumps(state, ensure_ascii=False), float(updated_at)),
        )
    finally:
      conn.close()

  def session_get(self, session_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
      row = conn.execute("SELECT state_json FROM session_states WHERE session_id=%s", (session_id,)).fetchone()
    finally:
      conn.close()
    if not row:
      return None
    state = _json_loads(row[0], None)
    return state if isinstance(state, dict) else None

  def session_delete(self, session_id: str) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute("DELETE FROM session_states WHERE session_id=%s", (session_id,))
    finally:
      conn.close()

  # ----- Pending parse -----
  def pending_put(self, *, session_id: str, pending: dict[str, Any], updated_at: float) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(
          """
          INSERT INTO pending_parse(session_id,pending_json,updated_at)
          VALUES (%s,%s,%s)
          ON CONFLICT (session_id) DO UPDATE SET pending_json=EXCLUDED.pending_json, updated_at=EXCLUDED.updated_at
          """,
          (session_id, json.dumps(pending, ensure_ascii=False), float(updated_at)),
        )
    finally:
      conn.close()

  def pending_get(self, session_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
      row = conn.execute("SELECT pending_json FROM pending_parse WHERE session_id=%s", (session_id,)).fetchone()
    finally:
      conn.close()
    if not row:
      return None
    pending = _json_loads(row[0], None)
    return pending if isinstance(pending, dict) else None

  def pending_delete(self, session_id: str) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute("DELETE FROM pending_parse WHERE session_id=%s", (session_id,))
    finally:
      conn.close()

  # ----- "Checkpointer" replacement -----
  def checkpoint_put(self, *, thread_id: str, checkpoint: dict[str, Any], updated_at: float) -> None:
    conn = connect()
    try:
      with conn:
        conn.execute(
          """
          INSERT INTO checkpoints(thread_id,checkpoint_json,updated_at)
          VALUES (%s,%s,%s)
          ON CONFLICT (thread_id) DO UPDATE SET checkpoint_json=EXCLUDED.checkpoint_json, updated_at=EXCLUDED.updated_at
          """,
          (thread_id, json.dumps(checkpoint, ensure_ascii=False), float(updated_at)),
        )
    finally:
      conn.close()

  def checkpoint_get(self, thread_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
      row = conn.execute("SELECT checkpoint_json FROM checkpoints WHERE thread_id=%s", (thread_id,)).fetchone()
    finally:
      conn.close()
    if not row:
      return None
    v = _json_loads(row[0], None)
    return v if isinstance(v, dict) else None


_PG: PgStore | None = None


def startup_check() -> None:
  """Fail fast if Postgres is configured but cannot be used.

  If Postgres isn't configured, do nothing (SQLite/files remain active).
  """
  if not configured():
    logger.info("Postgres not configured; using local SQLite/files under .memory/.")
    return
  if psycopg is None:
    raise RuntimeError("Postgres is enabled but psycopg is not installed.")
  get_pg_store()
  logger.info("Postgres configured and ready.")


def get_pg_store() -> PgStore:
  global _PG
  if _PG is None:
    _PG = PgStore()
    _PG.init_schema()
    logger.info("Initialized Postgres schema.")
  return _PG
