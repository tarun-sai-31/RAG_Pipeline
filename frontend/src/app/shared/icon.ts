import { Component, input } from '@angular/core';

export type IconName =
  | 'dots'
  | 'pin'
  | 'unpin'
  | 'pencil'
  | 'folder'
  | 'folder-plus'
  | 'folder-minus'
  | 'trash'
  | 'check'
  | 'back'
  | 'chevron';

/** Small line icons (24×24, drawn with the current text colour). */
@Component({
  selector: 'app-icon',
  template: `
    <svg viewBox="0 0 24 24" aria-hidden="true" [attr.width]="size()" [attr.height]="size()">
      @switch (name()) {
        @case ('dots') {
          <circle cx="5" cy="12" r="1.6" class="fill" /><circle cx="12" cy="12" r="1.6" class="fill" /><circle cx="19" cy="12" r="1.6" class="fill" />
        }
        @case ('pin') {
          <path d="M9 4h6l-1 6 3 3H7l3-3z" /><path d="M12 13v7" />
        }
        @case ('unpin') {
          <path d="M9 4h6l-1 6 3 3H7l3-3z" /><path d="M12 13v7M4 4l16 16" />
        }
        @case ('pencil') {
          <path d="M4 20h4L19 9l-4-4L4 16z" /><path d="m13.5 6.5 4 4" />
        }
        @case ('folder') {
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        }
        @case ('folder-plus') {
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 10v6M9 13h6" />
        }
        @case ('folder-minus') {
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M9 13h6" />
        }
        @case ('trash') {
          <path d="M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13" /><path d="M10 11v6M14 11v6" />
        }
        @case ('check') {
          <path d="m5 12 5 5 9-10" />
        }
        @case ('back') {
          <path d="m14 6-6 6 6 6" />
        }
        @case ('chevron') {
          <path d="m9 6 6 6-6 6" />
        }
      }
    </svg>
  `,
  styles: `
    :host { display: inline-flex; flex-shrink: 0; }
    svg { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .fill { fill: currentColor; stroke: none; }
  `,
})
export class Icon {
  readonly name = input.required<IconName>();
  readonly size = input(18);
}
