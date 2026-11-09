"""Registering files. Content is stored once under its SHA-256, which is also the document id; a file
already processed with the current pipeline version is returned as ready immediately, with no work queued."""
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from psycopg.types.json import Jsonb

from . import vectors
from .config import get_settings
from .db import connection, iso
from .extractors import detect_type


class TooLarge(Exception):
    pass


def _store(stream: BinaryIO, max_bytes: int) -> tuple[Path, str, int]:
    """Stream to a temp file while hashing; never holds the whole file in memory."""
    settings = get_settings()
    settings.files_dir.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(dir=settings.files_dir, delete=False, suffix=".part") as tmp:
        while block := stream.read(1 << 20):
            size += len(block)
            if size > max_bytes:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise TooLarge(f"File is larger than {max_bytes >> 20} MB")
            digest.update(block)
            tmp.write(block)
    return Path(tmp.name), digest.hexdigest(), size


def get_document(document_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone()


def register(stream: BinaryIO, filename: str, metadata: dict | None = None) -> dict:
    """Store an uploaded file and queue it unless identical content is already known."""
    settings = get_settings()
    tmp, sha, size = _store(stream, settings.max_upload_mb << 20)
    filename = Path(filename).name or "upload"

    existing = get_document(sha)
    if existing is None:
        file_type = detect_type(tmp, filename)
        target = settings.files_dir / sha[:2] / f"{sha}{Path(filename).suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, target)
        with connection() as conn:
            row = conn.execute(
                """INSERT INTO documents (id, filename, file_type, size_bytes, storage_path, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING RETURNING *""",
                (sha, filename, file_type, size, str(target), Jsonb(metadata or {})),
            ).fetchone()
        if row is not None:
            return {**public(row), "duplicate": False}
        existing = get_document(sha)  # the same file was uploaded at the same moment
    else:
        tmp.unlink(missing_ok=True)

    if metadata:
        merged = {**(existing.get("metadata") or {}), **metadata}
        with connection() as conn:
            existing = conn.execute("UPDATE documents SET metadata = %s, updated_at = now() WHERE id = %s RETURNING *",
                                    (Jsonb(merged), sha)).fetchone()
        if existing["status"] == "ready":
            vectors.set_metadata(sha, merged)
    if existing["status"] == "failed":
        existing = requeue(sha)
    return {**public(existing), "duplicate": True}


def requeue(document_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute(
            """UPDATE documents SET status = 'queued', stage = NULL, error = NULL, attempts = 0,
                      available_at = now(), locked_at = NULL, updated_at = now()
               WHERE id = %s RETURNING *""", (document_id,)).fetchone()


def requeue_stale() -> int:
    """Queue every document processed by an older pipeline version (after a parser/chunker/model change)."""
    with connection() as conn:
        cur = conn.execute(
            """UPDATE documents SET status = 'queued', attempts = 0, available_at = now(), updated_at = now()
               WHERE status IN ('ready', 'failed') AND pipeline_version IS DISTINCT FROM %s""",
            (get_settings().pipeline_version,))
        return cur.rowcount


PUBLIC_FIELDS = ("id", "filename", "file_type", "size_bytes", "metadata", "status", "stage", "error",
                 "attempts", "page_count", "ocr_page_count", "chunk_count", "pipeline_version",
                 "created_at", "updated_at")


def public(doc: dict) -> dict:
    return {k: iso(doc.get(k)) for k in PUBLIC_FIELDS}
