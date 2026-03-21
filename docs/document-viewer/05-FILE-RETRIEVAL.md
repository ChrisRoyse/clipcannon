# 05 — File Retrieval Strategy

## The Problem

Documents in the database have a `file_path` column that records where the file was located when it was ingested. This file may be:

1. On the host filesystem (accessible via `/host` read-only mount)
2. In a staged upload directory (`/data/staged/{batch_id}/`)
3. Bundled with the Docker image (`/data/bundled/` or similar)
4. On a Windows drive via WSL (`/host-windows/c/...`)

The viewer needs to copy this file into a viewer-specific cache directory inside the container so it can serve it to the browser.

## File Path Resolution Algorithm

```
resolveDocumentPath(file_path: string) → string | null

Input: file_path from documents.file_path column
Output: absolute container path where the file actually exists, or null

Algorithm:
1. Try file_path as-is
   → if exists → return file_path

2. If file_path starts with /host/ or /host-windows/
   → already a container-accessible path
   → if exists → return file_path (already tried in step 1)
   → return null (host file was moved/deleted)

3. If file_path starts with / (absolute host path)
   → This is an original host-side path (e.g., /home/user/docs/file.pdf)
   → Read OCR_PROVENANCE_HOST_HOME env var (e.g., /home/user)
   → Strip the host home prefix: /home/user/docs/file.pdf → /docs/file.pdf
   → Try /host/docs/file.pdf
   → Also try /host + file_path directly as fallback

4. If file_path does not start with /
   → Relative path → try /host/{file_path}

5. Search /data/staged/ directories
   → Extract filename from file_path
   → Walk /data/staged/{batch_id}/ directories
   → Try each batch directory for a matching filename

6. If no path found → return null
```

## Edge Cases

### Case 1: File was deleted from host after ingestion
- `resolveDocumentPath` returns null
- Viewer shows error: "Source file not found. The original file may have been moved or deleted from the host filesystem."
- Shows the original file_path so the user knows what to look for
- Shows all paths that were tried for debugging

### Case 2: File was uploaded via HTTP upload endpoint
- `file_path` will be `/data/staged/{batch_id}/{filename}`
- This path exists inside the container
- Direct copy from staged to viewer-cache works
- Note: staged files auto-expire after 48 hours. If expired, treated as Case 1.

### Case 3: File is a bundled demo document
- `file_path` will be a container path like `/data/bundled/AlexHormoziTranscripts/...`
- Direct copy works

### Case 4: Windows path translation
- `file_path` might be stored as `C:\Users\chris\Documents\file.pdf`
- The wrapper translates Windows paths when mounting: `C:\...` → `/host-windows/c/...`
- Resolution: if `file_path` contains `\`, convert to `/` and check `/host-windows/c/...`

### Case 5: Multiple documents with same filename
- Each document has a unique `id`
- Cache directory is per-document: `/data/viewer-cache/{document_id}/`
- No filename collisions possible

### Case 6: Very large files (>1GB)
- No artificial size limit — if the host has the file and container has disk space, copy it
- For very large PDFs, the browser's PDF viewer may struggle
- No special handling needed at the server level

## Security Considerations

### Path Traversal Prevention
The `file_path` from the database is used to construct the source path. We MUST prevent path traversal attacks:

```typescript
function resolveDocumentPath(filePath: string): string | null {
  // Normalize and reject directory traversal
  const normalized = path.normalize(filePath);
  if (normalized.includes('..')) {
    console.error(`[viewer] Path traversal attempt blocked: ${filePath}`);
    return null;
  }
  // ... rest of resolution logic
}
```

### Read-Only Host Mount
The `/host` mount is read-only. The viewer only reads files from it (copy to cache). No write operations to `/host`.

### No Sensitive File Access
The `file_path` comes from the `documents` table — it was put there during ingestion. The user (or their AI agent) already had access to the file when they ingested it. Serving it back in the viewer does not expand access beyond what was already granted.

### Viewer Cache Directory Permissions
```
/data/viewer-cache/           → mode 700 (owner only)
/data/viewer-cache/{doc_id}/  → mode 700 (owner only)
/data/viewer-cache/{doc_id}/file.pdf → mode 600 (owner read/write only)
```

## File Copy Implementation

```typescript
import * as fs from 'fs';
import * as path from 'path';

const VIEWER_CACHE_DIR = path.join(
  process.env.OCR_PROVENANCE_DATABASES_PATH ?? '/data',
  'viewer-cache'
);

function cacheDocumentFile(documentId: string, sourcePath: string, fileName: string): string {
  const cacheDir = path.join(VIEWER_CACHE_DIR, documentId);

  // Create cache directory with restricted permissions
  fs.mkdirSync(cacheDir, { recursive: true, mode: 0o700 });

  const destPath = path.join(cacheDir, fileName);

  // Copy file
  fs.copyFileSync(sourcePath, destPath);

  // Set restrictive permissions on cached file
  fs.chmodSync(destPath, 0o600);

  return destPath;
}
```

## Office File Conversion

For Office files (docx, doc, pptx, ppt, xlsx, xls), after copying to cache, convert to PDF:

```typescript
import { execSync } from 'child_process';

async function convertToPdf(filePath: string, outDir: string): Promise<string> {
  const basename = path.basename(filePath, path.extname(filePath));
  const expectedOutput = path.join(outDir, `${basename}.pdf`);

  // LibreOffice conversion
  execSync(
    `libreoffice --headless --norestore --convert-to pdf --outdir "${outDir}" "${filePath}"`,
    {
      timeout: 120_000,    // 2 minute timeout
      stdio: 'pipe',       // Capture output for error reporting
      env: {
        ...process.env,
        HOME: '/tmp',       // LibreOffice needs a writable HOME
      },
    }
  );

  if (!fs.existsSync(expectedOutput)) {
    throw new Error(
      `LibreOffice conversion completed but output file not found. ` +
      `Expected: ${expectedOutput}. Input: ${path.basename(filePath)}`
    );
  }

  // Remove the original Office file from cache (only keep the PDF)
  if (filePath !== expectedOutput) {
    fs.unlinkSync(filePath);
  }

  return expectedOutput;
}
```

### LibreOffice Installation (Dockerfile)

Add to the runtime stage of `Dockerfile`:

```dockerfile
# LibreOffice for document viewer Office-to-PDF conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      libreoffice-writer \
      libreoffice-calc \
      libreoffice-impress \
      fonts-liberation \
      fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*
```

**Size impact**: ~150-200MB added to the Docker image.

**Fonts**: `fonts-liberation` and `fonts-dejavu-core` ensure Office documents render with standard fonts.

### Conversion Performance

| File Type | Typical Size | Conversion Time |
|-----------|-------------|----------------|
| DOCX (10 pages) | 50KB | 2-5 seconds |
| DOCX (100 pages) | 500KB | 5-15 seconds |
| PPTX (30 slides) | 5MB | 10-20 seconds |
| XLSX (1000 rows) | 200KB | 3-8 seconds |
| DOC (legacy) | 1MB | 5-15 seconds |

These are acceptable — the viewer shows a loading indicator during conversion.
