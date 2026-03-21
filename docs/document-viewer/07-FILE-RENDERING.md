# 07 — File Rendering Strategy (All 18 File Types)

## Rendering Categories

Every file type maps to one of four render modes: `pdf`, `image`, `text`, `markdown`.

## Complete Mapping

| File Type | Extension(s) | Render Mode | How It's Rendered | Conversion Required |
|-----------|-------------|-------------|-------------------|-------------------|
| PDF | `.pdf` | `pdf` | Browser's native PDF viewer in `<iframe>` | No |
| Word Document | `.docx` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| Legacy Word | `.doc` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| PowerPoint | `.pptx` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| Legacy PowerPoint | `.ppt` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| Excel | `.xlsx` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| Legacy Excel | `.xls` | `pdf` | LibreOffice converts to PDF → `<iframe>` | Yes |
| PNG Image | `.png` | `image` | `<img>` tag with zoom controls | No |
| JPEG Image | `.jpg`, `.jpeg` | `image` | `<img>` tag with zoom controls | No |
| TIFF Image | `.tiff`, `.tif` | `image` | `<img>` tag with zoom controls | No (browsers support TIFF) |
| BMP Image | `.bmp` | `image` | `<img>` tag with zoom controls | No |
| GIF Image | `.gif` | `image` | `<img>` tag with zoom controls | No |
| WebP Image | `.webp` | `image` | `<img>` tag with zoom controls | No |
| Plain Text | `.txt` | `text` | Fetched as text, rendered in `<pre>` with monospace font | No |
| CSV | `.csv` | `text` | Fetched as text, rendered in `<pre>` with monospace font | No |
| Markdown | `.md` | `markdown` | Fetched as text, parsed with `marked`, rendered as styled HTML | No |

## PDF Rendering (`render_as: 'pdf'`)

### Implementation

```tsx
function PdfViewer({ url, filename }: { url: string; filename: string }) {
  return (
    <iframe
      src={url}
      title={`Viewing: ${filename}`}
      className="w-full h-full border-0"
    />
  );
}
```

### Browser Support
- Chrome: Full PDF viewer with navigation, zoom, search, print
- Firefox: Full PDF viewer (PDF.js built-in)
- Safari: Full PDF viewer
- Edge: Full PDF viewer (Chromium-based)

### Why iframe?
- Zero dependencies
- Full browser-native PDF viewing experience
- Page navigation, zoom, search, print — all built in
- No JavaScript PDF libraries needed (no pdf.js bundle)

### Office-to-PDF Conversion Notes
- LibreOffice `--headless --convert-to pdf` produces standard PDF/A
- Formatting may differ slightly from the original Office app
- Complex Excel formulas are rendered as their computed values
- Charts and graphs are rasterized
- This is the standard approach used by Google Drive, Nextcloud, and OnlyOffice for preview

## Image Rendering (`render_as: 'image'`)

### Implementation

```tsx
function ImageViewer({ url, filename }: { url: string; filename: string }) {
  const [zoom, setZoom] = useState(1);
  const [loadError, setLoadError] = useState(false);

  if (loadError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        <p>Failed to load image: {filename}</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-slate-950 relative">
      {/* Zoom controls - floating top-right */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1 bg-slate-800/90 rounded-lg px-2 py-1 border border-slate-700">
        <button
          onClick={() => setZoom(z => Math.max(0.1, z - 0.25))}
          className="text-slate-400 hover:text-white px-2 py-1 text-sm"
        >
          −
        </button>
        <span className="text-slate-300 text-xs w-12 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom(z => Math.min(5, z + 0.25))}
          className="text-slate-400 hover:text-white px-2 py-1 text-sm"
        >
          +
        </button>
        <button
          onClick={() => setZoom(1)}
          className="text-slate-400 hover:text-white px-2 py-1 text-xs border-l border-slate-700 ml-1"
        >
          Reset
        </button>
      </div>

      {/* Image container - centered */}
      <div className="flex items-start justify-center min-h-full p-8">
        <img
          src={url}
          alt={filename}
          className="max-w-none transition-transform duration-100"
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: 'top center',
          }}
          onError={() => setLoadError(true)}
        />
      </div>
    </div>
  );
}
```

### TIFF Handling
Most modern browsers (Chrome 90+, Firefox 96+, Edge 90+) support TIFF display natively. If a browser doesn't support TIFF:
- The `<img>` `onError` fires
- Error state shows "Failed to load image"
- No conversion fallback — fail fast, user can convert externally

### Large Images
- Browser handles large images natively with scroll
- Zoom controls allow scaling down or up
- No image resizing on the server — serve original resolution

## Text Rendering (`render_as: 'text'`)

### Implementation

```tsx
function TextViewer({ url, filename }: { url: string; filename: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        return res.text();
      })
      .then(setContent)
      .catch(err => setError(err.message));
  }, [url]);

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-red-400">Failed to load text file</p>
          <p className="text-slate-500 text-sm mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (content === null) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-slate-400">Loading text content...</span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-slate-950 p-6">
      <pre className="text-sm text-slate-300 font-mono whitespace-pre-wrap break-words leading-relaxed max-w-none">
        {content}
      </pre>
    </div>
  );
}
```

### CSV Display
CSV files are rendered as plain text in `<pre>`. The monospace font naturally aligns columns. For a table view, users can use the Chunks tab which shows the parsed text.

No fancy CSV table rendering — keep it simple, reliable, and consistent.

## Markdown Rendering (`render_as: 'markdown'`)

### Implementation

```tsx
function MarkdownViewer({ url, filename }: { url: string; filename: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        return res.text();
      })
      .then(mdText => {
        // Parse Markdown to HTML using marked
        const { marked } = require('marked');
        marked.setOptions({
          breaks: true,
          gfm: true,
        });
        const rendered = marked.parse(mdText);
        setHtml(rendered);
      })
      .catch(err => setError(err.message));
  }, [url]);

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-red-400">Failed to load Markdown file</p>
          <p className="text-slate-500 text-sm mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (html === null) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-slate-400">Loading Markdown...</span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-slate-950 p-6">
      <article
        className="prose prose-invert prose-slate max-w-4xl mx-auto"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
```

### Markdown Parser Dependency

Add to `packages/dashboard/package.json`:
```json
{
  "dependencies": {
    "marked": "^15.0.0"
  }
}
```

`marked` is chosen because:
- Lightweight (~50KB)
- GitHub-Flavored Markdown (GFM) support built-in
- No XSS risk with `sanitize: true` option
- Well-maintained (100M+ weekly downloads)

### Prose Styling

Tailwind's `@tailwindcss/typography` plugin provides the `prose` class which styles rendered HTML with:
- Proper heading sizes and spacing
- Styled code blocks
- Tables with borders
- Blockquotes with left border
- Links in blue

Check if `@tailwindcss/typography` is already a dependency. If not, add it.

## Error States

Every renderer has a consistent error display pattern:

```tsx
function ViewerErrorState({
  error,
  filename,
}: {
  error: string;
  filename?: string;
}) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md">
        <div className="text-red-400 text-4xl mb-4">!</div>
        <p className="text-red-400 text-lg font-medium">Unable to display file</p>
        {filename && (
          <p className="text-slate-400 text-sm mt-2">{filename}</p>
        )}
        <p className="text-slate-500 text-sm mt-3 bg-slate-800 rounded-lg p-3 font-mono text-left">
          {error}
        </p>
      </div>
    </div>
  );
}
```

## Loading States

```tsx
function ViewerLoadingState({ message }: { message?: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-slate-600 border-t-blue-400 rounded-full animate-spin mx-auto" />
        <p className="text-slate-400 text-sm mt-4">
          {message || 'Preparing document for viewing...'}
        </p>
      </div>
    </div>
  );
}
```

## Content-Type Headers (Server Side)

The MCP server sends correct Content-Type headers for each file type:

| Extension | Content-Type | Notes |
|-----------|-------------|-------|
| `.pdf` | `application/pdf` | Browser renders natively |
| `.png` | `image/png` | |
| `.jpg`/`.jpeg` | `image/jpeg` | |
| `.gif` | `image/gif` | |
| `.webp` | `image/webp` | |
| `.bmp` | `image/bmp` | |
| `.tiff`/`.tif` | `image/tiff` | |
| `.txt` | `text/plain; charset=utf-8` | UTF-8 ensures correct encoding |
| `.csv` | `text/csv; charset=utf-8` | Treated as text |
| `.md` | `text/markdown; charset=utf-8` | Fetched as text, parsed client-side |

All Office files (docx, doc, pptx, ppt, xlsx, xls) are converted to PDF before serving, so their Content-Type is always `application/pdf`.
