"""All settings come from environment variables (see .env.example)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/rag/config.py -> project root, where .env lives (inside Docker, env vars come from compose instead)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Bump when extraction output changes: every document is re-extracted (and OCR'd) on requeue-stale.
EXTRACT_VERSION = "2"  # 2: scanned pages and images read with Docling
# Bump when chunking changes: documents are re-chunked from cached extractions, no re-OCR.
CHUNK_VERSION = "4"  # 4: chunks stored in Milvus


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # Gemini
    gemini_api_key: str = ""
    embed_model: str = "all-MiniLM-L6-v2"
    embed_dim: int = 384
    embed_batch_size: int = 100
    embed_batch_tokens: int = 20_000  # tokens per embedding request
    embed_tokens_per_minute: int = 0  # pace embedding requests to stay under the key's quota; 0 = no pacing
    quota_wait_minutes: int = 20  # on a quota error (429), keep waiting and retrying for this long (< stale lock)
    gemini_model: str = "gemini-3.5-flash-lite"  # env GEMINI_MODEL
    llm_temperature: float = 0.2

    # PostgreSQL: documents + job queue, chats, history, groups, API log, embedding cache
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    # Milvus: document chunks for search (vectors + BM25 + phrase match)
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""  # "user:password" when Milvus authentication is on
    collection_prefix: str = "rag"

    # Files
    data_dir: Path = PROJECT_ROOT / "data"  # uploaded files and extraction cache

    # API
    api_key: str = ""  # when set, every request must send header X-API-Key
    max_upload_mb: int = 200
    log_get_requests: bool = False  # GET calls are logged only when they fail (keeps polling out of the log)

    # Extraction
    ocr_engine: str = "docling"  # docling (open-source layout + tables + OCR) | tesseract | gemini
    ocr_lang: str = "eng"  # Tesseract languages, e.g. eng+hin
    docling_ocr: str = "tesseract"  # OCR engine inside Docling: tesseract (best on our scans) | easyocr | rapidocr
    docling_lang: str = "en"  # languages for Docling's OCR engine, e.g. "en,hi" when documents contain Hindi
    ocr_dpi: int = 300
    ocr_workers: int = 4
    min_text_chars: int = 50  # a PDF page with fewer real characters is treated as scanned

    # Chunking (tokens are estimated as characters / 4; gemini-embedding-001 reads up to 2048 tokens)
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 60

    # Guardrails (see guardrails.py)
    ask_rate_per_minute: int = 30  # questions per client per minute; 0 = no limit
    min_document_words: int = 5  # a document with fewer readable words is rejected as empty or unreadable
    guard_retry: bool = True  # ask the model once more when its answer has numbers its sources do not contain

    # Worker
    embedded_workers: int = 2  # worker threads started by the API itself; 0 when separate workers run (Docker)
    max_attempts: int = 3
    stale_lock_minutes: int = 30
    poll_seconds: float = 2.0

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def extract_cache_dir(self) -> Path:
        return self.data_dir / "extracted"

    @property
    def pipeline_version(self) -> str:
        return f"x{EXTRACT_VERSION}.c{CHUNK_VERSION}.{self.embed_model}.{self.embed_dim}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
