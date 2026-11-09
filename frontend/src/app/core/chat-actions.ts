import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';

import { MenuItem } from '../shared/menu';
import { PromptService } from '../shared/prompt';
import { ChatStore } from './chat.store';
import { ConversationsStore } from './conversations.store';
import { ChatGroup, Conversation } from './models';

/** The "⋯" menus for chats and groups, shared by the sidebar and the History page. */
@Injectable({ providedIn: 'root' })
export class ChatActions {
  private readonly store = inject(ConversationsStore);
  private readonly chat = inject(ChatStore);
  private readonly prompt = inject(PromptService);
  private readonly router = inject(Router);

  /** `startRename` switches the row to an inline text box (the caller owns that state). */
  chatMenu(c: Conversation, startRename: () => void): MenuItem[] {
    const groups = this.store.groups();
    const moveTo: MenuItem[] = [
      ...groups.map((g) => ({
        label: g.name,
        icon: 'folder' as const,
        checked: c.group_id === g.id,
        action: () => this.store.moveTo(c, g.id),
      })),
      { label: 'New group…', icon: 'folder-plus', divider: groups.length > 0, action: () => this.newGroupFor(c) },
    ];
    if (c.group_id) {
      moveTo.push({ label: 'Remove from group', icon: 'folder-minus', action: () => this.store.moveTo(c, null) });
    }
    return [
      { label: c.pinned ? 'Unpin' : 'Pin', icon: c.pinned ? 'unpin' : 'pin', action: () => this.store.pin(c) },
      { label: 'Rename', icon: 'pencil', action: startRename },
      { label: 'Move to group', icon: 'folder', children: moveTo },
      { label: 'Delete', icon: 'trash', danger: true, divider: true, action: () => this.deleteChat(c) },
    ];
  }

  groupMenu(g: ChatGroup): MenuItem[] {
    return [
      { label: 'Rename group', icon: 'pencil', action: () => this.renameGroup(g) },
      { label: 'Delete group', icon: 'trash', danger: true, action: () => this.deleteGroup(g) },
    ];
  }

  private async newGroupFor(c: Conversation) {
    const name = await this.prompt.ask('New group', { label: 'Group name', confirm: 'Create and move' });
    if (name) this.store.moveToNewGroup(c, name);
  }

  private async renameGroup(g: ChatGroup) {
    const name = await this.prompt.ask('Rename group', { label: 'Group name', value: g.name });
    if (name && name !== g.name) this.store.renameGroup(g, name);
  }

  private deleteGroup(g: ChatGroup) {
    if (confirm(`Delete the group "${g.name}"? Its chats are kept and move back to Recents.`)) {
      this.store.removeGroup(g);
    }
  }

  private deleteChat(c: Conversation) {
    if (!confirm(`Delete the chat "${c.title}"? This cannot be undone.`)) return;
    this.store.remove(c);
    if (this.chat.conversationId() === c.id) {
      this.chat.reset();
      this.router.navigate(['/chat']);
    }
  }
}
