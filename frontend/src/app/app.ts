import { Component, ElementRef, OnInit, computed, effect, inject, signal, viewChild } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';
import { AuthService } from './core/auth';
import { ChatStore } from './core/chat.store';
import { ConversationsStore } from './core/conversations.store';
import { DocumentsStore } from './core/documents.store';
import { SidebarChats } from './layout/sidebar-chats';
import { DocScope } from './shared/doc-scope';
import { PromptDialog } from './shared/prompt';
import { SourceViewer } from './shared/source-viewer';
import { AppConfig } from './core/models';

/** App shell: sidebar (new chat, pages, recent chats) and the API key dialog. */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, SidebarChats, DocScope, PromptDialog, SourceViewer],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  protected readonly docs = inject(DocumentsStore);
  protected readonly chat = inject(ChatStore);
  protected readonly conversations = inject(ConversationsStore);
  private readonly keyDialog = viewChild.required<ElementRef<HTMLDialogElement>>('keyDialog');

  protected readonly config = signal<AppConfig | null>(null);
  protected readonly working = computed(() => (this.docs.counts().queued ?? 0) + (this.docs.counts().processing ?? 0));

  constructor() {
    effect(() => {
      const dialog = this.keyDialog().nativeElement;
      if (this.auth.needsKey() && !dialog.open) dialog.showModal();
    });
  }

  ngOnInit() {
    this.api.config().subscribe({
      next: (cfg) => {
        this.config.set(cfg);
        if (cfg.auth_required && !this.auth.apiKey()) this.auth.needsKey.set(true);
      },
    });
    this.docs.start();
    this.conversations.refresh();
  }

  newChat() {
    this.chat.reset();
  }

  saveKey(value: string) {
    this.auth.save(value);
    this.keyDialog().nativeElement.close();
    this.docs.refresh();
  }
}
