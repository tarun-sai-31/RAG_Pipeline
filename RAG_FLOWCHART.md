# Document Assistant RAG Pipeline: Step-by-Step Flowcharts

This document provides visual flowcharts and technical breakdowns for the two core pipelines in the system:
1. **Document Ingestion & Indexing Pipeline** (Upload ➔ Parsing ➔ Chunking ➔ Embedding ➔ Milvus)
2. **Query Retrieval & Answer Generation Pipeline** (Question ➔ 4-Way Hybrid Search ➔ Context Assembly ➔ Gemini LLM ➔ Interactive Citations)

---

## 1. High-Level Architecture Overview

```mermaid
flowchart TD
    subgraph Frontend["Frontend (Angular 22)"]
        UI["Chat & Document Management UI"]
    end

    subgraph Backend["Backend (FastAPI)"]
        API["FastAPI App (rag/api.py)"]
        Worker["Background Workers (rag/worker.py)"]
    end

    subgraph Databases["Databases & Storage"]
        PG[("PostgreSQL 16: Job Queue, History, Embedding Cache")]
        Milvus[("Milvus 3.0: Vectors, BM25, Phrase Match")]
        Disk[("Local Storage: Original Files & Extraction Cache")]
    end

    subgraph External["Google Gemini API"]
        EmbedAPI["gemini-embedding-001 (1536-d)"]
        LLMAPI["gemini-3.5-flash-lite (Answers & Rewrites)"]
    end

    UI -->|"Uploads & Queries"| API
    API -->|"Enqueues Jobs & Logs"| PG
    Worker -->|"Claims Jobs (SKIP LOCKED)"| PG
    Worker -->|"Stores Files & Caches"| Disk
    Worker -->|"Generates Embeddings"| EmbedAPI
    Worker -->|"Indexes Chunks"| Milvus
    API -->|"4-Way Hybrid Search"| Milvus
    API -->|"Prompts with Sources"| LLMAPI
    API -->|"Returns Answers + Citations"| UI
```

---

## 2. Document Ingestion Pipeline (Step-by-Step)

When a user uploads a document (PDF, DOCX, XLSX, Image), this pipeline processes it once in the background.

```mermaid
flowchart TD
    Start(["User Uploads File"]) --> Upload["FastAPI POST /documents"]
    Upload --> Hash["Stream to disk & calculate SHA-256 hash"]
    
    Hash --> Dedupe{"Content SHA-256 already in database?"}
    Dedupe -- Yes --> ReturnReady["Return status: ready immediately (Duplicate detected, 0 work)"]
    Dedupe -- No --> Enqueue["Save file to data/files/ and insert into PostgreSQL documents table with status: queued"]

    Enqueue --> WorkerClaim["Background Worker claims job via UPDATE ... SKIP LOCKED"]
    WorkerClaim --> CacheCheck{"Extraction cache exists on disk?"}
    
    CacheCheck -- Yes --> LoadCache["Load cached JSON extraction"]
    CacheCheck -- No --> DetectType["Detect file type (Magic bytes & extension)"]

    DetectType --> PageRouting{"Is it a PDF?"}
    
    PageRouting -- Yes --> PDFPages["Inspect PDF page-by-page"]
    PageCheck{"Does page have digital text?"}
    PDFPages --> PageCheck
    PageCheck -- Yes --> PyMuPDF["PyMuPDF: Fast extraction of text & tables (milliseconds)"]
    PageCheck -- No --> DoclingPDF["Docling: Layout Analysis + TableFormer + Tesseract OCR"]
    
    PageRouting -- No --> OtherExt{"File Type?"}
    OtherExt -- Images --> DoclingImg["Docling Image OCR & Table Structure"]
    OtherExt -- Office (.docx, .xlsx, .csv) --> OfficeDirect["Direct Parser (preserve sheets, headers, rows)"]
    OtherExt -- Legacy (.doc, .xls, .ppt) --> LibreOffice["LibreOffice (soffice) convert to modern format"]
    LibreOffice --> OfficeDirect

    PyMuPDF --> MergeExtract["Combine into Extraction Segments"]
    DoclingPDF --> MergeExtract
    DoclingImg --> MergeExtract
    OfficeDirect --> MergeExtract
    LoadCache --> MergeExtract

    MergeExtract --> SaveExtractCache["Cache Extraction JSON on disk (sha256.v2.json)"]
    SaveExtractCache --> Chunking["Structure-Aware Chunking (rag/chunking.py)"]

    subgraph ChunkLogic["Chunking Details"]
        Chunking --> TablePreserve["Tables: repeat column headers across row chunks"]
        Chunking --> Breadcrumbs["Inject location: 'filename > Sheet > Page > Rows'"]
        Chunking --> SizeControl["Pack prose into ~500 tokens with 60 token overlap"]
    end

    SizeControl --> EmbedBatch["Batch Chunks for Embedding"]
    EmbedBatch --> EmbedCacheCheck{"Embedding in PostgreSQL cache?"}
    EmbedCacheCheck -- Yes --> ReuseEmbed["Reuse cached float32 vector (Save cost/quota)"]
    EmbedCacheCheck -- No --> GeminiEmbed["Call Gemini API (gemini-embedding-001) with Quota Pacing"]
    GeminiEmbed --> SaveEmbedCache["Save new vectors to embedding_cache table"]

    ReuseEmbed --> MilvusIndex["Milvus Upsert (rag/vectors.py)"]
    SaveEmbedCache --> MilvusIndex

    subgraph MilvusStorage["Milvus Collection: rag_chunks"]
        MilvusIndex --> Dense["1. embedding: 1536-d float vector (HNSW cosine)"]
        MilvusIndex --> BodyBM25["2. body_bm25: Sparse vector on full text"]
        MilvusIndex --> TermsBM25["3. terms_bm25: Sparse vector on normalized terms"]
        MilvusIndex --> ExactTerms["4. terms: Raw normalized text for PHRASE_MATCH"]
    end

    MilvusStorage --> MarkReady["PostgreSQL UPDATE documents SET status='ready'"]
    MarkReady --> EndIngest(["Document Ready for Search"])
```

---

## 3. Query Retrieval & Answer Generation Pipeline (Step-by-Step)

When a user asks a question like: **`"what is topic about the b.p.no 153 ?"`**:

```mermaid
flowchart TD
    UserQuery(["User Question: 'what is topic about the b.p.no 153 ?'"]) --> UIAction["Angular ChatPage dispatches POST /api/ask"]
    UIAction --> APIRoute["FastAPI POST /ask (rag/api.py)"]

    APIRoute --> CheckHistory{"Has prior conversation turns?"}
    CheckHistory -- Yes --> GeminiRewrite["Call Gemini Flash: Rewrite follow-up into standalone query"]
    CheckHistory -- No --> UseRawQuery["Use original question as query"]

    GeminiRewrite --> QueryString["Query String"]
    UseRawQuery --> QueryString

    QueryString --> TermParsing["rag/terms.py Normalization"]
    subgraph TermProcessing["Query Decomposition"]
        TermParsing --> CleanTerms["split_terms: 'what is topic about the b p no 153'"]
        TermParsing --> IDPhrases["id_phrases: detects '153' ➔ phrase 'b p no 153'"]
    end

    CleanTerms --> ParallelSearch["Milvus 4-Way Hybrid Search (rag/search.py)"]
    IDPhrases --> ParallelSearch

    subgraph MilvusHybrid["4 Parallel Milvus Queries"]
        ParallelSearch --> Search1["Signal 1: kNN Dense Vector Search (Gemini embed_query) | Weight: 1.0"]
        ParallelSearch --> Search2["Signal 2: Keyword BM25 on Context + Text | Weight: 1.0"]
        ParallelSearch --> Search3["Signal 3: Split Terms BM25 on 'b p no 153' | Weight: 1.0"]
        ParallelSearch --> Search4["Signal 4: Exact ID Match: PHRASE_MATCH(terms, 'b p no 153') | Weight: 3.0"]
    end

    Search1 --> RRF["Weighted Reciprocal Rank Fusion (RRF)"]
    Search2 --> RRF
    Search3 --> RRF
    Search4 --> RRF

    RRF --> TopHits["Select Top 8 Highest Scoring Chunks"]

    TopHits --> PromptAssembly["Assemble Structured Prompt Context"]

    subgraph PromptStructure["Context Sent to Gemini"]
        PromptAssembly --> SystemRules["System Prompt: 'Use only numbered sources. Cite with [1][2]. Do not guess.'"]
        PromptAssembly --> NumberedSources["[1] doc.pdf > Page 4 > Section 2 ...\n[2] other.xlsx > Sheet 1 ..."]
        PromptAssembly --> ConvHistory["Conversation history (if any)"]
        PromptAssembly --> FinalQuestion["Question: 'what is topic about the b.p.no 153 ?'"]
    end

    SystemRules --> GeminiCall["Gemini API: gemini-3.5-flash-lite"]
    NumberedSources --> GeminiCall
    ConvHistory --> GeminiCall
    FinalQuestion --> GeminiCall

    GeminiCall --> LLMOutput["Model Output: Grounded text citing [1], [2]"]
    
    LLMOutput --> SaveHistory["Save question, answer, sources, and latency to PostgreSQL history"]
    LLMOutput --> SaveLog["Log API call to api_logs"]
    
    SaveHistory --> ReturnJSON["Return JSON response to Frontend"]
    ReturnJSON --> FrontendRender["Angular Answer Component (shared/answer.ts)"]

    subgraph UIRender["Frontend Interactive Citations"]
        FrontendRender --> MarkdownText["Render markdown answer"]
        FrontendRender --> ClickableCite["Transform [1] into interactive clickable badge"]
        ClickableCite --> ClickEvent["User clicks [1] ➔ Auto-scroll & highlight Source #1 accordion"]
    end

    ClickEvent --> Finish(["User views answer and verifies exact source"])
```

---

## 4. Key Data Formats at Critical Steps

### A. What a Chunk Looks Like in Milvus
```json
{
  "id": "e3b0c44...-00004",
  "document_id": "e3b0c44...",
  "chunk_index": 4,
  "filename": "Tower_C_Approvals.pdf",
  "context": "Tower_C_Approvals.pdf > Page 4 > Approval Details",
  "text": "B.P. No. 153: Sanction of revised building plan for Tower C. Total area: 45,200 sq.m.",
  "body": "Tower_C_Approvals.pdf > Page 4 > Approval Details\nB.P. No. 153: Sanction of revised building plan...",
  "terms": "tower c approvals pdf page 4 approval details b p no 153 sanction of revised building plan...",
  "embedding": [0.0123, -0.0456, ...],
  "location": {"page": 4, "section": "Approval Details"}
}
```

### B. What is Sent to Gemini for Generating the Answer
```text
SYSTEM INSTRUCTIONS:
You are a helpful assistant that answers questions about the user's uploaded documents.
Use only the numbered sources provided.
- Cite every fact with its source number in square brackets, e.g. [2] or [1][3].
- Quote numbers, dates and names exactly as the sources give them, with their units.
- Use a short Markdown table when comparing several items.
- If sources disagree, say so and cite each.
- If the sources do not contain the answer, say you could not find it in the documents. Do not guess.

USER PROMPT:
Sources:

[1] Tower_C_Approvals.pdf > Page 4 > Approval Details
B.P. No. 153: Sanction of revised building plan for Tower C. Total area: 45,200 sq.m. Approved on 12/04/2023.

[2] Meeting_Minutes.pdf > Page 2
Pending files discussed: B.P. No. 153 was finalized after fire safety clearance.

Question: what is topic about the b.p.no 153 ?
```
