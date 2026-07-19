# Shared State Schema

All agents read/write this state object. This is the "contract" between agents.

```python
{
    # Session metadata
    "session_id": str,
    "topic": str,
    "expertise_level": str,  # "beginner" | "intermediate" | "advanced" | "expert"
    "learning_mode": str,  # "visual" | "auditory" | "reading"
    
    # Planner output (set once)
    "study_plan": [
        {
            "subtopic": str,
            "order": int,
            "initial_difficulty_estimate": float,  # 1.0-10.0
            "content_format": str
        }
    ],
    
    # Current session progress
    "current_subtopic": str,
    "current_subtopic_index": int,
    
    # Adaptive difficulty state (per subtopic)
    "current_difficulty": float,  # 1.0-10.0
    "step_size": float,  # Decays over turns
    "confidence_reached": bool,
    
    # Question/answer history (per subtopic)
    "answer_history": [
        {
            "question_id": str,
            "question_text": str,
            "difficulty_attempted": float,
            "user_answer": str,
            "correct": bool,
            "feedback": str
        }
    ],
    
    # Latest output (for frontend)
    "current_question": {
        "question_id": str,
        "question_text": str,
        "difficulty_tag": float
    },
    
    # Mastery tracking
    "subtopic_mastery": {
        "subtopic_name": float  # 0.0-1.0, percentage confident
    },
    
    # Next action (routing signal)
    "next_action": str  # "continue_subtopic" | "advance" | "end_session"
}
```

## Rules
- Agents MUST NOT delete or rewrite history
- Step size decays: start at 2.0, decay by 0.5 each turn
- Confidence threshold: step_size < 0.25 AND ≥3 consecutive answers in same difficulty band