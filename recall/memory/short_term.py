import sqlite3
import time
from pathlib import Path

from recall.config.config import config
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents.middleware import SummarizationMiddleware
from recall.db import postgres as pg
from recall.observability.logger import get_logger
from recall.llm.factory import get_llm


logger = get_logger(__name__)


def get_checkpointer() -> object:
   if pg.enabled():
      pg.get_pg_store()  # ensure schema
      logger.info("Using Postgres checkpointer.")

      class _PgCheckpointer:  # minimal subset used by get_session_history
         def get(self, cfg: dict) -> dict | None:
            thread_id = ((cfg or {}).get("configurable") or {}).get("thread_id")
            if not thread_id:
               return None
            return pg.get_pg_store().checkpoint_get(str(thread_id))

         def put(self, cfg: dict, checkpoint: dict) -> None:
            thread_id = ((cfg or {}).get("configurable") or {}).get("thread_id")
            if not thread_id:
               return
            pg.get_pg_store().checkpoint_put(thread_id=str(thread_id), checkpoint=checkpoint, updated_at=time.time())

      return _PgCheckpointer()  # type: ignore[return-value]
   db_path = config["memory"]["db_path"]
   Path(db_path).parent.mkdir(exist_ok=True)
   logger.info(f"Using SQLite checkpointer at {db_path}")
   conn = sqlite3.connect(db_path, check_same_thread=False)
   return SqliteSaver(conn)

def get_session_history(thread_id: str) -> list[dict]:
   checkpointer = get_checkpointer()
   config_ = {"configurable": {"thread_id": thread_id}}
   checkpoint = checkpointer.get(config_)
   if not checkpoint:
       return []
   messages = checkpoint["channel_values"].get("messages", [])
   return [
       {"role": "user" if m.type == "human" else "assistant", "content": m.content}
       for m in messages
   ]

def get_summarization_middleware() -> SummarizationMiddleware:
   return SummarizationMiddleware(
       model=get_llm(),
       trigger=("tokens", config["memory"]["summarize_at_tokens"]),
       keep=("messages", config["memory"]["keep_last_messages"]),
   )
