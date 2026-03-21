# 04 — Dashboard Components

## Overview

Three new React components are created. One existing component (`DocumentTable`) is modified.

**Location**: `/home/cabdru/ocrprovenance-cloud/packages/dashboard/components/`

## 4.1 Modified: DocumentTable (`document-table.tsx`)

### Changes

1. **Remove** `expandedId` state and all expand-on-click logic
2. **Add** `viewerDoc` state to track which document the viewer is open for
3. **Add** `onDocumentClick` callback that sets `viewerDoc`
4. **Render** `<DocumentViewerModal>` when `viewerDoc` is set

### Specific Code Changes

**Remove**:
- Line 90: `const [expandedId, setExpandedId] = useState<string | null>(null);`
- Lines 456-463: `const isExpanded = expandedId === doc.id;` and `onClick={() => setExpandedId(...)}`
- Lines 465-495: The entire `isExpanded ? (...)` branch (the colSpan=6 expanded view)

**Add**:
```typescript
// New state
const [viewerDoc, setViewerDoc] = useState<McpDocument | null>(null);

// Row click handler (replaces expand toggle)
onClick={() => setViewerDoc(doc)}

// After the table, before pagination:
{viewerDoc && (
  <DocumentViewerModal
    document={viewerDoc}
    dbName={dbName}
    onClose={() => setViewerDoc(null)}
  />
)}
```

**Row rendering** — The `<tr>` always renders the collapsed row. No conditional. Every row shows: file_name, type, status, pages, quality, created. Clicking anywhere on the row opens the viewer.

### Updated Row Click Behavior

```tsx
<tr
  key={doc.id}
  className="transition-colors cursor-pointer hover:bg-slate-800/40"
  onClick={() => setViewerDoc(doc)}
>
  {/* Always render the 6-column collapsed view — no expand branch */}
  <td className="px-4 py-2.5">
    <span className="max-w-xs truncate block text-slate-200" title={doc.file_name}>
      {doc.file_name}
    </span>
  </td>
  {/* ... remaining 5 columns identical to current collapsed view ... */}
</tr>
```

## 4.2 New: DocumentViewerModal (`document-viewer-modal.tsx`)

### Props Interface

```typescript
interface DocumentViewerModalProps {
  document: McpDocument;    // From mcp-types.ts
  dbName: string;           // Database name for API calls
  onClose: () => void;      // Called when user closes the modal
}
```

### Component Structure

```
┌──────────────────────────────────────────────────────────────────────┐
│  Full-screen overlay (fixed inset-0, z-50, bg-slate-900/95)         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  HEADER BAR (h-14, flex, items-center, bg-slate-800)           │  │
│  │                                                                │  │
│  │  [← icon] file_name.pdf          [View] [Chunks] [Info]  [X]  │  │
│  │                                                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  CONTENT AREA (flex-1, overflow-hidden)                        │  │
│  │                                                                │  │
│  │  ┌────────────────────────────────────────────────────────┐    │  │
│  │  │                                                        │    │  │
│  │  │  Active tab content fills remaining space               │    │  │
│  │  │  (ViewerTabContent | ChunksTabContent | InfoTabContent) │    │  │
│  │  │                                                        │    │  │
│  │  └────────────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### State Management

```typescript
type ViewerTab = 'view' | 'chunks' | 'info';

const [activeTab, setActiveTab] = useState<ViewerTab>('view');
const [prepareResult, setPrepareResult] = useState<ViewerPrepareResponse | null>(null);
const [prepareError, setPrepareError] = useState<string | null>(null);
const [loading, setLoading] = useState(true);
```

### Lifecycle

1. **Mount**: Call `GET /api/mcp/viewer/prepare/{doc.id}?db={dbName}`
2. **Set state**: `prepareResult` on success, `prepareError` on failure
3. **Render**: Based on `prepareResult.render_as`, render appropriate viewer
4. **Unmount** (onClose): Call `POST /api/mcp/viewer/close/{doc.id}` (fire-and-forget)
5. **Keyboard**: Listen for `Escape` key to close

### Prepare call on mount

```typescript
useEffect(() => {
  let cancelled = false;
  setLoading(true);
  setPrepareError(null);

  fetch(`/api/mcp/viewer/prepare/${encodeURIComponent(document.id)}?db=${encodeURIComponent(dbName)}`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (cancelled) return;
      if (data.ready) {
        setPrepareResult(data);
      } else {
        setPrepareError(data.message || 'File could not be prepared for viewing');
      }
      setLoading(false);
    })
    .catch(err => {
      if (cancelled) return;
      setPrepareError(err.message);
      setLoading(false);
    });

  return () => { cancelled = true; };
}, [document.id, dbName]);
```

### Close handler (fire-and-forget cleanup signal)

```typescript
const handleClose = useCallback(() => {
  // Signal server to start cleanup timer
  fetch(`/api/mcp/viewer/close/${encodeURIComponent(document.id)}`, { method: 'POST' })
    .catch(() => {}); // Best-effort, don't block close
  onClose();
}, [document.id, onClose]);
```

### Escape key handler

```typescript
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') handleClose();
  };
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}, [handleClose]);
```

### Body scroll lock

```typescript
useEffect(() => {
  document.body.style.overflow = 'hidden';
  return () => { document.body.style.overflow = ''; };
}, []);
```

### Full Component Skeleton

```tsx
export function DocumentViewerModal({ document, dbName, onClose }: DocumentViewerModalProps) {
  const [activeTab, setActiveTab] = useState<ViewerTab>('view');
  const [prepareResult, setPrepareResult] = useState<ViewerPrepareResponse | null>(null);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // ... lifecycle hooks from above ...

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-900/98">
      {/* Header */}
      <div className="flex items-center h-14 px-4 bg-slate-800 border-b border-slate-700 shrink-0">
        <button onClick={handleClose} className="text-slate-400 hover:text-white mr-3" title="Close">
          ← Back
        </button>
        <span className="text-slate-200 font-medium truncate flex-1">{document.file_name}</span>

        {/* Tab buttons */}
        <div className="flex gap-1 mx-4">
          {(['view', 'chunks', 'info'] as ViewerTab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                activeTab === tab
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              {tab === 'view' ? 'View' : tab === 'chunks' ? 'Chunks' : 'Info'}
            </button>
          ))}
        </div>

        <button onClick={handleClose} className="text-slate-400 hover:text-white text-lg" title="Close (Esc)">
          ✕
        </button>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden">
        {loading && <ViewerLoadingState />}
        {prepareError && <ViewerErrorState error={prepareError} document={document} />}
        {!loading && !prepareError && prepareResult && (
          <>
            {activeTab === 'view' && (
              <ViewerTabContent prepareResult={prepareResult} document={document} dbName={dbName} />
            )}
            {activeTab === 'chunks' && (
              <ChunksTabContent document={document} dbName={dbName} />
            )}
            {activeTab === 'info' && (
              <InfoTabContent document={document} dbName={dbName} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
```

## 4.3 New: ViewerTabContent (`viewer-tab-content.tsx`)

Renders the document content based on `prepareResult.render_as`.

### Props

```typescript
interface ViewerTabContentProps {
  prepareResult: ViewerPrepareResponse;
  document: McpDocument;
  dbName: string;
}
```

### Render Logic

```typescript
export function ViewerTabContent({ prepareResult, document, dbName }: ViewerTabContentProps) {
  const fileUrl = `/api/mcp/viewer/file/${encodeURIComponent(document.id)}?db=${encodeURIComponent(dbName)}`;

  switch (prepareResult.render_as) {
    case 'pdf':
      return <PdfViewer url={fileUrl} filename={prepareResult.filename} />;
    case 'image':
      return <ImageViewer url={fileUrl} filename={prepareResult.filename} />;
    case 'text':
      return <TextViewer url={fileUrl} filename={prepareResult.filename} />;
    case 'markdown':
      return <MarkdownViewer url={fileUrl} filename={prepareResult.filename} />;
    default:
      return (
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <p className="text-red-400 text-lg">Unsupported render type: {prepareResult.render_as}</p>
            <p className="text-slate-500 mt-2">File type: {document.file_type}</p>
          </div>
        </div>
      );
  }
}
```

### Sub-renderers

**PdfViewer**: Full-height `<iframe>` with PDF URL
```tsx
function PdfViewer({ url, filename }: { url: string; filename: string }) {
  return (
    <iframe
      src={url}
      title={`Viewing: ${filename}`}
      className="w-full h-full border-0"
      sandbox="allow-same-origin"
    />
  );
}
```

**ImageViewer**: Centered `<img>` with overflow-auto for zoom/scroll
```tsx
function ImageViewer({ url, filename }: { url: string; filename: string }) {
  const [zoom, setZoom] = useState(1);
  return (
    <div className="h-full overflow-auto flex items-start justify-center p-4 bg-slate-950">
      <div className="sticky top-2 right-2 z-10 flex gap-1 absolute top-2 right-4">
        <button onClick={() => setZoom(z => Math.max(0.25, z - 0.25))} className="...">−</button>
        <span className="...">{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(z => Math.min(4, z + 0.25))} className="...">+</button>
        <button onClick={() => setZoom(1)} className="...">Reset</button>
      </div>
      <img
        src={url}
        alt={filename}
        style={{ transform: `scale(${zoom})`, transformOrigin: 'top center' }}
        className="max-w-none"
        onError={(e) => { /* show error state */ }}
      />
    </div>
  );
}
```

**TextViewer**: Fetch text content, render in `<pre>`
```tsx
function TextViewer({ url, filename }: { url: string; filename: string }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(url)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text(); })
      .then(setText)
      .catch(e => setError(e.message));
  }, [url]);

  if (error) return <ViewerErrorState error={error} />;
  if (!text) return <ViewerLoadingState />;

  return (
    <div className="h-full overflow-auto p-6 bg-slate-950">
      <pre className="text-sm text-slate-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
        {text}
      </pre>
    </div>
  );
}
```

**MarkdownViewer**: Fetch text, parse Markdown to HTML, render
```tsx
function MarkdownViewer({ url, filename }: { url: string; filename: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(url)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text(); })
      .then(md => {
        // Simple Markdown-to-HTML (use a lightweight parser)
        setHtml(parseMarkdown(md));
      })
      .catch(e => setError(e.message));
  }, [url]);

  if (error) return <ViewerErrorState error={error} />;
  if (!html) return <ViewerLoadingState />;

  return (
    <div className="h-full overflow-auto p-6 bg-slate-950">
      <div
        className="prose prose-invert prose-slate max-w-none"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
```

**Markdown parsing**: Use a lightweight parser. Options:
1. `marked` (npm package, ~50KB) — recommended, well-maintained
2. Simple regex-based parser (no dependency, limited features)

Decision: Add `marked` as a dependency to the dashboard package. It's a single dependency, widely used, and handles all standard Markdown features.

## 4.4 New: ChunksTabContent (`chunks-tab-content.tsx`)

Displays all chunks for the document, with pagination and text expansion.

### Props

```typescript
interface ChunksTabContentProps {
  document: McpDocument;
  dbName: string;
}
```

### Design

```
┌──────────────────────────────────────────────────────────────────┐
│  Search chunks... [input]         Showing 1-20 of 225 chunks    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ #1  Page 1  │ Section: Introduction                        │  │
│  │ ─────────────────────────────────────────────────────────  │  │
│  │ The fundamental premise of this book is that there are     │  │
│  │ only four ways to increase the value of an offer...        │  │
│  │ [Show full text]                                           │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ #2  Page 1  │ Section: Introduction                        │  │
│  │ ─────────────────────────────────────────────────────────  │  │
│  │ When you increase the value of an offer, you increase...   │  │
│  │ [Show full text]                                           │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ...                                                             │
│                                                                  │
│  [← Previous]  1 2 3 ... 12  [Next →]                           │
└──────────────────────────────────────────────────────────────────┘
```

### API Call

Uses the existing chunks endpoint with `document_id` filter:
```
GET /api/mcp/databases/{dbName}/chunks?document_id={doc.id}&page=1&limit=20
```

This endpoint already exists and supports `document_id` filtering (bin-http.ts line 1647).

### Features

1. Paginated chunk list (20 per page)
2. Each chunk shows: index, page number, section path, content preview (first 200 chars)
3. Click "Show full text" to expand and show complete chunk text
4. Search within chunks (uses existing `search` parameter on chunks endpoint)
5. Chunk count badge in header

## 4.5 New: InfoTabContent (`info-tab-content.tsx`)

Displays comprehensive document metadata and provenance information.

### Props

```typescript
interface InfoTabContentProps {
  document: McpDocument;
  dbName: string;
}
```

### API Call

Uses the new document-detail endpoint:
```
GET /api/mcp/databases/{dbName}/document-detail?document_id={doc.id}
```

### Design

```
┌──────────────────────────────────────────────────────────────────┐
│  DOCUMENT DETAILS                                                │
│                                                                  │
│  ┌── File Information ────────────────────────────────────────┐  │
│  │ File Name:     contract.pdf                                │  │
│  │ File Path:     /host/Documents/contracts/contract.pdf      │  │
│  │ File Type:     PDF                                         │  │
│  │ File Size:     2.3 MB                                      │  │
│  │ File Hash:     sha256:abcdef1234...                        │  │
│  │ Page Count:    184                                         │  │
│  │ Status:        ✓ complete                                  │  │
│  │ Created:       2026-03-17 6:06 PM                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── OCR Processing ─────────────────────────────────────────┐  │
│  │ Quality Score:     5.0 / 5.0                               │  │
│  │ Text Length:       450,000 characters                      │  │
│  │ Duration:          1m 35s                                  │  │
│  │ Started:           2026-03-17 6:06:42 PM                   │  │
│  │ Completed:         2026-03-17 6:08:15 PM                   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Content Summary ────────────────────────────────────────┐  │
│  │ Chunks:            225                                     │  │
│  │ Embeddings:        225                                     │  │
│  │ Images:            42 (38 analyzed, 4 pending)             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Provenance ─────────────────────────────────────────────┐  │
│  │ Chain Depth:       4                                       │  │
│  │ Total Records:     493                                     │  │
│  │ Integrity:         ✓ Verified                              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## 4.6 New Types (`mcp-types.ts` additions)

```typescript
export interface ViewerPrepareResponse {
  ready: boolean;
  document_id: string;
  filename: string;
  original_filename: string;
  render_as: 'pdf' | 'image' | 'text' | 'markdown';
  content_type: string;
  size_bytes: number;
  cached_at: string;
  source_path: string;
  // Error fields (when ready=false)
  error?: string;
  message?: string;
  paths_tried?: string[];
}

export interface DocumentDetail {
  document: {
    id: string;
    file_name: string;
    file_path: string;
    file_type: string;
    file_hash: string;
    file_size: number | null;
    status: string;
    page_count: number | null;
    doc_title: string | null;
    doc_author: string | null;
    doc_subject: string | null;
    created_at: string;
    modified_at: string | null;
    ocr_completed_at: string | null;
  };
  ocr_result: {
    id: string;
    text_length: number;
    page_count: number | null;
    parse_quality_score: number | null;
    processing_duration_ms: number | null;
    processing_started_at: string | null;
    processing_completed_at: string | null;
  } | null;
  counts: {
    chunks: number;
    embeddings: number;
    images: number;
    vlm_complete: number;
    vlm_pending: number;
  };
  provenance: {
    root_id: string | null;
    chain_depth: number;
    total_records: number;
    verified: boolean;
  };
}
```

## 4.7 New API Proxy Route

The existing catch-all proxy at `app/api/mcp/[...path]/route.ts` already handles:
- GET requests → proxied to MCP server
- POST requests → proxied to MCP server

The viewer endpoints (`/api/viewer/*`) need a **special handler** because `/api/viewer/file/{id}` returns binary data (not JSON). The current proxy does `await res.json()` which will fail for binary responses.

**New file**: `app/api/mcp-file/[...path]/route.ts`

```typescript
// This route proxies binary file responses from the MCP server's viewer endpoint
// Unlike the JSON proxy in /api/mcp/[...path], this streams raw bytes.

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const apiPath = '/api/' + path.join('/');
  const search = request.nextUrl.searchParams.toString();
  const url = `${MCP_SERVER_URL}${apiPath}${search ? '?' + search : ''}`;

  const headers = mcpHeaders();
  const res = await fetch(url, { cache: 'no-store', headers });

  if (!res.ok) {
    const body = await res.text();
    return NextResponse.json({ error: body }, { status: res.status });
  }

  // Stream binary response
  const contentType = res.headers.get('content-type') || 'application/octet-stream';
  const contentLength = res.headers.get('content-length');
  const disposition = res.headers.get('content-disposition');

  const responseHeaders = new Headers();
  responseHeaders.set('Content-Type', contentType);
  if (contentLength) responseHeaders.set('Content-Length', contentLength);
  if (disposition) responseHeaders.set('Content-Disposition', disposition);
  responseHeaders.set('Cache-Control', 'private, max-age=3600');

  return new Response(res.body, {
    status: 200,
    headers: responseHeaders,
  });
}
```

The viewer components will use `/api/mcp-file/viewer/file/{id}` for binary file requests and `/api/mcp/viewer/prepare/{id}` for JSON prepare requests.

Alternatively, update the existing proxy to detect non-JSON responses. The simplest approach: check `Content-Type` header before parsing as JSON.
