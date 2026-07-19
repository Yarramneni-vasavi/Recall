from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from recall.config.config import config
from recall.db import postgres as pg


@dataclass
class PendingParse:
  topic: str | None = None
  level: str | None = None
  last_clarification: str | None = None


def _dir() -> Path:
  base = Path(config["memory"]["db_path"]).parent
  d = base / "pending_parse"
  d.mkdir(parents=True, exist_ok=True)
  return d


def path(session_id: str) -> Path:
  return _dir() / f"{session_id}.json"


def load(session_id: str) -> PendingParse | None:
  if pg.enabled():
    raw = pg.get_pg_store().pending_get(session_id)
    if not raw:
      return None
    return PendingParse(
      topic=raw.get("topic"),
      level=raw.get("level"),
      last_clarification=raw.get("last_clarification"),
    )
  p = path(session_id)
  if not p.exists():
    return None
  try:
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
      return None
    return PendingParse(
      topic=raw.get("topic"),
      level=raw.get("level"),
      last_clarification=raw.get("last_clarification"),
    )
  except Exception:
    return None


def save(session_id: str, pending: PendingParse) -> None:
  if pg.enabled():
    pg.get_pg_store().pending_put(session_id=session_id, pending=asdict(pending), updated_at=time.time())
    return
  p = path(session_id)
  p.write_text(json.dumps(asdict(pending), ensure_ascii=False, indent=2), encoding="utf-8")


def clear(session_id: str) -> None:
  if pg.enabled():
    pg.get_pg_store().pending_delete(session_id)
    return
  p = path(session_id)
  if p.exists():
    p.unlink()
