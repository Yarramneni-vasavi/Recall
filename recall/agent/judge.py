from __future__ import annotations

import json
import re
from typing import Any, Literal

from recall.agent.state import Level, Question
from recall.llm.factory import get_llm
from recall.observability.logger import get_logger


logger = get_logger(__name__)

Adjustment = Literal["same", "easier", "harder"]


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


def judge_batch(
  *,
  answered: list[Question],
  level: Level,
) -> tuple[float, str, Adjustment, str, list[dict[str, Any]], list[str]]:
  """
  Evaluator/AI Judge: returns (accuracy, assessment, adjustment, feedback[]).
  """
  llm = get_llm()
  qa = [
    {
      "q_id": q.q_id,
      "question_text": q.question_text,
      "type": q.type,
      "options": q.options,
      "correct_answer": q.correct_answer,
      "user_answer": q.user_answer,
    }
    for q in answered
  ]
  prompt = (
    "You are an AI judge for a quiz session.\n"
    f"Stated level: {level}\n"
    "Evaluate each answer vs the correct answer. Be strict but fair.\n"
    "Also identify weak areas based on incorrect answers (short bullet-like phrases).\n"
    "Return ONLY JSON with keys:\n"
    "accuracy (0-1), assessment (string), next_level_adjustment (same|easier|harder),\n"
    "adjustment_reason (string),\n"
    "weak_areas (list[string], 1-6 items),\n"
    "feedback (list of {q_id, correct (bool), explanation (string)}).\n"
    f"User answers: {json.dumps(qa, ensure_ascii=False)[:8000]}"
  )
  resp = llm.invoke(prompt)
  content = getattr(resp, "content", str(resp))
  parsed = _safe_json(content)
  if not isinstance(parsed, dict):
    raise ValueError("Judge did not return valid JSON.")

  try:
    accuracy = float(parsed.get("accuracy", 0.0))
  except Exception:
    accuracy = 0.0
  assessment = str(parsed.get("assessment") or "").strip()[:1000]
  adj = parsed.get("next_level_adjustment")
  if adj not in ("same", "easier", "harder"):
    adj = "same"
  reason = str(parsed.get("adjustment_reason") or "").strip()[:500]
  if not reason:
    reason = "No reason provided."
  fb = parsed.get("feedback")
  if not isinstance(fb, list):
    fb = []
  weak = parsed.get("weak_areas")
  if not isinstance(weak, list):
    weak = []
  weak = [str(x).strip() for x in weak if isinstance(x, (str, int, float)) and str(x).strip()][:6]
  return accuracy, assessment, adj, reason, fb, weak  # type: ignore[return-value]


def apply_feedback(answered: list[Question], feedback: list[dict[str, Any]]) -> None:
  m = {q.q_id: q for q in answered}
  for item in feedback:
    if not isinstance(item, dict):
      continue
    qid = item.get("q_id")
    if qid not in m:
      continue
    q = m[qid]
    q.correct = bool(item.get("correct"))
    exp = item.get("explanation")
    if isinstance(exp, str) and exp.strip():
      q.explanation = exp.strip()[:2000]
