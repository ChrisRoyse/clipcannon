# 08 — Chunks Tab Design

## Purpose

The Chunks tab shows all text chunks stored in the database for the currently viewed document. This lets users see exactly what text the OCR system extracted, how it was segmented, and what's available for search.

## Data Source

Uses the **existing** chunks REST API endpoint:
```
GET /api/databases/{dbName}/chunks?document_id={doc_id}&page={page}&limit={limit}&search={query}
```

This endpoint already exists in `bin-http.ts` at line 1647 and supports the `document_id` filter parameter.

**No new API endpoints needed for this tab.**

## Response Type (existing)

From `lib/mcp-types.ts`:
```typescript
interface ChunkBrowser {
  chunks: {
    id: string;
    document_id: string;
    filename: string;
    page: number | null;
    section: string | null;
    content_types: string;
    content_preview: string;  // First ~200 chars
    char_count: number;
    has_embedding: boolean;
    quality: number;
  }[];
  total: number;
  page: number;
  limit: number;
}
```

## Chunk Full Text Fetching

The existing chunks API returns `content_preview` (truncated). To show full text, we need to fetch the complete chunk text.

The **existing** chunk browser component (`chunk-browser.tsx`) already has a pattern for this — it fetches full text via a separate endpoint when the user expands a chunk.

Looking at the existing `chunk-browser.tsx`, it fetches full text from:
```
GET /api/mcp/databases/{dbName}/chunks/{chunkId}/text
```

Wait — let me verify this endpoint exists. If not, we use the MCP tool `ocr_chunk_get` which returns full text.

**Approach**: The chunks list endpoint returns previews. For full text, we have two options:

1. **Option A**: Add a `GET /api/databases/{name}/chunks/{id}` endpoint that returns full chunk text
2. **Option B**: Use the existing chunk browser pattern from `chunk-browser.tsx`

Looking at the existing `chunk-browser.tsx`, it caches expanded chunk text client-side using a `Map<string, string>`. We follow the same pattern.

For the chunks tab, we need to either:
- Add `GET /api/databases/{name}/chunk-text/{id}` endpoint to return full text for a single chunk, OR
- Include full text in the paginated response (but this could be expensive for large chunks)

**Decision**: Add a new minimal endpoint `GET /api/databases/{name}/chunk-text/{id}` that returns `{ id, text }`.

## Component: ChunksTabContent

```typescript
interface ChunksTabContentProps {
  document: McpDocument;
  dbName: string;
}
```

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Search chunks...                       225 chunks total  │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Chunk #1  │ Page 1 │ Section: Introduction │ 1,842 chars  │  │
│  │ has_embedding: ✓ │ quality: 5.0 │ types: text              │  │
│  │ ─────────────────────────────────────────────────────────  │  │
│  │ The fundamental premise of this book is that there are     │  │
│  │ only four ways to increase the value of an offer. We can   │  │
│  │ increase the dream outcome...                              │  │
│  │                                        [▼ Show full text] │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Chunk #2  │ Page 1 │ Section: Introduction │ 2,003 chars  │  │
│  │ ...                                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ...                                                             │
│                                                                  │
│  Showing 1-20 of 225  [← Previous] 1 2 3 ... 12 [Next →]       │
└──────────────────────────────────────────────────────────────────┘
```

### State

```typescript
const [chunks, setChunks] = useState<ChunkBrowser['chunks']>([]);
const [total, setTotal] = useState(0);
const [page, setPage] = useState(1);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);
const [search, setSearch] = useState('');
const [searchInput, setSearchInput] = useState('');
const [expandedTexts, setExpandedTexts] = useState<Map<string, string>>(new Map());
const [expandedChunks, setExpandedChunks] = useState<Set<string>>(new Set());
const [loadingText, setLoadingText] = useState<Set<string>>(new Set());
const LIMIT = 20;
```

### Fetching Chunks

```typescript
useEffect(() => {
  let cancelled = false;
  setLoading(true);
  setError(null);

  const params = new URLSearchParams();
  params.set('document_id', document.id);
  params.set('page', String(page));
  params.set('limit', String(LIMIT));
  if (search) params.set('search', search);

  fetch(`/api/mcp/databases/${encodeURIComponent(dbName)}/chunks?${params}`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data: ChunkBrowser) => {
      if (cancelled) return;
      setChunks(data.chunks);
      setTotal(data.total);
      setLoading(false);
    })
    .catch(err => {
      if (cancelled) return;
      setError(err.message);
      setLoading(false);
    });

  return () => { cancelled = true; };
}, [document.id, dbName, page, search]);
```

### Expanding Chunk Text

```typescript
async function toggleChunk(chunkId: string) {
  if (expandedChunks.has(chunkId)) {
    // Collapse
    const next = new Set(expandedChunks);
    next.delete(chunkId);
    setExpandedChunks(next);
    return;
  }

  // Check if we already have the full text cached
  if (expandedTexts.has(chunkId)) {
    const next = new Set(expandedChunks);
    next.add(chunkId);
    setExpandedChunks(next);
    return;
  }

  // Fetch full text
  setLoadingText(prev => new Set(prev).add(chunkId));
  try {
    const res = await fetch(
      `/api/mcp/databases/${encodeURIComponent(dbName)}/chunk-text/${encodeURIComponent(chunkId)}`
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setExpandedTexts(prev => new Map(prev).set(chunkId, data.text));
    setExpandedChunks(prev => new Set(prev).add(chunkId));
  } catch (err) {
    console.error(`Failed to load chunk text: ${err}`);
  } finally {
    setLoadingText(prev => {
      const next = new Set(prev);
      next.delete(chunkId);
      return next;
    });
  }
}
```

### Chunk Card Rendering

```tsx
{chunks.map((chunk, i) => (
  <div key={chunk.id} className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
    {/* Header */}
    <div className="flex items-center gap-3 text-xs text-slate-400 mb-2">
      <span className="text-slate-300 font-medium">
        Chunk #{(page - 1) * LIMIT + i + 1}
      </span>
      {chunk.page != null && (
        <span>Page {chunk.page}</span>
      )}
      {chunk.section && (
        <span className="text-blue-400 truncate max-w-[200px]" title={chunk.section}>
          {chunk.section}
        </span>
      )}
      <span>{chunk.char_count.toLocaleString()} chars</span>
      <span className={chunk.has_embedding ? 'text-emerald-400' : 'text-slate-600'}>
        {chunk.has_embedding ? '● embedded' : '○ no embedding'}
      </span>
    </div>

    {/* Content */}
    <div className="text-sm text-slate-300">
      {expandedChunks.has(chunk.id) ? (
        <pre className="whitespace-pre-wrap break-words font-sans leading-relaxed">
          {expandedTexts.get(chunk.id) || chunk.content_preview}
        </pre>
      ) : (
        <p className="text-slate-400 line-clamp-3">
          {chunk.content_preview}
        </p>
      )}
    </div>

    {/* Expand/collapse button */}
    <button
      onClick={() => toggleChunk(chunk.id)}
      className="mt-2 text-xs text-blue-400 hover:text-blue-300"
    >
      {loadingText.has(chunk.id)
        ? 'Loading...'
        : expandedChunks.has(chunk.id)
          ? '▲ Hide full text'
          : '▼ Show full text'}
    </button>
  </div>
))}
```

## New API Endpoint Needed

### GET /api/databases/{name}/chunk-text/{chunk_id}

Returns the full text of a single chunk.

**Location**: Add to `bin-http.ts` in the GET handler section.

**Response**:
```json
{
  "id": "chunk-abc-123",
  "text": "The full chunk text here...",
  "char_count": 1842
}
```

**SQL**:
```sql
SELECT id, text, LENGTH(text) as char_count FROM chunks WHERE id = ?
```

**Implementation**:
```typescript
const chunkTextMatch = pathname.match(
  /^\/api\/databases\/([^/]+)\/chunk-text\/([^/]+)$/
);
if (chunkTextMatch) {
  const name = decodeURIComponent(chunkTextMatch[1]);
  const chunkId = decodeURIComponent(chunkTextMatch[2]);
  const verified = openVerifiedOcrDb(name);
  if (!verified) return;
  const conn = verified.conn;
  try {
    const chunk = conn.prepare(
      'SELECT id, text, LENGTH(text) as char_count FROM chunks WHERE id = ?'
    ).get(chunkId) as { id: string; text: string; char_count: number } | undefined;
    if (!chunk) {
      res.writeHead(404, JSON_CT);
      res.end(JSON.stringify({ error: `Chunk '${chunkId}' not found` }));
      return;
    }
    json({ id: chunk.id, text: chunk.text, char_count: chunk.char_count });
  } finally {
    conn.close();
  }
}
```

## Search Within Chunks

The search input filters chunks by content. The existing chunks endpoint supports a `search` parameter that does a LIKE query on chunk text.

```typescript
// Debounced search (same pattern as DocumentTable)
const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const handleSearchInput = useCallback((value: string) => {
  setSearchInput(value);
  if (debounceRef.current) clearTimeout(debounceRef.current);
  debounceRef.current = setTimeout(() => {
    setSearch(value);
    setPage(1);
  }, 300);
}, []);
```
