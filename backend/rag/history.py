"""Chat history (every question with the full response returned) and the API call log, in PostgreSQL."""
import logging
import uuid

from psycopg.types.json import Jsonb

from .db import connection, iso

log = logging.getLogger("rag.history")

SUMMARY_FIELDS = ["id", "conversation_id", "created_at", "question", "query", "answer", "source_files", "model",
                  "status", "error", "latency_ms", "source_count", "turn"]
FULL_FIELDS = SUMMARY_FIELDS + ["document_ids", "filters", "response"]


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _out(row: dict) -> dict:
    return {k: iso(v) for k, v in row.items() if v is not None}


def save_question(record: dict) -> str:
    """Store one question/answer. Never fails the request: history is best effort."""
    history_id = uuid.uuid4().hex
    try:
        with connection() as conn:
            conn.execute(
                """INSERT INTO history (id, conversation_id, created_at, question, query, answer, source_files,
                       document_ids, filters, model, status, error, latency_ms, source_count, turn, response)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (history_id, record["conversation_id"], record["created_at"], record["question"],
                 record.get("query"), record.get("answer"), record.get("source_files") or [],
                 record.get("document_ids") or [], Jsonb(record.get("filters") or {}), record.get("model"),
                 record["status"], record.get("error"), record.get("latency_ms"), record.get("source_count"),
                 record.get("turn"), Jsonb(record["response"]) if record.get("response") is not None else None))
    except Exception:
        log.exception("could not save chat history")
    return history_id


def list_questions(q: str | None, conversation_id: str | None, status: str | None,
                   limit: int, offset: int, include_response: bool = False) -> dict:
    where, params = [], []
    if conversation_id:
        where.append("conversation_id = %s")
        params.append(conversation_id)
    if status:
        where.append("status = %s")
        params.append(status)
    if q:
        where.append("(question ILIKE %s OR answer ILIKE %s OR query ILIKE %s)")
        params += [_like(q)] * 3
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    fields = ", ".join(SUMMARY_FIELDS + (["response"] if include_response else []))
    order = "ASC" if conversation_id else "DESC"
    with connection() as conn:
        rows = conn.execute(f"SELECT {fields} FROM history {clause} ORDER BY created_at {order} LIMIT %s OFFSET %s",
                            (*params, limit, offset)).fetchall()
        stats = conn.execute(
            f"""SELECT count(*) AS total, count(DISTINCT conversation_id) AS conversations,
                       coalesce(avg(latency_ms), 0) AS avg_latency, count(*) FILTER (WHERE status = 'error') AS errors
                FROM history {clause}""", params).fetchone()
    return {"total": stats["total"], "conversations": stats["conversations"],
            "avg_latency_ms": round(float(stats["avg_latency"])), "errors": stats["errors"],
            "items": [_out(r) for r in rows]}


def get_question(history_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(f"SELECT {', '.join(FULL_FIELDS)} FROM history WHERE id = %s", (history_id,)).fetchone()
    return _out(row) if row else None


def delete_question(history_id: str) -> bool:
    with connection() as conn:
        return conn.execute("DELETE FROM history WHERE id = %s", (history_id,)).rowcount > 0


def save_api_call(entry: dict):
    try:
        with connection() as conn:
            conn.execute(
                """INSERT INTO api_logs (timestamp, request_id, method, path, route, status, duration_ms, client, summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (entry["timestamp"], entry["request_id"], entry["method"], entry["path"], entry["route"],
                 entry["status"], entry["duration_ms"], entry["client"], entry["summary"]))
    except Exception:
        log.exception("could not save API log")


def list_api_calls(path: str | None, status: str | None, method: str | None, limit: int, offset: int) -> dict:
    where, params = [], []
    if path:
        where.append("route LIKE %s")
        params.append(path.replace("%", "\\%") + "%")
    if method:
        where.append("method = %s")
        params.append(method.upper())
    if status == "error":
        where.append("status >= 400")
    elif status == "ok":
        where.append("status < 400")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with connection() as conn:
        rows = conn.execute(f"SELECT * FROM api_logs {clause} ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                            (*params, limit, offset)).fetchall()
        total = conn.execute(f"SELECT count(*) AS n FROM api_logs {clause}", params).fetchone()["n"]
        routes = conn.execute(
            f"""SELECT route, count(*) AS calls, round(avg(duration_ms)::numeric, 1) AS avg_ms,
                       count(*) FILTER (WHERE status >= 400) AS errors
                FROM api_logs {clause} GROUP BY route ORDER BY calls DESC LIMIT 20""", params).fetchall()
    return {"total": total,
            "routes": [{**r, "avg_ms": float(r["avg_ms"] or 0)} for r in routes],
            "items": [{**{k: iso(v) for k, v in r.items()}, "id": str(r["id"])} for r in rows]}
