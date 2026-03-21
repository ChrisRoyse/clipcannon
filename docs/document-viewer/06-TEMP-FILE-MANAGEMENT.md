# 06 — Temporary File Management (24-Hour Auto-Cleanup)

## Overview

Cached viewer files live at `/data/viewer-cache/{document_id}/`. Each document gets its own directory containing exactly one file (the viewable version — original or converted PDF).

Files are cleaned up automatically 24 hours after the user closes the viewer. Re-opening the viewer resets the timer. Accessing the file (viewing it) also resets the timer.

## Timer Lifecycle

```
Event: User opens document viewer
  → POST /api/viewer/prepare/{doc_id}
  → File copied to /data/viewer-cache/{doc_id}/
  → NO timer started yet (file is actively being viewed)

Event: User accesses file for rendering
  → GET /api/viewer/file/{doc_id}
  → If a cleanup timer exists, reset it to 24 hours from now
  → (This handles re-access within a session)

Event: User closes document viewer
  → POST /api/viewer/close/{doc_id}
  → Start 24-hour cleanup timer
  → Timer stored in in-memory Map: viewerCleanupTimers

Event: Timer fires (24 hours after close with no re-access)
  → rm -rf /data/viewer-cache/{doc_id}/
  → Remove timer from Map

Event: User re-opens same document before timer fires
  → GET /api/viewer/prepare/{doc_id}
  → File already exists in cache (no copy needed)
  → Cancel existing cleanup timer
  → Return cached file info immediately

Event: Server restarts
  → Scan /data/viewer-cache/*/
  → For each directory, check file mtime
  → If mtime > 24 hours ago → delete immediately
  → If mtime < 24 hours ago → set timer for remaining time
```

## In-Memory Timer Storage

```typescript
// Module-level state (in bin-http.ts)
const viewerCleanupTimers = new Map<string, ReturnType<typeof setTimeout>>();
const VIEWER_CLEANUP_DELAY_MS = 24 * 60 * 60 * 1000; // 24 hours

function startCleanupTimer(documentId: string): void {
  // Cancel any existing timer for this document
  const existing = viewerCleanupTimers.get(documentId);
  if (existing) clearTimeout(existing);

  const cleanupAt = new Date(Date.now() + VIEWER_CLEANUP_DELAY_MS);
  console.error(`[viewer] Cleanup timer set for ${documentId}, fires at ${cleanupAt.toISOString()}`);

  const timer = setTimeout(() => {
    const cacheDir = path.join(VIEWER_CACHE_DIR, documentId);
    try {
      if (fs.existsSync(cacheDir)) {
        fs.rmSync(cacheDir, { recursive: true, force: true });
        console.error(`[viewer] Auto-cleanup: removed cache for ${documentId}`);
      }
    } catch (err) {
      console.error(`[viewer] Cleanup error for ${documentId}: ${err instanceof Error ? err.message : err}`);
    }
    viewerCleanupTimers.delete(documentId);
  }, VIEWER_CLEANUP_DELAY_MS);

  // Prevent timer from keeping Node.js process alive
  timer.unref();

  viewerCleanupTimers.set(documentId, timer);
}

function cancelCleanupTimer(documentId: string): void {
  const timer = viewerCleanupTimers.get(documentId);
  if (timer) {
    clearTimeout(timer);
    viewerCleanupTimers.delete(documentId);
    console.error(`[viewer] Cleanup timer cancelled for ${documentId}`);
  }
}

function resetCleanupTimer(documentId: string): void {
  // Only reset if a timer exists (meaning the viewer was closed)
  if (viewerCleanupTimers.has(documentId)) {
    startCleanupTimer(documentId);
  }
}
```

## Server Startup Reconciliation

When the MCP server starts, it must handle cached files from before the restart (timers are lost when the process dies).

```typescript
function reconcileViewerCache(): void {
  if (!fs.existsSync(VIEWER_CACHE_DIR)) return;

  const now = Date.now();
  let cleaned = 0;
  let timersSet = 0;

  try {
    const entries = fs.readdirSync(VIEWER_CACHE_DIR, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const dirPath = path.join(VIEWER_CACHE_DIR, entry.name);
      const documentId = entry.name;

      // Get the files in the cache directory
      let files: string[];
      try {
        files = fs.readdirSync(dirPath);
      } catch {
        continue;
      }

      // Empty directory → remove it
      if (files.length === 0) {
        fs.rmdirSync(dirPath);
        continue;
      }

      // Find the newest file's mtime
      let newestMtime = 0;
      for (const f of files) {
        try {
          const stat = fs.statSync(path.join(dirPath, f));
          if (stat.mtimeMs > newestMtime) newestMtime = stat.mtimeMs;
        } catch { /* skip unreadable files */ }
      }

      const ageMs = now - newestMtime;

      if (ageMs >= VIEWER_CLEANUP_DELAY_MS) {
        // Expired — delete now
        fs.rmSync(dirPath, { recursive: true, force: true });
        cleaned++;
      } else {
        // Not expired — set timer for remaining time
        // But since we don't know if the viewer is still open,
        // start a cleanup timer (conservative: assume closed)
        startCleanupTimer(documentId);
        timersSet++;
      }
    }

    if (cleaned > 0 || timersSet > 0) {
      console.error(`[viewer] Startup reconciliation: cleaned ${cleaned} expired, set ${timersSet} timers`);
    }
  } catch (err) {
    console.error(`[viewer] Startup reconciliation error: ${err instanceof Error ? err.message : err}`);
  }
}
```

**Call location**: After the HTTP server starts listening, call `reconcileViewerCache()`.

## Disk Space Monitoring

No explicit disk space monitoring is implemented. The 24-hour cleanup ensures files don't accumulate indefinitely. In extreme cases (hundreds of large documents opened), the container's `/data` volume may fill up, but this is handled by:

1. The 24-hour auto-cleanup timer
2. The Docker volume's size limits (if configured)
3. The MCP server's existing `/data` volume usage

## Cleanup on Server Shutdown

When the MCP server shuts down gracefully, all timers are automatically cancelled (process exits). The startup reconciliation handles this on next boot.

No explicit cleanup-on-shutdown is needed because:
1. `timer.unref()` prevents the timer from keeping the process alive
2. Startup reconciliation handles stale caches
3. Files in the cache are temporary and low-value (can always be re-fetched from host)

## Directory Structure

```
/data/
├── viewer-cache/                    ← NEW: Created on first prepare request
│   ├── abc-123-def-456/            ← document_id
│   │   └── contract.pdf            ← cached file (original or converted)
│   ├── ghi-789-jkl-012/
│   │   └── presentation.pdf        ← converted from .pptx
│   └── mno-345-pqr-678/
│       └── photo.png               ← image file (no conversion needed)
├── staged/                          ← existing: HTTP upload staging
├── *.db                             ← existing: user databases
└── _*.db                            ← existing: internal databases
```

## What Happens If...

### ...the user never closes the viewer (leaves browser tab open)?
- No cleanup timer is started until `POST /api/viewer/close` is called
- The file stays in cache indefinitely
- On server restart, `reconcileViewerCache()` will set a 24-hour timer

### ...the user opens 100 documents simultaneously?
- 100 directories created in viewer-cache
- No timer started for any (all are actively viewed)
- When closed, 100 timers start (JavaScript handles this fine)
- All cleaned up 24 hours later

### ...the server crashes before cleanup fires?
- Timers are lost (in-memory)
- On restart, `reconcileViewerCache()` scans and sets new timers
- Files that are >24 hours old are immediately deleted
- Files that are <24 hours old get timers for the remaining time

### ...the cached file is manually deleted?
- Next `GET /api/viewer/file/{id}` returns 404 with `NOT_CACHED` error
- Client can call prepare again to re-fetch the file
