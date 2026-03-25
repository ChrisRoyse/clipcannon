# Dashboard

Source: `src/clipcannon/dashboard/`

## Application Scaffold (`dashboard/app.py`)

FastAPI app on port 3200 (env `CLIPCANNON_DASHBOARD_PORT`). Dev mode enabled by default (`CLIPCANNON_DEV_MODE=1`).

`create_app()` builds the app:
1. CORS: localhost:3200, 127.0.0.1:3200, localhost:3000, 127.0.0.1:3000 (all methods/headers, credentials allowed)
2. Global exception handler -> JSON error (500)
3. Registers 7 route modules + auth router
4. Mounts `static/` at `/static` (if exists, mounted last so API routes take precedence)

## Authentication (`dashboard/auth.py`)

JWT dev-mode auth: HS256, 30-day TTL, HTTP-only cookie, dev user `dev-user-001`.

## Route Groups

### Home: `GET /`, `GET /api/overview`

### Credits: `GET /api/credits/balance`, `GET /api/credits/history`, `POST /api/credits/add`, `GET /api/credits/packages`

### Projects: `GET /api/projects`, `GET /api/projects/{project_id}`, `GET /api/projects/{project_id}/status`

### Provenance: `GET /api/provenance/{project_id}`, `GET /api/provenance/{project_id}/verify`, `GET /api/provenance/{project_id}/timeline`

### Editing (`dashboard/routes/editing.py`)

- `GET /api/projects/{project_id}/edits` -- list edits, optional `status` filter, `limit` (1-200, default 50). Returns: `project_id`, `edits[]` (edit_id, name, status, target_platform, total_duration_ms, segment_count, created_at, render_id), `count`.
- `GET /api/projects/{project_id}/edits/{edit_id}` -- full edit details with EDL JSON.

### Review (`dashboard/routes/review.py`)

- `GET /api/projects/{project_id}/review/queue` -- rendered edits ready for approval, joined with render metadata.
- `POST /api/projects/{project_id}/review/batch` -- batch approve/reject edits.
- `GET /api/projects/{project_id}/review/stats` -- review queue statistics.

### Timeline (`dashboard/routes/timeline.py`)

Uses `_safe_fetch_all()` for graceful handling of databases without newer tables.

- `GET /api/projects/{project_id}/timeline` -- aggregated timeline: `duration_ms`, `scenes`, `speakers`, `emotion_curve`, `topics`, `highlights`.
- `GET /api/projects/{project_id}/transcript-search` -- search transcript segments.
- `GET /api/projects/{project_id}/enhanced` -- combined metadata + timeline data.

## Rendering Strategy

Hybrid: static HTML (`static/index.html`) served at `/` if exists, otherwise all routes return JSON for SPA consumption.
