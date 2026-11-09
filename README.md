# Document Assistant

Upload any document (text PDF, scanned PDF, Word, Excel, PowerPoint, images, legacy `.doc/.xls/.xlsb`) and
ask questions about it in a chat. Each file is processed **once**, in the background, when it is uploaded.
Every question, and the exact response the API returned, is kept in a searchable history.

| Part | Technology |
|---|---|
| Frontend | Angular 22 (standalone components, signals), served by nginx |
| Backend | FastAPI (Python) with built-in background workers |
| Search | **Milvus 3.0** — kNN on embeddings + BM25 full-text + phrase match |
| App data | **PostgreSQL 16** — documents + job queue, chats, history, groups, API log, embedding cache |
| Reading scans and images | **Docling** (open-source layout + TableFormer tables + OCR via Tesseract), all local |
| Embeddings | Gemini `gemini-embedding-001` (1536 dimensions) |
| Answers | Gemini `gemini-3.5-flash-lite` |

## Run

The databases run in Docker. Start them once; they keep running, also after a reboot:
```bash
docker compose up -d
```

Then two commands, each in its own terminal:

```bash
# 1. Backend (API + background processing of uploads)
cd backend
./start.sh             # activates backend/.venv, then runs `fastapi dev` (auto-reload)
                       # ./start.sh run  → `fastapi run` (no auto-reload)
```

```bash
# 2. Frontend
cd frontend
npm start              # uses a Node that Angular accepts (24.15+), from nvm if this terminal's is older
```

| Open | Address |
|---|---|
| **The app** (chat, documents, history) | http://localhost:4200 |
| Backend API + Swagger docs | http://localhost:8000/docs |
| Milvus web UI (status) | http://localhost:9091/webui |
| Attu, browse the Milvus collection (optional) | `docker compose --profile tools up -d attu` → http://localhost:8001 |

Settings come from `RAG_Pipeline/.env`. Uploaded files and the extraction cache are in `RAG_Pipeline/data/`.
The backend processes uploads itself with `EMBEDDED_WORKERS` threads (default 2), so no separate worker is needed.
Stop with `Ctrl+C`; `docker compose down -t 0` stops the databases (their data is kept).

First-time setup on a new machine:
```bash
cp .env.example .env                                   # set GEMINI_API_KEY
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && nvm install && npm ci && cd ..
# also needed on the machine: tesseract-ocr (+ eng/hin language data) and LibreOffice (soffice)
docker compose up -d
```
Docling downloads its open-source models (layout and table structure) the first time it reads a scan.

**Everything in Docker instead** (e.g. on a server):
`docker compose --profile app up -d --build` → app on http://localhost:4200 (the API is reached through it at `/api`).

## Project structure

```
RAG_Pipeline/
├── docker-compose.yml            PostgreSQL, Milvus (+ etcd, MinIO), optional Attu, optional app containers
├── .env / .env.example           settings (keys, models, databases, OCR)
│
├── backend/                      FastAPI + workers (Python)
│   ├── start.sh                  activates .venv and runs `fastapi dev`
│   ├── main.py                   entry point for the FastAPI CLI
│   ├── Dockerfile                Python + Tesseract + LibreOffice + CPU PyTorch for Docling
│   ├── requirements.txt
│   ├── rag/
│   │   ├── api.py                HTTP endpoints + API call logging
│   │   ├── config.py             settings from .env
│   │   ├── db.py, schema.sql     PostgreSQL pool and tables
│   │   ├── vectors.py            Milvus collection: schema, BM25 functions, indexes, search, upsert/delete
│   │   ├── ingest.py             saving uploads, duplicate detection
│   │   ├── worker.py             background job loop (PostgreSQL SKIP LOCKED queue)
│   │   ├── pipeline.py           extract → chunk → embed → index (with caches)
│   │   ├── extractors/           pdf.py (text pages), docling_reader.py (scans, images, tables),
│   │   │                         office.py (Word, Excel), ocr.py (Tesseract / Gemini fallback)
│   │   ├── chunking.py           structure-aware chunking
│   │   ├── terms.py              ID-friendly terms ("b.p.no 5" = "B_P_No_5")
│   │   ├── gemini.py             Gemini embedding + generation calls, quota handling
│   │   ├── search.py             hybrid search, follow-up rewriting, cited answers
│   │   ├── guardrails.py         checks on questions, sources, answers and uploaded documents
│   │   ├── history.py            chat history + API call log
│   │   ├── chats.py              chat list: pin, rename, groups, delete
│   │   ├── migrate_opensearch.py one-off copy from the old OpenSearch setup
│   │   └── cli.py                ingest / preview / requeue-stale / ask
│   └── tests/                    pytest (fake Gemini, real PostgreSQL + Milvus, throwaway database)
│
└── frontend/                     Angular app
    ├── Dockerfile, nginx.conf    build with Node, serve with nginx, forward /api/* to the backend
    ├── proxy.conf.json           same forwarding for `npm start` during development
    └── src/app/
        ├── app.*                 shell: sidebar (new chat, pages, pinned / groups / recent chats)
        ├── layout/               sidebar chat list with the "⋯" menu
        ├── core/                 api.service (all endpoints), models, stores, chat actions
        ├── shared/               answer (citations + sources), menu, icons, name dialog, pipes
        └── features/             chat/, documents/, history/
```

## Services and ports

| Service | Port | Role |
|---|---|---|
| `postgres` | 5432 (localhost only) | documents + job queue, chats, history, groups, API log, embedding cache |
| `milvus` (+ `milvus-etcd`, `milvus-minio`) | 19530, web UI 9091 (localhost only) | search collection `rag_chunks` |
| `attu` *(profile tools)* | 8001 (localhost only) | browse the Milvus collection |
| `frontend`, `api`, `worker` *(profile app)* | 4200 | the app in Docker instead of on this machine |

## API endpoints

All endpoints are documented and can be tried at **/docs**. When `API_KEY` is set, send it as `X-API-Key`.

| Method | Path | What it does |
|---|---|---|
| POST | `/documents` | Upload files (multipart `files`, optional `metadata` JSON) |
| GET | `/documents` | All files with status and counts |
| GET / DELETE | `/documents/{id}` | One file / delete file, chunks and cache |
| POST | `/documents/{id}/reprocess` | Process again (uses caches) |
| POST | `/ask` | Answer a question; saved to history |
| POST | `/search` | Matching chunks only, no answer |
| GET | `/conversations` | Chats: pinned first, then most recent (`q` to search) |
| PATCH / DELETE | `/conversations/{id}` | Pin, rename, move to group / delete a chat |
| GET / POST | `/groups` | List / create chat groups |
| PATCH / DELETE | `/groups/{id}` | Rename / delete a group (its chats are kept) |
| GET / DELETE | `/history`, `/history/{id}` | Questions asked, with the full response |
| GET | `/api-logs` | API calls with per-endpoint counts, average time, errors |
| GET | `/config`, `/health` | UI settings, health check (PostgreSQL + Milvus chunk count) |

## How processing works

```
Upload ─► store file by SHA-256 ─► already indexed? ── yes ─► "ready" at once, no work
                                       │ no
                                       ▼
                      documents table (PostgreSQL) = job queue
                                       │  worker threads
   detect type ─► extract ─► scanned pages & images → Docling ─► chunk ─► embed (Gemini) ─► Milvus
                 (cached on disk per file hash)                       (embedding_cache in PostgreSQL)
```

| Type | Method |
|---|---|
| PDF page with a text layer | PyMuPDF text + tables (milliseconds per page) |
| PDF page without text (scan) | **Docling**: layout model, TableFormer for tables, Tesseract OCR on the text regions only (stamps and specks are skipped). About 8 s per page on a laptop CPU. |
| Images (png, jpg, tiff…) | **Docling**, as for scanned pages |
| .docx / .xlsx / .csv | read directly: headings, tables, every sheet |
| .doc .xls .xlsb .ppt .pptx … | converted by LibreOffice, then as above |

`OCR_ENGINE` picks the reader for scans: `docling` (default), `tesseract` (fast, plain text) or `gemini` (paid,
best on very poor scans). Inside Docling, `DOCLING_OCR=tesseract` read our scans best (EasyOCR was slower and
less accurate); `DOCLING_LANG=en,hi` adds Hindi. If Docling fails on a file, plain Tesseract is used instead.

## How a question is answered

1. Guardrails check the question; an attempt to override the assistant's rules is answered with a refusal
   (saved to the history with status `blocked`) and nothing is searched.
2. A follow-up is rewritten into a standalone question (Gemini, only when the chat has history).
3. The question is embedded (Gemini) and four searches run in Milvus:
   **kNN** on the embedding (HNSW, cosine) · **BM25** on context + text · **BM25** on split terms
   (`b.p.no 5` = `B.P. No. 5` = `B_P_No_5…pdf`) · **exact ID phrase** (`PHRASE_MATCH`, counts 3×).
4. The lists are merged by weighted reciprocal rank fusion; the best 8 chunks go to Gemini, which answers only
   from them with numbered citations.
5. Guardrails check the answer (see below), and the question and the full response are saved to the history.

## Guardrails

Plain checks in `rag/guardrails.py`, no extra models; they add milliseconds. What they find is returned with
every answer as `guardrails: {status: passed | warning | blocked, findings: [...]}` and shown under the answer.

| Where | Check | What happens |
|---|---|---|
| Question | Prompt injection ("ignore previous instructions", "system prompt", "you are now DAN"…) | Refused, not searched, status `blocked` |
| Question | More than `ASK_RATE_PER_MINUTE` questions from one client (API key, else IP) | HTTP 429 |
| Sources | A chunk carrying instructions for the assistant (hidden text in a document) | Left out of the prompt, reported |
| Sources | Every chunk is fenced as `<source n="…">` and the prompt says source text is data, not instructions | — |
| Answer | Citations to sources that do not exist (`[9]` with 8 sources) | Removed, reported |
| Answer | Every number must appear in the source its sentence cites (or in the question) | Asked once more with the numbers named (`GUARD_RETRY`); a number that survives is reported as a warning |
| Answer | Facts without any citation | Reported |
| Upload | An error page saved as a PDF ("the page you were trying to reach doesn't exist"), or fewer than `MIN_DOCUMENT_WORDS` words | Document fails with the reason; not indexed |

## Gemini quota (429 RESOURCE_EXHAUSTED)

Big files need several embedding requests in a row and can hit a key's per-minute limit. Embeddings are saved
after every request; on a 429 processing pauses until the quota window passes and then continues (up to
`QUOTA_WAIT_MINUTES`). Chat questions do not wait: the answer asks to try again in a minute.
Set `EMBED_TOKENS_PER_MINUTE` slightly below your key's limit to avoid the pauses.

## Nothing is processed twice

Re-uploads are free, failed files retry from the cached extraction, embeddings are cached per text. After changing
`CHUNK_VERSION`, `EXTRACT_VERSION` or the embedding model, run `backend/.venv/bin/python -m rag.cli requeue-stale`.

## Bulk load a folder

```bash
cd backend && .venv/bin/python -m rag.cli ingest "/path/to/reports"     # the running backend processes them
```

## Tests

```bash
docker compose up -d
cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests
```
They use a throwaway `rag_test` database and a throwaway Milvus collection; your data is not touched.

## Moved from OpenSearch (October 2026)

Documents, chats, history, groups, API log and embeddings were copied into PostgreSQL with
`python -m rag.migrate_opensearch`, and all documents re-indexed into Milvus. The old OpenSearch data is still in
the Docker volume `rag_pipeline_osdata`; delete it once you are happy: `docker volume rm rag_pipeline_osdata`.

## Before going live on a server

- Set `API_KEY` and a real `POSTGRES_PASSWORD` (and `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`) in `.env`.
- Keep PostgreSQL, Milvus and Attu on localhost or a private network; put 4200/8000 behind HTTPS.
- With the Gemini API, document text is sent to Google. Use a paid key for confidential documents.
  Docling runs entirely on your server.







## To Delete the allt eh documents from the Database 
  "curl -s http://localhost:8000/documents?limit=1000 | jq -r '.documents[].id' | while read id; do curl -s -X DELETE "http://localhost:8000/documents/$id"; echo "Deleted $id"; done  "