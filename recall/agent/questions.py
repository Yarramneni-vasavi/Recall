from __future__ import annotations

import json
import re
from typing import Any

from recall.agent.state import Level, Question
from recall.llm.factory import get_llm
from recall.observability.logger import get_logger


logger = get_logger(__name__)


def _safe_json(raw: str) -> Any:
  try:
    return json.loads(raw)
  except Exception:
    pass
  m = re.search(r"\[.*\]", raw, re.S)
  if m:
    try:
      return json.loads(m.group(0))
    except Exception:
      return None
  m = re.search(r"\{.*\}", raw, re.S)
  if m:
    try:
      return json.loads(m.group(0))
    except Exception:
      return None
  return None


def generate_questions(
  *,
  topic: str,
  level: Level,
  batch_num: int,
  target_difficulty: float,
  previous_answers: list[dict] | None = None,
  avoid_questions: list[str] | None = None,
) -> list[Question]:
  """
  Question Generator agent: creates 8 questions (MCQ or fill_blank) with answers.
  """
  prev = previous_answers or []
  avoid = avoid_questions or []
  llm = get_llm()
  prompt = (
    "Generate exactly 8 quiz questions for spaced revision.\n"
    f"Topic: {topic}\n"
    f"User level: {level}\n"
    f"Target difficulty (1-10): {target_difficulty:.1f}\n"
    "Do NOT repeat questions that are semantically similar to the provided avoid-list.\n"
    "Types allowed: mcq, fill_blank.\n"
    "For mcq: provide exactly 4 options and a correct_answer that matches one option.\n"
    "For fill_blank: options must be null and provide a correct_answer.\n"
    "Return ONLY JSON: a list of 8 objects with keys:\n"
    'q_id (string), question_text (string), type ("mcq"|"fill_blank"), options (list[string]|null), correct_answer (string), difficulty_estimate (number 1-10).\n'
    f"Previous answers (may be empty): {json.dumps(prev, ensure_ascii=False)[:4000]}\n"
    f"Avoid-list (do not repeat): {json.dumps(avoid, ensure_ascii=False)[:4000]}\n"
  )
  resp = llm.invoke(prompt)
  content = getattr(resp, "content", str(resp))
  parsed = _safe_json(content)
  if not isinstance(parsed, list):
    raise ValueError("Question generator did not return a JSON list.")

  out: list[Question] = []
  for i, item in enumerate(parsed[:8], start=1):
    if not isinstance(item, dict):
      continue
    qid = str(item.get("q_id") or f"b{batch_num}_q{i}")
    qtype = item.get("type")
    if qtype not in ("mcq", "fill_blank"):
      qtype = "fill_blank"
    options = item.get("options")
    if qtype == "mcq":
      if not isinstance(options, list):
        options = []
      options = [str(o) for o in options][:4]
      if len(options) < 4:
        options = (options + [""] * 4)[:4]
    else:
      options = None
    diff = item.get("difficulty_estimate")
    try:
      diff_f = float(diff)
    except Exception:
      diff_f = None
    out.append(
      Question(
        q_id=qid,
        question_text=str(item.get("question_text") or "").strip()[:2000],
        type=qtype,  # type: ignore[arg-type]
        options=options,
        correct_answer=str(item.get("correct_answer") or "").strip()[:500],
        difficulty=diff_f,
        batch_num=batch_num,
      )
    )
  if len(out) < 8:
    logger.warning(f"Generated only {len(out)} questions; expected 8.")
  return out[:8]
