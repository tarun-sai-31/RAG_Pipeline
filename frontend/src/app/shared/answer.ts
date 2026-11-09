import { Component, computed, inject, input } from '@angular/core';

import { Source } from '../core/models';
import { MarkdownPipe } from './format';
import { SourceViewerService } from './source-viewer';

/** An answer with clickable [n] citations and the files it cites. Used in the chat and in the history. */
@Component({
  selector: 'app-answer',
  imports: [MarkdownPipe],
  template: `
    <div class="md" [innerHTML]="text() | markdown" (click)="onClick($event)"></div>
    @if (files().length) {
      <div class="sources">
        <span class="label">{{ files().length === 1 ? 'Source' : 'Sources' }}</span>
        @for (s of files(); track s.document_id) {
          <button
            type="button"
            class="src"
            [class.hl]="viewer.source()?.document_id === s.document_id"
            title="Open the file"
            (click)="viewer.open(s)"
          >
            📄 {{ s.filename }}
          </button>
        }
      </div>
    }
  `,
  styles: `
    .sources {
      display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
      margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px;
    }
    .label { color: var(--muted); font-size: 12px; }
    .src {
      max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      border: 1px solid var(--line); border-radius: 8px; padding: 4px 10px; font-size: 12px;
      background: none; color: inherit; cursor: pointer;
    }
    .src:hover, .src.hl { border-color: var(--accent); background: var(--accent-soft); }
  `,
})
export class Answer {
  readonly text = input.required<string>();
  readonly sources = input<Source[]>([]);
  protected readonly viewer = inject(SourceViewerService);

  /** One entry per file the answer cites ([1], [1, 2]…), in order of first citation; each opens at its first cited page. */
  protected readonly files = computed(() => {
    const cited = [...this.text().matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g)].flatMap((m) => m[1].split(',').map(Number));
    const sources = cited.length
      ? cited.map((n) => this.sources().find((s) => s.n === n)).filter((s): s is Source => !!s)
      : this.sources();
    return sources.filter((s, i) => sources.findIndex((o) => o.document_id === s.document_id) === i);
  });

  protected onClick(event: MouseEvent) {
    const cite = (event.target as HTMLElement).closest<HTMLElement>('.cite');
    if (!cite) return;
    const source = this.sources().find((s) => s.n === Number(cite.dataset['n']));
    if (source) this.viewer.open(source);
  }
}
