"""Chats as shown in the sidebar and History page: a conversation's questions live in `history`;
its settings (custom title, pinned, group) in `chats`; groups in `chat_groups`. All in PostgreSQL."""
import uuid

from .db import connection, iso


class NotFound(Exception):
    pass


# One row per conversation: first question, number of questions, last activity, and its settings.
CHATS_SQL = """
WITH stats AS (
    SELECT conversation_id,
           count(*) AS questions,
           max(created_at) AS updated_at,
           (array_agg(question ORDER BY created_at))[1] AS first_question
    FROM history
    GROUP BY conversation_id
)
SELECT s.conversation_id AS id, coalesce(c.title, s.first_question) AS title, s.questions, s.updated_at,
       coalesce(c.pinned, false) AS pinned, c.pinned_at, c.group_id
FROM stats s LEFT JOIN chats c ON c.conversation_id = s.conversation_id
{where}
ORDER BY coalesce(c.pinned, false) DESC, c.pinned_at DESC NULLS LAST, s.updated_at DESC
LIMIT %s
"""


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_chats(q: str | None = None, limit: int = 100) -> dict:
    """Pinned first (most recently pinned on top), then by last activity. Pinned and grouped chats are
    always included; a search matches any question or answer in the chat, or its custom title."""
    params: list = []
    if q:
        where = """WHERE c.title ILIKE %s OR s.conversation_id IN (
                       SELECT conversation_id FROM history WHERE question ILIKE %s OR answer ILIKE %s)"""
        params = [_like(q)] * 3
        sql = CHATS_SQL.format(where=where)
    else:
        sql = CHATS_SQL.format(where="")
    with connection() as conn:
        rows = conn.execute(sql, (*params, limit)).fetchall()
        if not q:  # make sure organised chats are never cut off by the limit
            ids = {r["id"] for r in rows}
            extra = conn.execute(CHATS_SQL.format(where="WHERE c.pinned OR c.group_id IS NOT NULL"), (1000,)).fetchall()
            rows += [r for r in extra if r["id"] not in ids]
        total = conn.execute("SELECT count(DISTINCT conversation_id) AS n FROM history").fetchone()["n"]
    items = [{**r, "updated_at": iso(r["updated_at"]), "pinned_at": iso(r["pinned_at"])} for r in rows]
    items.sort(key=lambda i: i["updated_at"] or "", reverse=True)
    pinned = sorted((i for i in items if i["pinned"]), key=lambda i: i["pinned_at"] or "", reverse=True)
    return {"total": total, "items": pinned + [i for i in items if not i["pinned"]]}


def update_chat(conversation_id: str, changes: dict) -> dict:
    """changes: any of title (str, "" resets to the first question), pinned (bool), group_id (str or None)."""
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM history WHERE conversation_id = %s LIMIT 1", (conversation_id,)).fetchone():
            raise NotFound(conversation_id)
        if changes.get("group_id") and not conn.execute("SELECT 1 FROM chat_groups WHERE id = %s",
                                                        (changes["group_id"],)).fetchone():
            raise NotFound(changes["group_id"])
        conn.execute("INSERT INTO chats (conversation_id) VALUES (%s) ON CONFLICT DO NOTHING", (conversation_id,))
        sets, params = [], []
        if "title" in changes:
            sets.append("title = %s")
            params.append((changes["title"] or "").strip()[:200] or None)
        if "pinned" in changes:
            sets.append("pinned = %s, pinned_at = CASE WHEN %s THEN now() ELSE NULL END")
            params += [bool(changes["pinned"]), bool(changes["pinned"])]
        if "group_id" in changes:
            sets.append("group_id = %s")
            params.append(changes["group_id"] or None)
        sets.append("updated_at = now()")
        row = conn.execute(f"UPDATE chats SET {', '.join(sets)} WHERE conversation_id = %s RETURNING *",
                           (*params, conversation_id)).fetchone()
    return {"id": conversation_id, **{k: iso(v) for k, v in row.items() if k != "conversation_id"}}


def delete_chat(conversation_id: str) -> int:
    with connection() as conn:
        deleted = conn.execute("DELETE FROM history WHERE conversation_id = %s", (conversation_id,)).rowcount
        conn.execute("DELETE FROM chats WHERE conversation_id = %s", (conversation_id,))
    return deleted


# ---------- groups ----------

def list_groups() -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT g.id, g.name, count(c.conversation_id) AS chats
               FROM chat_groups g LEFT JOIN chats c ON c.group_id = g.id
               GROUP BY g.id, g.name ORDER BY g.name""").fetchall()
    return [dict(r) for r in rows]


def get_group(group_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM chat_groups WHERE id = %s", (group_id,)).fetchone()


def create_group(name: str) -> dict:
    group_id = uuid.uuid4().hex
    with connection() as conn:
        row = conn.execute("INSERT INTO chat_groups (id, name) VALUES (%s, %s) RETURNING *",
                           (group_id, name.strip()[:80])).fetchone()
    return {"id": row["id"], "name": row["name"], "created_at": iso(row["created_at"]), "chats": 0}


def rename_group(group_id: str, name: str) -> dict:
    with connection() as conn:
        row = conn.execute("UPDATE chat_groups SET name = %s WHERE id = %s RETURNING *",
                           (name.strip()[:80], group_id)).fetchone()
    if row is None:
        raise NotFound(group_id)
    return {"id": row["id"], "name": row["name"], "created_at": iso(row["created_at"])}


def delete_group(group_id: str) -> int:
    """Deletes the group; its chats are kept and go back to Recents."""
    with connection() as conn:
        moved = conn.execute("UPDATE chats SET group_id = NULL WHERE group_id = %s", (group_id,)).rowcount
        if conn.execute("DELETE FROM chat_groups WHERE id = %s", (group_id,)).rowcount == 0:
            raise NotFound(group_id)
    return moved
