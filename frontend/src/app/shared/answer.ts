import { Component, input, signal } from '@angular/core';

import { Source } from '../core/models';
import { MarkdownPipe } from './format';

/** An answer with clickable [n] citations and its numbered sources. Used in the chat and in the history. */
@Component({
  selector: 'app-answer',
  imports: [MarkdownPipe],
  template: `
    <div class="md" [innerHTML]="text() | markdown" (click)="onClick($event)"></div>
    @if (sources().length) {
      <details class="sources" [open]="open()" (toggle)="open.set($any($event.target).open)">
        <summary>Sources ({{ sources().length }})</summary>
        @for (s of sources(); track s.n) {
          <div class="src" [class.hl]="highlighted() === s.n" [attr.id]="anchor(s.n)">
            <b>[{{ s.n }}]</b> <span class="ctx">{{ s.context }}</span>
            <pre>{{ s.text }}</pre>
          </div>
        }
      </details>
    }
  `,
  styles: `
    .sources { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
    summary { cursor: pointer; color: var(--muted); font-size: 12px; }
    .src { margin-top: 8px; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 12px; }
    .src.hl { border-color: var(--accent); background: var(--accent-soft); }
    .src b { color: var(--accent); }
    .ctx { color: var(--muted); }
    pre {
      white-space: pre-wrap; word-break: break-word; margin: 6px 0 0; max-height: 220px; overflow: auto;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
    }
  `,
})
export class Answer {
  readonly text = input.required<string>();
  readonly sources = input<Source[]>([]);
  protected readonly open = signal(false);
  protected readonly highlighted = signal<number | null>(null);
  private readonly uid = Math.random().toString(36).slice(2, 8);

  protected anchor(n: number) {
    return `src-${this.uid}-${n}`;
  }

  protected onClick(event: MouseEvent) {
    const cite = (event.target as HTMLElement).closest<HTMLElement>('.cite');
    if (!cite) return;
    const n = Number(cite.dataset['n']);
    this.open.set(true);
    this.highlighted.set(n);
    setTimeout(() => document.getElementById(this.anchor(n))?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }
}
