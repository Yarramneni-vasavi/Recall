# API Endpoints

## POST /quiz/{session_id}/start
{
  "input": "revise python intermediate"  # or just "python", just "intermediate", etc.
}
→ {
  "session_id": "...",
  "topic": "python",
  "level": "intermediate",
  "questions": [
    {"q_id": "q1", "text": "...", "options": [...], "type": "mcq"},
    {"q_id": "q2", "text": "...", "type": "fill_blank"},
    ...
  ],  # First 4 (best 4 from batch of 8)
  "batch_info": {"batch_num": 1, "question_count": 4}
}

## POST /quiz/{session_id}/submit
{
  "answers": [
    {"q_id": "q1", "answer": "option_b_answer_text"},
    {"q_id": "q2", "answer": "decorator"},
    ...
  ]
}
→ {
  "feedback": [
    {"q_id": "q1", "correct": true, "explanation": "..."},
    ...
  ],
  "batch_stats": {
    "accuracy": 0.75,
    "questions_answered": 4
  },
  "next_batch": {
    "level_adjustment": "easier" | "same" | "harder",
    "total_questions_so_far": 8,
    "continue_prompt": "You got 3/4. Want to continue? (yes/no)"
  }
}

## POST /quiz/{session_id}/continue
{
  "action": "yes"  # or "no"
}
→ {
  "questions": [next 4 questions],  # or session ends
  "batch_info": {"batch_num": 2, "question_count": 8}
}

## GET /quiz/{session_id}/summary
→ {
  "total_questions": 8,
  "accuracy": 0.75,
  "final_level": "intermediate",
  "topics_strong": ["decorators"],
  "topics_weak": ["metaclasses"]
}
