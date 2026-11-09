"""Background worker. PostgreSQL is the queue: each worker claims one document with FOR UPDATE SKIP LOCKED,
so any number of workers can run side by side. A worker that dies leaves a stale lock that is reclaimed
after STALE_LOCK_MINUTES."""
import logging
import signal
import threading

from .config import get_settings
from .db import connection
from .extractors import UnsupportedFile
from .pipeline import DocumentDeleted, process

log = logging.getLogger("rag.worker")


def claim() -> dict | None:
    with connection() as conn:
        return conn.execute(
            """UPDATE documents SET status = 'processing', locked_at = now(), attempts = attempts + 1,
                      updated_at = now()
               WHERE id = (
                   SELECT id FROM documents
                   WHERE (status = 'queued' AND available_at <= now())
                      OR (status = 'processing' AND locked_at < now() - make_interval(mins => %s))
                   ORDER BY available_at
                   FOR UPDATE SKIP LOCKED
                   LIMIT 1)
               RETURNING *""",
            (get_settings().stale_lock_minutes,),
        ).fetchone()


def fail(doc: dict, error: Exception):
    settings = get_settings()
    permanent = isinstance(error, (UnsupportedFile, ValueError)) or doc["attempts"] >= settings.max_attempts
    message = f"{type(error).__name__}: {error}"[:2000]
    with connection() as conn:
        if permanent:
            conn.execute("UPDATE documents SET status = 'failed', error = %s, locked_at = NULL, updated_at = now() "
                         "WHERE id = %s", (message, doc["id"]))
        else:  # retry later with backoff: 1, 4, 9 ... minutes
            conn.execute("UPDATE documents SET status = 'queued', error = %s, locked_at = NULL, "
                         "available_at = now() + make_interval(mins => %s), updated_at = now() WHERE id = %s",
                         (message, doc["attempts"] ** 2, doc["id"]))


def run_once() -> bool:
    doc = claim()
    if doc is None:
        return False
    if doc["attempts"] > get_settings().max_attempts:  # reclaimed after crashes (e.g. out of memory) too often
        fail(doc, RuntimeError("worker stopped while processing this file on every attempt"))
        return True
    log.info("processing %s (%s, attempt %d)", doc["filename"], doc["id"], doc["attempts"])
    try:
        process(doc)
    except DocumentDeleted:
        log.info("%s was deleted while it was being processed; stopped", doc["filename"])
    except Exception as e:
        log.exception("failed %s", doc["filename"])
        fail(doc, e)
    return True


def run_forever(stop: threading.Event):
    """Process queued documents until `stop` is set (finishes the current document first)."""
    while not stop.is_set():
        try:
            busy = run_once()
        except Exception:  # e.g. OpenSearch restarting; keep the worker alive
            log.exception("queue error")
            busy = False
        if not busy:
            stop.wait(get_settings().poll_seconds)


def start_background(count: int) -> threading.Event:
    """Run `count` workers as threads inside the API process (so `fastapi dev` is all you need)."""
    stop = threading.Event()
    for i in range(count):
        threading.Thread(target=run_forever, args=(stop,), name=f"rag-worker-{i + 1}", daemon=True).start()
    log.info("%d background worker(s) started", count)
    return stop


def main():
    """Standalone worker process (used by the Docker `worker` service)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = threading.Event()

    def on_signal(*_):
        log.info("stopping after the current document")
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("worker started")
    run_forever(stop)


if __name__ == "__main__":
    main()
