# OCR Provenance MCP: Next-Level Improvements Report

> **Date**: 2026-03-20 | **Scope**: Comprehensive feature, UX, adoption, and architecture analysis
> **Based on**: Deep research across 100+ sources covering market leaders, academic papers, user feedback, and emerging technology

---

## Executive Summary

This report identifies **47 high-impact improvements** across 9 categories that would transform OCR Provenance MCP from a strong document processing platform into a category-defining product. The recommendations are prioritized by impact and effort, grounded in current market research, competitor analysis, and user pain points.

**The three biggest opportunities:**

1. **Knowledge Graph Layer** -- Transform from document storage to a queryable knowledge system that understands relationships between entities across documents. This is the single highest-value architectural addition.

2. **ColPali/Visual Document Retrieval** -- Replace the OCR-then-embed pipeline with vision-language embeddings that operate directly on document page images. This eliminates OCR errors from propagating into search and enables layout-aware retrieval.

3. **Agentic Document Workflows** -- Build event-driven pipelines where document ingestion triggers automated classification, extraction, compliance checking, and downstream actions. 67% of enterprises are evaluating this approach; only 11% have it in production.

**Market context**: The IDP market is growing at 30%+ CAGR to $17.8B by 2032. Self-hosted local-GPU processing costs $0.09-$0.60 per 1,000 pages vs. cloud APIs at $1.50-$50 per 1,000 pages -- a 10-167x cost advantage that is your strongest competitive moat.

---

## Table of Contents

1. [Knowledge & Intelligence Layer](#1-knowledge--intelligence-layer)
2. [Search & Retrieval Upgrades](#2-search--retrieval-upgrades)
3. [Document Processing Pipeline](#3-document-processing-pipeline)
4. [UI/UX Overhaul](#4-uiux-overhaul)
5. [Adoption & Growth Strategy](#5-adoption--growth-strategy)
6. [Performance & Infrastructure](#6-performance--infrastructure)
7. [Security & Compliance](#7-security--compliance)
8. [Integration Ecosystem](#8-integration-ecosystem)
9. [Vertical-Specific Features](#9-vertical-specific-features)

---

## 1. Knowledge & Intelligence Layer

These additions transform the system from a document store into an intelligent knowledge platform.

### 1.1 Temporal Knowledge Graph (CRITICAL)

**What**: Build an entity-relationship graph layer on top of your existing SQLite storage that extracts entities (people, organizations, dates, amounts, clauses) and their relationships from documents, tracking how facts change over time.

**Why**: Microsoft GraphRAG has proven this architecture at scale (12M nodes, 89M relationships in production). Zep's Graphiti engine achieves 94.8% accuracy on memory benchmarks. Knowledge graphs improve factual correctness by 8% over pure vector RAG and enable cross-document reasoning that vector search alone cannot do.

**Architecture**:
- Extract entities and relationships during the chunking phase using the existing VLM or a dedicated NER model
- Store in a lightweight graph structure within SQLite (nodes table + edges table + properties) or integrate FalkorDB (140ms p99 queries vs Neo4j's 40s+)
- Bi-temporal model: track when a fact was stated AND when it was ingested
- Three search modes: cosine semantic similarity, BM25 full-text, breadth-first graph traversal
- Query example: "Show me all contracts where Company X is a party, ordered by most recent amendment"

**Impact**: Enables cross-document reasoning, entity timeline tracking, relationship discovery, and knowledge-grounded RAG that competitors like ABBYY, Hyperscience, and Textract cannot match.

**New MCP tools**:
- `ocr_graph_build` -- Extract entities and relationships from a database
- `ocr_graph_query` -- Query the knowledge graph (entity lookup, path finding, subgraph extraction)
- `ocr_graph_timeline` -- View how an entity's relationships change over time
- `ocr_graph_stats` -- Entity/relationship counts and type distributions
- `ocr_entity_search` -- Find documents containing specific entities

**Effort**: High (2-4 weeks). Requires NER pipeline, graph storage schema, and new query tools.

---

### 1.2 Automated Document Classification (HIGH)

**What**: Zero-shot and few-shot document classification that automatically categorizes ingested documents by type (invoice, contract, medical record, resume, research paper, etc.) without pre-training.

**Why**: Google Document AI and ABBYY Vantage 3.0 both shipped this in 2025. Users currently must manually organize documents. Auto-classification enables smart routing, type-specific extraction templates, and workflow automation.

**Implementation**:
- Use the existing embedding model to classify against a library of document type descriptions (zero-shot via cosine similarity)
- Allow users to define custom categories with 3-5 example documents (few-shot)
- Store classification result + confidence score on the document record
- Use classification to trigger type-specific processing pipelines

**New MCP tools**:
- `ocr_classify_document` -- Classify a single document
- `ocr_classify_batch` -- Classify all unclassified documents in a database
- `ocr_classifier_train` -- Train a custom classifier from examples
- `ocr_classifier_list` -- List available classifiers and their accuracy

**Effort**: Medium (1-2 weeks). Leverages existing embedding infrastructure.

---

### 1.3 Automated PII Detection and Redaction (HIGH)

**What**: Detect and redact personally identifiable information (names, SSNs, addresses, phone numbers, email addresses, dates of birth, financial account numbers) from documents before storage or export.

**Why**: AI-powered redaction achieves 90-95% accuracy, reducing manual effort by 70% and redaction time by up to 98%. HIPAA, GDPR, and CCPA require PII protection. Azure shipped this as a core Document Intelligence feature in late 2025. VIDIZMO supports 255+ file formats and 40+ PII types.

**Implementation**:
- Run NER (Named Entity Recognition) on OCR text to identify PII entities
- Store PII locations as annotations with type labels
- Provide redaction modes: mask (replace with [REDACTED]), pseudonymize (replace with fake data), or remove
- Apply redaction on export, leaving originals intact for authorized users
- Integrate with existing compliance tools (`ocr_compliance_hipaa`, `ocr_compliance_export`)

**New MCP tools**:
- `ocr_pii_detect` -- Scan document for PII, return findings with locations and confidence
- `ocr_pii_redact` -- Apply redaction to a document or export
- `ocr_pii_report` -- Summary of PII across a database
- `ocr_pii_policy` -- Configure auto-redaction rules (always redact SSNs, flag but don't redact names, etc.)

**Effort**: Medium (2-3 weeks). NER model can piggyback on existing Python worker infrastructure.

---

### 1.4 Cross-Document Summarization (MEDIUM)

**What**: Generate structured summaries that synthesize information across multiple related documents, not just single-document summaries.

**Why**: This is a largely unmet need identified across user complaints. Few tools can answer "summarize all lease agreements expiring in 2026" or "what are the common risk factors across these 50 medical studies?" Current `ocr_corpus_summarize` operates at the corpus level but doesn't do targeted cross-document synthesis.

**Implementation**:
- Use existing search to gather relevant chunks across documents
- Assemble context with provenance tracking
- Output structured summary with source citations (document ID, page, chunk)
- Support question-driven summarization ("What are the payment terms across all vendor contracts?")

**Enhancement to existing tools**:
- Enhance `ocr_corpus_summarize` with query-driven mode
- Enhance `ocr_rag_context` with multi-document synthesis output

**Effort**: Low-Medium (1 week). Primarily prompt engineering on existing infrastructure.

---

### 1.5 Document Relationship Discovery (MEDIUM)

**What**: Automatically discover relationships between documents -- amendments to contracts, revisions of policies, responses to RFPs, citations between research papers.

**Why**: Users currently must manually track document relationships. Automated discovery enables version tracking, amendment chains, citation graphs, and compliance audit trails.

**Implementation**:
- Use existing `ocr_document_find_similar` and `ocr_comparison_discover` as foundations
- Add relationship type classification (amendment, revision, response, citation, supersedes)
- Build relationship graph stored alongside the knowledge graph
- Enable traversal queries ("show me all amendments to this master agreement")

**New MCP tools**:
- `ocr_relationship_discover` -- Find and classify relationships between documents
- `ocr_relationship_graph` -- Visualize document relationship network
- `ocr_relationship_chain` -- Follow a chain (original -> amendment 1 -> amendment 2)

**Effort**: Medium (1-2 weeks).

---

## 2. Search & Retrieval Upgrades

### 2.1 ColPali Visual Document Retrieval (CRITICAL)

**What**: Implement late interaction visual retrieval using ColPali/ColQwen models that embed document pages as images directly, preserving layout, tables, figures, and formatting in the embedding space.

**Why**: ColPali eliminates the OCR-then-embed pipeline for retrieval, treating each document page as an image and producing multi-vector embeddings that capture both text content AND visual layout. NVIDIA's Nemotron ColEmbed V2 (8B params) ranks #1 on the ViDoRe benchmark. This is the single biggest retrieval quality improvement available.

**How it differs from current approach**:
- Current: PDF -> OCR text -> chunk text -> embed text -> search text embeddings
- ColPali: PDF -> render page images -> embed page images -> search visual embeddings
- ColPali preserves table structure, figure context, and layout relationships that OCR+chunking loses

**Implementation**:
- Add a ColPali/ColQwen worker (similar architecture to existing VLM daemon)
- Generate multi-vector page embeddings during ingestion (alongside existing text embeddings)
- Store page-level embeddings in a separate vec table
- Implement late interaction scoring (MaxSim) for retrieval
- Offer as an alternative search mode: `search_mode: "visual"` or `"hybrid_visual"`

**Performance**: ColPali models are 3B-8B parameters and can run on the existing GPU alongside other workers.

**New MCP tools**:
- Extend `ocr_search` with `mode: "visual"` parameter
- `ocr_embedding_rebuild` extended to support visual embeddings

**Effort**: High (2-3 weeks). New Python worker + storage schema + search integration.

---

### 2.2 Three-Way Hybrid Retrieval with SPLADE (HIGH)

**What**: Add learned sparse retrieval (SPLADE) as a third retrieval method alongside your existing BM25 and dense vector search, then fuse all three with Reciprocal Rank Fusion.

**Why**: IBM research confirmed three-way retrieval (BM25 + dense + sparse) is optimal. Real-world improvement: 15-30% better recall than any two-way combination. SPLADE provides learned query expansion that captures synonyms and related terms that BM25 misses while being more interpretable than dense vectors.

**Implementation**:
- Add SPLADE model to Python workers (small model, ~110M params, runs on CPU or GPU)
- Generate sparse vectors during chunking (stored as sparse arrays in SQLite)
- Fuse BM25 + dense + SPLADE scores using existing RRF implementation
- Existing cross-encoder reranker sits on top

**New parameters on `ocr_search`**:
- `sparse_weight: float` -- weight for SPLADE component (default 1.0)
- `retrieval_mode: "three_way" | "hybrid" | "semantic" | "keyword"` -- explicitly select retrieval strategy

**Effort**: Medium (1-2 weeks). SPLADE model is small; main work is sparse vector storage and fusion.

---

### 2.3 Matryoshka Embedding Support (MEDIUM)

**What**: Switch to an embedding model that supports Matryoshka Representation Learning (MRL), allowing embeddings to be truncated from 768 to 512/256/128 dimensions without retraining.

**Why**: Nomic Embed Text V2 (MoE architecture, 100 languages, MRL support) is a direct upgrade from your current nomic-embed-text-v1.5. Variable-dimension embeddings enable storage/speed tradeoffs: use 768-dim for high-quality search, 256-dim for fast approximate search on large databases, 128-dim for real-time filtering.

**Implementation**:
- Update embedding worker to use nomic-embed-text-v2-moe
- Store full 768-dim embeddings but allow truncated search
- Add dimension parameter to search tools
- Backwards-compatible with existing 768-dim embeddings

**Effort**: Low (3-5 days). Model swap + minor search parameter changes.

---

### 2.4 Query Understanding and Guidance (MEDIUM)

**What**: Enhance the search pipeline with query classification, expansion, and user guidance that helps users write better queries.

**Why**: Over 70% of errors in modern RAG applications stem from incomplete, irrelevant, or poorly structured context. Your existing keyword list detection is a good start. Adding query expansion (synonyms, related terms), query classification (factual vs. conceptual vs. navigational), and suggested refinements would significantly improve search quality.

**Implementation**:
- Expand existing query classification with more categories
- Add query expansion using the embedding model (find similar terms)
- Suggest follow-up queries based on search results
- Auto-detect and handle multi-part queries

**Enhancement to existing tools**:
- `ocr_search` returns `suggested_queries: string[]` in results
- `ocr_search` returns `query_analysis: { type, expanded_terms, confidence }` in results

**Effort**: Low-Medium (1 week).

---

### 2.5 Saved Search Alerts with Webhooks (LOW)

**What**: Enhance existing `ocr_search_alert_check` to push notifications via webhooks when new documents match saved searches.

**Why**: Users need to be notified when relevant new documents arrive, not manually poll. This enables "watch folders" and document monitoring workflows.

**Implementation**: Connect existing saved search + alert infrastructure to existing webhook system.

**Effort**: Low (2-3 days). Wiring existing systems together.

---

## 3. Document Processing Pipeline

### 3.1 Chandra OCR 2 / VLM Upgrade Path (CRITICAL)

**What**: Upgrade from Chandra v0.1.8 to Chandra OCR 2 (released October 2025) which is fine-tuned on Qwen-3-VL at 9B parameters, scoring 83.1 on olmOCR-Bench (highest open-source score).

**Why**: Chandra OCR 2 handles handwriting, checkboxes, complex tables, and mathematical formulas across 40+ languages. The current Chandra v0.1.8 is significantly behind state-of-the-art. This single upgrade would improve VLM analysis quality across the board.

**Implementation**:
- Update VLM worker to load Chandra OCR 2 model
- VRAM requirement similar (~18GB on H100)
- JSON output format likely compatible or easily adapted
- Update model path in Dockerfile and entrypoint

**Effort**: Low-Medium (3-5 days). Model swap with output format adaptation.

---

### 3.2 Handwriting Recognition Mode (HIGH)

**What**: Add a dedicated handwriting recognition mode that uses models optimized for handwritten text (HTR-VT, Mistral OCR's 88.9% handwriting accuracy).

**Why**: Traditional OCR achieves only 60% accuracy on handwritten content. Modern HTR models reach 88-90%+ in structured scenarios. Healthcare (prescriptions, clinical notes), legal (handwritten annotations), and government (forms) all need this capability.

**Implementation**:
- Detect handwritten regions during OCR using layout analysis
- Route handwritten regions to a specialized HTR model
- Merge handwritten text back into the document flow with confidence scores
- Flag low-confidence handwriting recognition for human review

**New MCP tools**:
- `ocr_ingest_files` gains `handwriting_mode: "auto" | "enabled" | "disabled"` parameter
- Handwriting confidence stored in chunk metadata

**Effort**: Medium (1-2 weeks). Requires additional model and detection logic.

---

### 3.3 Structured Data Extraction Templates (HIGH)

**What**: Pre-built and custom extraction templates that pull structured fields from specific document types (invoices: vendor, amount, date, line items; contracts: parties, effective date, term, governing law; medical records: patient name, DOB, diagnoses, medications).

**Why**: This is what enterprise users actually need. Raw OCR text is the starting point, not the end product. Reducto's schema-level extraction and ABBYY's pre-configured AI models are key competitive features. 75% of AP departments use some AI, but only 8% are fully automated -- the gap is structured extraction.

**Implementation**:
- Define JSON schemas for common document types
- Use existing VLM + LLM to extract fields matching the schema
- Store extracted data in the existing `extractions` table
- Provide a template builder for custom schemas
- Confidence scores per field for human review routing

**New MCP tools**:
- `ocr_template_create` -- Define extraction template (JSON schema + document type)
- `ocr_template_list` -- List available templates
- `ocr_template_extract` -- Apply template to document(s)
- `ocr_template_validate` -- Validate extracted data against business rules

**Effort**: Medium-High (2-3 weeks).

---

### 3.4 Model Routing and Cascading (MEDIUM)

**What**: Implement a cascade routing system that uses a lightweight model for initial document assessment, then routes to the appropriate processing pipeline based on document complexity.

**Why**: 60-70% of documents are simple enough for fast processing. Cascade routing achieves 60-87% cost reduction over using premium models for everything, with 2-10x faster responses on simple queries. GPT-5 uses this internally.

**Implementation**:
- Quick document complexity assessment (page count, text density, image count, language)
- Simple documents (typed English, standard layout): fast OCR path
- Complex documents (handwriting, tables, multi-language, poor scan quality): full Marker + VLM path
- Configurable thresholds

**Effort**: Medium (1-2 weeks).

---

### 3.5 Incremental Processing / Delta Updates (MEDIUM)

**What**: When a document is re-ingested (updated version), only re-process changed pages instead of the entire document.

**Why**: Re-processing a 500-page document because one page changed wastes GPU time and billing. Delta processing compares page hashes to identify changes.

**Implementation**:
- Store per-page content hashes during initial processing
- On re-ingestion, compare page hashes to identify changed pages
- Only re-OCR changed pages, re-chunk affected sections, re-embed affected chunks
- Update provenance chain to reflect partial re-processing

**Effort**: Medium (1-2 weeks).

---

### 3.6 Multi-Language Detection and Processing (MEDIUM)

**What**: Automatic language detection per page/region with appropriate model routing.

**Why**: PaddleOCR-VL supports 109 languages, Mistral OCR handles thousands of scripts. Your current Marker-pdf supports 90+ languages but doesn't detect or optimize per-language. Enterprises processing international documents need this.

**Implementation**:
- Add language detection during OCR (FastText or similar lightweight detector)
- Store detected languages on document and chunk records
- Route search queries through language-appropriate embedding models
- Support cross-lingual search (query in English, find results in any language)

**Effort**: Low-Medium (1 week).

---

## 4. UI/UX Overhaul

### 4.1 Interactive Document Viewer with Annotations (CRITICAL)

**What**: Transform the current basic document viewer into a full-featured viewer with text selection, annotation, highlighting, search-result overlay, entity highlighting, and side-by-side OCR comparison.

**Why**: PSPDFKit and Apryse charge $5K-50K/year for document viewer SDKs. A built-in viewer that overlays OCR results, entity annotations, PII highlights, and search hit markers on the original document is a massive UX differentiator. PDF.js is the proven open-source foundation.

**Features**:
- Overlay OCR text on original document (show what was extracted)
- Highlight search result locations on the actual document pages
- Click a chunk to see it highlighted in context
- Entity highlighting (people, organizations, dates, amounts in different colors)
- PII indicators (yellow highlight for detected PII)
- Annotation tools (comment, highlight, flag, approve)
- Side-by-side view: original document | OCR markdown output
- Thumbnail navigation for multi-page documents
- Provenance overlay: click any text to see its full provenance chain

**Implementation**: Build on existing `/api/viewer/` endpoints. Add a client-side viewer application served from the dashboard.

**Effort**: High (3-4 weeks). Frontend development + API extensions.

---

### 4.2 Dashboard Redesign: Analytics-First (HIGH)

**What**: Redesign the dashboard from a billing-focused interface to an analytics-first command center showing processing pipeline health, document statistics, search quality metrics, and system status.

**Why**: Gartner research shows developer tools with fewer than 12 panels per page and "golden signals first" (request rate, error rate, latency, saturation) achieve highest engagement. The current dashboard shows balance and charges -- useful but not the primary user need.

**Dashboard pages**:
- **Overview**: Documents processed (today/week/month), processing pipeline status, recent activity feed, system health (GPU utilization, VRAM, disk usage)
- **Documents**: Searchable document browser with thumbnails, status filters, batch actions
- **Search Console**: Test queries, view relevance scores, compare search modes, query analytics
- **Processing Queue**: Real-time processing status, queue depth, estimated completion times, error log
- **Analytics**: Document type distribution, processing time trends, quality score distribution, cost analytics
- **Account**: Current balance, charges, payments (existing functionality)

**Effort**: High (3-4 weeks). Frontend redesign.

---

### 4.3 Real-Time Processing Feedback (HIGH)

**What**: Live progress updates during document processing showing each pipeline stage (ingestion -> OCR -> chunking -> embedding -> indexing) with per-page progress, elapsed time, and estimated completion.

**Why**: Users currently have no visibility into processing status beyond polling `ocr_status`. Long processing runs (160-page PDF = ~5 minutes) with no feedback feel broken. Every competitor provides real-time progress.

**Implementation**:
- Use existing SSE transport for push updates
- Emit events at each pipeline stage transition
- Include: stage name, page progress (page 45/160), elapsed time, estimated remaining time
- Dashboard shows animated progress bar with stage indicators
- MCP clients receive progress events via SSE

**Effort**: Medium (1-2 weeks). Event emission from existing pipeline stages + SSE integration.

---

### 4.4 Onboarding Wizard (HIGH)

**What**: Guided first-run experience that gets users from install to first successful search in under 15 minutes.

**Why**: The "15-Minute Rule" is critical -- if a developer cannot achieve meaningful first success within 15 minutes, activation and retention plummet. Visual onboarding increases comprehension by 80%.

**Wizard flow**:
1. Welcome + system status check (GPU detected, services healthy)
2. Create first database (with suggested name)
3. Ingest sample document (bundled demo PDF) OR upload your own
4. Watch processing happen (with explanation of each stage)
5. Run first search (suggested query + explanation of results)
6. Show provenance chain for a result (explain what makes this system unique)
7. Show dashboard with completed analytics

**Implementation**: Dashboard page served as first-run experience when no databases exist.

**Effort**: Medium (1-2 weeks).

---

### 4.5 Search Results UI with Provenance Visualization (MEDIUM)

**What**: Rich search results display with document thumbnails, highlighted text snippets, confidence scores, provenance path breadcrumbs, and interactive provenance DAG visualization.

**Why**: Provenance tracking is the core differentiator but currently requires tool calls to explore. Making it visual and interactive transforms it from a compliance feature into a trust-building UX element.

**Features**:
- Search result cards: thumbnail + title + highlighted snippet + score + doc type badge
- Provenance breadcrumb on each result: Document -> OCR -> Chunk -> Embedding (clickable)
- Interactive DAG visualization showing the full provenance tree for any document
- Color-coded by processing stage and confidence

**Effort**: Medium (2 weeks). Frontend component + API for provenance tree data.

---

### 4.6 Dark Mode and Theming (LOW)

**What**: Dark mode support for the dashboard (overwhelmingly preferred by developers) and basic theming support for enterprise white-labeling.

**Effort**: Low (3-5 days).

---

## 5. Adoption & Growth Strategy

### 5.1 MCP Marketplace Optimization (CRITICAL)

**What**: Optimize the MCP server listing for discoverability across Claude Code, Cursor, Windsurf, and VS Code. The MCP ecosystem has exploded to 5,800+ servers and 97M monthly SDK downloads.

**Actions**:
- Ensure listing on mcp.run, smithery.ai, and glama.ai marketplaces
- Optimize tool descriptions for AI agent discovery (clear, action-oriented names)
- Add `ocr_guide` as the primary entry point tool with smart recommendations
- Publish example workflows for each AI client
- Create a "Quick Start" that works with `npx` in under 2 minutes

**Effort**: Low (3-5 days).

---

### 5.2 Plugin / Extension Ecosystem (HIGH)

**What**: Define a plugin API that allows third parties to add custom extraction templates, document type handlers, integration connectors, and workflow automations.

**Why**: Cursor, Supabase, and Obsidian all grew through plugin ecosystems. Obsidian has 1,800+ community plugins. A plugin system turns users into contributors and dramatically expands the feature surface without core development cost.

**Plugin types**:
- **Extractors**: Custom extraction logic for specific document types (W-2 forms, invoices, prescriptions)
- **Connectors**: Output integrations (Salesforce, SAP, Slack, email)
- **Analyzers**: Custom analysis pipelines (sentiment analysis, risk scoring)
- **Classifiers**: Domain-specific document classification models

**Effort**: High (3-4 weeks for API definition and runtime).

---

### 5.3 Free Tier / Playground (HIGH)

**What**: Offer a web-based playground where users can upload a single document and see the full pipeline in action (OCR, chunks, embeddings, search, provenance) without installing anything.

**Why**: Cursor reached $2B ARR through pure product-led growth. Supabase grew from 1M to 4.5M developers in a year. The #1 pattern: instant time-to-value with zero installation friction. A playground removes the Docker/GPU barrier for evaluation.

**Implementation options**:
- Host a demo instance on RunPod ($98/hr for H100, but only while in use)
- Allow 3 free documents per session with 24-hour expiry
- Show the full processing pipeline with timing and provenance

**Effort**: Medium (2 weeks). Existing system + rate limiting + hosted instance.

---

### 5.4 CLI Experience Polish (MEDIUM)

**What**: Improve the `npx -y ocr-provenance-mcp` CLI experience with colored output, progress spinners, helpful error messages, and interactive prompts.

**Why**: The wrapper CLI is the first touch point. Every friction point in install/start/status reduces activation. Modern CLI tools (Cursor, Supabase CLI, Vercel CLI) set high UX expectations.

**Improvements**:
- Colored, formatted output with emoji indicators for status
- Spinner animations during Docker pull/build
- Clear error messages with suggested fixes
- `npx ocr-provenance-mcp doctor` with automated diagnostics
- `npx ocr-provenance-mcp demo` to run a complete demo workflow

**Effort**: Low-Medium (1 week).

---

### 5.5 Video Tutorials and Documentation (MEDIUM)

**What**: Create 3-5 minute video tutorials for common workflows: installation, first document, search, provenance verification, Stripe setup, cloud deployment.

**Why**: Visual onboarding increases comprehension by 80%. Video content is the #1 way developer tools drive adoption. Text-only documentation is insufficient for complex multi-service systems.

**Effort**: Medium (1-2 weeks of content creation).

---

### 5.6 Community Templates Library (MEDIUM)

**What**: Curated library of extraction templates, search configurations, and workflow recipes contributed by users and maintained by the project.

**Why**: Templates reduce time-to-value for specific use cases. "Process invoices" template vs. "configure OCR, then write extraction logic, then validate fields" is the difference between 5 minutes and 5 hours.

**Starter templates**:
- Invoice processing (vendor, amount, date, line items)
- Contract review (parties, term, governing law, key clauses)
- Resume parsing (name, contact, experience, education, skills)
- Medical record summary (patient, diagnoses, medications, procedures)
- Research paper extraction (title, authors, abstract, citations, methodology)
- Real estate lease abstraction (parties, premises, rent, term, renewal options)

**Effort**: Medium (1-2 weeks).

---

## 6. Performance & Infrastructure

### 6.1 Model Quantization for Smaller GPUs (HIGH)

**What**: Offer quantized model variants (4-bit AWQ or GGUF) that run on consumer GPUs (RTX 3080 10GB, RTX 4060 8GB) with acceptable quality loss.

**Why**: The current system requires ~30GB VRAM for all models simultaneously. Quantization can achieve 70% file size reduction with 90-95% quality retention. Unsloth Dynamic 2.0 can shrink models by 75% with per-layer selective quantization. This dramatically expands the addressable market.

**Target configurations**:
- **Full** (current): RTX 4090/5090 32GB -- all models at full precision
- **Standard**: RTX 3080/4070 12-16GB -- OCR + embedding at full, VLM quantized
- **Lite**: RTX 3060/4060 8-10GB -- all models quantized, VLM optional
- **CPU-only**: No GPU -- OCR via CPU, embedding via ONNX, VLM disabled

**Implementation**:
- Quantize Marker, Chandra, and nomic models using AWQ or GPTQ
- Package as separate Docker images: `ocr-provenance-models:v1-full`, `v1-standard`, `v1-lite`
- Auto-detect GPU VRAM and select appropriate model variant

**Effort**: Medium (1-2 weeks). Model quantization + Docker image variants.

---

### 6.2 Parallel Processing Pipeline (HIGH)

**What**: Pipeline OCR, chunking, embedding, and VLM as concurrent stages rather than sequential, so that while page N is being OCR'd, page N-1 is being chunked, and page N-2 is being embedded.

**Why**: Current sequential processing means the GPU sits idle during chunking (CPU-bound) and the CPU sits idle during embedding (GPU-bound). Pipelining can achieve 2-3x throughput improvement on multi-page documents.

**Implementation**:
- Stream OCR results page-by-page to the chunking stage
- Stream chunks to the embedding stage as they're created
- Stream images to the VLM stage as they're extracted
- Coordinate via async queues in the TypeScript layer

**Effort**: Medium-High (2-3 weeks). Significant refactor of the processing pipeline.

---

### 6.3 Embedding Cache and Deduplication (MEDIUM)

**What**: Cache embedding vectors for identical text chunks across documents to avoid redundant GPU inference.

**Why**: When processing many similar documents (100 contracts from the same template), large portions of text are identical. Caching embeddings for seen text hashes eliminates redundant GPU work.

**Implementation**:
- Hash chunk text before embedding
- Check cache (SQLite table keyed by text hash) before sending to GPU
- On cache hit, reuse existing embedding vector
- Track cache hit rate in processing stats

**Effort**: Low (3-5 days).

---

### 6.4 DuckDB Analytics Layer (MEDIUM)

**What**: Add DuckDB as a read-only analytics engine alongside SQLite for complex analytical queries across large databases.

**Why**: DuckDB's SQLite scanner extension enables DuckDB to query SQLite tables directly with zero migration. DuckDB excels at aggregation, window functions, and analytical queries that SQLite struggles with. The pattern of "SQLite for durability, DuckDB for analysis" is becoming standard.

**Use cases**:
- Complex analytics across millions of chunks
- Cross-database aggregation
- Export to Parquet/CSV for external analysis
- Time-series analysis of processing metrics

**Effort**: Medium (1-2 weeks).

---

### 6.5 Streaming Ingestion API (MEDIUM)

**What**: Accept document streams (not just file paths) for processing, enabling direct upload from browsers, APIs, and cloud storage without staging to disk.

**Why**: The current upload endpoint stages to disk before processing. For large-scale integrations, streaming directly from S3/GCS/Azure Blob to the processing pipeline eliminates disk I/O and staging management.

**Effort**: Medium (1-2 weeks).

---

### 6.6 SGLang/vLLM Integration for VLM (LOW-MEDIUM)

**What**: Use SGLang or vLLM as the VLM inference backend instead of raw HuggingFace transformers, for significant throughput improvements.

**Why**: SGLang's RadixAttention achieves 85-95% cache hit rates for shared prefixes (your document prompts share long common prefixes). SGLang achieves 95-98% GPU utilization vs. raw transformers' ~35%. This could improve VLM throughput by 3-5x.

**Effort**: Medium (1-2 weeks). VLM worker refactor to use SGLang/vLLM API.

---

## 7. Security & Compliance

### 7.1 Confidential Computing Support (HIGH)

**What**: Document and test deployment on Azure Confidential VMs with NVIDIA H100 GPUs (AMD SEV-SNP + H100 TEE), providing hardware-enforced encryption of all data in memory during processing.

**Why**: Azure Confidential GPU VMs are now generally available. All code, model weights, prompts, and outputs remain encrypted in CPU memory and across the PCIe bus. This is the strongest possible proof that data cannot be accessed even by cloud administrators. For healthcare, financial, and government customers, this eliminates the "trust the cloud provider" concern entirely.

**Implementation**:
- Test and document deployment on `Standard_NCC40ads_H100_v5` VMs
- Add GPU attestation verification to healthcheck
- Document the security guarantees for enterprise sales

**Effort**: Low (3-5 days of testing and documentation).

---

### 7.2 Document Watermarking and Fingerprinting (MEDIUM)

**What**: Invisible forensic watermarking on exported documents that enables tracking of document distribution and detecting unauthorized sharing.

**Why**: EU AI Act mandates machine-readable markings on AI-generated outputs starting August 1, 2026. EchoMark, InvisMark, and Steg.AI provide the technology. For enterprise customers, watermarking exported documents enables leak detection.

**Implementation**:
- Add invisible watermark to exported PDFs/documents containing: export timestamp, user/session ID, database name
- Provide watermark verification tool
- Optional visible watermark ("Processed by OCR Provenance")

**New MCP tools**:
- `ocr_export` gains `watermark: boolean` parameter
- `ocr_watermark_verify` -- Check if a document contains a valid watermark

**Effort**: Medium (1-2 weeks).

---

### 7.3 Role-Based Access Control (RBAC) Enhancement (MEDIUM)

**What**: Enhance the existing user/role system with database-level and document-level permissions.

**Why**: Enterprise adoption requires granular access control. Current system has roles (viewer/reviewer/editor/admin) but they're not enforced at the database or document level. SOC 2 and ISO 27001 require role-based access controls.

**Implementation**:
- Database-level permissions: who can read/write/admin each database
- Document-level access control: restrict sensitive documents to specific users/roles
- Audit log every access control decision
- SSO integration (SAML 2.0 / OIDC) for enterprise identity providers

**Effort**: Medium-High (2-3 weeks).

---

### 7.4 Cosign Image Signing in CI/CD (LOW)

**What**: Sign Docker images with Cosign in the release pipeline and publish SBOM with every release.

**Why**: Already identified in the Air-Gap Verification Report as Phase 1 (0 cost, immediate impact). Enterprise security teams increasingly require image signatures and SBOMs. Cosign integration takes ~30 minutes in GitHub Actions.

**Effort**: Low (1-2 days).

---

### 7.5 Air-Gap Mode Toggle (LOW)

**What**: A single configuration flag that disables all network calls (billing, secrets bootstrap, Stripe) for fully air-gapped deployments with a site license.

**Why**: Already architecturally supported via `--network=none`, but needs a clean UX. Government and defense customers need a single toggle, not a Docker flag.

**Implementation**:
- `AIR_GAP_MODE=true` environment variable
- Disables billing (unlimited processing)
- Uses locally-generated secrets only
- Site license key injected via environment variable

**Effort**: Low (3-5 days).

---

## 8. Integration Ecosystem

### 8.1 Cloud Storage Connectors (HIGH)

**What**: Native ingestion from S3, GCS, Azure Blob, SharePoint, OneDrive, Google Drive, Box, and Dropbox -- without requiring files to be on the local filesystem.

**Why**: 40% of IDP implementations underperform due to extracted data stuck in silos. Enterprise documents live in cloud storage, not local filesystems. ChatGPT Enterprise added these connectors in June 2025. This is a top enterprise request.

**Implementation**:
- `ocr_ingest_files` accepts `source: "s3://bucket/path"` syntax
- Background connector downloads, stages, and processes
- Supports incremental sync (only process new/changed files)
- Credential management via environment variables or secrets

**New MCP tools**:
- `ocr_source_connect` -- Configure a cloud storage source
- `ocr_source_sync` -- Sync documents from a configured source
- `ocr_source_list` -- List configured sources and sync status

**Effort**: High (3-4 weeks). One connector per cloud storage service.

---

### 8.2 Webhook Event System (HIGH)

**What**: Enhance the existing webhook system to emit events for all document lifecycle stages, enabling integration with Zapier, Make, n8n, and Power Automate.

**Events to emit**:
- `document.ingested` -- New document registered
- `document.processing` -- OCR started
- `document.completed` -- Processing finished (with stats)
- `document.failed` -- Processing failed (with error)
- `search.alert` -- Saved search matched new document
- `pii.detected` -- PII found in document
- `classification.completed` -- Document classified

**Implementation**: Extend existing webhook infrastructure with more event types and a standardized payload format.

**Effort**: Low-Medium (1 week).

---

### 8.3 REST API with OpenAPI Spec (MEDIUM)

**What**: Expose core functionality as a documented REST API (in addition to MCP) with an OpenAPI/Swagger specification for non-MCP integrations.

**Why**: MCP is powerful but not universally supported. REST APIs are understood by every developer and tool. An OpenAPI spec enables code generation, Postman collections, and integration with any HTTP-capable system. This is essential for enterprise integrations.

**Implementation**:
- Map top 20 MCP tools to REST endpoints
- Generate OpenAPI 3.1 spec
- Serve Swagger UI from the dashboard
- Support API key authentication (existing X-License-Key header)

**Effort**: Medium (2 weeks).

---

### 8.4 Export to Business Systems (MEDIUM)

**What**: Export extracted data directly to CSV, Excel, JSON-LD, and common business system formats (QuickBooks CSV, SAP IDoc, Salesforce API).

**Why**: The "last mile" problem: extracting data is only valuable if it reaches the business system. Most users currently export to JSON and manually transform.

**Implementation**: Template-based export formatters that map extracted fields to target system schemas.

**Effort**: Medium (1-2 weeks per target system).

---

### 8.5 Slack/Teams Notifications (LOW)

**What**: Send processing status, alerts, and search results to Slack channels or Teams channels via incoming webhooks.

**Why**: Teams shouldn't have to check the dashboard for status updates. A Slack message saying "12 invoices processed, 2 failed (low scan quality), total: $45,678.90 extracted" is immediately actionable.

**Effort**: Low (3-5 days).

---

## 9. Vertical-Specific Features

### 9.1 Legal: Contract Intelligence Suite (HIGH)

**What**: Enhance existing contract tools (`ocr_contract_extract`, `ocr_obligation_list`, `ocr_playbook_compare`) into a full contract intelligence suite.

**Why**: CLM market exceeded $1.24B in 2025. Corporate legal AI adoption doubled from 23% to 54% in one year. Document review accounts for 80% of litigation spend ($42B/year).

**Additions**:
- **Clause library**: Extract and categorize clauses across all contracts (indemnification, limitation of liability, termination, force majeure)
- **Risk scoring**: Score contract risk based on deviations from playbook
- **Amendment tracking**: Automatically link amendments to master agreements
- **Deadline calendar**: Enhanced obligation calendar with email/webhook reminders
- **Comparison mode**: Side-by-side clause comparison between two contracts with difference highlighting
- **eDiscovery export**: Export in EDRM XML format for litigation support

**Effort**: Medium-High (2-3 weeks). Builds on existing contract tools.

---

### 9.2 Healthcare: Clinical Document Processing (MEDIUM)

**What**: HIPAA-compliant document processing with automatic PII redaction, medical terminology extraction, and structured output for clinical documents.

**Why**: Healthcare IDP is the fastest-growing segment. AI achieves 20-30% cost reduction in claims processing. 41% of providers reported denial rates of 10%+ in 2025.

**Features**:
- Auto-detect medical documents (lab reports, discharge summaries, prescriptions, insurance forms)
- Extract structured medical data (ICD codes, CPT codes, medications, dosages)
- HIPAA-compliant processing with automatic PHI detection
- Integration with FHIR format for EHR systems

**Effort**: High (3-4 weeks). Requires medical NER model and domain templates.

---

### 9.3 Finance: Invoice and Financial Document Processing (MEDIUM)

**What**: Turnkey invoice processing with field extraction, three-way matching (PO-invoice-receipt), and export to accounting systems.

**Why**: AP automation market is $6.94B growing to $12.46B by 2031. Manual invoice processing costs $12.88-$22.75 per invoice; AI reduces this to $2.36-$4.00 (76-80% reduction). Only 8% of AP departments are fully automated.

**Features**:
- Pre-built invoice extraction template (vendor, amount, date, PO number, line items, tax)
- Three-way matching: link invoices to POs and receipts
- Duplicate invoice detection (beyond file hash -- content-level matching)
- Export to QuickBooks CSV, Xero, SAP formats
- Spending analytics dashboard

**Effort**: Medium (2-3 weeks). Extraction template + matching logic + export formats.

---

### 9.4 Real Estate: Lease Abstraction (LOW-MEDIUM)

**What**: Automated lease abstraction that extracts key terms from commercial leases (parties, premises, rent schedule, term, renewal options, operating expenses, insurance requirements).

**Why**: Traditional lease abstraction takes 4-8 hours per lease; AI reduces this to 7 minutes. ASC 842 and IFRS 16 compliance is driving demand. Few local/on-premise tools offer this.

**Implementation**: Extraction template + specialized prompts for lease document structure.

**Effort**: Low-Medium (1 week). Template + prompts.

---

### 9.5 Research: Academic Paper Processing (LOW-MEDIUM)

**What**: Extract structured metadata from research papers (title, authors, abstract, sections, citations, tables, figures, methodology, results) and build citation graphs.

**Why**: 91.2% of academics use AI tools but lack specialized document processing. Elicit and Consensus search 125M+ papers but don't offer local processing. Citation graph construction enables research discovery workflows.

**Implementation**: Extraction template for academic papers + citation extraction + citation graph storage.

**Effort**: Low-Medium (1 week).

---

## Implementation Priority Matrix

### Phase 1: Immediate Impact (0-30 days)

| # | Improvement | Category | Effort | Impact |
|---|-----------|----------|--------|--------|
| 1 | Chandra OCR 2 upgrade | Pipeline | Low-Medium | CRITICAL |
| 2 | MCP marketplace optimization | Adoption | Low | CRITICAL |
| 3 | Cosign image signing + SBOM | Security | Low | HIGH |
| 4 | Air-gap mode toggle | Security | Low | HIGH |
| 5 | Matryoshka embedding support | Search | Low | MEDIUM |
| 6 | Embedding cache/dedup | Performance | Low | MEDIUM |
| 7 | Onboarding wizard | UX | Medium | HIGH |
| 8 | CLI experience polish | Adoption | Low-Medium | MEDIUM |
| 9 | Dark mode | UX | Low | LOW |
| 10 | Saved search alerts + webhooks | Search | Low | LOW |

### Phase 2: Competitive Moat (30-90 days)

| # | Improvement | Category | Effort | Impact |
|---|-----------|----------|--------|--------|
| 11 | Temporal knowledge graph | Intelligence | High | CRITICAL |
| 12 | ColPali visual retrieval | Search | High | CRITICAL |
| 13 | Interactive document viewer | UX | High | CRITICAL |
| 14 | Auto PII detection/redaction | Intelligence | Medium | HIGH |
| 15 | Auto document classification | Intelligence | Medium | HIGH |
| 16 | Three-way hybrid retrieval (SPLADE) | Search | Medium | HIGH |
| 17 | Real-time processing feedback | UX | Medium | HIGH |
| 18 | Structured extraction templates | Pipeline | Medium-High | HIGH |
| 19 | Dashboard redesign | UX | High | HIGH |
| 20 | Webhook event system | Integration | Low-Medium | HIGH |

### Phase 3: Market Expansion (90-180 days)

| # | Improvement | Category | Effort | Impact |
|---|-----------|----------|--------|--------|
| 21 | Model quantization (smaller GPUs) | Performance | Medium | HIGH |
| 22 | Cloud storage connectors | Integration | High | HIGH |
| 23 | Contract intelligence suite | Vertical | Medium-High | HIGH |
| 24 | Invoice processing | Vertical | Medium | HIGH |
| 25 | Plugin/extension ecosystem | Adoption | High | HIGH |
| 26 | REST API + OpenAPI spec | Integration | Medium | MEDIUM |
| 27 | Parallel processing pipeline | Performance | Medium-High | HIGH |
| 28 | Handwriting recognition | Pipeline | Medium | MEDIUM |
| 29 | Cross-document summarization | Intelligence | Low-Medium | MEDIUM |
| 30 | RBAC enhancement + SSO | Security | Medium-High | MEDIUM |

### Phase 4: Enterprise Scale (180-360 days)

| # | Improvement | Category | Effort | Impact |
|---|-----------|----------|--------|--------|
| 31 | Free tier / playground | Adoption | Medium | HIGH |
| 32 | Healthcare clinical processing | Vertical | High | MEDIUM |
| 33 | Confidential computing docs | Security | Low | HIGH |
| 34 | SGLang/vLLM VLM backend | Performance | Medium | MEDIUM |
| 35 | DuckDB analytics layer | Performance | Medium | MEDIUM |
| 36 | Document watermarking | Security | Medium | MEDIUM |
| 37 | Model routing/cascading | Pipeline | Medium | MEDIUM |
| 38 | Multi-language detection | Pipeline | Low-Medium | MEDIUM |
| 39 | Document relationship discovery | Intelligence | Medium | MEDIUM |
| 40 | Real estate lease abstraction | Vertical | Low-Medium | LOW-MEDIUM |
| 41 | Academic paper processing | Vertical | Low-Medium | LOW-MEDIUM |
| 42 | Incremental/delta processing | Pipeline | Medium | MEDIUM |
| 43 | Export to business systems | Integration | Medium | MEDIUM |
| 44 | Slack/Teams notifications | Integration | Low | LOW |
| 45 | Streaming ingestion API | Performance | Medium | MEDIUM |
| 46 | Community templates library | Adoption | Medium | MEDIUM |
| 47 | Video tutorials | Adoption | Medium | MEDIUM |

---

## Competitive Positioning Summary

### Current Strengths (Preserve and Amplify)

| Capability | Your Position | Nearest Competitor |
|-----------|--------------|-------------------|
| 100% local GPU processing | UNIQUE | Hyperscience (cloud GPU) |
| `--network=none` air-gap proof | UNIQUE | No competitor offers this |
| SHA-256 provenance chain | UNIQUE | No competitor has hash-chain integrity |
| 153 MCP tools | MARKET-LEADING | LlamaParse (limited MCP) |
| $0.03/file self-hosted | 10-167x CHEAPER | Mistral OCR ($2/1K pages) |
| Open source + source-available | STRONG | ABBYY/Hyperscience are proprietary |
| HIPAA/SOC 2/SOX compliance exports | STRONG | Hyperscience (FedRAMP), ABBYY (SOC 2) |

### Key Gaps to Close

| Capability | Gap | Priority |
|-----------|-----|----------|
| Knowledge graph / entity extraction | No entity or relationship layer | CRITICAL |
| Visual document retrieval (ColPali) | Only text-based embeddings | CRITICAL |
| Interactive document viewer | Basic viewer, no annotations | CRITICAL |
| PII detection/redaction | No automated PII handling | HIGH |
| Document classification | No auto-classification | HIGH |
| Structured extraction templates | No pre-built templates | HIGH |
| Cloud storage connectors | Local files only | HIGH |
| Smaller GPU support | Requires 30GB+ VRAM | HIGH |
| Handwriting recognition | Limited via Marker-pdf | MEDIUM |
| REST API + OpenAPI | MCP-only interface | MEDIUM |

---

## Market Opportunity Sizing

| Vertical | Market Size (2026) | Addressable with Improvements | Key Features Needed |
|----------|-------------------|-------------------------------|-------------------|
| BFSI (Invoice/KYC) | $6.94B (AP alone) | $200M-500M (on-premise segment) | Invoice templates, KYC extraction, audit trails |
| Legal (CLM/eDiscovery) | $1.24B (CLM) + $32.54B (eDiscovery) | $100M-300M | Contract intelligence, clause library, EDRM export |
| Healthcare | Fastest CAGR segment | $100M-250M | HIPAA compliance, medical NER, PHI redaction |
| Government | $500M+ (records management) | $50M-150M | Air-gap mode, FOIA processing, FedRAMP path |
| Real Estate | Growing (ASC 842 driver) | $20M-50M | Lease abstraction templates |
| SMEs (all verticals) | Underserved, accessible pricing | $50M-100M | Quantized models, simple UX, templates |

**Total addressable with recommended improvements: $500M-1.3B**

---

## Key Research Sources

### Market & Competitive
- Gartner Magic Quadrant for IDP (October 2025) -- ABBYY, Hyperscience, Infrrd, Tungsten, UiPath named Leaders
- Precedence Research: IDP market $3.22B (2025) to $43.92B (2034) at 33.68% CAGR
- Reducto: $108M Series B (Feb 2026, a16z), 1B+ pages processed
- Mistral OCR 3: 74% win rate, $2/1K pages, 88.9% handwriting accuracy

### Technology
- Microsoft GraphRAG: 12M nodes, 89M relationships in production
- Zep/Graphiti: 94.8% on DMR benchmark, temporal knowledge graphs
- ColPali/ColQwen: ViDoRe benchmark for visual document retrieval
- NVIDIA Nemotron ColEmbed V2: #1 on ViDoRe V3 (NDCG@10 = 63.42)
- IBM: Three-way hybrid retrieval (BM25 + dense + sparse) is optimal
- SGLang: 85-95% KV cache hit rates via RadixAttention
- Azure Confidential GPU VMs with H100 (GA 2025)
- Intel Heracles FHE chip: 1,074-5,547x speedup

### UX & Adoption
- Cursor: $2B ARR, 360K paying customers via pure PLG
- Supabase: 1M to 4.5M developers in under a year
- MCP ecosystem: 97M monthly SDK downloads, 5,800+ servers
- 15-Minute Rule: activation and retention plummet without quick time-to-value
- Gartner: teams with high-quality DX are 33% more likely to hit business outcomes

### User Pain Points (from G2, HackerNews, Reddit)
- Accuracy degrades outside lab conditions (95% -> 85% on real documents)
- Pricing opacity and complexity
- Confidence score unreliability
- Integration breaks the last mile
- Exception handling is an afterthought
- Steep learning curves for enterprise platforms
- Benchmarks don't reflect real automation rates
