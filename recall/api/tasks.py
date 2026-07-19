from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from recall.config.config import config
from recall.db import postgres as pg


Status = Literal["pending", "running", "done", "error"]


def _db_path() -> Path:
  p = Path(config["memory"]["db_path"])
  p.parent.mkdir(parents=True, exist_ok=True)
  return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id     TEXT PRIMARY KEY,
  status      TEXT NOT NULL,
  stage       TEXT NOT NULL,
  result_json TEXT,
  error       TEXT,
  updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);
"""


def _connect() -> sqlite3.Connection:
  conn = sqlite3.connect(_db_path(), check_same_thread=False)
  conn.execute("PRAGMA journal_mode=WAL;")
  conn.executescript(_SCHEMA)
  return conn


def new_task(*, stage: str = "queued") -> str:
  task_id = str(uuid.uuid4())
  now = time.time()
  if pg.enabled():
    pg.get_pg_store().task_create(task_id=task_id, status="pending", stage=stage, result=None, error=None, updated_at=now)
    return task_id
  conn = _connect()
  try:
    with conn:
      conn.execute(
        "INSERT INTO tasks(task_id,status,stage,result_json,error,updated_at) VALUES (?,?,?,?,?,?)",
        (task_id, "pending", stage, None, None, now),
      )
  finally:
    conn.close()
  return task_id


def set_task_running(task_id: str, *, stage: str) -> None:
  if pg.enabled():
    existing = pg.get_pg_store().task_get(task_id)
    pg.get_pg_store().task_create(
      task_id=task_id,
      status="running",
      stage=stage,
      result=(existing or {}).get("result"),
      error=(existing or {}).get("error"),
      updated_at=time.time(),
    )
    return
  conn = _connect()
  try:
    with conn:
      conn.execute(
        "UPDATE tasks SET status=?, stage=?, updated_at=? WHERE task_id=?",
        ("running", stage, time.time(), task_id),
      )
  finally:
    conn.close()


def set_task_stage(task_id: str, *, stage: str) -> None:
  if pg.enabled():
    existing = pg.get_pg_store().task_get(task_id)
    if not existing:
      pg.get_pg_store().task_create(
        task_id=task_id,
        status="running",
        stage=stage,
        result=None,
        error=None,
        updated_at=time.time(),
      )
      return
    pg.get_pg_store().task_create(
      task_id=task_id,
      status=str(existing.get("status") or "running"),
      stage=stage,
      result=existing.get("result"),
      error=existing.get("error"),
      updated_at=time.time(),
    )
    return
  conn = _connect()
  try:
    with conn:
      conn.execute(
        "UPDATE tasks SET stage=?, updated_at=? WHERE task_id=?",
        (stage, time.time(), task_id),
      )
  finally:
    conn.close()


def set_task_done(task_id: str, *, result: Any) -> None:
  if pg.enabled():
    pg.get_pg_store().task_create(
      task_id=task_id,
      status="done",
      stage="done",
      result=result,
      error=None,
      updated_at=time.time(),
    )
    return
  conn = _connect()
  try:
    with conn:
      conn.execute(
        "UPDATE tasks SET status=?, stage=?, result_json=?, error=?, updated_at=? WHERE task_id=?",
        ("done", "done", json.dumps(result, ensure_ascii=False), None, time.time(), task_id),
      )
  finally:
    conn.close()


def set_task_error(task_id: str, *, stage: str, error: str) -> None:
  if pg.enabled():
    pg.get_pg_store().task_create(
      task_id=task_id,
      status="error",
      stage=stage,
      result=None,
      error=str(error)[:2000],
      updated_at=time.time(),
    )
    return
  conn = _connect()
  try:
    with conn:
      conn.execute(
        "UPDATE tasks SET status=?, stage=?, result_json=?, error=?, updated_at=? WHERE task_id=?",
        ("error", stage, None, str(error)[:2000], time.time(), task_id),
      )
  finally:
    conn.close()


def get_task(task_id: str) -> dict[str, Any] | None:
  if pg.enabled():
    return pg.get_pg_store().task_get(task_id)
  conn = _connect()
  try:
    row = conn.execute(
      "SELECT task_id,status,stage,result_json,error,updated_at FROM tasks WHERE task_id=?",
      (task_id,),
    ).fetchone()
  finally:
    conn.close()
  if not row:
    return None
  tid, status, stage, result_json, error, updated_at = row
  result = None
  if isinstance(result_json, str) and result_json:
    try:
      result = json.loads(result_json)
    except Exception:
      result = result_json
  return {
    "task_id": tid,
    "status": status,
    "stage": stage,
    "result": result,
    "error": error,
    "updated_at": updated_at,
  }
