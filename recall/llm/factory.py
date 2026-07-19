from recall.config.config import config
from recall.observability.logger import get_logger


logger = get_logger(__name__)


def _build_chat_openai(model: str, max_tokens: int | None):
  from langchain_openai import ChatOpenAI

  kwargs = {"model": model}
  if max_tokens is not None:
    kwargs["max_tokens"] = max_tokens
  return ChatOpenAI(**kwargs)


def get_reasoning_llm():
  """Return the primary (reasoning) chat model based on recall/config.yaml."""
  provider = config["llm"]["provider"]
  if provider != "openai":
    raise ValueError(f"Unsupported LLM provider: {provider}")

  model = config["llm"]["reasoning_model"]
  max_tokens = config["llm"].get("reasoning_model_max_tokens")
  logger.info(f"Using reasoning LLM provider: {provider}, model: {model}, max_tokens: {max_tokens}")

  return _build_chat_openai(model, max_tokens)


def get_fast_llm():
  """Return the fast (small) chat model based on recall/config.yaml."""
  provider = config["llm"]["provider"]
  if provider != "openai":
    raise ValueError(f"Unsupported LLM provider: {provider}")

  model = config["llm"]["fast_model"]
  max_tokens = config["llm"].get("fast_model_max_tokens")
  logger.info(f"Using fast LLM provider: {provider}, model: {model}, max_tokens: {max_tokens}")

  return _build_chat_openai(model, max_tokens)


def get_llm():
  """Back-compat alias used across the codebase."""
  return get_reasoning_llm()

