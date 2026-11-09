"""Milvus: the search collection holding every document chunk.

  embedding   dense vector (Gemini, 1536-d) → HNSW, cosine        meaning search (kNN)
  body        context + text, analysed     → BM25 sparse vector  keyword search
  terms       split terms (see terms.py)    → BM25 sparse vector  IDs written differently ("b.p.no 5")
                                            + PHRASE_MATCH        exact IDs ("b p no 5" as a phrase)
Milvus computes the BM25 vectors itself from the text on insert."""
import json
from functools import lru_cache

from pymilvus import DataType, Function, FunctionType, MilvusClient

from .config import get_settings

TEXT_MAX = 65_535
OUTPUT = ["document_id", "chunk_index", "filename", "context", "text", "location", "metadata"]


def collection() -> str:
    return f"{get_settings().collection_prefix}_chunks"


@lru_cache
def client() -> MilvusClient:
    s = get_settings()
    c = MilvusClient(uri=s.milvus_uri, token=s.milvus_token or None)
    ensure_collection(c, collection(), s.embed_dim)
    return c


def ensure_collection(c: MilvusClient, name: str, dim: int):
    if c.has_collection(name):
        c.load_collection(name)
        return
    schema = c.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=96)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("filename", DataType.VARCHAR, max_length=1024)
    schema.add_field("context", DataType.VARCHAR, max_length=4096)
    schema.add_field("text", DataType.VARCHAR, max_length=TEXT_MAX)
    schema.add_field("body", DataType.VARCHAR, max_length=TEXT_MAX, enable_analyzer=True)
    schema.add_field("terms", DataType.VARCHAR, max_length=TEXT_MAX, enable_analyzer=True, enable_match=True)
    schema.add_field("body_bm25", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("terms_bm25", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("location", DataType.JSON)
    schema.add_field("metadata", DataType.JSON)
    schema.add_function(Function(name="body_bm25_fn", function_type=FunctionType.BM25,
                                 input_field_names=["body"], output_field_names=["body_bm25"]))
    schema.add_function(Function(name="terms_bm25_fn", function_type=FunctionType.BM25,
                                 input_field_names=["terms"], output_field_names=["terms_bm25"]))
    idx = c.prepare_index_params()
    idx.add_index("embedding", index_type="HNSW", metric_type="COSINE", params={"M": 16, "efConstruction": 128})
    for field in ("body_bm25", "terms_bm25"):
        idx.add_index(field, index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
                      params={"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75})
    idx.add_index("document_id", index_type="INVERTED")
    # Strong consistency: a document is searchable as soon as it is marked ready.
    c.create_collection(name, schema=schema, index_params=idx, consistency_level="Strong")
    c.load_collection(name)


def _clip(text: str, limit: int) -> str:
    """VARCHAR limits are in bytes; cut on a character boundary."""
    data = text.encode("utf-8")
    return text if len(data) <= limit else data[:limit].decode("utf-8", "ignore")


def upsert_chunks(rows: list[dict]):
    """rows: id, document_id, chunk_index, filename, context, text, terms, embedding, location, metadata."""
    data = [{
        "id": r["id"], "document_id": r["document_id"], "chunk_index": r["chunk_index"],
        "filename": _clip(r["filename"], 1024), "context": _clip(r["context"], 4096),
        "text": _clip(r["text"], TEXT_MAX), "body": _clip(f"{r['context']}\n{r['text']}", TEXT_MAX),
        "terms": _clip(r["terms"], TEXT_MAX), "embedding": r["embedding"],
        "location": r["location"], "metadata": r["metadata"],
    } for r in rows]
    for i in range(0, len(data), 200):
        client().upsert(collection(), data[i:i + 200])


def _quote(value: str) -> str:
    return json.dumps(value)  # a double-quoted string literal with escapes


def delete_document(document_id: str, from_index: int = 0):
    expr = f"document_id == {_quote(document_id)}"
    if from_index:
        expr += f" and chunk_index >= {int(from_index)}"
    client().delete(collection(), filter=expr)


def count(document_id: str | None = None) -> int:
    expr = f"document_id == {_quote(document_id)}" if document_id else ""
    res = client().query(collection(), filter=expr, output_fields=["count(*)"])
    return int(res[0]["count(*)"]) if res else 0


def set_metadata(document_id: str, metadata: dict):
    """Copy a document's metadata onto its chunks (used as a search filter)."""
    rows = client().query(collection(), filter=f"document_id == {_quote(document_id)}",
                          output_fields=OUTPUT + ["terms", "embedding"], limit=16_384)
    for r in rows:
        r["metadata"] = metadata
    if rows:
        upsert_chunks(rows)


def filter_expr(document_ids: list[str] | None, metadata: dict | None) -> tuple[str, dict]:
    """A Milvus filter plus its template values (values are never pasted into the expression)."""
    parts, params = [], {}
    if document_ids:
        parts.append("document_id in {doc_ids}")
        params["doc_ids"] = list(document_ids)
    for i, (key, value) in enumerate((metadata or {}).items()):
        if not key.replace("_", "").isalnum():
            continue  # metadata keys are plain words; anything else is ignored
        name = f"m{i}"
        if isinstance(value, list):
            parts.append(f'metadata["{key}"] in {{{name}}}')
        else:
            parts.append(f'metadata["{key}"] == {{{name}}}')
        params[name] = value
    return " and ".join(parts), params


def search(anns_field: str, data, limit: int, expr: str, params: dict, search_params: dict | None = None) -> list[dict]:
    res = client().search(collection(), data=[data], anns_field=anns_field, limit=limit,
                          filter=expr, filter_params=params or None,
                          search_params=search_params or {}, output_fields=OUTPUT)
    return [{"id": h["id"], "score": h["distance"], **h["entity"]} for h in res[0]]
