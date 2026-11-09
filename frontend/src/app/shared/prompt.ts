import { Component, ElementRef, Injectable, effect, inject, signal, viewChild } from '@angular/core';

interface PromptRequest {
  title: string;
  label: string;
  value: string;
  confirm: string;
  resolve: (value: string | null) => void;
}

/** Ask the user for a short name (new group, rename group). Resolves to null when cancelled. */
@Injectable({ providedIn: 'root' })
export class PromptService {
  readonly request = signal<PromptRequest | null>(null);

  ask(title: string, opts: { label?: string; value?: string; confirm?: string } = {}): Promise<string | null> {
    return new Promise((resolve) =>
      this.request.set({
        title,
        label: opts.label ?? 'Name',
        value: opts.value ?? '',
        confirm: opts.confirm ?? 'Save',
        resolve,
      }),
    );
  }
}

/** The dialog behind PromptService; placed once in the app shell. */
@Component({
  selector: 'app-prompt-dialog',
  template: `
    <dialog #dialog (close)="finish(null)">
      @if (prompt.request(); as r) {
        <form (submit)="$event.preventDefault(); finish(input.value)">
          <h3>{{ r.title }}</h3>
          <label class="field">
            <span class="muted">{{ r.label }}</span>
            <input #input class="input" [value]="r.value" maxlength="80" required autocomplete="off" />
          </label>
          <div class="actions">
            <button type="button" class="btn ghost" (click)="finish(null)">Cancel</button>
            <button type="submit" class="btn">{{ r.confirm }}</button>
          </div>
        </form>
      }
    </dialog>
  `,
  styles: `
    h3 { margin: 0 0 12px; }
    .field { display: grid; gap: 4px; font-size: 13px; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  `,
})
export class PromptDialog {
  protected readonly prompt = inject(PromptService);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  constructor() {
    effect(() => {
      const dialog = this.dialog().nativeElement;
      if (this.prompt.request() && !dialog.open) {
        dialog.showModal();
        setTimeout(() => dialog.querySelector('input')?.select());
      }
    });
  }

  finish(value: string | null) {
    const request = this.prompt.request();
    if (!request) return;
    this.prompt.request.set(null);
    const dialog = this.dialog().nativeElement;
    if (dialog.open) dialog.close();
    const name = value?.trim();
    request.resolve(name ? name : null);
  }
}
