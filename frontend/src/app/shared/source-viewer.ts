import { Component, Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';

import { ApiService } from '../core/api.service';
import { DocumentsStore } from '../core/documents.store';
import { Source } from '../core/models';

/** Which cited source is open in the side panel. */
@Injectable({ providedIn: 'root' })
export class SourceViewerService {
  readonly source = signal<Source | null>(null);

  open(source: Source) {
    this.source.set(source);
  }

  close() {
    this.source.set(null);
  }
}

/** Side panel showing a source: the PDF at its page, the image, or (Word, Excel…) the matching text.
 *  Placed once in the app shell. The file is downloaded with the API key and shown from a blob URL. */
@Component({
  selector: 'app-source-viewer',
  host: { '(document:keydown.escape)': 'viewer.close()' },
  template: `
    @if (viewer.source(); as s) {
      <aside class="viewer">
        <header>
          <div class="title">
            <strong [title]="s.filename">{{ s.filename }}</strong>
          </div>
          <button type="button" class="icon-btn" title="Close (Esc)" (click)="viewer.close()">✕</button>
        </header>
        @if (kind() === 'text') {
          <pre>{{ s.text }}</pre>
        } @else if (error()) {
          <p class="error-text">{{ error() }}</p>
        } @else if (!file()) {
          <p class="muted">Loading…</p>
        } @else if (kind() === 'pdf') {
          @for (src of [pdfSrc()]; track src) {
            <iframe [src]="src" [title]="s.filename"></iframe>
          }
        } @else {
          <div class="image"><img [src]="file()!.url" [alt]="s.filename" /></div>
        }
      </aside>
    }
  `,
  styles: `
    :host { display: block; min-height: 0; }
    .viewer {
      display: flex; flex-direction: column; height: 100%;
      width: min(48vw, 760px); background: var(--panel); border-left: 1px solid var(--line);
    }
    header {
      display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--line);
    }
    .title { display: grid; min-width: 0; flex: 1; font-size: 13px; }
    .title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    iframe { flex: 1; width: 100%; border: 0; }
    .image { flex: 1; overflow: auto; padding: 12px; }
    .image img { max-width: 100%; }
    p { padding: 0 14px; }
    pre {
      flex: 1; overflow: auto; margin: 0; padding: 14px; white-space: pre-wrap; word-break: break-word;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    @media (max-width: 900px) {
      .viewer { position: fixed; inset: 0; width: auto; z-index: 20; }
    }
  `,
})
export class SourceViewer {
  protected readonly viewer = inject(SourceViewerService);
  private readonly api = inject(ApiService);
  private readonly docs = inject(DocumentsStore);
  private readonly sanitizer = inject(DomSanitizer);

  /** The downloaded file of the open source (kept while sources of the same document are clicked). */
  protected readonly file = signal<{ id: string; url: string } | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly page = computed(() => {
    const page = this.viewer.source()?.location['page'];
    return typeof page === 'number' ? page : null;
  });

  protected readonly kind = computed<'pdf' | 'image' | 'text'>(() => {
    const s = this.viewer.source();
    const type = this.docs.documents().find((d) => d.id === s?.document_id)?.file_type
      ?? (s?.filename.toLowerCase().endsWith('.pdf') ? 'pdf' : '');
    return type === 'pdf' || type === 'image' ? type : 'text';
  });

  protected readonly pdfSrc = computed(() => {
    const url = this.file()?.url;
    const page = this.page();
    return url ? this.sanitizer.bypassSecurityTrustResourceUrl(page ? `${url}#page=${page}` : url) : null;
  });

  constructor() {
    effect(() => {
      const s = this.viewer.source();
      if (!s || this.kind() === 'text' || untracked(this.file)?.id === s.document_id) return;
      this.release();
      this.error.set(null);
      this.api.documentFile(s.document_id).subscribe({
        next: (blob) => {
          if (this.viewer.source()?.document_id === s.document_id) {
            this.file.set({ id: s.document_id, url: URL.createObjectURL(blob) });
          }
        },
        error: () => this.error.set('Could not load the file. It may have been deleted.'),
      });
    });
  }

  private release() {
    const current = this.file();
    if (current) URL.revokeObjectURL(current.url);
    this.file.set(null);
  }
}
