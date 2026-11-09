"""Gemini API: embeddings (gemini-embedding-001) and generation (GEMINI_MODEL).

gemini-embedding-001 takes task_type (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY), returns one vector per
input string, reads up to 2048 tokens per input, and must be L2-normalised below 3072 dimensions."""
import logging
import random
import threading
import time
from collections import deque
from functools import lru_cache

import numpy as np
from google import genai
from google.genai import errors, types

from .config import get_settings

RETRYABLE = {408, 429, 500, 502, 503, 504}
log = logging.getLogger("rag.gemini")

# Quota (429) handling, shared by all threads: when one call hits the per-minute quota, every call
# waits until the quota window has passed, then continues. Nothing fails just because a file is big.
_quota_lock = threading.Lock()
_quota_until: dict[str, float] = {}  # model -> time its quota window ends (each model has its own quota)
# Optional pacing (EMBED_TOKENS_PER_MINUTE): tokens sent in the last 60 s.
_sent: deque[tuple[float, int]] = deque()
# A person is waiting for chat answers: wait at most this long for the quota, then say so.
INTERACTIVE_QUOTA_WAIT = 20.0


@lru_cache
def client() -> genai.Client:
    key = get_settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def _retry_delay(e: errors.APIError) -> float | None:
    """Seconds Google asks us to wait (RetryInfo.retryDelay, e.g. "37s"), if it says."""
    details = (e.details or {}).get("error", {}).get("details", []) if isinstance(e.details, dict) else []
    for d in details:
        if str(d.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(d.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                return None
    return None


def _wait_for_quota(model: str, deadline: float) -> bool:
    """Wait until this model's quota window has passed. False if that would be later than `deadline`."""
    until = _quota_until.get(model, 0.0)
    if until > deadline:
        return False
    while (remaining := until - time.monotonic()) > 0:
        time.sleep(min(remaining, 5))
        until = _quota_until.get(model, 0.0)
    return True


def _pace(tokens: int):
    """Keep under EMBED_TOKENS_PER_MINUTE (0 = no pacing) so the quota is never hit."""
    limit = get_settings().embed_tokens_per_minute
    if limit <= 0:
        return
    tokens = min(tokens, limit)
    while True:
        with _quota_lock:
            now = time.monotonic()
            while _sent and now - _sent[0][0] > 60:
                _sent.popleft()
            used = sum(t for _, t in _sent)
            if used + tokens <= limit:
                _sent.append((now, tokens))
                return
            wait = 60 - (now - _sent[0][0]) + 0.5
        time.sleep(wait)


class QuotaExceeded(Exception):
    """The Gemini API key's quota is used up (HTTP 429) and we were not allowed to wait any longer."""


def _with_retry(fn, model: str, tokens: int = 0, attempts: int = 6, quota_wait: float | None = None):
    """Call Gemini. Quota errors (429) wait for the quota window and retry for up to `quota_wait` seconds
    (default QUOTA_WAIT_MINUTES, for background work); other temporary errors retry with backoff."""
    if quota_wait is None:
        quota_wait = get_settings().quota_wait_minutes * 60
    quota_deadline = time.monotonic() + quota_wait
    failures = 0
    busy = QuotaExceeded("The Gemini API quota is used up for now. Please try again in a minute.")
    while True:
        if not _wait_for_quota(model, quota_deadline):
            raise busy
        _pace(tokens)
        try:
            return fn()
        except errors.APIError as e:
            if e.code == 429:
                delay = _retry_delay(e) or 60.0
                with _quota_lock:
                    _quota_until[model] = max(_quota_until.get(model, 0.0),
                                              time.monotonic() + delay + random.random() * 3)
                if time.monotonic() + delay > quota_deadline:
                    raise busy from e
                log.warning("Gemini quota reached for %s; waiting %.0f s, then continuing", model, delay)
                continue
            failures += 1
            if e.code not in RETRYABLE or failures >= attempts:
                raise
            time.sleep(min(60, 2 ** failures) + random.random())


def batches(items: list, text_of=lambda x: x):
    """Groups of at most embed_batch_size items and about embed_batch_tokens tokens (one request each)."""
    s = get_settings()
    batch, tokens = [], 0
    for item in items:
        size = len(text_of(item)) // 4 + 1
        if batch and (len(batch) >= s.embed_batch_size or tokens + size > s.embed_batch_tokens):
            yield batch
            batch, tokens = [], 0
        batch.append(item)
        tokens += size
    if batch:
        yield batch


def _embed(texts: list[str], task_type: str, title: str | None = None,
           quota_wait: float | None = None) -> list[np.ndarray]:
    s = get_settings()
    vectors: list[np.ndarray] = []
    for batch in batches(texts):
        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=s.embed_dim,
                                          title=title or None)
        tokens = sum(len(t) // 4 + 1 for t in batch)
        result = _with_retry(lambda: client().models.embed_content(model=s.embed_model, contents=batch,
                                                                   config=config),
                             model=s.embed_model, tokens=tokens, quota_wait=quota_wait)
        if len(result.embeddings) != len(batch):
            raise RuntimeError(f"Expected {len(batch)} embeddings, got {len(result.embeddings)}")
        for e in result.embeddings:
            v = np.asarray(e.values, dtype=np.float32)
            norm = np.linalg.norm(v)
            vectors.append(v / norm if norm else v)
    return vectors


@lru_cache
def _local_model(model_name: str):
    from sentence_transformers import SentenceTransformer
    log.info("loading sentence-transformers embedding model: %s", model_name)
    return SentenceTransformer(model_name)


def _is_local_model(model_name: str) -> bool:
    return not (model_name.startswith("gemini") or model_name.startswith("models/gemini") or model_name.startswith("text-embedding"))


def embed_documents(texts: list[str], title: str = "") -> list[np.ndarray]:
    s = get_settings()
    if _is_local_model(s.embed_model):
        model = _local_model(s.embed_model)
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return [np.asarray(v, dtype=np.float32) for v in vecs]
    return _embed(texts, "RETRIEVAL_DOCUMENT", title)


def embed_query(text: str) -> np.ndarray:
    s = get_settings()
    if _is_local_model(s.embed_model):
        model = _local_model(s.embed_model)
        vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)
    return _embed([text], "RETRIEVAL_QUERY", quota_wait=INTERACTIVE_QUOTA_WAIT)[0]


def generate(system: str, prompt: str, temperature: float | None = None,
             quota_wait: float = 0) -> str:
    s = get_settings()
    resp = _with_retry(model=s.gemini_model, quota_wait=quota_wait, fn=lambda: client().models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=s.llm_temperature if temperature is None else temperature),
    ))
    return resp.text or ""
