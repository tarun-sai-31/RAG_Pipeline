"""Tests run against the real PostgreSQL and Milvus, using a throwaway database `rag_test` and a throwaway
Milvus collection (rag_test_<random>_chunks), with Gemini replaced by a deterministic bag-of-words embedder,
so no API key or network is needed. OCR uses Tesseract here for speed; Docling has its own test."""
import hashlib
import os
import re
import tempfile
import uuid

import numpy as np
import psycopg
import pytest

BASE_URL = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")
os.environ["DATABASE_URL"] = BASE_URL.rsplit("/", 1)[0] + "/rag_test"
os.environ.setdefault("MILVUS_URI", "http://localhost:19530")
os.environ["COLLECTION_PREFIX"] = f"rag_test_{uuid.uuid4().hex[:8]}"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="rag-test-")
os.environ["GEMINI_API_KEY"] = "test"
os.environ["OCR_ENGINE"] = "tesseract"
os.environ["DOCLING_OCR"] = "tesseract"
os.environ["DOCLING_LANG"] = "en"
os.environ["OCR_LANG"] = "eng"
os.environ["API_KEY"] = ""
os.environ["EMBEDDED_WORKERS"] = "0"  # tests drive the worker themselves
os.environ["ASK_RATE_PER_MINUTE"] = "0"  # many questions in one run; the rate-limit test sets its own


def fake_vector(text: str, dim: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v + 1e-3


@pytest.fixture(scope="session", autouse=True)
def databases():
    with psycopg.connect(BASE_URL, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS rag_test WITH (FORCE)")
        conn.execute("CREATE DATABASE rag_test")
    yield
    from rag import vectors
    vectors.client().drop_collection(vectors.collection())


@pytest.fixture(autouse=True)
def fake_gemini(monkeypatch):
    from rag import gemini
    from rag.config import get_settings

    calls = {"embedded": 0, "prompts": []}

    def embed_documents(texts, title):
        calls["embedded"] += len(texts)
        return [fake_vector(t, get_settings().embed_dim) for t in texts]

    def generate(system, prompt, temperature=None):
        calls["prompts"].append((system, prompt))
        if system.startswith("Rewrite"):
            return "Ambala demarcation plot area"
        return "ANSWER [1]"

    monkeypatch.setattr(gemini, "embed_documents", embed_documents)
    monkeypatch.setattr(gemini, "embed_query", lambda text: fake_vector(text, get_settings().embed_dim))
    monkeypatch.setattr(gemini, "generate", generate)
    return calls
