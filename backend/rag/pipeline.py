"""Processing one document: extract -> chunk -> embed -> index. Each expensive stage is cached:
extraction (incl. OCR) on disk per content hash + EXTRACT_VERSION, embeddings in PostgreSQL per input text.
Chunks go to Milvus; the document's status lives in PostgreSQL."""
import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np

from . import gemini, guardrails, vectors
from .chunking import Chunk, chunk_segments
from .config import EXTRACT_VERSION, get_settings
from .db import connection, now
from .extractors import Extraction, extract
from .terms import split_terms

log = logging.getLogger("rag.pipeline")


class DocumentDeleted(Exception):
    """The document was deleted while it was being processed."""


def extract_cached(path: Path, sha: str, file_type: str) -> Extraction:
    settings = get_settings()
    cache = settings.extract_cache_dir / sha[:2] / f"{sha}.v{EXTRACT_VERSION}.json"
    if cache.exists():
        return Extraction.from_json(json.loads(cache.read_text()))
    extraction = extract(path, file_type)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(extraction.to_json(), ensure_ascii=False))
    tmp.replace(cache)
    return extraction


def embed_cached(chunks: list[Chunk], title: str, on_progress=None) -> list[np.ndarray]:
    settings = get_settings()
    by_key: dict[str, str] = {}
    keys = []
    for c in chunks:
        text = f"{c.context}\n{c.text}"
        key = hashlib.sha256(f"{settings.embed_model}|{settings.embed_dim}|{title}|{text}".encode()).hexdigest()
        by_key[key] = text
        keys.append(key)
    unique = list(by_key)
    with connection() as conn:
        rows = conn.execute("SELECT key, embedding FROM embedding_cache WHERE key = ANY(%s)", (unique,)).fetchall()
    found = {r["key"]: np.frombuffer(r["embedding"], dtype=np.float32) for r in rows}
    missing = [k for k in unique if k not in found]
    done = len(unique) - len(missing)
    # One request per batch, saved straight away: if the quota or a crash stops us halfway,
    # the next attempt continues from here instead of starting over.
    for group in gemini.batches(missing, text_of=lambda k: by_key[k]):
        new = gemini.embed_documents([by_key[k] for k in group], title)
        with connection() as conn, conn.cursor() as cur:
            cur.executemany("INSERT INTO embedding_cache (key, embedding) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                            [(k, np.asarray(v, dtype=np.float32).tobytes()) for k, v in zip(group, new)])
        found.update(zip(group, new))
        done += len(group)
        if on_progress:
            on_progress(done, len(unique))
    log.info("embeddings: %d cached, %d new", len(unique) - len(missing), len(missing))
    return [found[k] for k in keys]


def _update(doc_id: str, **fields):
    """Update the document row; raises DocumentDeleted if it no longer exists."""
    cols = ", ".join(f"{k} = %s" for k in fields)
    with connection() as conn:
        cur = conn.execute(f"UPDATE documents SET {cols}, updated_at = now() WHERE id = %s",
                           (*fields.values(), doc_id))
        if cur.rowcount == 0:
            raise DocumentDeleted(doc_id)


def process(doc: dict):
    settings = get_settings()
    doc_id, started = doc["id"], time.monotonic()

    _update(doc_id, stage="extract", locked_at=now())
    extraction = extract_cached(Path(doc["storage_path"]), doc["id"], doc["file_type"])

    _update(doc_id, stage="chunk", locked_at=now())
    chunks = chunk_segments(extraction.segments, doc["filename"], settings.chunk_tokens, settings.chunk_overlap_tokens)
    if not chunks:
        raise ValueError("No text found in the document")
    problem = guardrails.check_document("\n".join(c.text for c in chunks))
    if problem:
        raise ValueError(problem)  # permanent: retrying will not make the file readable

    _update(doc_id, stage="embed", locked_at=now())
    embeddings = embed_cached(chunks, doc["filename"], on_progress=lambda done, total: _update(
        doc_id, stage=f"embed {done}/{total}", locked_at=now()))

    _update(doc_id, stage="index", locked_at=now())
    # Upsert chunks in place (stable ids), then drop any left over from a longer previous version,
    # so the document is never missing from search while it is reprocessed.
    vectors.upsert_chunks([{
        "id": f"{doc_id}-{i:05d}", "document_id": doc_id, "chunk_index": i, "filename": doc["filename"],
        "context": c.context, "text": c.text, "terms": split_terms(f"{doc['filename']} {c.context} {c.text}"),
        "embedding": np.asarray(v, dtype=np.float32).tolist(), "location": c.location,
        "metadata": doc.get("metadata") or {},
    } for i, (c, v) in enumerate(zip(chunks, embeddings))])
    vectors.delete_document(doc_id, from_index=len(chunks))
    try:
        _update(doc_id, status="ready", stage=None, error=None, locked_at=None,
                pipeline_version=settings.pipeline_version, page_count=extraction.page_count,
                ocr_page_count=extraction.ocr_page_count, chunk_count=len(chunks))
    except DocumentDeleted:
        vectors.delete_document(doc_id)  # deleted while we were indexing: leave nothing behind in search
        raise
    log.info("%s: %d chunks, %s OCR pages, %.1fs", doc["filename"], len(chunks),
             extraction.ocr_page_count, time.monotonic() - started)
