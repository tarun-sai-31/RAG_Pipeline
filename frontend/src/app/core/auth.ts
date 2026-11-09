import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { catchError, throwError } from 'rxjs';

const KEY = 'rag.apiKey';

/** Holds the API key (if the server requires one) and whether the key dialog should be shown. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly apiKey = signal<string | null>(read());
  readonly needsKey = signal(false);

  save(key: string) {
    const value = key.trim();
    try {
      localStorage.setItem(KEY, value);
    } catch {
      /* storage blocked: key lives for this tab only */
    }
    this.apiKey.set(value);
    this.needsKey.set(false);
  }
}

function read(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/** Adds X-API-Key to API calls and opens the key dialog on 401. */
export const apiKeyInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const key = auth.apiKey();
  const request = key && req.url.startsWith('/api/') ? req.clone({ setHeaders: { 'X-API-Key': key } }) : req;
  return next(request).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 401) auth.needsKey.set(true);
      return throwError(() => err);
    }),
  );
};

/** A readable message from any HTTP error (FastAPI puts it in `detail`). */
export function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
    const detail = (err.error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    if (detail) return JSON.stringify(detail);
    return `Request failed (${err.status} ${err.statusText})`;
  }
  return err instanceof Error ? err.message : String(err);
}
