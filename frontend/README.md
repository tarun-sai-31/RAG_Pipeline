# Frontend (Angular)

The Document Assistant UI. See the main [README](../README.md) for the whole project.

```bash
npm install
npm start         # ng serve on http://localhost:4200 — /api, /docs are proxied to the backend on :8000
npx ng build      # production build in dist/frontend/browser
```

Angular needs Node ≥ 24.15; `npm start` (scripts/serve.mjs) picks one from nvm if the terminal's Node is older. In Docker (`docker compose up -d --build frontend`) no local Node is needed.

- `src/app/core/` — `api.service.ts` (every backend endpoint), `models.ts` (response types), `auth.ts`
  (X-API-Key interceptor), `documents.store.ts` and `chat.store.ts` (shared state with signals)
- `src/app/shared/` — answer with citations, JSON viewer, markdown/format pipes
- `src/app/features/` — `chat`, `documents`, `history` pages (lazy-loaded routes)
