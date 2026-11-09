-- PostgreSQL holds everything except the search chunks (those are in Milvus).

-- One row per unique file (id = SHA-256 of the content). The table doubles as the job queue.
CREATE TABLE IF NOT EXISTS documents (
    id               text PRIMARY KEY,
    filename         text NOT NULL,
    file_type        text NOT NULL,
    size_bytes       bigint NOT NULL,
    storage_path     text NOT NULL,
    metadata         jsonb NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'queued',  -- queued | processing | ready | failed
    stage            text,
    error            text,
    attempts         int NOT NULL DEFAULT 0,
    available_at     timestamptz NOT NULL DEFAULT now(),
    locked_at        timestamptz,
    pipeline_version text,
    page_count       int,
    ocr_page_count   int,
    chunk_count      int,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_queue_idx ON documents (status, available_at);
CREATE INDEX IF NOT EXISTS documents_created_idx ON documents (created_at DESC);

-- Embeddings keyed by model/dim/title/text: the same text is never paid for twice.
CREATE TABLE IF NOT EXISTS embedding_cache (
    key        text PRIMARY KEY,
    embedding  bytea NOT NULL,          -- float32 values
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Every question asked, with the full response returned.
CREATE TABLE IF NOT EXISTS history (
    id              text PRIMARY KEY,
    conversation_id text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    question        text NOT NULL,
    query           text,
    answer          text,
    source_files    text[] NOT NULL DEFAULT '{}',
    document_ids    text[] NOT NULL DEFAULT '{}',
    filters         jsonb NOT NULL DEFAULT '{}',
    model           text,
    status          text NOT NULL,      -- ok | blocked (by guardrails) | error
    error           text,
    latency_ms      int,
    source_count    int,
    turn            int,
    response        jsonb
);
CREATE INDEX IF NOT EXISTS history_conversation_idx ON history (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS history_created_idx ON history (created_at DESC);

-- Chat groups and per-chat settings (custom title, pinned, group).
CREATE TABLE IF NOT EXISTS chat_groups (
    id         text PRIMARY KEY,
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chats (
    conversation_id text PRIMARY KEY,
    title           text,
    pinned          boolean NOT NULL DEFAULT false,
    pinned_at       timestamptz,
    group_id        text REFERENCES chat_groups (id) ON DELETE SET NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Every API call (writes always, reads when they fail).
CREATE TABLE IF NOT EXISTS api_logs (
    id          bigserial PRIMARY KEY,
    timestamp   timestamptz NOT NULL DEFAULT now(),
    request_id  text,
    method      text,
    path        text,
    route       text,
    status      int,
    duration_ms real,
    client      text,
    summary     text
);
CREATE INDEX IF NOT EXISTS api_logs_time_idx ON api_logs (timestamp DESC);
