import { HttpClient, HttpEvent, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AppConfig,
  AskRequest,
  AskResponse,
  ChatGroup,
  DocumentItem,
  ConversationList,
  DocumentList,
  HistoryList,
} from './models';

/** Every backend endpoint in one place. Calls go to /api/..., which nginx (or the dev proxy) forwards to FastAPI. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  config(): Observable<AppConfig> {
    return this.http.get<AppConfig>(`${this.base}/config`);
  }

  // ----- documents -----
  listDocuments(): Observable<DocumentList> {
    return this.http.get<DocumentList>(`${this.base}/documents`, { params: { limit: 1000 } });
  }

  upload(file: File, metadata?: Record<string, unknown>): Observable<HttpEvent<{ documents: DocumentItem[] }>> {
    const form = new FormData();
    form.append('files', file, file.name);
    if (metadata && Object.keys(metadata).length) {
      form.append('metadata', JSON.stringify(metadata));
    }
    return this.http.post<{ documents: DocumentItem[] }>(`${this.base}/documents`, form, {
      reportProgress: true,
      observe: 'events',
    });
  }

  reprocess(id: string): Observable<DocumentItem> {
    return this.http.post<DocumentItem>(`${this.base}/documents/${id}/reprocess`, {});
  }

  moveToFolder(id: string, folder: string): Observable<DocumentItem> {
    return this.http.patch<DocumentItem>(`${this.base}/documents/${id}`, { folder });
  }

  documentFile(id: string): Observable<Blob> {
    return this.http.get(`${this.base}/documents/${id}/file`, { responseType: 'blob' });
  }

  deleteDocument(id: string): Observable<{ deleted: string }> {
    return this.http.delete<{ deleted: string }>(`${this.base}/documents/${id}`);
  }

  // ----- questions -----
  ask(body: AskRequest): Observable<AskResponse> {
    return this.http.post<AskResponse>(`${this.base}/ask`, body);
  }

  // ----- history -----
  history(opts: {
    q?: string;
    status?: string;
    conversationId?: string;
    includeResponse?: boolean;
    limit?: number;
    offset?: number;
  }): Observable<HistoryList> {
    let params = new HttpParams().set('limit', opts.limit ?? 50).set('offset', opts.offset ?? 0);
    if (opts.q) params = params.set('q', opts.q);
    if (opts.status) params = params.set('status', opts.status);
    if (opts.conversationId) params = params.set('conversation_id', opts.conversationId);
    if (opts.includeResponse) params = params.set('include_response', true);
    return this.http.get<HistoryList>(`${this.base}/history`, { params });
  }

  conversations(opts: { q?: string; limit?: number } = {}): Observable<ConversationList> {
    let params = new HttpParams().set('limit', opts.limit ?? 50);
    if (opts.q) params = params.set('q', opts.q);
    return this.http.get<ConversationList>(`${this.base}/conversations`, { params });
  }

  updateConversation(id: string, changes: { title?: string; pinned?: boolean; group_id?: string | null }) {
    return this.http.patch<unknown>(`${this.base}/conversations/${id}`, changes);
  }

  deleteConversation(id: string): Observable<{ deleted: string }> {
    return this.http.delete<{ deleted: string }>(`${this.base}/conversations/${id}`);
  }

  // ----- chat groups -----
  groups(): Observable<{ groups: ChatGroup[] }> {
    return this.http.get<{ groups: ChatGroup[] }>(`${this.base}/groups`);
  }

  createGroup(name: string): Observable<ChatGroup> {
    return this.http.post<ChatGroup>(`${this.base}/groups`, { name });
  }

  renameGroup(id: string, name: string): Observable<ChatGroup> {
    return this.http.patch<ChatGroup>(`${this.base}/groups/${id}`, { name });
  }

  deleteGroup(id: string): Observable<unknown> {
    return this.http.delete(`${this.base}/groups/${id}`);
  }
}
