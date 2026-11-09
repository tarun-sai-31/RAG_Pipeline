import { NgTemplateOutlet } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ChatActions } from '../core/chat-actions';
import { ChatStore } from '../core/chat.store';
import { ConversationsStore } from '../core/conversations.store';
import { Conversation } from '../core/models';
import { Icon } from '../shared/icon';
import { Menu } from '../shared/menu';

const COLLAPSED_KEY = 'rag.collapsedGroups';

/** Sidebar chat list: Pinned, groups (folders), Recents. Each chat has a "⋯" menu. */
@Component({
  selector: 'app-sidebar-chats',
  imports: [RouterLink, Menu, Icon, NgTemplateOutlet],
  template: `
    <ng-template #chatRow let-c>
      @if (editing() === c.id) {
        <input
          class="rename"
          [value]="c.title"
          maxlength="200"
          aria-label="Chat name"
          (keydown.enter)="saveRename(c, $any($event.target).value)"
          (keydown.escape)="editing.set(null)"
          (blur)="saveRename(c, $any($event.target).value)"
        />
      } @else {
        <div class="chat" [class.active]="c.id === chat.conversationId()">
          <a class="title" routerLink="/chat" [queryParams]="{ conversation: c.id }" [title]="c.title">{{ c.title }}</a>
          <app-menu class="dots" [items]="actions.chatMenu(c, startRename(c))" label="Chat options" />
        </div>
      }
    </ng-template>

    <div class="lists">
      @if (store.pinned().length) {
        <div class="section">
          <div class="heading">Pinned</div>
          @for (c of store.pinned(); track c.id) {
            <ng-container *ngTemplateOutlet="chatRow; context: { $implicit: c }" />
          }
        </div>
      }

      @for (g of store.grouped(); track g.group.id) {
        <div class="section">
          <div class="group">
            <button type="button" class="group-toggle" (click)="toggleGroup(g.group.id)" [attr.aria-expanded]="!collapsed().has(g.group.id)">
              <app-icon name="chevron" [size]="14" class="caret" [class.open]="!collapsed().has(g.group.id)" />
              <app-icon name="folder" [size]="16" />
              <span class="title">{{ g.group.name }}</span>
              <span class="count">{{ g.chats.length }}</span>
            </button>
            <app-menu class="dots" [items]="actions.groupMenu(g.group)" label="Group options" />
          </div>
          @if (!collapsed().has(g.group.id)) {
            <div class="group-chats">
              @for (c of g.chats; track c.id) {
                <ng-container *ngTemplateOutlet="chatRow; context: { $implicit: c }" />
              } @empty {
                <div class="empty">No chats in this group.</div>
              }
            </div>
          }
        </div>
      }

      <div class="section">
        <div class="heading">Recents</div>
        @for (c of store.recent(); track c.id) {
          <ng-container *ngTemplateOutlet="chatRow; context: { $implicit: c }" />
        } @empty {
          <div class="empty">Your chats will appear here.</div>
        }
      </div>
    </div>
  `,
  styleUrl: './sidebar-chats.scss',
})
export class SidebarChats {
  protected readonly store = inject(ConversationsStore);
  protected readonly chat = inject(ChatStore);
  protected readonly actions = inject(ChatActions);

  protected readonly editing = signal<string | null>(null);
  protected readonly collapsed = signal<ReadonlySet<string>>(readCollapsed());

  startRename(c: Conversation) {
    return () => {
      this.editing.set(c.id);
      setTimeout(() => {
        const box = document.querySelector<HTMLInputElement>('app-sidebar-chats input.rename');
        box?.focus();
        box?.select();
      });
    };
  }

  saveRename(c: Conversation, value: string) {
    if (this.editing() !== c.id) return; // already saved (Enter, then blur)
    this.editing.set(null);
    const title = value.trim();
    if (title && title !== c.title) this.store.rename(c, title);
  }

  toggleGroup(id: string) {
    const next = new Set(this.collapsed());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.collapsed.set(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
    } catch {
      /* storage blocked: remembered for this visit only */
    }
  }
}

function readCollapsed(): ReadonlySet<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]') as string[]);
  } catch {
    return new Set();
  }
}
