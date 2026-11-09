import { NgTemplateOutlet } from '@angular/common';
import { Component, ElementRef, HostListener, input, signal, viewChild } from '@angular/core';

import { Icon, IconName } from './icon';

export interface MenuItem {
  label: string;
  icon?: IconName;
  danger?: boolean;
  checked?: boolean;
  divider?: boolean; // a line above this item
  action?: () => void;
  children?: MenuItem[]; // opens a second page in the menu (e.g. "Move to group")
}

let openMenu: Menu | null = null; // only one menu open at a time

/**
 * A "⋯" button that opens a small menu. The menu is fixed-positioned, so it is never cut off by a
 * scrolling list (like the sidebar), and closes on an outside click, Escape, or after an action.
 */
@Component({
  selector: 'app-menu',
  imports: [Icon, NgTemplateOutlet],
  template: `
    <button
      #trigger
      type="button"
      class="trigger"
      [class.open]="open()"
      [attr.aria-label]="label()"
      [title]="label()"
      aria-haspopup="menu"
      [attr.aria-expanded]="open()"
      (click)="toggle($event)"
    >
      <app-icon name="dots" />
    </button>
    @if (open()) {
      <div class="menu" role="menu" [style.top.px]="pos().top" [style.left.px]="pos().left" (click)="$event.stopPropagation()">
        @if (page(); as sub) {
          <button type="button" class="item back" (click)="page.set(null)">
            <app-icon name="back" /> <span>{{ sub.label }}</span>
          </button>
          <div class="sep"></div>
          @for (item of sub.children; track item.label) {
            <ng-container [ngTemplateOutlet]="row" [ngTemplateOutletContext]="{ $implicit: item }" />
          }
        } @else {
          @for (item of items(); track item.label) {
            <ng-container [ngTemplateOutlet]="row" [ngTemplateOutletContext]="{ $implicit: item }" />
          }
        }
      </div>
    }

    <ng-template #row let-item>
      @if (item.divider) {
        <div class="sep"></div>
      }
      <button type="button" role="menuitem" class="item" [class.danger]="item.danger" (click)="choose(item)">
        @if (item.icon) {
          <app-icon [name]="item.icon" />
        }
        <span class="text">{{ item.label }}</span>
        @if (item.checked) {
          <app-icon name="check" class="check" />
        }
        @if (item.children) {
          <app-icon name="chevron" class="more" />
        }
      </button>
    </ng-template>
  `,
  styles: `
    :host { display: inline-flex; }
    .trigger {
      border: 0; background: none; color: var(--muted); border-radius: 6px; padding: 3px 4px; display: inline-flex;
      &:hover, &.open { background: var(--line); color: var(--text); }
    }
    .menu {
      position: fixed; z-index: 1000; min-width: 200px; max-width: 280px; padding: 5px;
      background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
      box-shadow: 0 10px 30px rgba(16, 24, 40, 0.18);
    }
    .item {
      display: flex; align-items: center; gap: 10px; width: 100%; border: 0; background: none;
      padding: 7px 10px; border-radius: 7px; text-align: left; font-size: 14px; color: var(--text);
      &:hover { background: var(--bg); }
      &.danger { color: var(--err); }
      &.danger:hover { background: var(--err-soft); }
      &.back { color: var(--muted); font-size: 13px; }
    }
    .text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .check { color: var(--accent); }
    .more { color: var(--muted); }
    .sep { height: 1px; background: var(--line); margin: 4px 2px; }
  `,
})
export class Menu {
  readonly items = input.required<MenuItem[]>();
  readonly label = input('More options');

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  protected readonly open = signal(false);
  protected readonly page = signal<MenuItem | null>(null);
  protected readonly pos = signal({ top: 0, left: 0 });

  toggle(event: Event) {
    event.stopPropagation();
    event.preventDefault(); // the trigger sits inside links (sidebar rows)
    if (this.open()) return this.close();
    const r = this.trigger().nativeElement.getBoundingClientRect();
    const width = 220;
    const height = 44 * (this.items().length + 1);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    const below = r.bottom + 4;
    const top = below + height > window.innerHeight ? Math.max(8, r.top - height - 4) : below;
    this.pos.set({ top, left });
    this.page.set(null);
    if (openMenu && openMenu !== this) openMenu.close();
    openMenu = this;
    this.open.set(true);
  }

  choose(item: MenuItem) {
    if (item.children) {
      this.page.set(item);
      return;
    }
    this.close();
    item.action?.();
  }

  close() {
    this.open.set(false);
    this.page.set(null);
    if (openMenu === this) openMenu = null;
  }

  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  @HostListener('window:resize')
  onOutside() {
    if (this.open()) this.close();
  }

}
