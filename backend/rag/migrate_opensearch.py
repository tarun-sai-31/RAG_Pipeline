"""One-off: copy everything from the old OpenSearch indices into PostgreSQL, then queue every document so
the worker re-indexes it into Milvus (extraction and embeddings are reused from the caches, so no Gemini
cost for unchanged text).

    python -m rag.migrate_opensearch [http://localhost:9200] [index-prefix]
Safe to run more than once: existing rows are kept (ON CONFLICT DO NOTHING)."""
import json
import sys
import urllib.request

import numpy as np
from psycopg.types.json import Jsonb

from .db import connection


def fetch_all(base: str, index: str) -> list[dict]:
    req = urllib.request.Request(f"{base}/{index}/_search", method="POST",
                                 data=json.dumps({"size": 10000, "query": {"match_all": {}}}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            hits = json.loads(resp.read())["hits"]["hits"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return [{"_id": h["_id"], **h["_source"]} for h in hits]


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9200").rstrip("/")
    prefix = sys.argv[2] if len(sys.argv) > 2 else "rag"
    counts = {}
    with connection() as conn, conn.cursor() as cur:
        rows = fetch_all(base, f"{prefix}-documents")
        cur.executemany(
            """INSERT INTO documents (id, filename, file_type, size_bytes, storage_path, metadata, status,
                   page_count, ocr_page_count, chunk_count, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            [(d["_id"], d["filename"], d["file_type"], d["size_bytes"], d["storage_path"], Jsonb(d.get("metadata") or {}),
              d.get("page_count"), d.get("ocr_page_count"), d.get("chunk_count"), d["created_at"], d["updated_at"])
             for d in rows])
        counts["documents"] = len(rows)

        rows = fetch_all(base, f"{prefix}-embeddings")
        cur.executemany("INSERT INTO embedding_cache (key, embedding) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                        [(r["_id"], np.asarray(r["embedding"], dtype=np.float32).tobytes()) for r in rows])
        counts["embeddings"] = len(rows)

        rows = fetch_all(base, f"{prefix}-chat-groups")
        cur.executemany("INSERT INTO chat_groups (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        [(g["_id"], g["name"], g["created_at"]) for g in rows])
        counts["groups"] = len(rows)

        rows = fetch_all(base, f"{prefix}-history")
        cur.executemany(
            """INSERT INTO history (id, conversation_id, created_at, question, query, answer, source_files, document_ids,
                   filters, model, status, error, latency_ms, source_count, turn, response)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            [(h["_id"], h["conversation_id"], h["created_at"], h["question"], h.get("query"), h.get("answer"),
              h.get("source_files") or [], h.get("document_ids") or [], Jsonb(h.get("filters") or {}), h.get("model"),
              h.get("status", "ok"), h.get("error"), h.get("latency_ms"), h.get("source_count"), h.get("turn"),
              Jsonb(h["response"]) if h.get("response") is not None else None) for h in rows])
        counts["questions"] = len(rows)

        rows = fetch_all(base, f"{prefix}-chats")
        cur.executemany(
            """INSERT INTO chats (conversation_id, title, pinned, pinned_at, group_id, updated_at)
               VALUES (%s, %s, %s, %s, %s, coalesce(%s, now())) ON CONFLICT (conversation_id) DO NOTHING""",
            [(c["_id"], c.get("title"), bool(c.get("pinned")), c.get("pinned_at"), c.get("group_id"), c.get("updated_at"))
             for c in rows])
        counts["chat settings"] = len(rows)

        already = cur.execute("SELECT count(*) AS n FROM api_logs").fetchone()["n"]
        rows = [] if already else fetch_all(base, f"{prefix}-api-logs")  # logs have no id: copy only once
        cur.executemany(
            """INSERT INTO api_logs (timestamp, request_id, method, path, route, status, duration_ms, client, summary)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(r["timestamp"], r.get("request_id"), r.get("method"), r.get("path"), r.get("route"), r.get("status"),
              r.get("duration_ms"), r.get("client"), r.get("summary")) for r in rows])
        counts["API log entries"] = len(rows)

    for what, n in counts.items():
        print(f"{what:<16} {n}")
    print("Documents are queued; the worker re-indexes them into Milvus.")


if __name__ == "__main__":
    main()
