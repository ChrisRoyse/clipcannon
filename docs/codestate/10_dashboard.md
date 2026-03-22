# 10 - Dashboard

> Current-state documentation of the ClipCannon dashboard web application, covering the FastAPI scaffold, authentication system, route groups, and data endpoints.

## Application Scaffold

**Source:** `src/clipcannon/dashboard/app.py`

The dashboard is a FastAPI application that serves both a JSON API and static HTML frontend. It runs on port 3200 by default.

### Configuration

| Setting | Source | Default |
|---------|--------|---------|
| Port | `CLIPCANNON_DASHBOARD_PORT` env var | `3200` |
| Dev mode | `CLIPCANNON_DEV_MODE` env var | `1` (enabled) |
| Hot reload | Enabled when `is_dev_mode()` returns true | Enabled |
| Static files | `src/clipcannon/dashboard/static/` | Mounted at `/static` if directory exists |

### Startup

The `create_app()` factory function builds the application:

1. Creates a `FastAPI` instance with title "ClipCannon Dashboard" and version from `clipcannon.__version__`.
2. Adds CORS middleware allowing origins: `localhost:3200`, `127.0.0.1:3200`, `localhost:3000`, `127.0.0.1:3000`. All methods and headers are allowed. Credentials are permitted.
3. Registers a global exception handler that catches unhandled exceptions and returns a structured JSON error response (HTTP 500).
4. Registers the `/health` endpoint.
5. Includes seven route modules: `home_router`, `credits_router`, `projects_router`, `provenance_router`, `editing_router`, `review_router`, `timeline_router`.
6. Includes the `auth_router`.
7. Mounts the `static/` directory at `/static` (if it exists) -- mounted last so API routes take precedence.

---

## Authentication System

**Source:** `src/clipcannon/dashboard/auth.py`

*(Unchanged from Phase 1 -- JWT dev-mode auth with HS256, 30-day TTL, HTTP-only cookie, dev user `dev-user-001`)*

---

## Route Groups

### Home Routes

*(Unchanged from Phase 1 -- `GET /`, `GET /api/overview`)*

---

### Credits Routes

*(Unchanged from Phase 1 -- `GET /api/credits/balance`, `GET /api/credits/history`, `POST /api/credits/add`, `GET /api/credits/packages`)*

---

### Projects Routes

*(Unchanged from Phase 1 -- `GET /api/projects`, `GET /api/projects/{project_id}`, `GET /api/projects/{project_id}/status`)*

---

### Provenance Routes

*(Unchanged from Phase 1 -- `GET /api/provenance/{project_id}`, `GET /api/provenance/{project_id}/verify`, `GET /api/provenance/{project_id}/timeline`)*

---

### Editing Routes -- Phase 2

**Source:** `src/clipcannon/dashboard/routes/editing.py`

**Router prefix:** `/api/projects`

#### `GET /api/projects/{project_id}/edits`

Lists all edits for a project with optional filtering.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `status` | `string` | `null` | Optional status filter | Filter by edit status |
| `limit` | `integer` | `50` | 1-200 | Max edits to return |

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "edits": [
    {
      "edit_id": "edit_12345678",
      "name": "TikTok Clip 1",
      "status": "draft",
      "target_platform": "tiktok",
      "total_duration_ms": 45000,
      "segment_count": 3,
      "created_at": "2026-03-21T...",
      "render_id": null
    }
  ],
  "count": 1
}
```

#### `GET /api/projects/{project_id}/edits/{edit_id}`

Returns full edit details including EDL JSON and segment data.

---

### Review Routes -- Phase 2

**Source:** `src/clipcannon/dashboard/routes/review.py`

**Router prefix:** `/api/projects`

#### `GET /api/projects/{project_id}/review/queue`

Returns edits with `status='rendered'` ready for approval, joined with render metadata.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "queue": [
    {
      "edit_id": "edit_12345678",
      "name": "TikTok Clip 1",
      "status": "rendered",
      "target_platform": "tiktok",
      "render_id": "ren_abcdef12",
      "output_path": "/path/to/output.mp4",
      "file_size_bytes": 5242880,
      "duration_ms": 45000
    }
  ],
  "count": 1
}
```

#### `POST /api/projects/{project_id}/review/batch`

Batch approve or reject multiple edits.

#### `GET /api/projects/{project_id}/review/stats`

Returns review queue statistics.

---

### Timeline Routes -- Phase 2

**Source:** `src/clipcannon/dashboard/routes/timeline.py`

**Router prefix:** `/api/projects`

Uses `_safe_fetch_all()` helper that checks table existence before querying (graceful handling of Phase 1 databases without Phase 2 tables).

#### `GET /api/projects/{project_id}/timeline`

Returns aggregated timeline data suitable for visual timeline rendering.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "duration_ms": 120000,
  "scenes": [...],
  "speakers": [...],
  "emotion_curve": [...],
  "topics": [...],
  "highlights": [...]
}
```

**Data sources:** Aggregates from `scenes`, `speakers`, `transcript_segments`, `emotion_curve`, `topics`, `highlights` tables.

#### `GET /api/projects/{project_id}/transcript-search`

Searches transcript segments within the project.

#### `GET /api/projects/{project_id}/enhanced`

Returns enhanced project view with combined metadata and timeline data.

---

## Template Rendering Approach

The dashboard uses a hybrid rendering strategy:

1. **Static HTML:** If `src/clipcannon/dashboard/static/index.html` exists, the root route (`GET /`) serves it as a `FileResponse`. The static directory is mounted at `/static`.
2. **JSON API fallback:** If no static index exists, all routes return JSON responses. The frontend is expected to be a static SPA or plain HTML that calls the JSON API endpoints.
