import { Component, DestroyRef, ElementRef, HostListener, OnInit, computed, effect, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { errorMessage } from '../../core/auth';
import { ChatStore } from '../../core/chat.store';
import { DocumentsStore } from '../../core/documents.store';
import { Answer } from '../../shared/answer';

const SUGGESTIONS = [
  'Summarise the latest progress of each project',
  'Which towers are behind schedule?',
  'List the open critical issues',
];

@Component({
  selector: 'app-chat-page',
  imports: [Answer, RouterLink],
  templateUrl: './chat.page.html',
  styleUrl: './chat.page.scss',
})
export class ChatPage implements OnInit {
  protected readonly chat = inject(ChatStore);
  protected readonly docs = inject(DocumentsStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  private readonly scroller = viewChild.required<ElementRef<HTMLElement>>('scroller');
  private readonly input = viewChild.required<ElementRef<HTMLTextAreaElement>>('questionBox');

  protected readonly suggestions = SUGGESTIONS;
  protected readonly scopeOpen = signal(false); // the "Ask about" dropdown
  private readonly scopeEl = viewChild.required<ElementRef<HTMLElement>>('scope');
  protected readonly question = signal('');
  protected readonly docFilter = signal('');
  protected readonly showJump = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly visibleDocs = computed(() => {
    const f = this.docFilter().trim().toLowerCase();
    return this.docs.ready().filter((d) => !f || d.filename.toLowerCase().includes(f));
  });

  constructor() {
    // Keep the newest message in view whenever the conversation grows.
    effect(() => {
      this.chat.messages();
      this.chat.busy();
      setTimeout(() => this.scrollToBottom());
    });
  }

  /** Close the "Ask about" dropdown on a click outside it or on Escape. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    if (this.scopeOpen() && !this.scopeEl().nativeElement.contains(event.target as Node)) this.scopeOpen.set(false);
  }

  @HostListener('document:keydown.escape')
  onEscape() {
    this.scopeOpen.set(false);
  }

  ngOnInit() {
    // ?conversation=<id> opens that chat (sidebar Recents, History); no id means a new chat.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('conversation');
      if (id && id !== this.chat.conversationId()) {
        this.loadError.set(null);
        this.chat.resume(id).subscribe({ error: (err) => this.loadError.set(errorMessage(err)) });
      } else if (!id && this.chat.conversationId()) {
        this.chat.reset();
      }
    });
  }

  send(text = this.question()) {
    const q = text.trim();
    if (!q || this.chat.busy()) return;
    this.question.set('');
    this.resize();
    this.chat.send(q).subscribe({
      next: (res) => {
        if (this.chat.conversationId() === res.conversation_id) {
          this.router.navigate([], { queryParams: { conversation: res.conversation_id }, replaceUrl: true });
        }
      },
      error: () => undefined, // shown in the conversation by the store
      complete: () => setTimeout(() => this.input().nativeElement.focus()),
    });
  }

  newChat() {
    this.chat.reset();
    this.router.navigate([], { queryParams: {}, replaceUrl: true });
    this.input().nativeElement.focus();
  }

  onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this.send();
    }
  }

  onInput(value: string) {
    this.question.set(value);
    this.resize();
  }

  /** The wheel scrolls the conversation from anywhere in the chat column (question box, margins). */
  onWheel(event: WheelEvent) {
    const el = this.scroller().nativeElement;
    if (el.contains(event.target as Node)) return;
    const box = this.input().nativeElement;
    if (event.target === box && box.scrollHeight > box.clientHeight) return;
    el.scrollTop += event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
    event.preventDefault();
  }

  onScroll() {
    const el = this.scroller().nativeElement;
    this.showJump.set(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
  }

  scrollToBottom(smooth = false) {
    const el = this.scroller().nativeElement;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    this.onScroll();
  }

  private resize() {
    const box = this.input().nativeElement;
    box.style.height = 'auto';
    box.style.height = `${Math.min(box.scrollHeight, 180)}px`;
  }
}
