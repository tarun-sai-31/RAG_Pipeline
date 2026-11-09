"""Command line:
  python -m rag.cli ingest <folder> [--metadata '{"project": "Vyom"}']   register every file (bulk backfill)
  python -m rag.cli preview <file>                                        show extraction + chunks, no API calls
  python -m rag.cli requeue-stale                                         reprocess after a pipeline version change
  python -m rag.cli ask "question"
"""
import argparse
import json
import sys
import time
from pathlib import Path

from .config import get_settings


def cmd_ingest(args):
    from .ingest import register
    meta = json.loads(args.metadata) if args.metadata else None
    files = [p for p in sorted(Path(args.folder).rglob("*")) if p.is_file() and not p.name.startswith((".", "~$"))]
    new = dup = 0
    for p in files:
        rel = str(p.relative_to(args.folder))
        with open(p, "rb") as fh:
            doc = register(fh, p.name, {**(meta or {}), "source_path": rel})
        new, dup = (new, dup + 1) if doc["duplicate"] else (new + 1, dup)
        print(f"{'dup ' if doc['duplicate'] else 'new '} {doc['status']:<10} {rel}")
    print(f"\n{new} queued, {dup} already known, {len(files)} files")


def cmd_preview(args):
    from .chunking import chunk_segments
    from .extractors import detect_type, extract
    path = Path(args.file)
    settings = get_settings()
    t = time.monotonic()
    file_type = detect_type(path, path.name)
    ex = extract(path, file_type)
    chunks = chunk_segments(ex.segments, path.name, settings.chunk_tokens, settings.chunk_overlap_tokens)
    print(f"type={file_type} pages={ex.page_count} ocr_pages={ex.ocr_page_count} segments={len(ex.segments)} "
          f"chunks={len(chunks)} time={time.monotonic() - t:.2f}s")
    for c in chunks[: args.limit]:
        print(f"\n--- {c.context}  ({len(c.text)} chars)\n{c.text[:args.chars]}")


def cmd_requeue_stale(_args):
    from .ingest import requeue_stale
    print(f"{requeue_stale()} documents queued for pipeline {get_settings().pipeline_version}")


def _delete_one(doc_id: str):
    from . import ingest, vectors
    from .config import EXTRACT_VERSION, get_settings
    from .db import connection
    doc = ingest.get_document(doc_id)
    if not doc:
        return None
    vectors.delete_document(doc_id)
    with connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    Path(doc["storage_path"]).unlink(missing_ok=True)
    cache = get_settings().extract_cache_dir / doc_id[:2] / f"{doc_id}.v{EXTRACT_VERSION}.json"
    cache.unlink(missing_ok=True)
    return doc["filename"]


def cmd_delete(args):
    name = _delete_one(args.document_id)
    if name:
        print(f"Deleted {name} ({args.document_id})")
    else:
        print(f"Document not found: {args.document_id}")


def cmd_delete_all(args):
    from .db import connection
    with connection() as conn:
        rows = conn.execute("SELECT id FROM documents").fetchall()
    if not rows:
        print("No documents found.")
        return
    if not args.yes:
        confirm = input(f"Are you sure you want to delete ALL {len(rows)} documents and their Milvus chunks? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            return
    count = 0
    for r in rows:
        name = _delete_one(r["id"])
        if name:
            count += 1
            print(f"Deleted: {name} ({r['id'][:12]}...)")
    print(f"\nSuccessfully deleted {count} document(s).")


def cmd_ask(args):
    from .search import answer
    result = answer(args.question, top_k=args.top_k)
    print(result["answer"], "\n")
    for s in result["sources"]:
        print(f"[{s['n']}] {s['context']}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rag")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("folder"); p.add_argument("--metadata"); p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("preview"); p.add_argument("file"); p.add_argument("--limit", type=int, default=5)
    p.add_argument("--chars", type=int, default=800); p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("requeue-stale"); p.set_defaults(fn=cmd_requeue_stale)
    p = sub.add_parser("delete"); p.add_argument("document_id"); p.set_defaults(fn=cmd_delete)
    p = sub.add_parser("delete-all"); p.add_argument("-y", "--yes", action="store_true"); p.set_defaults(fn=cmd_delete_all)
    p = sub.add_parser("ask"); p.add_argument("question"); p.add_argument("--top-k", type=int, default=8)
    p.set_defaults(fn=cmd_ask)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
