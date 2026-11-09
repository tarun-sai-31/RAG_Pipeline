import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Subject, debounceTime, switchMap } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { errorMessage } from '../../core/auth';
import { ChatActions } from '../../core/chat-actions';
import { ConversationsStore } from '../../core/conversations.store';
import { Conversation } from '../../core/models';
import { TimeAgoPipe } from '../../shared/format';
import { Icon } from '../../shared/icon';
import { Menu } from '../../shared/menu';

/** All chats, like a chat app's history: search, open, and the same "⋯" menu as the sidebar. */
@Component({
  selector: 'app-history-page',
  imports: [RouterLink, TimeAgoPipe, Menu, Icon],
  templateUrl: './history.page.html',
  styleUrl: './history.page.scss',
})
export class HistoryPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly store = inject(ConversationsStore);
  protected readonly actions = inject(ChatActions);
  private readonly search$ = new Subject<string>();

  protected readonly q = signal('');
  protected readonly results = signal<Conversation[] | null>(null); // search results; null = no search
  protected readonly searching = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly editing = signal<string | null>(null);

  protected readonly items = computed(() => (this.q().trim() ? (this.results() ?? []) : this.store.all()));
  protected readonly groupName = computed(() => new Map(this.store.groups().map((g) => [g.id, g.name])));

  constructor() {
    this.store.refresh();
    this.search$
      .pipe(
        debounceTime(250),
        switchMap((q) => this.api.conversations({ q, limit: 200 })),
      )
      .subscribe({
        next: (res) => {
          this.results.set(res.items);
          this.searching.set(false);
          this.error.set(null);
        },
        error: (err) => {
          this.error.set(errorMessage(err));
          this.searching.set(false);
        },
      });
    // Re-run the search after any change (pin, rename, delete…) so results stay current.
    effect(() => {
      this.store.all();
      const q = untracked(() => this.q().trim());
      if (q) this.search$.next(q);
    });
  }

  onSearch(value: string) {
    this.q.set(value);
    if (value.trim()) {
      this.searching.set(true);
      this.search$.next(value.trim());
    } else {
      this.results.set(null);
    }
  }

  open(c: Conversation) {
    if (this.editing() === c.id) return;
    this.router.navigate(['/chat'], { queryParams: { conversation: c.id } });
  }

  startRename(c: Conversation) {
    return () => {
      this.editing.set(c.id);
      setTimeout(() => {
        const box = document.querySelector<HTMLInputElement>('app-history-page input.rename');
        box?.focus();
        box?.select();
      });
    };
  }

  saveRename(c: Conversation, value: string) {
    if (this.editing() !== c.id) return;
    this.editing.set(null);
    const title = value.trim();
    if (title && title !== c.title) this.store.rename(c, title);
  }
}
