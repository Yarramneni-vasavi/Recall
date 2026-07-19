from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from recall.llm.factory import get_fast_llm
from recall.observability.logger import get_logger


logger = get_logger(__name__)

Level = Literal["beginner", "intermediate", "advanced"]


_LEVEL_PATTERNS: list[tuple[Level, re.Pattern[str]]] = [
  ("beginner", re.compile(r"\b(beginner|newbie|novice|fresh(er)?|noob)\b", re.I)),
  ("intermediate", re.compile(r"\b(intermediate|mid(level)?|some experience)\b", re.I)),
  ("advanced", re.compile(r"\b(advanced|expert|pro|senior)\b", re.I)),
]

_NOISE = re.compile(
  r"\b(revise|revision|learn|study|practice|help\s+me\s+with|i\s+want\s+to|i\s*'?m|i\s+am)\b",
  re.I,
)


@dataclass(frozen=True)
class ParseResult:
  topic: str | None
  level: Level | None
  session_id: str
  question_count: int = 0
  current_batch: int = 1
  needs_level: bool = False
  clarification: str | None = None


def _extract_level(text: str) -> Level | None:
  for lvl, pat in _LEVEL_PATTERNS:
    if pat.search(text):
      return lvl
  return None


def _cleanup_topic(text: str) -> str:
  t = _NOISE.sub(" ", text)
  for _, pat in _LEVEL_PATTERNS:
    t = pat.sub(" ", t)
  t = re.sub(r"[,;:]+", " ", t)
  t = re.sub(r"\s+", " ", t).strip()

  # If the user adds extra clauses after the topic (common pattern: "... python, while I'm intermediate ..."),
  # keep the prefix when the suffix looks like meta info rather than the topic itself.
  if " while " in t.lower():
    left, right = re.split(r"\bwhile\b", t, maxsplit=1, flags=re.I)
    if left.strip() and re.search(r"\b(level|that|it|i)\b", right, re.I):
      t = left.strip()

  # Trim common dangling stopwords introduced by cleanup.
  tokens = t.split()
  stop = {"a", "an", "the", "to", "for", "of", "while", "level", "that", "it", "in", "on", "at", "with", "about"}
  while tokens and tokens[0].lower() in stop:
    tokens = tokens[1:]
  while tokens and tokens[-1].lower() in stop:
    tokens = tokens[:-1]
  return " ".join(tokens).strip()


def _safe_json_from_text(raw: str) -> dict | None:
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


def parse_topic_and_level(user_input: str, *, session_id: str | None = None) -> ParseResult:
  """
  Parser Agent (ARCHITECTURE.md):
  - Extract topic + level from natural input using pattern matching + fast LLM.
  - If level is missing/ambiguous, mark needs_level and provide a clarification question.
  """
  text = (user_input or "").strip()
  if not text:
    return ParseResult(
      topic=None,
      level=None,
      session_id=session_id or str(uuid.uuid4()),
      needs_level=True,
      clarification="What topic do you want to revise, and what's your level (beginner/intermediate/advanced)?",
    )

  level = _extract_level(text)
  topic_guess = _cleanup_topic(text)
  topic = topic_guess if len(topic_guess) >= 2 else None

  # If we already got both, return without LLM.
  if topic and level:
    return ParseResult(topic=topic, level=level, session_id=session_id or str(uuid.uuid4()))

  # Use fast model to extract structured fields (if available).
  try:
    llm = get_fast_llm()
    prompt = (
      "Extract the revision topic and the user's level from the input.\n"
      "Valid levels: beginner, intermediate, advanced.\n"
      'Return ONLY valid JSON: {"topic": string|null, "level": "beginner"|"intermediate"|"advanced"|null}.\n'
      f"Input: {text!r}"
    )
    resp = llm.invoke(prompt)
    content = getattr(resp, "content", str(resp))
    parsed = _safe_json_from_text(content) or {}
    llm_topic = parsed.get("topic")
    llm_level = parsed.get("level")

    if isinstance(llm_topic, str):
      llm_topic = llm_topic.strip()
    if llm_topic:
      topic = llm_topic[:200]

    if llm_level in ("beginner", "intermediate", "advanced"):
      level = llm_level
  except Exception as e:
    logger.warning(f"Parser LLM extraction failed, falling back to heuristics: {e}")

  if not topic:
    return ParseResult(
      topic=None,
      level=level,
      session_id=session_id or str(uuid.uuid4()),
      needs_level=True,
      clarification="What topic do you want to revise?",
    )

  if not level:
    return ParseResult(
      topic=topic,
      level=None,
      session_id=session_id or str(uuid.uuid4()),
      needs_level=True,
      clarification="What's your level: beginner, intermediate, or advanced?",
    )

  return ParseResult(topic=topic, level=level, session_id=session_id or str(uuid.uuid4()))
