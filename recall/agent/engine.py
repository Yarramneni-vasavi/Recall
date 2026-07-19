from __future__ import annotations

from recall.agent.judge import Adjustment, apply_feedback, judge_batch
from recall.agent.questions import generate_questions
from recall.agent.ranker import select_top_4
from recall.agent.state import Level, Question, SessionState
from recall.agent.dedupe import filter_similar_questions
from typing import Callable
from recall.config.config import config
from recall.observability.logger import get_logger

logger = get_logger(__name__)


def _level_base_difficulty(level: Level) -> float:
  if level == "beginner":
    return 3.5
  if level == "advanced":
    return 7.0
  return 5.0


def init_state(*, session_id: str, topic: str, level: Level) -> SessionState:
  max_q = int((config.get("quiz") or {}).get("max_questions_per_session") or 20)
  return SessionState(
    session_id=session_id,
    topic=topic,
    stated_level=level,
    question_count=0,
    current_batch=1,
    target_difficulty=_level_base_difficulty(level),
    awaiting_continue=False,
    next_prompt_at=20,
    max_questions=max(1, max_q),
    ended=False,
  )


def ensure_questions(state: SessionState) -> None:
  return ensure_questions_with_stage(state, stage=None)


def ensure_questions_with_stage(state: SessionState, *, stage: Callable[[str], None] | None) -> None:
  if state.ended or state.question_count >= state.max_questions:
    state.ended = True
    return
  if state.awaiting_continue:
    return
  if state.pending_index < len(state.pending_questions):
    return

  prev = [
    {"q_id": q.q_id, "user_answer": q.user_answer, "correct": q.correct}
    for q in state.all_questions[-12:]
    if q.user_answer is not None
  ]
  prev_texts = [q.question_text for q in state.all_questions[-80:] if q.question_text]

  # Generate and de-duplicate against prior questions (fast, small N).
  if stage:
    stage("generating")
  pool: list[Question] = []
  for _ in range(2):
    need = max(0, 8 - len(pool))
    if need == 0:
      break
    qs8 = generate_questions(
      topic=state.topic,
      level=state.stated_level,
      batch_num=state.current_batch,
      target_difficulty=state.target_difficulty,
      previous_answers=prev,
      avoid_questions=prev_texts,
    )
    filtered = filter_similar_questions(
      qs8,
      previous_texts=prev_texts + [q.question_text for q in pool if q.question_text],
      threshold=0.84,
    )
    pool.extend(filtered)
    if len(pool) >= 8:
      break

  # Fallback: if we still can't get enough unique items, accept what we have.
  pool = pool[:8] if pool else generate_questions(
    topic=state.topic,
    level=state.stated_level,
    batch_num=state.current_batch,
    target_difficulty=state.target_difficulty,
    previous_answers=prev,
    avoid_questions=prev_texts,
  )

  if stage:
    stage("ranking")
  top4 = select_top_4(questions=pool, level=state.stated_level)
  state.pending_questions = top4
  state.pending_index = 0


def current_question(state: SessionState) -> Question | None:
  if state.awaiting_continue:
    return None
  if state.pending_index >= len(state.pending_questions):
    return None
  return state.pending_questions[state.pending_index]


def record_answer(state: SessionState, *, answer: str) -> list[Question]:
  if state.ended or state.question_count >= state.max_questions:
    state.ended = True
    return []
  q = current_question(state)
  if q is None:
    return []
  q.user_answer = answer.strip()[:4000]
  state.all_questions.append(q)
  state.pending_index += 1
  state.question_count += 1
  state.session_stats.total_questions = state.question_count
  if state.question_count >= state.max_questions:
    state.ended = True
  return [q]


def record_batch_answers(state: SessionState, *, answers: dict[str, str]) -> list[Question]:
  if state.awaiting_continue:
    return []
  if state.ended or state.question_count >= state.max_questions:
    state.ended = True
    return []
  if state.pending_index >= len(state.pending_questions):
    return []
  recorded: list[Question] = []
  for q in state.pending_questions[state.pending_index :]:
    if state.question_count >= state.max_questions:
      state.ended = True
      break
    q.user_answer = (answers.get(q.q_id) or "").strip()[:4000]
    state.all_questions.append(q)
    recorded.append(q)
    state.question_count += 1
  state.pending_index = len(state.pending_questions)
  state.session_stats.total_questions = state.question_count
  return recorded


def finalize_batch_if_ready(state: SessionState) -> tuple[bool, dict | None]:
  if state.awaiting_continue:
    return False, None
  if state.pending_index < len(state.pending_questions):
    return False, None
  if not state.pending_questions:
    if state.question_count >= state.max_questions:
      state.ended = True
      return True, {
        "accuracy": 0.0,
        "assessment": "Questions limit reached for this session.",
        "next_level_adjustment": "same",
        "feedback": [],
        "batch_difficulty": state.target_difficulty,
      }
    return False, None

  answered = state.pending_questions
  accuracy, assessment, adjustment, reason, fb, weak_areas = judge_batch(answered=answered, level=state.stated_level)
  apply_feedback(answered, fb)

  # Estimate difficulty attempted for scorecard/expertise reporting.
  diffs = [(q.difficulty if isinstance(q.difficulty, (int, float)) else state.target_difficulty) for q in answered]
  batch_difficulty = float(sum(diffs) / max(1, len(diffs)))

  correct = sum(1 for q in answered if q.correct)
  state.session_stats.total_correct += correct
  if state.session_stats.total_questions:
    state.session_stats.current_accuracy = state.session_stats.total_correct / state.session_stats.total_questions

  _apply_adjustment(state, adjustment)
  logger.info(
    "Difficulty adjustment: %s | reason=%s | accuracy=%.3f | topic=%s | level=%s | target_difficulty=%.2f",
    adjustment,
    reason,
    accuracy,
    state.topic,
    state.stated_level,
    state.target_difficulty,
  )

  state.pending_questions = []
  state.pending_index = 0
  state.current_batch += 1

  if state.question_count >= state.max_questions:
    state.ended = True

  return (
    True,
    {
      "accuracy": accuracy,
      "assessment": assessment,
      "next_level_adjustment": adjustment,
      "adjustment_reason": reason,
      "feedback": fb,
      "weak_areas": weak_areas,
      "batch_difficulty": batch_difficulty,
    },
  )


def _apply_adjustment(state: SessionState, adjustment: Adjustment) -> None:
  if adjustment == "harder":
    state.target_difficulty = min(10.0, state.target_difficulty + 1.0)
  elif adjustment == "easier":
    state.target_difficulty = max(1.0, state.target_difficulty - 1.0)


def handle_continue_response(state: SessionState, *, text: str) -> bool:
  """
  Returns True if session should continue, False if it should end.
  """
  if not state.awaiting_continue:
    return True
  t = (text or "").strip().lower()
  if t in ("y", "yes", "continue", "c"):
    state.awaiting_continue = False
    state.next_prompt_at = max(state.next_prompt_at + 20, state.question_count + 20)
    state.pending_questions = []
    state.pending_index = 0
    return True
  if t in ("n", "no", "stop", "end", "q", "quit", "exit"):
    return False
  return True
