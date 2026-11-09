import { Pipe, PipeTransform, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

export function fileSize(bytes: number): string {
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleString();
}

@Pipe({ name: 'fileSize' })
export class FileSizePipe implements PipeTransform {
  transform(bytes: number): string {
    return fileSize(bytes);
  }
}

@Pipe({ name: 'timeAgo' })
export class TimeAgoPipe implements PipeTransform {
  transform(iso: string): string {
    return timeAgo(iso);
  }
}

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

/**
 * Minimal Markdown for answers: paragraphs, headings, lists, tables, code, bold/italic, and [n] citations.
 * Every piece of text is HTML-escaped before any tag is added, so the result is safe to trust.
 */
export function renderMarkdown(src: string): string {
  const inline = (s: string) =>
    escapeHtml(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/\[(\d{1,2})\]/g, '<button type="button" class="cite" data-n="$1" title="Show source $1">$1</button>');
  const cells = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim());
  const isBlockStart = /^(```|\s*\||#{1,4}\s|\s*([-*•]|\d+[.)])\s+)/;
  const lines = src.replace(/\r/g, '').split('\n');
  let html = '';
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      html += `<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;
      continue;
    }
    if (/^\s*\|/.test(line)) {
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const [head, ...rest] = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
      html +=
        '<div class="table-wrap"><table><thead><tr>' +
        cells(head).map((c) => `<th>${inline(c)}</th>`).join('') +
        '</tr></thead><tbody>' +
        rest.map((r) => '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
        '</tbody></table></div>';
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)/);
    if (heading) {
      const level = heading[1].length < 3 ? 3 : 4;
      html += `<h${level}>${inline(heading[2])}</h${level}>`;
      i++;
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ''));
      }
      const tag = ordered ? 'ol' : 'ul';
      html += `<${tag}>${items.map((t) => `<li>${inline(t)}</li>`).join('')}</${tag}>`;
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart.test(lines[i])) para.push(lines[i++]);
    html += `<p>${para.map(inline).join('<br>')}</p>`;
  }
  return html;
}

@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  private readonly sanitizer = inject(DomSanitizer);

  transform(src: string | null | undefined): SafeHtml {
    // Safe: renderMarkdown escapes all text; it only adds its own fixed tags.
    return this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(src ?? ''));
  }
}
