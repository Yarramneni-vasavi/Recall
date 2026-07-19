from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from recall.config.config import config
from recall.memory.long_term import get_long_term_store


def topic_key(topic: str) -> str:
  t = (topic or "").strip().lower()
  t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE)
  t = re.sub(r"\s+", " ", t).strip()
  return t


@dataclass(frozen=True)
class ScoreEntry:
  topic: str
  attempts: int
  expertise: str
  level_streak: int
  ema_accuracy: float
  last_accuracy: float
  ema_difficulty: float
  last_difficulty: float

  def to_dict(self) -> dict[str, Any]:
    return {
      "topic": self.topic,
      "attempts": self.attempts,
      "expertise": self.expertise,
      "level_streak": self.level_streak,
      "ema_accuracy": self.ema_accuracy,
      "last_accuracy": self.last_accuracy,
      "ema_difficulty": self.ema_difficulty,
      "last_difficulty": self.last_difficulty,
    }


_PROJECT = "recall"
_CATEGORY = "scorecard"


def get_score(*, topic: str) -> ScoreEntry | None:
  key = topic_key(topic)
  if not key:
    return None
  store = get_long_term_store()
  rec = store.get(project=_PROJECT, category=_CATEGORY, key=key)
  if rec is None or not isinstance(rec.value, dict):
    return None
  v = rec.value
  try:
    return ScoreEntry(
      topic=str(v.get("topic") or topic),
      attempts=int(v.get("attempts") or 0),
      expertise=str(v.get("expertise") or "beginner"),
      level_streak=int(v.get("level_streak") or 0),
      ema_accuracy=float(v.get("ema_accuracy") or 0.0),
      last_accuracy=float(v.get("last_accuracy") or 0.0),
      ema_difficulty=float(v.get("ema_difficulty") or 0.0),
      last_difficulty=float(v.get("last_difficulty") or 0.0),
    )
  except Exception:
    return None


def record_performance(
  *,
  topic: str,
  accuracy: float,
  difficulty: float,
  alpha: float = 0.4,
) -> ScoreEntry | None:
  key = topic_key(topic)
  if not key:
    return None
  a = max(0.0, min(float(accuracy), 1.0))
  d = max(1.0, min(float(difficulty), 10.0))
  prev = get_score(topic=topic)

  cfg = dict(config.get("scorecard") or {})
  min_acc = float(cfg.get("min_accuracy_to_level_up") or 0.99)
  beginner_max = int(cfg.get("beginner_max_attempts") or 1)
  intermediate_max = int(cfg.get("intermediate_max_attempts") or 2)

  def _next(level: str) -> str:
    if level == "beginner":
      return "intermediate"
    if level == "intermediate":
      return "advanced"
    return "advanced"

  def _threshold(level: str) -> int:
    if level == "beginner":
      return max(1, beginner_max)
    if level == "intermediate":
      return max(1, intermediate_max)
    return 10**9

  if prev is None:
    prev_level = "beginner"
    prev_streak = 0
    prev_ema_a = a
    prev_ema_d = d
  else:
    prev_level = prev.expertise or "beginner"
    prev_streak = max(0, int(prev.level_streak))
    prev_ema_a = float(prev.ema_accuracy)
    prev_ema_d = float(prev.ema_difficulty)

  streak = (prev_streak + 1) if (a >= min_acc) else 0
  level = prev_level
  if level != "advanced" and streak >= _threshold(level):
    level = _next(level)
    streak = 0

  ema = (alpha * a) + ((1.0 - alpha) * prev_ema_a)
  ema_d = (alpha * d) + ((1.0 - alpha) * prev_ema_d)
  entry = ScoreEntry(
    topic=(prev.topic if prev is not None else topic) or topic,
    attempts=(max(0, prev.attempts) + 1) if prev is not None else 1,
    expertise=level,
    level_streak=streak,
    ema_accuracy=ema,
    last_accuracy=a,
    ema_difficulty=ema_d,
    last_difficulty=d,
  )

  store = get_long_term_store()
  store.put(project=_PROJECT, category=_CATEGORY, key=key, value=entry.to_dict(), tags=["scorecard"], source="quiz_submit")
  return entry


def list_scores(*, limit: int = 50) -> list[ScoreEntry]:
  store = get_long_term_store()
  rows = store.search(project=_PROJECT, category=_CATEGORY, limit=limit)
  out: list[ScoreEntry] = []
  for r in rows:
    if not isinstance(r.value, dict):
      continue
    v = r.value
    try:
      out.append(
        ScoreEntry(
          topic=str(v.get("topic") or r.memory_key),
          attempts=int(v.get("attempts") or 0),
          expertise=str(v.get("expertise") or "beginner"),
          level_streak=int(v.get("level_streak") or 0),
          ema_accuracy=float(v.get("ema_accuracy") or 0.0),
          last_accuracy=float(v.get("last_accuracy") or 0.0),
          ema_difficulty=float(v.get("ema_difficulty") or 0.0),
          last_difficulty=float(v.get("last_difficulty") or 0.0),
        )
      )
    except Exception:
      continue
  return out
