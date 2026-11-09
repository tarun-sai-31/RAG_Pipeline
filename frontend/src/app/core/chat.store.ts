import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, map, tap } from 'rxjs';

import { ApiService } from './api.service';
import { errorMessage } from './auth';
import { ConversationsStore } from './conversations.store';
import { DocumentsStore } from './documents.store';
import { AskResponse, Guardrails, Source, Turn } from './models';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  guardrails?: Guardrails;
  query?: string;
  latencyMs?: number;
  historyId?: string;
  error?: boolean;
}

const HISTORY_TURNS = 12; // messages of context sent with each question

/** The current conversation. Lives in a service so it survives switching pages. */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ApiService);
  private readonly docs = inject(DocumentsStore);
  private readonly conversations = inject(ConversationsStore);

  readonly messages = signal<ChatMessage[]>([]);
  readonly conversationId = signal<string | null>(null);
  readonly busy = signal(false);
  readonly empty = computed(() => this.messages().length === 0);
  private generation = 0; // bumped when switching chats, so a late answer can't land in the wrong one

  send(question: string): Observable<AskResponse> {
    const history: Turn[] = this.messages()
      .filter((m) => !m.error)
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content }));
    const selected = [...this.docs.selected()];
    this.messages.update((list) => [...list, { role: 'user', content: question }]);
    this.busy.set(true);
    const generation = this.generation;
    return this.api
      .ask({
        query: question,
        history: history.length ? history : undefined,
        conversation_id: this.conversationId() ?? undefined,
        document_ids: selected.length ? selected : undefined,
      })
      .pipe(
        tap({
          next: (res) => {
            this.conversations.refresh();
            if (generation !== this.generation) return; // the user moved to another chat meanwhile
            this.conversationId.set(res.conversation_id);
            this.messages.update((list) => [
              ...list,
              {
                role: 'assistant',
                content: res.answer,
                sources: res.sources,
                guardrails: res.guardrails,
                query: res.query,
                latencyMs: res.latency_ms,
                historyId: res.history_id,
              },
            ]);
            this.busy.set(false);
          },
          error: (err) => {
            if (generation !== this.generation) return;
            this.messages.update((list) => [...list, { role: 'assistant', content: errorMessage(err), error: true }]);
            this.busy.set(false);
          },
        }),
      );
  }

  reset() {
    this.generation++;
    this.messages.set([]);
    this.conversationId.set(null);
    this.busy.set(false);
  }

  /** Reopen a past conversation from the history, with its answers and sources. */
  resume(conversationId: string): Observable<void> {
    this.generation++;
    this.busy.set(false);
    this.conversationId.set(conversationId);
    this.messages.set([]);
    return this.api.history({ conversationId, includeResponse: true, limit: 200 }).pipe(
      map((res) => {
        const messages: ChatMessage[] = [];
        for (const item of res.items) {
          messages.push({ role: 'user', content: item.question });
          if (item.status !== 'error') {
            messages.push({
              role: 'assistant',
              content: item.answer ?? '',
              sources: item.response?.sources ?? [],
              guardrails: item.response?.guardrails,
              query: item.query,
              latencyMs: item.latency_ms,
              historyId: item.id,
            });
          } else {
            messages.push({ role: 'assistant', content: item.error ?? 'This question failed.', error: true });
          }
        }
        this.messages.set(messages);
        this.conversationId.set(conversationId);
      }),
    );
  }
}
