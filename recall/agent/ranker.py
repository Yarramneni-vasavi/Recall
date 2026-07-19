from __future__ import annotations

import json
import re
from typing import Any

from recall.agent.state import Level, Question
from recall.llm.factory import get_fast_llm
from recall.observability.logger import get_logger


logger = get_logger(__name__)


def _safe_json(raw: str) -> dict | None:
  try:
    return json.loads(raw)
  except Exception:
    pass
  m = re.search(r"\{.*\}", raw, re.S)
  if not m:
    return None
  try:
    return json.loads(m.group(0))
  except Exception:
    return None


def select_top_4(*, questions: list[Question], level: Level) -> list[Question]:
  """
  Ranker/Validator agent (small model): pick best 4 of 8.
  Falls back to first 4 on any failure to keep CLI snappy.
  """
  if len(questions) <= 4:
    return questions

  try:
    llm = get_fast_llm()
    payload: list[dict[str, Any]] = [
      {
        "q_id": q.q_id,
        "question_text": q.question_text,
        "type": q.type,
        "options": q.options,
        "difficulty_estimate": q.difficulty,
      }
      for q in questions
    ]
    prompt = (
      "You are a question ranker.\n"
      f"Stated level: {level}\n"
      "Score each question for relevance, clarity, and matches_level.\n"
      "Return ONLY JSON with keys: ranked_questions (list of {q_id, score (1-10), matches_level (bool)}), top_4 (list of 4 q_id), reason (string).\n"
      f"Questions: {json.dumps(payload, ensure_ascii=False)[:6000]}"
    )
    resp = llm.invoke(prompt)
    content = getattr(resp, "content", str(resp))
    parsed = _safe_json(content) or {}
    top = parsed.get("top_4")
    if isinstance(top, list):
      top_ids = [str(x) for x in top][:4]
      m = {q.q_id: q for q in questions}
      picked = [m[qid] for qid in top_ids if qid in m]
      if len(picked) == 4:
        return picked
  except Exception as e:
    logger.warning(f"Ranker failed, falling back to first 4: {e}")

  return questions[:4]

