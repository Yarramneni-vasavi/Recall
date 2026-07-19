from __future__ import annotations

import re
import zlib
from typing import Iterable

try:
  import numpy as np  # type: ignore
except Exception:  # pragma: no cover
  np = None  # type: ignore


_WORD = re.compile(r"[a-z0-9]+", re.I)


def _tokens(text: str) -> list[str]:
  return [t.lower() for t in _WORD.findall(text or "") if len(t) >= 2]


def _hash_token(tok: str) -> int:
  # Stable across runs (unlike Python's built-in hash()).
  return zlib.crc32(tok.encode("utf-8")) & 0xFFFFFFFF


def _vec_dense(text: str, *, dim: int):
  assert np is not None
  v = np.zeros(dim, dtype=np.float32)
  for tok in _tokens(text):
    v[_hash_token(tok) % dim] += 1.0
  n = float(np.linalg.norm(v))
  if n > 0:
    v /= n
  return v


def _vec_sparse(text: str, *, dim: int) -> dict[int, float]:
  counts: dict[int, float] = {}
  for tok in _tokens(text):
    i = _hash_token(tok) % dim
    counts[i] = counts.get(i, 0.0) + 1.0
  n2 = sum(v * v for v in counts.values())
  if n2 <= 0.0:
    return {}
  inv = 1.0 / (n2 ** 0.5)
  return {k: v * inv for k, v in counts.items()}


def max_cosine_similarity(
  text: str,
  *,
  corpus: Iterable[str],
  dim: int = 1024,
) -> float:
  if np is not None:
    base = _vec_dense(text, dim=dim)
    if float(np.linalg.norm(base)) == 0.0:
      return 0.0
    best = 0.0
    for c in corpus:
      v = _vec_dense(c, dim=dim)
      if float(np.linalg.norm(v)) == 0.0:
        continue
      sim = float(base @ v)
      if sim > best:
        best = sim
    return best

  base = _vec_sparse(text, dim=dim)
  if not base:
    return 0.0
  best = 0.0
  for c in corpus:
    v = _vec_sparse(c, dim=dim)
    if not v:
      continue
    # dot product over smaller dict
    if len(v) < len(base):
      sim = sum(val * base.get(i, 0.0) for i, val in v.items())
    else:
      sim = sum(val * v.get(i, 0.0) for i, val in base.items())
    if sim > best:
      best = sim
  return float(best)


def filter_similar_questions(
  questions: list,
  *,
  previous_texts: list[str],
  threshold: float = 0.84,
  dim: int = 1024,
) -> list:
  if not questions or not previous_texts:
    return questions

  out = []
  corpus = [t for t in previous_texts if t and t.strip()]
  for q in questions:
    qt = getattr(q, "question_text", "") or ""
    if not qt.strip():
      continue
    if max_cosine_similarity(qt, corpus=corpus, dim=dim) >= threshold:
      continue
    out.append(q)
    corpus.append(qt)
  return out
