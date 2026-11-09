"""Entry point for the FastAPI CLI, which finds this file by itself:

    fastapi dev     # development: auto-reload on code changes, http://127.0.0.1:8000
    fastapi run     # production: http://0.0.0.0:8000

Uploads are processed by worker threads started inside the API (EMBEDDED_WORKERS in .env)."""
from rag.api import app

__all__ = ["app"]
