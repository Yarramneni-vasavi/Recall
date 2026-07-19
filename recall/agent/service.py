from __future__ import annotations

from typing import Any

from recall.agent.engine import (
  current_question,
  ensure_questions_with_stage,
  finalize_batch_if_ready,
  handle_continue_response,
  init_state,
  record_batch_answers,
  record_answer,
)
from recall.agent.parser import parse_topic_and_level
from recall.agent.scorecard import record_performance
from recall.agent.state import clear_state, load_state, save_state
from recall.agent.pending_parse import PendingParse, clear as clear_pending, load as load_pending, save as save_pending
from recall.agent.review import summarize_strengths_and_weaknesses


def _question_payload(q) -> dict[str, Any]:
  return {
    "q_id": q.q_id,
    "question_text": q.question_text,
    "type": q.type,
    "options": q.options,
    "batch_num": q.batch_num,
  }


def handle_input(*, session_id: str, text: str) -> dict[str, Any]:
  """
  Shared entrypoint for both CLI and API.
  Contract: takes (session_id, user text) and returns a JSON-serializable dict.
  """
  user_text = (text or "").strip()
  state = load_state(session_id)

  # First turn: parse once, then start session.
  if state is None:
    result = parse_topic_and_level(user_text, session_id=session_id)
    if result.needs_level:
      return {
        "session_id": session_id,
        "kind": "clarification",
        "message": result.clarification or "Need more information.",
      }

    state = init_state(
      session_id=session_id,
      topic=(result.topic or "").strip(),
      level=(result.level or "beginner"),
    )
    ensure_questions_with_stage(state, stage=None)
    q = current_question(state)
    save_state(state)
    return {
      "session_id": session_id,
      "kind": "question" if q is not None else "info",
      "topic": state.topic,
      "level": state.stated_level,
      "question_count": state.question_count,
      "message": "Session started.",
      "question": _question_payload(q) if q is not None else None,
    }

  # Continue prompt turn.
  if state.awaiting_continue:
    should_continue = handle_continue_response(state, text=user_text)
    if not should_continue:
      clear_state(session_id)
      return {"session_id": session_id, "kind": "end", "message": "Session ended."}
    if state.awaiting_continue:
      save_state(state)
      return {
        "session_id": session_id,
        "kind": "continue",
        "message": "Continue? (y/n)",
        "question_count": state.question_count,
      }
    ensure_questions_with_stage(state, stage=None)
    q = current_question(state)
    save_state(state)
    return {
      "session_id": session_id,
      "kind": "question" if q is not None else "info",
      "message": "Continuing.",
      "question_count": state.question_count,
      "question": _question_payload(q) if q is not None else None,
  }

  # Normal answer turn.
  ensure_questions_with_stage(state, stage=None)
  q = current_question(state)
  if q is None:
    ensure_questions_with_stage(state, stage=None)
    q = current_question(state)
  if q is None:
    save_state(state)
    return {"session_id": session_id, "kind": "error", "message": "No question available."}

  record_answer(state, answer=user_text)
  completed, judge = finalize_batch_if_ready(state)

  ensure_questions_with_stage(state, stage=None)
  q2 = current_question(state)
  save_state(state)

  if state.awaiting_continue:
    return {
      "session_id": session_id,
      "kind": "continue",
      "message": "Reached 20 questions. Continue? (y/n)",
      "question_count": state.question_count,
      "judge": judge if completed else None,
    }

  if completed:
    return {
      "session_id": session_id,
      "kind": "judge",
      "message": "Batch evaluated.",
      "question_count": state.question_count,
      "judge": judge,
      "question": _question_payload(q2) if q2 is not None else None,
    }

  return {
    "session_id": session_id,
    "kind": "question" if q2 is not None else "info",
    "question_count": state.question_count,
    "question": _question_payload(q2) if q2 is not None else None,
  }


def start_quiz(*, session_id: str, input_text: str) -> dict[str, Any]:
  """
  Batch-oriented API: parse once and return the first 4 questions.
  """
  user_text = (input_text or "").strip()
  pending = load_pending(session_id)
  state = load_state(session_id)
  if state is None:
    result = parse_topic_and_level(user_text, session_id=session_id)

    # If we have a pending partial parse, try to complete it using this turn.
    if pending is not None:
      topic = result.topic or pending.topic
      level = result.level or pending.level
      if topic and level:
        clear_pending(session_id)
        state = init_state(session_id=session_id, topic=str(topic).strip(), level=level)  # type: ignore[arg-type]
      else:
        pending = PendingParse(
          topic=topic,
          level=level,
          last_clarification=result.clarification or pending.last_clarification,
        )
        save_pending(session_id, pending)
        return {
          "session_id": session_id,
          "topic": topic,
          "level": level,
          "questions": [],
          "batch_info": {"batch_num": 0, "question_count": 0},
          "clarification": pending.last_clarification or "Need more information.",
        }

    if state is None:
      if result.needs_level:
        # Store partial info so the next user message can answer just the missing field (eg "I'm beginner").
        save_pending(
          session_id,
          PendingParse(topic=result.topic, level=result.level, last_clarification=result.clarification),
        )
        return {
          "session_id": session_id,
          "topic": result.topic,
          "level": result.level,
          "questions": [],
          "batch_info": {"batch_num": 0, "question_count": 0},
          "clarification": result.clarification or "Need more information.",
        }
      clear_pending(session_id)
      state = init_state(
        session_id=session_id,
        topic=(result.topic or "").strip(),
        level=(result.level or "beginner"),
      )

  ensure_questions_with_stage(state, stage=None)
  questions = [_question_payload(q) for q in state.pending_questions[state.pending_index :]]
  save_state(state)
  return {
    "session_id": session_id,
    "topic": state.topic,
    "level": state.stated_level,
    "questions": [
      {"q_id": q["q_id"], "text": q["question_text"], "options": q["options"], "type": q["type"]}
      for q in questions
    ],
    "batch_info": {
      "batch_num": state.current_batch,
      "question_count": state.question_count + len(questions),
    },
  }


def submit_quiz(*, session_id: str, answers: list[dict[str, str]]) -> dict[str, Any]:
  """
  Batch-oriented API: submit answers for the current 4 questions, run judge, and return feedback/stats.
  """
  state = load_state(session_id)
  if state is None:
    return {"error": "Unknown session_id"}
  # If already ended (before this submission), reject.
  if getattr(state, "ended", False):
    state.ended = True
    save_state(state)
    return {"error": "questions_limit_reached", "message": "Questions limit reached for this session."}

  answers_by_id: dict[str, str] = {}
  for item in answers or []:
    if not isinstance(item, dict):
      continue
    qid = (item.get("q_id") or "").strip()
    if not qid:
      continue
    answers_by_id[qid] = str(item.get("answer") or "")

  record_batch_answers(state, answers=answers_by_id)
  completed, judge = finalize_batch_if_ready(state)
  save_state(state)

  fb = (judge or {}).get("feedback") if isinstance(judge, dict) else None
  if not isinstance(fb, list):
    fb = []
  weak = (judge or {}).get("weak_areas") if isinstance(judge, dict) else None
  if not isinstance(weak, list):
    weak = []
  weak = [str(x) for x in weak if str(x).strip()][:6]

  accuracy = (judge or {}).get("accuracy") if isinstance(judge, dict) else 0.0
  try:
    acc_f = float(accuracy)
  except Exception:
    acc_f = 0.0

  level_adj = (judge or {}).get("next_level_adjustment") if isinstance(judge, dict) else "same"
  if level_adj not in ("easier", "same", "harder"):
    level_adj = "same"

  score_entry = None
  if state.topic:
    try:
      batch_diff = 0.0
      if isinstance(judge, dict) and isinstance(judge.get("batch_difficulty"), (int, float)):
        batch_diff = float(judge["batch_difficulty"])
      if batch_diff <= 0.0:
        batch_diff = float(state.target_difficulty)
      score_entry = record_performance(topic=state.topic, accuracy=acc_f, difficulty=batch_diff)
    except Exception:
      score_entry = None

  return {
    "feedback": fb,
    "batch_stats": {"accuracy": acc_f, "questions_answered": 4},
    "weak_areas": weak,
    "scorecard_entry": score_entry.to_dict() if score_entry is not None else None,
    "next_batch": {
      "level_adjustment": level_adj,
      "total_questions_so_far": state.question_count,
      "continue_prompt": None,
    },
    "ended": bool(getattr(state, "ended", False)),
    "message": "Questions limit reached for this session." if getattr(state, "ended", False) else None,
  }


def continue_quiz(*, session_id: str, action: str) -> dict[str, Any]:
  """
  Batch-oriented API: continue (or end) and return next 4 questions.
  """
  state = load_state(session_id)
  if state is None:
    return {"error": "Unknown session_id"}
  if getattr(state, "ended", False) or state.question_count >= state.max_questions:
    state.ended = True
    save_state(state)
    return {"error": "questions_limit_reached", "ended": True, "message": "Questions limit reached for this session.", "questions": []}

  a = (action or "").strip().lower()
  if a in ("no", "n", "stop", "end", "quit", "exit"):
    clear_state(session_id)
    return {"questions": [], "ended": True}

  # Continuation is not allowed once the session reaches max_questions.

  ensure_questions_with_stage(state, stage=None)
  questions = [_question_payload(q) for q in state.pending_questions[state.pending_index :]]
  save_state(state)

  return {
    "questions": [
      {"q_id": q["q_id"], "text": q["question_text"], "options": q["options"], "type": q["type"]}
      for q in questions
    ],
    "batch_info": {
      "batch_num": state.current_batch,
      "question_count": state.question_count + len(questions),
    },
  }


def quiz_summary(*, session_id: str) -> dict[str, Any]:
  state = load_state(session_id)
  if state is None:
    return {"error": "Unknown session_id"}
  return {
    "total_questions": state.question_count,
    "accuracy": state.session_stats.current_accuracy,
    "final_level": state.stated_level,
    "topics_strong": [],
    "topics_weak": [],
  }


def current_quiz(*, session_id: str) -> dict[str, Any]:
  """
  UI helper: return the current pending batch/question for an existing session_id.
  """
  state = load_state(session_id)
  if state is None:
    pending = load_pending(session_id)
    if pending is None:
      return {"error": "Unknown session_id"}
    return {
      "session_id": session_id,
      "clarification": pending.last_clarification or "Need more information.",
      "topic": pending.topic,
      "level": pending.level,
      "questions": [],
      "pending_index": 0,
      "batch_info": {"batch_num": 0, "question_count": 0},
    }

  if state.awaiting_continue:
    return {
      "session_id": session_id,
      "continue_prompt": None,
      "topic": state.topic,
      "level": state.stated_level,
      "questions": [],
      "pending_index": 0,
      "batch_info": {"batch_num": state.current_batch, "question_count": state.question_count},
    }

  if getattr(state, "ended", False) or state.question_count >= state.max_questions:
    state.ended = True
    save_state(state)
    return {
      "session_id": session_id,
      "ended": True,
      "message": "Questions limit reached for this session.",
      "topic": state.topic,
      "level": state.stated_level,
      "questions": [],
      "pending_index": 0,
      "batch_info": {"batch_num": state.current_batch, "question_count": state.question_count},
    }

  ensure_questions_with_stage(state, stage=None)
  questions = [_question_payload(q) for q in state.pending_questions[state.pending_index :]]
  save_state(state)
  return {
    "session_id": session_id,
    "topic": state.topic,
    "level": state.stated_level,
    "questions": [
      {"q_id": q["q_id"], "text": q["question_text"], "options": q["options"], "type": q["type"]}
      for q in questions
    ],
    "pending_index": int(state.pending_index),
    "batch_info": {"batch_num": state.current_batch, "question_count": state.question_count + len(questions)},
  }


def review_quiz(*, session_id: str) -> dict[str, Any]:
  state = load_state(session_id)
  if state is None:
    return {"error": "Unknown session_id"}
  items = []
  for q in state.all_questions:
    items.append(
      {
        "q_id": q.q_id,
        "question_text": q.question_text,
        "type": q.type,
        "options": q.options,
        "correct_answer": q.correct_answer,
        "user_answer": q.user_answer,
        "correct": q.correct,
        "explanation": q.explanation,
        "batch_num": q.batch_num,
      }
    )

  strong: list[str] = []
  weak: list[str] = []
  try:
    # Cache by answered count to avoid repeated LLM calls on repeated "Review" opens.
    answered_n = len(items)
    cached = state.review_summary if isinstance(state.review_summary, dict) else None
    if cached and int(cached.get("answered_n") or -1) == answered_n:
      strong = list(cached.get("strong_areas") or [])
      weak = list(cached.get("weak_areas") or [])
    else:
      strong, weak = summarize_strengths_and_weaknesses(items=items)
      state.review_summary = {"answered_n": answered_n, "strong_areas": strong, "weak_areas": weak}
      save_state(state)
  except Exception:
    strong = []
    weak = []

  return {
    "session_id": session_id,
    "topic": state.topic,
    "level": state.stated_level,
    "total_answered": len(items),
    "strong_areas": strong,
    "weak_areas": weak,
    "items": items,
  }
