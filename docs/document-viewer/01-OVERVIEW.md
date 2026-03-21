# 01 — Feature Overview

## What This Feature Does

When a user clicks on any document row in the dashboard's document list (at `/dashboard/data/{database}?tab=documents`), instead of expanding an inline detail panel, a **full-screen document viewer modal** opens. This viewer provides:

1. **View Tab** — Renders the actual document content for reading/navigation (read-only)
2. **Chunks Tab** — Shows all text chunks stored in the database for that document
3. **Info Tab** — Shows document metadata, provenance chain, quality scores, and processing details

## What This Feature Replaces

The current behavior: clicking a document row in `DocumentTable` toggles `expandedId` state, rendering an inline `<td colSpan={6}>` with basic metadata (type, pages, quality, created date). This entire expand-on-click pattern is **removed and replaced** with the viewer modal.

**Current code being replaced** (in `document-table.tsx`):
- Line 90: `const [expandedId, setExpandedId] = useState<string | null>(null);`
- Line 463: `onClick={() => setExpandedId(isExpanded ? null : doc.id)}`
- Lines 465-495: The `isExpanded` branch rendering inline details

## Supported File Types (18 total)

From `src/models/document.ts` line 16:

| Category | Extensions | Rendering Strategy |
|----------|-----------|-------------------|
| **PDF** | `.pdf` | `<iframe>` with browser's native PDF viewer |
| **Office Documents** | `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls` | Convert to PDF server-side via LibreOffice, serve as PDF in `<iframe>` |
| **Images** | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.gif`, `.webp` | `<img>` tag with zoom/pan controls |
| **Text** | `.txt`, `.csv`, `.md` | Syntax-highlighted `<pre>` block (Markdown rendered as HTML) |

## Constraints

1. **Constitution IMM-11**: "NEVER serve HTML from the MCP server." — The MCP server serves raw file bytes and JSON APIs only. The dashboard (Next.js) handles all HTML rendering.
2. **Constitution IMM-03**: "Local GPU only. No document content leaves the machine." — File retrieval stays within the Docker container boundary.
3. **Docker volume**: Files live at `/host` (read-only mount of host `$HOME`) or `/data/staged/` (uploaded files). The viewer file cache lives at `/data/viewer-cache/`.
4. **No backwards compatibility**: The old expand behavior is deleted, not hidden behind a feature flag.
5. **Fail-fast**: If a file cannot be retrieved or rendered, the viewer shows an explicit error with full details (file path, error type, suggested fix).

## User Flow

```
1. User navigates to /dashboard/data/AlexHormoziTranscripts?tab=documents
2. User sees the document table (same as today, minus the expand behavior)
3. User clicks on "_OceanofPDF.com_00M_Money_Models_How_To_Make_Money_Alex_Hormozi.pdf"
4. Full-screen viewer modal opens with 3 tabs:
   [View] [Chunks] [Info]
5. View tab loads: system checks /data/viewer-cache/ for this document
6. If not cached: system reads provenance to find original file_path
7. System copies file from /host/{path} to /data/viewer-cache/{doc_id}/{filename}
8. File is served to browser via GET /api/viewer/file/{doc_id}
9. Browser renders the PDF in an <iframe>
10. User can switch to Chunks tab to see all text chunks
11. User can switch to Info tab to see metadata + provenance
12. User closes the viewer (X button or Escape key)
13. A 24-hour cleanup timer starts for that file in the cache
14. After 24 hours with no re-open, the cached file is deleted
```

## Non-Goals

- **Editing**: The viewer is read-only. No annotation, highlighting, or modification.
- **File conversion**: We do not convert between formats (except Office→PDF for viewing).
- **Download**: No download button. The user already has the file on their host.
- **Search within viewer**: Not in scope. Users search via the existing `ocr_search` tools.
