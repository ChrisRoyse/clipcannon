# 09 — Document Info Tab Design

## Purpose

The Info tab shows comprehensive metadata about the document: file details, OCR processing results, content statistics, and provenance chain summary. This is the "deep dive" tab for understanding everything about a document's processing history.

## Data Source

Uses the **new** `GET /api/databases/{name}/document-detail?document_id={id}` endpoint described in `03-MCP-SERVER-CHANGES.md`.

## Component: InfoTabContent

### Props

```typescript
interface InfoTabContentProps {
  document: McpDocument;
  dbName: string;
}
```

### State

```typescript
const [detail, setDetail] = useState<DocumentDetail | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);
```

### Data Fetching

```typescript
useEffect(() => {
  let cancelled = false;
  setLoading(true);
  setError(null);

  fetch(
    `/api/mcp/databases/${encodeURIComponent(dbName)}/document-detail?document_id=${encodeURIComponent(document.id)}`
  )
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data: DocumentDetail) => {
      if (cancelled) return;
      setDetail(data);
      setLoading(false);
    })
    .catch(err => {
      if (cancelled) return;
      setError(err.message);
      setLoading(false);
    });

  return () => { cancelled = true; };
}, [document.id, dbName]);
```

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌── File Information ────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  File Name       contract.pdf                              │  │
│  │  File Path       /host/Documents/contracts/contract.pdf    │  │
│  │  File Type       PDF                                       │  │
│  │  File Size       2.3 MB                                    │  │
│  │  File Hash       sha256:abcdef1234567890...                │  │
│  │  Page Count      184                                       │  │
│  │  Status          ✓ complete                                │  │
│  │  Created         March 17, 2026 6:06 PM                    │  │
│  │  OCR Completed   March 17, 2026 6:08 PM                    │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── OCR Processing ─────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  Quality Score    ████████████████████ 5.0 / 5.0           │  │
│  │  Text Length      450,000 characters                       │  │
│  │  Duration         1 minute 35 seconds                      │  │
│  │  Started          March 17, 2026 6:06:42 PM                │  │
│  │  Completed        March 17, 2026 6:08:15 PM                │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Content Summary ────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │  │
│  │  │   225    │  │   225    │  │    42    │  │   38/4   │  │  │
│  │  │  Chunks  │  │ Embeds   │  │  Images  │  │ VLM ✓/◦  │  │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Provenance Chain ───────────────────────────────────────┐  │
│  │                                                            │  │
│  │  DOCUMENT(0) → OCR_RESULT(1) → CHUNK(2) → EMBEDDING(3)   │  │
│  │                              → IMAGE(2) → VLM_DESC(3)     │  │
│  │                                         → EMBEDDING(4)    │  │
│  │                                                            │  │
│  │  Chain Depth:    4 levels                                  │  │
│  │  Total Records:  493                                       │  │
│  │  Integrity:      ✓ Verified (SHA-256 chain intact)         │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Section Components

#### InfoSection wrapper

```tsx
function InfoSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-5">
      <h3 className="text-sm font-medium text-slate-300 mb-4 uppercase tracking-wide">
        {title}
      </h3>
      {children}
    </div>
  );
}
```

#### InfoRow for key-value pairs

```tsx
function InfoRow({ label, value, mono }: { label: string; value: string | React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start py-1.5 border-b border-slate-700/50 last:border-0">
      <span className="text-xs text-slate-500 w-36 shrink-0 pt-0.5">{label}</span>
      <span className={`text-sm text-slate-200 flex-1 ${mono ? 'font-mono text-xs' : ''}`}>
        {value}
      </span>
    </div>
  );
}
```

### Rendering

```tsx
export function InfoTabContent({ document, dbName }: InfoTabContentProps) {
  // ... state and fetching ...

  if (loading) return <ViewerLoadingState message="Loading document details..." />;
  if (error) return <ViewerErrorState error={error} />;
  if (!detail) return null;

  const doc = detail.document;
  const ocr = detail.ocr_result;
  const counts = detail.counts;
  const prov = detail.provenance;

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      {/* File Information */}
      <InfoSection title="File Information">
        <InfoRow label="File Name" value={doc.file_name} />
        <InfoRow label="File Path" value={doc.file_path} mono />
        <InfoRow label="File Type" value={doc.file_type.toUpperCase()} />
        <InfoRow label="File Size" value={doc.file_size ? formatBytes(doc.file_size) : 'Unknown'} />
        <InfoRow label="File Hash" value={doc.file_hash} mono />
        <InfoRow label="Page Count" value={doc.page_count ? String(doc.page_count) : 'N/A'} />
        <InfoRow label="Status" value={<StatusBadge status={doc.status} />} />
        <InfoRow label="Created" value={formatDateTime(doc.created_at)} />
        {doc.ocr_completed_at && (
          <InfoRow label="OCR Completed" value={formatDateTime(doc.ocr_completed_at)} />
        )}
        {doc.doc_title && <InfoRow label="Title" value={doc.doc_title} />}
        {doc.doc_author && <InfoRow label="Author" value={doc.doc_author} />}
      </InfoSection>

      {/* OCR Processing */}
      {ocr && (
        <InfoSection title="OCR Processing">
          <InfoRow
            label="Quality Score"
            value={
              <div className="flex items-center gap-2">
                <QualityBar score={ocr.parse_quality_score} />
                <span>{ocr.parse_quality_score?.toFixed(1) ?? 'N/A'} / 5.0</span>
              </div>
            }
          />
          <InfoRow label="Text Length" value={`${ocr.text_length.toLocaleString()} characters`} />
          <InfoRow
            label="Duration"
            value={ocr.processing_duration_ms ? formatDuration(ocr.processing_duration_ms) : 'N/A'}
          />
          {ocr.processing_started_at && (
            <InfoRow label="Started" value={formatDateTime(ocr.processing_started_at)} />
          )}
          {ocr.processing_completed_at && (
            <InfoRow label="Completed" value={formatDateTime(ocr.processing_completed_at)} />
          )}
        </InfoSection>
      )}

      {/* Content Summary */}
      <InfoSection title="Content Summary">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <CountCard label="Chunks" value={counts.chunks} />
          <CountCard label="Embeddings" value={counts.embeddings} />
          <CountCard label="Images" value={counts.images} />
          <CountCard
            label="VLM Analysis"
            value={`${counts.vlm_complete}/${counts.vlm_complete + counts.vlm_pending}`}
            sub={counts.vlm_pending > 0 ? `${counts.vlm_pending} pending` : 'all complete'}
          />
        </div>
      </InfoSection>

      {/* Provenance Chain */}
      <InfoSection title="Provenance Chain">
        <InfoRow label="Chain Depth" value={`${prov.chain_depth} levels`} />
        <InfoRow label="Total Records" value={prov.total_records.toLocaleString()} />
        <InfoRow
          label="Integrity"
          value={
            <span className={prov.verified ? 'text-emerald-400' : 'text-red-400'}>
              {prov.verified ? '✓ Verified (SHA-256 chain intact)' : '✕ Verification failed'}
            </span>
          }
        />
      </InfoSection>
    </div>
  );
}
```

### Helper Components

```tsx
function CountCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-slate-900/50 rounded-lg p-3 text-center">
      <p className="text-xl font-bold text-slate-100">{typeof value === 'number' ? value.toLocaleString() : value}</p>
      <p className="text-xs text-slate-500 mt-1">{label}</p>
      {sub && <p className="text-xs text-slate-600 mt-0.5">{sub}</p>}
    </div>
  );
}

function QualityBar({ score }: { score: number | null }) {
  if (score === null) return <div className="w-24 h-2 bg-slate-700 rounded-full" />;
  const pct = Math.min(100, (score / 5) * 100);
  const color = score >= 4 ? 'bg-emerald-500' : score >= 3 ? 'bg-yellow-500' : score >= 2 ? 'bg-orange-500' : 'bg-red-500';
  return (
    <div className="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    complete: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    processing: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
    pending: 'text-slate-400 bg-slate-500/15 border-slate-500/30',
    failed: 'text-red-400 bg-red-500/15 border-red-500/30',
  };
  const icons: Record<string, string> = {
    complete: '✓', processing: '⟳', pending: '◦', failed: '✕',
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium border ${colors[status] || colors.pending}`}>
      {icons[status] || '?'} {status}
    </span>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs} second${secs !== 1 ? 's' : ''}`;
  const mins = Math.floor(secs / 60);
  const remainSecs = secs % 60;
  return `${mins} minute${mins !== 1 ? 's' : ''} ${remainSecs} second${remainSecs !== 1 ? 's' : ''}`;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
```
