import { HttpEventType } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { errorMessage } from '../../core/auth';
import { DocumentsStore, folderOf } from '../../core/documents.store';
import { DocStatus, DocumentItem } from '../../core/models';
import { FileSizePipe, TimeAgoPipe } from '../../shared/format';
import { PromptService } from '../../shared/prompt';

interface UploadRow {
  id: number;
  name: string;
  progress: number;
  message: string;
  failed: boolean;
}

const STATUSES: DocStatus[] = ['ready', 'processing', 'queued', 'failed'];

@Component({
  selector: 'app-documents-page',
  imports: [FileSizePipe, TimeAgoPipe],
  templateUrl: './documents.page.html',
  styleUrl: './documents.page.scss',
})
export class DocumentsPage {
  private readonly api = inject(ApiService);
  private readonly prompt = inject(PromptService);
  protected readonly store = inject(DocumentsStore);

  protected readonly statuses = STATUSES;
  protected readonly project = signal('');
  protected readonly filter = signal('');
  protected readonly statusFilter = signal<DocStatus | ''>('');
  protected readonly uploads = signal<UploadRow[]>([]);
  protected readonly dragging = signal(false);
  protected readonly actionError = signal<string | null>(null);
  private nextUploadId = 1;
  /** Paths of files dropped as part of a folder (dropped files have no webkitRelativePath). */
  private readonly droppedPaths = new WeakMap<File, string>();

  protected readonly visible = computed(() => {
    const f = this.filter().trim().toLowerCase();
    const status = this.statusFilter();
    return this.store
      .documents()
      .filter((d) => (!f || d.filename.toLowerCase().includes(f)) && (!status || d.status === status));
  });

  onFiles(list: FileList | File[] | null) {
    if (!list) return;
    const files = Array.from(list);
    if (!files.length) return;

    if (!this.project().trim()) {
      const withPath = files.find((f) => f.webkitRelativePath && f.webkitRelativePath.includes('/'));
      if (withPath) {
        const folderName = withPath.webkitRelativePath.split('/')[0];
        if (folderName) this.project.set(folderName);
      }
    }
    const project = this.project().trim();
    this.uploadBatch(files, project);
  }

  async onDrop(event: DragEvent) {
    event.preventDefault();
    this.dragging.set(false);
    const items = event.dataTransfer?.items;
    if (items && items.length > 0 && typeof (items[0] as any).webkitGetAsEntry === 'function') {
      const queue: any[] = [];
      for (let i = 0; i < items.length; i++) {
        const entry = (items[i] as any).webkitGetAsEntry();
        if (entry) queue.push(entry);
      }
      const files: File[] = [];
      await this.readEntriesRecursively(queue, files);
      if (files.length > 0) {
        this.onFiles(files);
        return;
      }
    }
    this.onFiles(event.dataTransfer?.files ?? null);
  }

  private async readEntriesRecursively(queue: any[], outFiles: File[]) {
    while (queue.length > 0) {
      const entry = queue.shift();
      if (!entry) continue;
      if (entry.isFile) {
        try {
          const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject));
          this.droppedPaths.set(file, String(entry.fullPath ?? '').replace(/^\//, ''));
          outFiles.push(file);
        } catch {
          // ignore unreadable
        }
      } else if (entry.isDirectory) {
        try {
          const reader = entry.createReader();
          const readBatch = (): Promise<any[]> => new Promise((resolve, reject) => reader.readEntries(resolve, reject));
          let batch: any[];
          do {
            batch = await readBatch();
            queue.push(...batch);
          } while (batch && batch.length > 0);
        } catch {
          // ignore unreadable
        }
      }
    }
  }

  reprocess(doc: DocumentItem) {
    this.actionError.set(null);
    this.api.reprocess(doc.id).subscribe({
      next: () => this.store.refresh(),
      error: (err) => this.actionError.set(errorMessage(err)),
    });
  }

  remove(doc: DocumentItem) {
    if (!confirm(`Delete "${doc.filename}" and everything indexed from it?`)) return;
    this.actionError.set(null);
    this.api.deleteDocument(doc.id).subscribe({
      next: () => this.store.refresh(),
      error: (err) => this.actionError.set(errorMessage(err)),
    });
  }

  statusLabel(doc: DocumentItem): string {
    return doc.status === 'processing' && doc.stage ? `processing · ${doc.stage}` : doc.status;
  }

  details(doc: DocumentItem): string {
    const bits = [doc.file_type.toUpperCase()];
    if (doc.page_count) bits.push(`${doc.page_count} ${doc.file_type === 'xlsx' ? 'sheets' : 'pages'}`);
    if (doc.ocr_page_count) bits.push(`${doc.ocr_page_count} OCR`);
    return bits.join(' · ');
  }

  protected readonly folderOf = folderOf;

  /** Put files into a folder, so the chat's "Ask about" can select them together. */
  async moveToFolder(docs: DocumentItem[]) {
    const current = folderOf(docs[0]);
    const title = docs.length === 1 ? `Move "${docs[0].filename}" to folder` : `Move ${docs.length} files to folder`;
    const folder = await this.prompt.ask(title, { label: 'Folder name', value: current, confirm: 'Move' });
    if (!folder) return;
    this.actionError.set(null);
    forkJoin(docs.map((d) => this.api.moveToFolder(d.id, folder))).subscribe({
      next: () => this.store.refresh(),
      error: (err) => this.actionError.set(errorMessage(err)),
    });
  }

  private async uploadBatch(files: File[], project: string) {
    const queue = [...files];
    const concurrency = 4;
    const worker = async () => {
      while (queue.length > 0) {
        const file = queue.shift();
        if (file) await this.uploadOneAsync(file, project);
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, files.length) }, () => worker()));
  }

  private uploadOneAsync(file: File, project: string): Promise<void> {
    return new Promise((resolve) => {
      const row: UploadRow = { id: this.nextUploadId++, name: file.name, progress: 0, message: 'uploading…', failed: false };
      this.uploads.update((rows) => [row, ...rows]);
      const patch = (changes: Partial<UploadRow>) =>
        this.uploads.update((rows) => rows.map((r) => (r.id === row.id ? { ...r, ...changes } : r)));

      // The folder the file came from (e.g. "2025/January"), so the chat can ask about one folder.
      const path = file.webkitRelativePath || this.droppedPaths.get(file) || '';
      const folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
      const metadata = { ...(project ? { project } : {}), ...(folder ? { folder } : {}) };
      this.api.upload(file, metadata).subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total) {
            patch({ progress: Math.round((event.loaded / event.total) * 100) });
          } else if (event.type === HttpEventType.Response) {
            const docs = event.body?.documents || [];
            if (docs.length > 1) {
              patch({ progress: 100, message: `extracted ${docs.length} files`, failed: false });
            } else {
              const doc = docs[0];
              const message =
                doc?.status === 'rejected'
                  ? (doc.error ?? 'rejected')
                  : doc?.duplicate
                    ? `already uploaded (${doc.status})`
                    : 'queued for processing';
              patch({ progress: 100, message, failed: doc?.status === 'rejected' });
            }
            this.store.refresh();
            setTimeout(() => this.uploads.update((rows) => rows.filter((r) => r.id !== row.id)), 6000);
            resolve();
          }
        },
        error: (err) => {
          patch({ message: errorMessage(err), failed: true });
          resolve();
        },
      });
    });
  }
}
