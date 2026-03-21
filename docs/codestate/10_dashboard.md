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
5. Includes four route modules: `home_router`, `credits_router`, `projects_router`, `provenance_router`.
6. Includes the `auth_router`.
7. Mounts the `static/` directory at `/static` (if it exists) -- mounted last so API routes take precedence.

The `lifespan` context manager logs startup and shutdown messages.

**Launch command:** `python -m clipcannon.dashboard.app` or via uvicorn directly:
```
uvicorn clipcannon.dashboard.app:create_app --factory --host 0.0.0.0 --port 3200
```

### Health Endpoint

`GET /health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "service": "clipcannon-dashboard"
}
```

---

## Authentication System

**Source:** `src/clipcannon/dashboard/auth.py`

Phase 1 uses a simple JWT-based dev-mode authentication system. Future phases will implement magic-link email authentication.

### JWT Configuration

| Setting | Value |
|---------|-------|
| Algorithm | HS256 |
| Secret | `CLIPCANNON_JWT_SECRET` env var, defaults to `"clipcannon-dev-secret-not-for-production"` |
| Session cookie name | `clipcannon_session` |
| Session TTL | 30 days (2,592,000 seconds) |
| Cookie flags | `httponly=True`, `samesite=lax`, `secure=False` |

### Dev Mode

Dev mode is enabled when the `CLIPCANNON_DEV_MODE` environment variable is set to `1`, `true`, or `yes` (case-insensitive). It defaults to `"1"` (enabled).

When dev mode is enabled:
- The `/auth/dev-login` endpoint is active and creates sessions without credentials.
- The `get_current_user` function auto-authenticates requests that have no session cookie, returning a synthetic dev user.

**Dev user identity:**
- User ID: `dev-user-001`
- Email: `dev@clipcannon.local`

### Token Structure

The JWT payload contains:

| Claim | Type | Description |
|-------|------|-------------|
| `sub` | `string` | User identifier |
| `email` | `string` | User email address |
| `iat` | `integer` | Issued-at timestamp (Unix epoch) |
| `exp` | `integer` | Expiration timestamp (iat + 30 days) |

### Auth Endpoints

All auth endpoints are under the `/auth` prefix.

#### `GET /auth/dev-login`

Auto-login for development mode. Creates a JWT token and sets it as an HTTP-only cookie.

**Response (dev mode enabled):**
```json
{
  "success": true,
  "user_id": "dev-user-001",
  "email": "dev@clipcannon.local",
  "message": "Logged in via dev mode. Session cookie set (30-day TTL)."
}
```

**Response (dev mode disabled):**
```json
{
  "success": false,
  "message": "Dev login is only available in development mode."
}
```

#### `GET /auth/me`

Returns the current authenticated user's information.

**Response (authenticated):**
```json
{
  "authenticated": true,
  "user_id": "dev-user-001",
  "email": "dev@clipcannon.local",
  "dev_mode": true
}
```

**Response (not authenticated):**
```json
{
  "authenticated": false,
  "user_id": null,
  "email": null
}
```

#### `GET /auth/logout`

Clears the session cookie.

**Response:**
```json
{
  "success": true,
  "message": "Session cleared."
}
```

### Route Protection

The `require_auth` decorator can be applied to route handlers. It calls `get_current_user(request)` and:
- If a valid user is found, stores it in `request.state.user` and proceeds.
- If no user is found, returns HTTP 401 with `UNAUTHORIZED` error code and a message directing to `/auth/dev-login`.

In dev mode, the decorator is effectively a no-op because `get_current_user` auto-authenticates.

---

## Route Groups

### Home Routes

**Source:** `src/clipcannon/dashboard/routes/home.py`

**Router prefix:** none (root)

#### `GET /`

Serves the dashboard home page. If `static/index.html` exists, returns it as a `FileResponse` with `text/html` media type. Otherwise, falls through to the JSON system overview response.

#### `GET /api/overview`

Returns the system overview as JSON. This is the same data that `GET /` returns when no static HTML is present.

**Response:**
```json
{
  "version": "0.1.0",
  "timestamp": "2026-03-21T...",
  "gpu": {
    "available": true,
    "device": "NVIDIA GeForce RTX 4090",
    "vram_total_gb": 24.0,
    "vram_used_gb": 0.5,
    "cuda_version": "12.1"
  },
  "recent_projects": [
    {
      "project_id": "proj_a1b2c3d4",
      "name": "proj_a1b2c3d4",
      "status": "ready",
      "created_at": "2026-03-20T...",
      "modified_at": "2026-03-21T..."
    }
  ],
  "system_health": {
    "disk": {
      "total_gb": 500.0,
      "used_gb": 120.0,
      "free_gb": 380.0,
      "usage_pct": 24.0
    },
    "status": "healthy"
  }
}
```

**Data sources:**
- **GPU status:** Attempts to import `torch` and query CUDA device properties. If torch is not installed or no GPU is available, returns `available: false` with null fields.
- **Recent projects:** Scans `~/.clipcannon/projects/` (or `CLIPCANNON_PROJECTS_DIR`), lists up to 10 directories sorted by modification time descending. Checks for `analysis.db` to determine status (`ready` if present, `created` otherwise).
- **Disk usage:** Calls `shutil.disk_usage` on the projects parent directory.

---

### Credits Routes

**Source:** `src/clipcannon/dashboard/routes/credits.py`

**Router prefix:** `/api/credits`

Uses a singleton `LicenseClient` instance. The license server URL defaults to `http://localhost:3100` and can be overridden via `CLIPCANNON_LICENSE_URL` environment variable.

#### `GET /api/credits/balance`

Returns the current credit balance from the license server.

**Response:**
```json
{
  "balance": 100,
  "balance_hmac": "a1b2c3...",
  "last_sync_utc": "2026-03-21T...",
  "spending_this_month": 10,
  "spending_limit": 200,
  "server_reachable": true
}
```

When the license server is unreachable, returns `balance: -1` and `server_reachable: false`.

#### `GET /api/credits/history`

Returns credit transaction history.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `limit` | `integer` | `20` | 1-100 | Max records to return |

**Response:**
```json
{
  "transactions": [...],
  "count": 5,
  "limit": 20
}
```

Each transaction is the full `TransactionRecord` model serialized via `model_dump()`.

#### `POST /api/credits/add`

Adds credits in development mode. Only available when `CLIPCANNON_DEV_MODE` is enabled.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `amount` | `integer` | `100` | 1-10000 | Credits to add |

**Response (success):**
```json
{
  "success": true,
  "amount": 100,
  "balance_after": 200,
  "timestamp": "2026-03-21T...",
  "message": "Added 100 credits in dev mode."
}
```

**Response (not in dev mode):**
```json
{
  "success": false,
  "error": "DEV_MODE_ONLY",
  "message": "Adding credits directly is only available in dev mode."
}
```

**Key behavior:** Uses the license client's `refund` method with a synthetic transaction ID (`dev-add-{8 hex chars}`) to add credits.

#### `GET /api/credits/packages`

Lists all available credit packages with prices.

**Response:**
```json
{
  "packages": [
    {
      "name": "starter",
      "credits": 50,
      "price_cents": 500,
      "price_display": "$5.00",
      "per_credit_cents": 10.0
    },
    {
      "name": "creator",
      "credits": 250,
      "price_cents": 2000,
      "price_display": "$20.00",
      "per_credit_cents": 8.0
    },
    {
      "name": "pro",
      "credits": 1000,
      "price_cents": 6000,
      "price_display": "$60.00",
      "per_credit_cents": 6.0
    },
    {
      "name": "studio",
      "credits": 5000,
      "price_cents": 20000,
      "price_display": "$200.00",
      "per_credit_cents": 4.0
    }
  ],
  "credit_rates": {
    "analyze": 10,
    "render": 2,
    "metadata": 1,
    "publish": 1
  }
}
```

---

### Provenance Routes

**Source:** `src/clipcannon/dashboard/routes/provenance.py`

**Router prefix:** `/api/provenance`

Reads from the per-project `analysis.db` via the `clipcannon.provenance` module.

#### `GET /api/provenance/{project_id}`

Returns all provenance records for a project.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "records": [...],
  "count": 12
}
```

Each record is serialized via `model_dump()` from the provenance Pydantic model.

Returns `count: 0` with an `error` field if the project database does not exist.

#### `GET /api/provenance/{project_id}/verify`

Verifies the integrity of a project's provenance hash chain.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "verified": true,
  "total_records": 12,
  "broken_at": null,
  "issue": null
}
```

Returns `verified: false` with an `error` field if the database is missing or verification encounters an error.

#### `GET /api/provenance/{project_id}/timeline`

Returns a timeline view of provenance records, suitable for visualization.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "timeline": [
    {
      "record_id": "...",
      "timestamp": "2026-03-21T...",
      "operation": "probe",
      "stage": "ffprobe",
      "description": "Initial probe of source video",
      "model_name": null,
      "duration_ms": 150,
      "parent_id": null,
      "chain_hash_prefix": "a1b2c3d4e5f6"
    }
  ],
  "count": 12
}
```

The `chain_hash_prefix` field contains the first 12 characters of the chain hash, or null if no hash exists.

---

### Projects Routes

**Source:** `src/clipcannon/dashboard/routes/projects.py`

**Router prefix:** `/api/projects`

Reads from per-project `analysis.db` files via the `clipcannon.db` module.

**Pipeline stages constant** (defined in this module):
1. `ingest`
2. `frame_extraction`
3. `scene_detection`
4. `transcription`
5. `diarization`
6. `emotion_analysis`
7. `visual_embedding`
8. `topic_segmentation`
9. `highlight_detection`

#### `GET /api/projects`

Lists all projects with basic metadata, sorted by modification time (newest first).

**Response:**
```json
{
  "projects": [
    {
      "project_id": "proj_a1b2c3d4",
      "name": "proj_a1b2c3d4",
      "has_database": true,
      "created_at": "2026-03-20T...",
      "modified_at": "2026-03-21T...",
      "status": "ready",
      "source_path": "/path/to/source.mp4",
      "duration_ms": 120000,
      "resolution": "1920x1080"
    }
  ],
  "count": 3
}
```

**Key behavior:** Scans directories under `CLIPCANNON_PROJECTS_DIR`. If `analysis.db` exists, queries the `project` table for status and metadata. Otherwise, reports status as `created`.

#### `GET /api/projects/{project_id}`

Returns detailed information about a specific project, including full metadata, pipeline status, and file listing.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "found": true,
  "has_database": true,
  "created_at": "2026-03-20T...",
  "modified_at": "2026-03-21T...",
  "metadata": {
    "project_id": "proj_a1b2c3d4",
    "name": "My Video",
    "source_path": "...",
    "status": "ready",
    "duration_ms": 120000,
    "resolution": "1920x1080",
    "fps": 29.97,
    "codec": "h264"
  },
  "pipeline": {
    "completed_stages": ["ingest", "frame_extraction", "transcription"],
    "total_stages": 9,
    "progress_pct": 33.3,
    "all_stages": ["ingest", "frame_extraction", "scene_detection", "..."]
  },
  "files": [
    {"name": "analysis.db", "size_bytes": 524288}
  ]
}
```

**Key behavior:**
- Pipeline progress is computed by querying distinct `stage` values from the `provenance` table and comparing against the 9-stage constant.
- The `files` array lists top-level files in the project directory (not recursive).
- Returns `found: false` with an error if the project directory does not exist.

#### `GET /api/projects/{project_id}/status`

Returns the pipeline processing status for a project.

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "status": "ready",
  "pipeline": {
    "completed_stages": ["ingest", "frame_extraction"],
    "total_stages": 9,
    "progress_pct": 22.2,
    "all_stages": ["ingest", "frame_extraction", "scene_detection", "..."]
  }
}
```

Returns `status: "not_found"` if the project database does not exist.

---

## Template Rendering Approach

The dashboard uses a hybrid rendering strategy:

1. **Static HTML:** If `src/clipcannon/dashboard/static/index.html` exists, the root route (`GET /`) serves it as a `FileResponse`. The static directory is mounted at `/static` for CSS, JS, and image assets.
2. **JSON API fallback:** If no static index exists, all routes return JSON responses. This allows the dashboard to function as a pure API server during development or when used with a separate frontend.

There is no server-side template engine (no Jinja2, no Mako). The frontend is expected to be a static SPA or plain HTML that calls the JSON API endpoints.
