// Types for the FastAPI backend responses (see backend/rag/api.py).

export type DocStatus = 'queued' | 'processing' | 'ready' | 'failed' | 'rejected';

export interface DocumentItem {
  id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  metadata: Record<string, unknown> | null;
  status: DocStatus;
  stage: string | null;
  error: string | null;
  attempts: number;
  page_count: number | null;
  ocr_page_count: number | null;
  chunk_count: number | null;
  pipeline_version: string | null;
  created_at: string;
  updated_at: string;
  duplicate?: boolean;
}

export interface DocumentList {
  total: number;
  counts: Partial<Record<DocStatus, number>>;
  documents: DocumentItem[];
}

export interface Source {
  n: number;
  document_id: string;
  filename: string;
  context: string;
  text: string;
  location: Record<string, unknown>;
  score: number;
}

export interface Turn {
  role: 'user' | 'assistant';
  content: string;
}

export interface AskRequest {
  query: string;
  history?: Turn[];
  conversation_id?: string;
  document_ids?: string[];
  metadata?: Record<string, unknown>;
  top_k?: number;
}

export interface GuardrailFinding {
  check: string;
  message: string;
  values?: (string | number)[];
  files?: string[];
}

/** What the guardrails found in a question and its answer (see backend/rag/guardrails.py). */
export interface Guardrails {
  status: 'passed' | 'warning' | 'blocked';
  findings: GuardrailFinding[];
  retried?: boolean;
}

export interface AskResponse {
  answer: string;
  query: string;
  sources: Source[];
  guardrails?: Guardrails;
  conversation_id: string;
  history_id: string;
  latency_ms: number;
}

export interface HistoryItem {
  id: string;
  conversation_id: string;
  created_at: string;
  question: string;
  query?: string;
  answer?: string;
  source_files?: string[];
  model: string;
  status: 'ok' | 'blocked' | 'error';
  error?: string;
  latency_ms?: number;
  source_count?: number;
  turn: number;
  document_ids?: string[];
  filters?: Record<string, unknown>;
  response?: Omit<AskResponse, 'conversation_id' | 'history_id' | 'latency_ms'>;
}

export interface HistoryList {
  total: number;
  conversations: number;
  avg_latency_ms: number;
  errors: number;
  items: HistoryItem[];
}

export interface Conversation {
  id: string;
  title: string; // custom name, or the first question
  questions: number;
  updated_at: string;
  pinned: boolean;
  pinned_at: string | null;
  group_id: string | null;
}

export interface ChatGroup {
  id: string;
  name: string;
  chats: number;
}

export interface ConversationList {
  total: number;
  items: Conversation[];
}

export interface AppConfig {
  auth_required: boolean;
  model: string;
  embed_model: string;
  max_upload_mb: number;
  ocr_engine: string;
}
