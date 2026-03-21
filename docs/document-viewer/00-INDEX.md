# Document Viewer Feature — Implementation Plan Index

> **Version**: 1.0 | **Date**: 2026-03-19 | **Status**: PLAN (not yet implemented)

## Plan Documents

| # | File | Description |
|---|------|-------------|
| 01 | [OVERVIEW.md](./01-OVERVIEW.md) | Feature overview, goals, constraints, supported file types |
| 02 | [ARCHITECTURE.md](./02-ARCHITECTURE.md) | System architecture, data flow, component diagram |
| 03 | [MCP-SERVER-CHANGES.md](./03-MCP-SERVER-CHANGES.md) | New REST API endpoints on the MCP server (bin-http.ts) |
| 04 | [DASHBOARD-COMPONENTS.md](./04-DASHBOARD-COMPONENTS.md) | New React components for the document viewer UI |
| 05 | [FILE-RETRIEVAL.md](./05-FILE-RETRIEVAL.md) | How files are fetched from host into container via provenance |
| 06 | [TEMP-FILE-MANAGEMENT.md](./06-TEMP-FILE-MANAGEMENT.md) | 24-hour auto-cleanup system for cached viewer files |
| 07 | [FILE-RENDERING.md](./07-FILE-RENDERING.md) | How each of the 18 file types is rendered in the viewer |
| 08 | [CHUNKS-TAB.md](./08-CHUNKS-TAB.md) | Chunks tab design — fetching and displaying document chunks |
| 09 | [DOCUMENT-INFO-TAB.md](./09-DOCUMENT-INFO-TAB.md) | Document info/provenance tab design |
| 10 | [ERROR-HANDLING.md](./10-ERROR-HANDLING.md) | Error handling strategy, logging, fail-fast behavior |
| 11 | [TESTING-PLAN.md](./11-TESTING-PLAN.md) | Complete testing strategy with real data |
| 12 | [IMPLEMENTATION-ORDER.md](./12-IMPLEMENTATION-ORDER.md) | Step-by-step implementation sequence with dependencies |
| 13 | [FILE-CHANGES-MANIFEST.md](./13-FILE-CHANGES-MANIFEST.md) | Every file that will be created or modified |
| 14 | [UX-DESIGN.md](./14-UX-DESIGN.md) | UI/UX design specification, layout, interactions |

## Key Principles

1. **No backwards compatibility** — old expand-on-click behavior is removed entirely
2. **Fail fast** — errors surface immediately with full context, never silently swallowed
3. **Real data testing** — no mocks, no stubs, real database queries and real files
4. **No workarounds** — if a file type can't render, error with clear message
5. **Auto-cleanup** — 24-hour timer ensures no garbage accumulation
