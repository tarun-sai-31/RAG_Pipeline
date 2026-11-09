import { Component, ElementRef, HostListener, computed, inject, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';

import { DocumentsStore, folderOf } from '../core/documents.store';
import { DocumentItem } from '../core/models';

/** "Ask about" in the sidebar: which documents the chat searches. Folders select all their files at once
 *  and can be expanded to pick single files. The selection lives in DocumentsStore. */
@Component({
  selector: 'app-doc-scope',
  imports: [RouterLink],
  template: `
    <div class="scope">
      <button
        type="button"
        class="scope-btn"
        [class.open]="scopeOpen()"
        [attr.aria-expanded]="scopeOpen()"
        aria-haspopup="listbox"
        (click)="scopeOpen.set(!scopeOpen())"
      >
        <span class="text">
          <span class="muted">Ask about</span>
          <strong [title]="scopeLabel()">{{ scopeLabel() }}</strong>
        </span>
        <svg class="caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>

      @if (scopeOpen()) {
        <div class="scope-menu card" role="listbox" aria-multiselectable="true">
          <input
            class="input"
            placeholder="Filter documents"
            [value]="docFilter()"
            (input)="docFilter.set($any($event.target).value)"
          />
          <label class="doc all">
            <input type="checkbox" [checked]="!docs.selected().size" (change)="docs.clearSelection()" />
            <span>All documents</span>
          </label>
          <div class="doc-list">
            @for (g of folders(); track g.name) {
              <div class="folder">
                <button
                  type="button"
                  class="expand"
                  [class.open]="isExpanded(g.name)"
                  [attr.aria-expanded]="isExpanded(g.name)"
                  [title]="isExpanded(g.name) ? 'Hide files' : 'Show files'"
                  (click)="toggleExpanded(g.name)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
                </button>
                <label class="doc">
                  <input
                    type="checkbox"
                    [checked]="folderState(g.docs) === 'all'"
                    [indeterminate]="folderState(g.docs) === 'some'"
                    (change)="selectFolder(g.docs, $any($event.target).checked)"
                  />
                  <span>📁 {{ g.name }} <span class="muted">({{ g.docs.length }})</span></span>
                </label>
              </div>
              @if (isExpanded(g.name)) {
                @for (d of g.docs; track d.id) {
                  <label class="doc nested">
                    <input
                      type="checkbox"
                      [checked]="docs.selected().has(d.id)"
                      (change)="docs.toggle(d.id, $any($event.target).checked)"
                    />
                    <span class="name" [title]="d.filename">{{ d.filename }}</span>
                  </label>
                }
              }
            }
            @for (d of looseDocs(); track d.id) {
              <label class="doc">
                <input
                  type="checkbox"
                  [checked]="docs.selected().has(d.id)"
                  (change)="docs.toggle(d.id, $any($event.target).checked)"
                />
                <span class="name" [title]="d.filename">{{ d.filename }}</span>
              </label>
            }
            @if (!visibleDocs().length) {
              <div class="muted small empty-list">
                @if (docs.ready().length) {
                  No documents match.
                } @else {
                  No ready documents yet. <a routerLink="/documents">Upload some</a>.
                }
              </div>
            }
          </div>
          <div class="menu-foot">
            <button type="button" class="btn small" (click)="scopeOpen.set(false)">Done</button>
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .small {
      font-size: 12px;
    }

    .scope {
      position: relative;
      min-width: 0;
    }

    .scope-btn {
      display: flex;
      align-items: center;
      gap: 6px;
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 10px;
      padding: 5px 8px 5px 10px;
      font-size: 13px;
      .text {
        display: grid;
        flex: 1;
        min-width: 0;
      }
      .muted {
        font-size: 11px;
        white-space: nowrap;
      }
      strong {
        font-weight: 600;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .caret {
        width: 18px;
        height: 18px;
        flex-shrink: 0;
        overflow: visible;
        fill: none;
        stroke: var(--muted);
        stroke-width: 2;
        stroke-linecap: round;
        stroke-linejoin: round;
        transition: transform 0.15s;
      }
      &:hover,
      &.open {
        border-color: var(--accent);
      }
      &.open .caret {
        transform: rotate(180deg);
      }
    }

    /* Opens inside the sidebar, pushing the links below it down. */
    .scope-menu {
      margin-top: 6px;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 13px;
    }

    .doc-list {
      max-height: 280px;
      overflow-y: auto;
    }

    .doc {
      display: flex;
      gap: 8px;
      align-items: flex-start;
      padding: 6px;
      border-radius: 6px;
      cursor: pointer;
      word-break: break-word;
      .name {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      &:hover {
        background: var(--bg);
      }
      &.all {
        font-weight: 600;
        border-bottom: 1px solid var(--line);
        border-radius: 6px 6px 0 0;
        padding-bottom: 8px;
      }
      input {
        margin-top: 3px;
        accent-color: var(--accent);
      }
      &.nested {
        margin-left: 24px;
      }
    }

    .folder {
      display: flex;
      align-items: flex-start;
      .doc {
        flex: 1;
        min-width: 0;
      }
    }

    .expand {
      flex-shrink: 0;
      display: grid;
      place-items: center;
      width: 24px;
      height: 28px;
      border: 0;
      background: none;
      border-radius: 6px;
      svg {
        width: 14px;
        height: 14px;
        fill: none;
        stroke: var(--muted);
        stroke-width: 2.2;
        stroke-linecap: round;
        stroke-linejoin: round;
        transition: transform 0.15s;
      }
      &.open svg {
        transform: rotate(90deg);
      }
      &:hover {
        background: var(--bg);
      }
    }

    .empty-list {
      padding: 8px 6px;
    }

    .menu-foot {
      display: flex;
      justify-content: flex-end;
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }
  `,
})
export class DocScope {
  protected readonly docs = inject(DocumentsStore);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  protected readonly scopeOpen = signal(false);
  protected readonly docFilter = signal('');
  protected readonly expanded = signal<ReadonlySet<string>>(new Set());

  protected readonly visibleDocs = computed(() => {
    const f = this.docFilter().trim().toLowerCase();
    return this.docs.ready().filter((d) => !f || d.filename.toLowerCase().includes(f));
  });

  /** Folders (each can be expanded to its files), then files outside any folder. */
  protected readonly folders = computed(() => {
    const groups = new Map<string, DocumentItem[]>();
    for (const d of this.visibleDocs()) {
      const name = folderOf(d);
      if (name) groups.set(name, [...(groups.get(name) ?? []), d]);
    }
    return [...groups].map(([name, docs]) => ({ name, docs })).sort((a, b) => a.name.localeCompare(b.name));
  });
  protected readonly looseDocs = computed(() => this.visibleDocs().filter((d) => !folderOf(d)));

  /** "All documents (7)", "📁 2025" when exactly one whole folder is chosen, else "3 selected documents". */
  protected readonly scopeLabel = computed(() => {
    const selected = this.docs.selected();
    if (!selected.size) return `All documents (${this.docs.ready().length})`;
    const folders = new Set(this.docs.ready().filter((d) => selected.has(d.id)).map(folderOf));
    const [only] = folders;
    if (folders.size === 1 && only && this.docs.ready().filter((d) => folderOf(d) === only).length === selected.size) {
      return `📁 ${only}`;
    }
    return `${selected.size} selected document${selected.size === 1 ? '' : 's'}`;
  });

  /** Close on a click outside or on Escape. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    if (this.scopeOpen() && !this.host.nativeElement.contains(event.target as Node)) this.scopeOpen.set(false);
  }

  @HostListener('document:keydown.escape')
  onEscape() {
    this.scopeOpen.set(false);
  }

  protected isExpanded(folder: string) {
    return this.expanded().has(folder) || !!this.docFilter().trim();
  }

  protected toggleExpanded(folder: string) {
    const next = new Set(this.expanded());
    if (!next.delete(folder)) next.add(folder);
    this.expanded.set(next);
  }

  protected folderState(docs: DocumentItem[]): 'all' | 'some' | 'none' {
    const n = docs.filter((d) => this.docs.selected().has(d.id)).length;
    return n === 0 ? 'none' : n === docs.length ? 'all' : 'some';
  }

  protected selectFolder(docs: DocumentItem[], on: boolean) {
    this.docs.toggleMany(docs.map((d) => d.id), on);
  }
}
