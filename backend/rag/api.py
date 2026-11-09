"""HTTP API used by the Angular frontend. Uploads return immediately; processing happens in the worker.
Every question is saved to the chat history and every API call to the API log."""
import io
import json
import logging
import re
import secrets
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import chats, gemini, guardrails, history, ingest, search, worker
from .config import EXTRACT_VERSION, get_settings
from . import vectors
from .db import connection, now

DOC_ID = re.compile(r"^[0-9a-f]{64}$")
HEX_ID = re.compile(r"^[0-9a-f]{32}$")


@asynccontextmanager
async def lifespan(_app):
    with connection():  # creates the PostgreSQL tables on first run
        pass
    vectors.client()  # creates the Milvus collection on first run
    stop = None
    workers = get_settings().embedded_workers
    if workers > 0:  # process uploads inside this process, so no separate worker command is needed
        _show_rag_logs()
        stop = worker.start_background(workers)
    yield
    if stop is not None:
        stop.set()


def _show_rag_logs():
    """Print the pipeline's progress (file processed, chunks, OCR pages) next to uvicorn's own logs."""
    rag_log = logging.getLogger("rag")
    if not rag_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        rag_log.addHandler(handler)
        rag_log.setLevel(logging.INFO)


app = FastAPI(title="Document Assistant API", version="3.0", lifespan=lifespan,
              description="Upload documents, track processing, ask questions, and read the history.")


# ---------- API call log ----------

@app.middleware("http")
async def log_calls(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.summary = None
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        # Reads (GET) are only logged when they fail, so the UI's status polling doesn't flood the log.
        if route_path != "/health" and (request.method != "GET" or status >= 400 or get_settings().log_get_requests):
            entry = {"timestamp": now(), "request_id": request_id, "method": request.method,
                     "path": request.url.path, "route": route_path, "status": status,
                     "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                     "client": request.client.host if request.client else None,
                     "summary": request.state.summary}
            await run_in_threadpool(history.save_api_call, entry)


def require_key(x_api_key: str | None = Header(default=None)):
    expected = get_settings().api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(401, "Missing or wrong X-API-Key")


def _doc_or_404(document_id: str) -> dict:
    doc = ingest.get_document(document_id) if DOC_ID.match(document_id) else None
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


# ---------- system ----------

@app.get("/", tags=["system"])
def root():
    return {"name": "Document Assistant API", "docs": "/docs"}


@app.get("/health", tags=["system"])
def health():
    with connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "postgres": "ok", "milvus_chunks": vectors.count()}


@app.get("/config", tags=["system"])
def public_config():
    s = get_settings()
    return {"auth_required": bool(s.api_key), "model": s.gemini_model, "embed_model": s.embed_model,
            "max_upload_mb": s.max_upload_mb, "ocr_engine": s.ocr_engine}


# ---------- documents ----------

@app.post("/documents", status_code=202, dependencies=[Depends(require_key)], tags=["documents"])
async def upload(request: Request, files: list[UploadFile] = File(...), metadata: str | None = Form(default=None)):
    """Upload one or more files. Optional `metadata` is a JSON object (e.g. {"project": "Habitat"})
    stored on each document and usable as a search filter."""
    meta = None
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(422, "metadata must be a JSON object")
        if not isinstance(meta, dict):
            raise HTTPException(422, "metadata must be a JSON object")
    results = []
    for f in files:
        fname = f.filename or "upload"
        if fname.lower().endswith(".zip"):
            try:
                content = await f.read()
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for info in z.infolist():
                        if info.is_dir() or Path(info.filename).name.startswith((".", "~$")) or "__MACOSX" in info.filename:
                            continue
                        sub_bytes = z.read(info)
                        sub_name = Path(info.filename).name
                        sub_meta = {**(meta or {}), "folder": str(Path(info.filename).parent)} if "/" in info.filename else meta
                        try:
                            results.append(await run_in_threadpool(ingest.register, io.BytesIO(sub_bytes), sub_name, sub_meta))
                        except ingest.TooLarge as e:
                            results.append({"filename": sub_name, "status": "rejected", "error": str(e)})
            except Exception as e:
                results.append({"filename": fname, "status": "rejected", "error": f"Failed to unzip: {e}"})
            finally:
                await f.close()
            continue

        try:
            results.append(await run_in_threadpool(ingest.register, f.file, fname, meta))
        except ingest.TooLarge as e:
            results.append({"filename": fname, "status": "rejected", "error": str(e)})
        finally:
            await f.close()
    request.state.summary = "uploaded " + ", ".join(
        f"{r.get('filename')} ({'duplicate' if r.get('duplicate') else r.get('status')})" for r in results)
    return {"documents": results}


@app.get("/documents", dependencies=[Depends(require_key)], tags=["documents"])
def list_documents(status: str | None = None, limit: int = Query(200, le=1000), offset: int = 0):
    where, params = ("WHERE status = %s", [status]) if status else ("", [])
    with connection() as conn:
        rows = conn.execute(f"SELECT * FROM documents {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                            (*params, limit, offset)).fetchall()
        total = conn.execute(f"SELECT count(*) AS n FROM documents {where}", params).fetchone()["n"]
        counts = conn.execute("SELECT status, count(*) AS n FROM documents GROUP BY status").fetchall()
    return {"total": total, "counts": {r["status"]: r["n"] for r in counts},
            "documents": [ingest.public(r) for r in rows]}


@app.get("/documents/{document_id}", dependencies=[Depends(require_key)], tags=["documents"])
def get_one(document_id: str):
    return ingest.public(_doc_or_404(document_id))


@app.post("/documents/{document_id}/reprocess", dependencies=[Depends(require_key)], tags=["documents"])
def reprocess(request: Request, document_id: str):
    doc = _doc_or_404(document_id)
    request.state.summary = f"reprocess {doc['filename']}"
    return ingest.public(ingest.requeue(document_id))


@app.delete("/documents/{document_id}", dependencies=[Depends(require_key)], tags=["documents"])
def delete_document(request: Request, document_id: str):
    doc = _doc_or_404(document_id)
    vectors.delete_document(document_id)
    with connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    Path(doc["storage_path"]).unlink(missing_ok=True)
    cache = get_settings().extract_cache_dir / document_id[:2] / f"{document_id}.v{EXTRACT_VERSION}.json"
    cache.unlink(missing_ok=True)
    request.state.summary = f"deleted {doc['filename']}"
    return {"deleted": document_id}


# ---------- questions ----------

class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    history: list[Turn] | None = Field(default=None, max_length=40)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    top_k: int = Field(8, ge=1, le=50)
    document_ids: list[str] | None = None
    metadata: dict | None = None


@app.post("/search", dependencies=[Depends(require_key)], tags=["questions"])
def search_chunks(request: Request, req: AskRequest):
    request.state.summary = f"search: {req.query[:200]}"
    return {"results": search.search(req.query, req.top_k, req.document_ids, req.metadata)}


@app.post("/ask", dependencies=[Depends(require_key)], tags=["questions"])
def ask(request: Request, req: AskRequest):
    """Answer a question from the documents. The question and the full response are saved to the history."""
    client = request.headers.get("x-api-key") or (request.client.host if request.client else "unknown")
    if not guardrails.rate_limiter.allow(client):
        raise HTTPException(429, "Too many questions in a minute. Please wait a moment and try again.")
    conversation_id = req.conversation_id or uuid.uuid4().hex
    turns = [t.model_dump() for t in req.history] if req.history else None
    started = time.perf_counter()
    record = {"conversation_id": conversation_id, "created_at": now(), "question": req.query,
              "turn": len(turns or []) // 2 + 1, "document_ids": req.document_ids or [],
              "filters": req.metadata or {}, "model": get_settings().gemini_model}
    request.state.summary = f"ask: {req.query[:200]}"
    try:
        result = search.answer(req.query, turns, req.top_k, req.document_ids, req.metadata)
    except Exception as e:
        record.update(status="error", error=f"{type(e).__name__}: {e}"[:2000],
                      latency_ms=round((time.perf_counter() - started) * 1000))
        history.save_question(record)
        if isinstance(e, gemini.QuotaExceeded):
            raise HTTPException(429, str(e))
        raise
    latency = round((time.perf_counter() - started) * 1000)
    record.update(status="blocked" if result["guardrails"]["status"] == "blocked" else "ok", query=result["query"], answer=result["answer"], latency_ms=latency,
                  source_count=len(result["sources"]),
                  source_files=sorted({s["filename"] for s in result["sources"]}),
                  response=result)
    history_id = history.save_question(record)
    return {**result, "conversation_id": conversation_id, "history_id": history_id, "latency_ms": latency}


# ---------- history and API log ----------

@app.get("/history", dependencies=[Depends(require_key)], tags=["history"])
def list_history(q: str | None = None, conversation_id: str | None = None,
                 status: Literal["ok", "error"] | None = None,
                 limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                 include_response: bool = False):
    """Questions asked, newest first (oldest first when filtered to one conversation).
    `include_response=true` adds the full response of each entry (used to reopen a conversation)."""
    return history.list_questions(q, conversation_id, status, limit, offset, include_response)


class ChatChanges(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    group_id: str | None = None


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _hex_id(value: str, what: str = "Conversation") -> str:
    if not HEX_ID.match(value):
        raise HTTPException(404, f"{what} not found")
    return value


@app.get("/conversations", dependencies=[Depends(require_key)], tags=["chats"])
def list_conversations(q: str | None = None, limit: int = Query(100, ge=1, le=500)):
    """Chats: pinned first, then most recent. Titled by their custom name or first question."""
    return chats.list_chats(q, limit)


@app.patch("/conversations/{conversation_id}", dependencies=[Depends(require_key)], tags=["chats"])
def update_conversation(request: Request, conversation_id: str, body: ChatChanges):
    """Pin/unpin, rename (empty title = back to the first question), or move to a group (null = no group)."""
    changes = body.model_dump(exclude_unset=True)
    try:
        result = chats.update_chat(_hex_id(conversation_id), changes)
    except chats.NotFound:
        raise HTTPException(404, "Conversation or group not found")
    request.state.summary = f"chat {conversation_id[:8]}: " + ", ".join(f"{k}={v}" for k, v in changes.items())
    return result


@app.delete("/conversations/{conversation_id}", dependencies=[Depends(require_key)], tags=["chats"])
def delete_conversation(request: Request, conversation_id: str):
    deleted = chats.delete_chat(_hex_id(conversation_id))
    if not deleted:
        raise HTTPException(404, "Conversation not found")
    request.state.summary = f"deleted chat {conversation_id[:8]} ({deleted} questions)"
    return {"deleted": conversation_id, "questions": deleted}


@app.get("/groups", dependencies=[Depends(require_key)], tags=["chats"])
def list_groups():
    return {"groups": chats.list_groups()}


@app.post("/groups", status_code=201, dependencies=[Depends(require_key)], tags=["chats"])
def create_group(request: Request, body: GroupBody):
    request.state.summary = f"new group {body.name}"
    return chats.create_group(body.name)


@app.patch("/groups/{group_id}", dependencies=[Depends(require_key)], tags=["chats"])
def rename_group(request: Request, group_id: str, body: GroupBody):
    try:
        group = chats.rename_group(_hex_id(group_id, "Group"), body.name)
    except chats.NotFound:
        raise HTTPException(404, "Group not found")
    request.state.summary = f"renamed group to {body.name}"
    return group


@app.delete("/groups/{group_id}", dependencies=[Depends(require_key)], tags=["chats"])
def delete_group(request: Request, group_id: str):
    """Delete a group. Its chats are kept and go back to Recents."""
    try:
        moved = chats.delete_group(_hex_id(group_id, "Group"))
    except chats.NotFound:
        raise HTTPException(404, "Group not found")
    request.state.summary = f"deleted group ({moved} chats back to Recents)"
    return {"deleted": group_id, "chats_moved": moved}


@app.get("/history/{history_id}", dependencies=[Depends(require_key)], tags=["history"])
def get_history(history_id: str):
    """One question with the full API response that was returned for it."""
    item = history.get_question(history_id) if HEX_ID.match(history_id) else None
    if item is None:
        raise HTTPException(404, "History entry not found")
    return item


@app.delete("/history/{history_id}", dependencies=[Depends(require_key)], tags=["history"])
def delete_history(history_id: str):
    if not (HEX_ID.match(history_id) and history.delete_question(history_id)):
        raise HTTPException(404, "History entry not found")
    return {"deleted": history_id}


@app.get("/api-logs", dependencies=[Depends(require_key)], tags=["history"])
def list_api_logs(path: str | None = None, method: str | None = None,
                  status: Literal["ok", "error"] | None = None,
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """API calls, newest first, with per-endpoint counts, average time and errors."""
    return history.list_api_calls(path, status, method, limit, offset)
