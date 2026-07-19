from __future__ import annotations

import json
import re
from typing import Any

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


def summarize_strengths_and_weaknesses(*, items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
  """
  Uses fast LLM to extract strong/weak areas from all answered questions.
  Returns (strong_areas, weak_areas).
  """
  llm = get_fast_llm()
  payload = [
    {
      "q_id": it.get("q_id"),
      "question_text": it.get("question_text"),
      "correct": it.get("correct"),
      "user_answer": it.get("user_answer"),
      "correct_answer": it.get("correct_answer"),
      "explanation": it.get("explanation"),
    }
    for it in items
  ]
  prompt = (
    "Given the quiz history, identify the user's strong areas and weak areas.\n"
    "Strong areas should reflect topics/patterns answered correctly.\n"
    "Weak areas should reflect concepts the user missed or misunderstood.\n"
    "Return ONLY JSON with keys: strong_areas (list[string], 0-6), weak_areas (list[string], 0-6).\n"
    f"History: {json.dumps(payload, ensure_ascii=False)[:12000]}"
  )
  resp = llm.invoke(prompt)
  content = getattr(resp, "content", str(resp))
  parsed = _safe_json(content) or {}
  strong = parsed.get("strong_areas")
  weak = parsed.get("weak_areas")
  if not isinstance(strong, list):
    strong = []
  if not isinstance(weak, list):
    weak = []
  strong_out = [str(x).strip() for x in strong if str(x).strip()][:6]
  weak_out = [str(x).strip() for x in weak if str(x).strip()][:6]
  return strong_out, weak_out

