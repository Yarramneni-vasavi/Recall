from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from recall.config.config import config
from recall.db import postgres as pg


def _state_path() -> Path:
  base = Path(config["memory"]["db_path"]).parent
  base.mkdir(parents=True, exist_ok=True)
  return base / "ui_state.json"


def load_ui_state() -> dict[str, Any]:
  if pg.enabled():
    return pg.get_pg_store().get_ui_state()
  p = _state_path()
  if not p.exists():
    return {"conversations": []}
  try:
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
      return {"conversations": []}
    if "conversations" not in data or not isinstance(data.get("conversations"), list):
      data["conversations"] = []
    return data
  except Exception:
    return {"conversations": []}


def save_ui_state(state: dict[str, Any]) -> None:
  if pg.enabled():
    payload = state if isinstance(state, dict) else {"conversations": []}
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
      conversations = []
    pg.get_pg_store().put_ui_state(conversations=conversations, updated_at=time.time())
    return
  p = _state_path()
  tmp = p.with_suffix(".tmp")
  payload = state if isinstance(state, dict) else {"conversations": []}
  if not isinstance(payload.get("conversations"), list):
    payload["conversations"] = []
  tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  tmp.replace(p)
