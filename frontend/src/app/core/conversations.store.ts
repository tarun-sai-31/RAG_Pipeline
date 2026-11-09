import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, forkJoin, switchMap, tap } from 'rxjs';

import { ApiService } from './api.service';
import { errorMessage } from './auth';
import { ChatGroup, Conversation } from './models';

/** Chats and groups for the sidebar and the History page, with the pin / rename / group / delete actions. */
@Injectable({ providedIn: 'root' })
export class ConversationsStore {
  private readonly api = inject(ApiService);

  readonly all = signal<Conversation[]>([]);
  readonly groups = signal<ChatGroup[]>([]);
  readonly error = signal<string | null>(null);

  readonly pinned = computed(() => this.all().filter((c) => c.pinned));
  /** Unpinned chats of each group, in the group order. */
  readonly grouped = computed(() =>
    this.groups().map((g) => ({ group: g, chats: this.all().filter((c) => !c.pinned && c.group_id === g.id) })),
  );
  readonly recent = computed(() => this.all().filter((c) => !c.pinned && !c.group_id));

  refresh() {
    forkJoin([this.api.conversations({ limit: 100 }), this.api.groups()]).subscribe({
      next: ([chats, groups]) => {
        this.all.set(chats.items);
        this.groups.set(groups.groups);
        this.error.set(null);
      },
      error: (err) => this.error.set(errorMessage(err)),
    });
  }

  pin(c: Conversation) {
    this.run(this.api.updateConversation(c.id, { pinned: !c.pinned }));
  }

  rename(c: Conversation, title: string) {
    this.patchLocal(c.id, { title: title.trim() || c.title });
    this.run(this.api.updateConversation(c.id, { title: title.trim() }));
  }

  moveTo(c: Conversation, groupId: string | null) {
    this.patchLocal(c.id, { group_id: groupId });
    this.run(this.api.updateConversation(c.id, { group_id: groupId }));
  }

  moveToNewGroup(c: Conversation, name: string) {
    this.run(this.api.createGroup(name).pipe(switchMap((g) => this.api.updateConversation(c.id, { group_id: g.id }))));
  }

  remove(c: Conversation) {
    this.all.update((list) => list.filter((x) => x.id !== c.id));
    this.run(this.api.deleteConversation(c.id));
  }

  renameGroup(g: ChatGroup, name: string) {
    this.run(this.api.renameGroup(g.id, name));
  }

  removeGroup(g: ChatGroup) {
    this.run(this.api.deleteGroup(g.id));
  }

  private patchLocal(id: string, changes: Partial<Conversation>) {
    this.all.update((list) => list.map((c) => (c.id === id ? { ...c, ...changes } : c)));
  }

  /** Run a change, then reload so the sidebar and History show the server's state. */
  private run(request: Observable<unknown>) {
    request.pipe(tap({ error: (err) => this.error.set(errorMessage(err)) })).subscribe({
      next: () => this.refresh(),
      error: () => this.refresh(),
    });
  }
}
