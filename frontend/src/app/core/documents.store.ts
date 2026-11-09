import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { errorMessage } from './auth';
import { DocStatus, DocumentItem } from './models';

const ACTIVE_POLL_MS = 3000; // while files are queued/processing
const IDLE_POLL_MS = 20000;

/** The folder a document was uploaded from, or the folder name typed at upload; '' for loose files. */
export function folderOf(doc: DocumentItem): string {
  const value = doc.metadata?.['folder'] ?? doc.metadata?.['project'];
  return typeof value === 'string' ? value : '';
}

/** The document list, kept fresh by polling, plus which documents the chat is limited to. */
@Injectable({ providedIn: 'root' })
export class DocumentsStore {
  private readonly api = inject(ApiService);
  private timer: ReturnType<typeof setTimeout> | null = null;

  readonly documents = signal<DocumentItem[]>([]);
  readonly counts = signal<Partial<Record<DocStatus, number>>>({});
  readonly total = signal(0);
  readonly loaded = signal(false);
  readonly error = signal<string | null>(null);
  readonly selected = signal<ReadonlySet<string>>(new Set());

  readonly ready = computed(() => this.documents().filter((d) => d.status === 'ready'));
  readonly busy = computed(() => (this.counts().queued ?? 0) + (this.counts().processing ?? 0) > 0);

  start() {
    if (this.timer === null) this.refresh();
  }

  refresh() {
    if (this.timer) clearTimeout(this.timer);
    this.api.listDocuments().subscribe({
      next: (res) => {
        this.documents.set(res.documents);
        this.counts.set(res.counts);
        this.total.set(res.total);
        this.error.set(null);
        this.loaded.set(true);
        const ids = new Set(res.documents.filter((d) => d.status === 'ready').map((d) => d.id));
        const kept = [...this.selected()].filter((id) => ids.has(id));
        if (kept.length !== this.selected().size) this.selected.set(new Set(kept));
        this.schedule(this.busy() ? ACTIVE_POLL_MS : IDLE_POLL_MS);
      },
      error: (err) => {
        this.error.set(errorMessage(err));
        this.loaded.set(true);
        this.schedule(10000);
      },
    });
  }

  toggle(id: string, on: boolean) {
    const next = new Set(this.selected());
    if (on) next.add(id);
    else next.delete(id);
    this.selected.set(next);
  }

  /** Select or clear several documents at once (a whole folder). */
  toggleMany(ids: string[], on: boolean) {
    const next = new Set(this.selected());
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    this.selected.set(next);
  }

  clearSelection() {
    this.selected.set(new Set());
  }

  private schedule(ms: number) {
    this.timer = setTimeout(() => this.refresh(), ms);
  }
}
