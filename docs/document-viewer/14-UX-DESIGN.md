# 14 — UX Design Specification

## Design Principles

1. **Instant feedback** — Every click produces immediate visual feedback (loading state, transition)
2. **Non-destructive navigation** — Escape and back button always work, never lose context
3. **Progressive disclosure** — Show summary first, details on demand (expand chunks, switch tabs)
4. **Consistent with existing UI** — Same color palette, same component patterns, same typography
5. **Full-screen immersion** — The viewer takes over the screen for focused document review
6. **Zero learning curve** — Tabs are self-explanatory, interactions are standard

## Color Palette (existing, from dashboard)

- Background: `bg-slate-900` (page), `bg-slate-800` (cards), `bg-slate-950` (viewer content)
- Text: `text-slate-100` (primary), `text-slate-300` (secondary), `text-slate-400` (muted), `text-slate-500` (disabled)
- Accent: `text-blue-400` (links, active states), `bg-blue-600` (active tab, buttons)
- Status: `text-emerald-400` (success), `text-amber-400` (warning), `text-red-400` (error)
- Borders: `border-slate-700` (standard), `border-slate-600` (hover)

## Document Table Interactions

### Current (Being Removed)
- Click row → row expands with inline details
- Click expanded row → collapses

### New
- **Click row** → Full-screen viewer modal opens
- **Hover row** → `bg-slate-800/40` background (unchanged)
- **Cursor** → `cursor-pointer` on all rows (unchanged)

### Visual Cue for Clickability
Each row keeps the existing hover effect. No additional icon is needed — the cursor and hover state communicate clickability.

## Viewer Modal Layout

### Viewport Dimensions
```
Full viewport: fixed inset-0 (covers entire screen)
Background: bg-slate-900 with 98% opacity (slight transparency)
Z-index: z-50 (above all other content)
```

### Header Bar (56px height)
```
┌────────────────────────────────────────────────────────────────────┐
│ ← Back  │  filename.pdf                    [View][Chunks][Info] X │
│          │                                                        │
│ h-14     │  Truncated with ellipsis           Active tab: blue bg  │
│ bg-slate-800                                  Inactive: slate-400  │
│ border-b border-slate-700                     X button: slate-400  │
└────────────────────────────────────────────────────────────────────┘
```

**Back button**: "← Back" text, not an icon. Left-aligned. Closes viewer.
**Filename**: Truncated with ellipsis if too long. `text-slate-200 font-medium`.
**Tab buttons**: Right of filename, centered in header. Pill-shaped (`rounded`).
**Close button**: "✕" at far right. `text-slate-400 hover:text-white`.

### Content Area
```
Fills remaining viewport height (flex-1)
overflow-hidden (each tab manages its own scroll)
```

## Tab Designs

### View Tab
```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  PDF:                                                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                                                              │  │
│  │  Browser's native PDF viewer fills entire content area        │  │
│  │  (Chrome: toolbar with page nav, zoom, search, download)     │  │
│  │  (Firefox: PDF.js with same controls)                        │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Image:                                                            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                          ┌─────────────────┐                 │  │
│  │  Dark background         │  [−] 100% [+]   │  Floating zoom  │  │
│  │  bg-slate-950            │     [Reset]      │  controls       │  │
│  │                          └─────────────────┘                 │  │
│  │           ┌────────────────────┐                             │  │
│  │           │                    │  Image centered              │  │
│  │           │    Image Content   │  Scrollable when zoomed      │  │
│  │           │                    │                             │  │
│  │           └────────────────────┘                             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Text/CSV:                                                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  bg-slate-950, p-6                                           │  │
│  │                                                              │  │
│  │  Monospace font, text-sm                                     │  │
│  │  Preserves whitespace and line breaks                        │  │
│  │  Scrollable                                                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Markdown:                                                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  bg-slate-950, p-6                                           │  │
│  │  max-w-4xl mx-auto (centered reading width)                  │  │
│  │                                                              │  │
│  │  Rendered HTML with prose styling                            │  │
│  │  Headings, lists, code blocks, links, tables all styled      │  │
│  │  Scrollable                                                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### Chunks Tab
```
┌────────────────────────────────────────────────────────────────────┐
│  p-6, overflow-auto                                                │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Search chunks... [___________________________] 225 chunks    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ #1  │ Page 1 │ Introduction │ 1,842 chars │ ● embedded     │  │
│  │ ───────────────────────────────────────────────────────────  │  │
│  │ Preview text here (3 lines max, line-clamp-3)...             │  │
│  │                                           [▼ Show full text] │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ #2  │ Page 1 │ Introduction │ 2,003 chars │ ● embedded     │  │
│  │ ───────────────────────────────────────────────────────────  │  │
│  │ Preview text here...                                         │  │
│  │                                           [▼ Show full text] │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ...                                                               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ [← Previous]    Page 1 of 12    [Next →]                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**Chunk card**: `bg-slate-800/50 rounded-lg border border-slate-700 p-4`
**Metadata row**: `text-xs text-slate-400` with gaps between items
**Preview text**: `text-slate-400 line-clamp-3` (collapsed)
**Full text**: `text-slate-300 whitespace-pre-wrap` (expanded)
**Expand button**: `text-blue-400 hover:text-blue-300 text-xs`

### Info Tab
```
┌────────────────────────────────────────────────────────────────────┐
│  p-6, overflow-auto, space-y-4                                     │
│                                                                    │
│  ┌── FILE INFORMATION ─────────────────────────────────────────┐  │
│  │  File Name      contract.pdf                                 │  │
│  │  File Path      /host/Documents/contracts/contract.pdf       │  │
│  │  File Type      PDF                                          │  │
│  │  ...                                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌── OCR PROCESSING ───────────────────────────────────────────┐  │
│  │  Quality   ████████████████████ 5.0 / 5.0                   │  │
│  │  ...                                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌── CONTENT SUMMARY ──────────────────────────────────────────┐  │
│  │  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐                        │  │
│  │  │ 225 │  │ 225 │  │  42 │  │38/4 │                        │  │
│  │  │Chunk│  │Embed│  │Image│  │ VLM │                        │  │
│  │  └─────┘  └─────┘  └─────┘  └─────┘                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌── PROVENANCE CHAIN ─────────────────────────────────────────┐  │
│  │  Chain Depth    4 levels                                     │  │
│  │  Total Records  493                                          │  │
│  │  Integrity      ✓ Verified                                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**Section card**: `bg-slate-800/50 rounded-lg border border-slate-700 p-5`
**Section title**: `text-sm font-medium text-slate-300 uppercase tracking-wide mb-4`
**Key-value row**: Label `text-xs text-slate-500 w-36`, Value `text-sm text-slate-200`
**Count card**: `bg-slate-900/50 rounded-lg p-3 text-center`, Value `text-xl font-bold text-slate-100`

## Loading States

### Document Prepare Loading
```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│                        [spinning circle]                           │
│                 Preparing document for viewing...                   │
│                                                                    │
│          (For Office files: "Converting to PDF...")                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Spinner: `w-8 h-8 border-2 border-slate-600 border-t-blue-400 rounded-full animate-spin`
Text: `text-slate-400 text-sm mt-4`

### Chunk Text Loading
When expanding a chunk, the "Show full text" button changes to "Loading..." with the same text style.

### Tab Content Loading
Each tab shows its own loading state centered in the content area.

## Error States

### File Not Found
```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│                    ┌───────────────────┐                            │
│                    │         !         │  Red circle indicator      │
│                    └───────────────────┘                            │
│                                                                    │
│              Unable to display document                            │
│              contract.pdf                                          │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Source file not found at any resolved path                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Original path: /host/Documents/old/contract.pdf                   │
│                                                                    │
│  Paths searched:                                                   │
│  ✕ /host/Documents/old/contract.pdf                                │
│  ✕ /data/staged/batch-xyz/contract.pdf                             │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Ensure the file exists at the original path, or              │  │
│  │ re-ingest the document.                                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Keyboard Interactions

| Key | Action | Context |
|-----|--------|---------|
| `Escape` | Close viewer modal | When viewer is open |
| `Tab` | Standard focus navigation | Always |

## Responsive Behavior

The viewer is designed for desktop use (the dashboard itself is desktop-focused). However:

- **Minimum width**: The viewer content is usable at 768px width
- **PDF iframe**: Scales with viewport
- **Image viewer**: Zoom controls work at any width
- **Text/Markdown**: `break-words` prevents horizontal overflow
- **Chunk cards**: Stack vertically at narrow widths
- **Info tab**: Grid collapses to 2 columns on smaller screens (`grid-cols-2 sm:grid-cols-4`)

## Animation & Transitions

- **Modal open**: No animation — appears instantly (fast)
- **Modal close**: No animation — disappears instantly (responsive)
- **Tab switching**: Content swaps instantly (no transition)
- **Hover effects**: `transition-colors duration-200` on buttons and rows
- **Loading spinner**: CSS `animate-spin`

No fade-in, slide-in, or other animations. Speed over style.

## Accessibility

- **Focus management**: When modal opens, focus moves to the close button
- **Focus trap**: Tab key cycles within the modal (doesn't leak to background)
- **ARIA**: Modal has `role="dialog"` and `aria-modal="true"`
- **Labels**: All buttons have descriptive text or `aria-label`
- **Color contrast**: All text meets WCAG AA contrast ratio (light text on dark background)
- **Keyboard navigation**: All interactive elements are keyboard-accessible
