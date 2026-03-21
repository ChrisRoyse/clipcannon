# AI Agent Tool Landscape Analysis

## Date: 2026-02-21
## Analyst: Code Analyzer Agent (claude-opus-4-6)
## Scope: All 22 tool files + shared.ts in /home/cabdru/datalab/src/tools/

---

## 1. Executive Summary

The OCR Provenance MCP system exposes **124 tools** (the MEMORY.md says 124; the constitution says 127 -- the discrepancy itself is a finding) to AI agents through a single flat namespace. This analysis reveals **systemic problems** that degrade agent performance:

1. **Catastrophic parameter overload**: The three search tools have 27/26/29 parameters respectively. This is the single biggest agent UX failure in the system. An agent seeing 29 parameters on `ocr_search_hybrid` will either hallucinate parameter values or avoid the tool entirely.

2. **Tool count exceeds cognitive capacity**: 124 tools in a flat list far exceeds what any LLM-based agent can reason about effectively. Research on MCP tool selection shows degradation above ~20 tools. The `ocr_guide` tool helps but is optional -- agents will still see all 124 in the tool list.

3. **Massive parameter duplication across search tools**: 24 parameters are copy-pasted identically across `ocr_search`, `ocr_search_semantic`, and `ocr_search_hybrid`. A unified search tool with a `mode` parameter would eliminate ~50 duplicated parameter definitions.

4. **Functional overlap**: At least 5 clusters of tools do substantially the same thing (detailed below), confusing agents about which to use.

5. **Inconsistent next_steps**: Only 6 of 22 tool files include `next_steps` guidance. The other 16 files return results without telling the agent what to do next, breaking the navigation flow.

6. **Tier tags add noise without enforcing behavior**: The 5-tier system ([CORE], [ADMIN], [SEARCH], [ANALYSIS], [PROCESSING]) is a flat label prefix that agents cannot act on programmatically. ADMIN has 45 tools (36% of all tools) -- it is not a useful discriminator.

### Key Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Total tools | 124 | Far too many for effective agent navigation |
| Tools with >10 params | 3 (search tools) | Critical overload |
| Tools with >5 params | ~15 | High friction |
| Duplicate parameter sets | ~50 params across 3 search tools | Massive redundancy |
| Tool files with next_steps | 6/22 (27%) | Inconsistent navigation |
| Functional overlaps found | 5 clusters | Consolidation needed |
| Tier: CORE tools | 15 | Reasonable core set |
| Tier: ADMIN tools | 45 | Too broad -- not a useful category |
| Tier: SEARCH tools | 9 | Appropriate |
| Tier: ANALYSIS tools | 34 | Too broad |
| Tier: PROCESSING tools | 21 | Appropriate |

---

## 2. Complete Tool Inventory

### 2.1 Database Tools (database.ts) -- 5 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_db_create | ADMIN | 1 (name) | 2 | 3 | No | Create a new database |
| ocr_db_list | CORE | 0 | 1 | 1 | No | List available databases |
| ocr_db_select | CORE | 1 (database_name) | 0 | 1 | **Yes** | Switch active database |
| ocr_db_stats | CORE | 0 | 1 | 1 | No | Get database statistics |
| ocr_db_delete | ADMIN | 2 (database_name, confirm) | 0 | 2 | No | Delete a database |

### 2.2 Ingestion Tools (ingestion.ts) -- 9 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_ingest_directory | PROCESSING | 1 (directory_path) | 2 | 3 | No | Bulk ingest from directory |
| ocr_ingest_files | PROCESSING | 1 (file_paths) | 0 | 1 | No | Ingest specific files |
| ocr_process_pending | PROCESSING | 0 | 7 | 7 | **Partial** | Run OCR pipeline |
| ocr_status | ADMIN | 0 | 2 | 2 | No | Check processing status |
| ocr_chunk_complete | PROCESSING | 0 | 0 | 0 | No | Fix missing chunks/embeddings |
| ocr_retry_failed | PROCESSING | 0 | 1 | 1 | No | Reset failed docs |
| ocr_reprocess | PROCESSING | 1 (document_id) | 2 | 3 | No | Re-run OCR |
| ocr_convert_raw | PROCESSING | 1 (file_path) | 3 | 4 | No | One-off OCR without DB |
| ocr_reembed_document | PROCESSING | 1 (document_id) | 1 | 2 | No | Regenerate embeddings |

### 2.3 Search Tools (search.ts) -- 12 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| **ocr_search** | SEARCH | 1 (query) | **26** | **27** | No | BM25 keyword search |
| **ocr_search_semantic** | SEARCH | 1 (query) | **25** | **26** | No | Vector similarity search |
| **ocr_search_hybrid** | CORE | 1 (query) | **28** | **29** | **Yes** | Combined BM25+semantic |
| ocr_fts_manage | ADMIN | 1 (action) | 0 | 1 | No | Rebuild/check FTS index |
| ocr_search_export | SEARCH | 2 (query, output_path) | 3 | 5 | No | Export search results |
| ocr_benchmark_compare | SEARCH | 2 (query, database_names) | 2 | 4 | No | Compare across databases |
| ocr_rag_context | CORE | 1 (question) | 3 | 4 | No | RAG context assembly |
| ocr_search_save | SEARCH | varies | varies | varies | No | Save search results |
| ocr_search_saved_list | SEARCH | 0 | varies | varies | No | List saved searches |
| ocr_search_saved_get | SEARCH | 1 (id) | 0 | 1 | No | Get saved search |
| ocr_search_saved_execute | SEARCH | 1 (id) | 0 | 1 | No | Re-run saved search |
| ocr_search_cross_db | SEARCH | 1 (query) | varies | varies | No | Cross-database search |

### 2.4 Document Tools (documents.ts) -- 12 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_document_list | CORE | 0 | 5 | 5 | **Yes** | Browse documents |
| ocr_document_get | CORE | 1 (document_id) | 4 | 5 | **Yes** | Get document details |
| ocr_document_delete | ADMIN | 2 (document_id, confirm) | 0 | 2 | No | Delete document |
| ocr_document_find_similar | ANALYSIS | 1 (document_id) | varies | varies | No | Find similar documents |
| ocr_document_structure | CORE | 1 (document_id) | varies | varies | No | Get document outline |
| ocr_document_update_metadata | ANALYSIS | varies | varies | varies | No | Update metadata |
| ocr_document_duplicates | ANALYSIS | 0 | varies | varies | No | Find duplicates |
| ocr_document_sections | CORE | 1 (document_id) | varies | varies | No | Get TOC |
| ocr_document_export | ADMIN | 1 (document_id) | varies | varies | No | Export document data |
| ocr_corpus_export | ADMIN | 0 | varies | varies | No | Export corpus |
| ocr_document_versions | ANALYSIS | 1 (file_path) | 0 | 1 | No | List document versions |
| ocr_document_workflow | ANALYSIS | varies | varies | varies | No | Manage workflow states |

### 2.5 Provenance Tools (provenance.ts) -- 6 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_provenance_get | ANALYSIS | 1 (item_id) | 1 | 2 | No | Get provenance chain |
| ocr_provenance_verify | ANALYSIS | 1 (item_id) | 2 | 3 | No | Verify integrity |
| ocr_provenance_export | ADMIN | 1 (scope) | 2 | 3 | No | Export provenance |
| ocr_provenance_query | ANALYSIS | 0 | 12 | 12 | No | Query provenance records |
| ocr_provenance_timeline | ANALYSIS | 1 (document_id) | 1 | 2 | No | Document timeline |
| ocr_provenance_processor_stats | ADMIN | 0 | 3 | 3 | No | Processor analytics |

### 2.6 Config Tools (config.ts) -- 2 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_config_get | ADMIN | 0 | 1 | 1 | No | View configuration |
| ocr_config_set | ADMIN | 2 (key, value) | 0 | 2 | No | Change configuration |

### 2.7 VLM Tools (vlm.ts) -- 6 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_vlm_describe | PROCESSING | 1 (image_path) | 2 | 3 | No | Describe single image |
| ocr_vlm_classify | PROCESSING | 1 (image_path) | 0 | 1 | No | Classify image |
| ocr_vlm_process_document | PROCESSING | 1 (document_id) | 1 | 2 | No | Process document images |
| ocr_vlm_process_pending | PROCESSING | 0 | 1 | 1 | No | Bulk process pending |
| ocr_vlm_analyze_pdf | PROCESSING | 1 (pdf_path) | 1 | 2 | No | Direct PDF analysis |
| ocr_vlm_status | ADMIN | 0 | 0 | 0 | No | VLM service health |

### 2.8 Image Tools (images.ts) -- 11 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_image_extract | PROCESSING | 4 (pdf_path, output_dir, document_id, ocr_result_id) | 2 | 6 | No | Extract images from PDF |
| ocr_image_list | ANALYSIS | 1 (document_id) | 2 | 3 | No | List document images |
| ocr_image_get | ANALYSIS | 1 (image_id) | 0 | 1 | No | Get image details |
| ocr_image_stats | ADMIN | 0 | 0 | 0 | No | Image statistics |
| ocr_image_delete | ADMIN | 1 (image_id) | 1 | 2 | No | Delete image |
| ocr_image_delete_by_document | ADMIN | 1 (document_id) | 1 | 2 | No | Delete document images |
| ocr_image_reset_failed | PROCESSING | 0 | 1 | 1 | No | Reset failed images |
| ocr_image_pending | ADMIN | 0 | 1 | 1 | No | List pending images |
| ocr_image_search | ANALYSIS | 0 | 8 | 8 | No | Search images by metadata |
| ocr_image_semantic_search | ANALYSIS | 1 (query) | 3 | 4 | No | Semantic image search |
| ocr_image_reanalyze | PROCESSING | 1 (image_id) | 2 | 3 | No | Re-run VLM on image |

### 2.9 Evaluation Tools (evaluation.ts) -- 3 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_evaluate_single | ADMIN | 1 (image_id) | 1 | 2 | No | Evaluate single image |
| ocr_evaluate_document | ADMIN | 1 (document_id) | 1 | 2 | No | Evaluate document images |
| ocr_evaluate_pending | ADMIN | 0 | 2 | 2 | No | Bulk evaluate |

### 2.10 Extraction Tools (extraction.ts) -- 3 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_extract_images | PROCESSING | 1 (document_id) | 5 | 6 | No | Extract images (PyMuPDF) |
| ocr_extract_images_batch | PROCESSING | 0 | 5 | 5 | No | Bulk extract images |
| ocr_extraction_check | ADMIN | 0 | 0 | 0 | No | Check Python deps |

### 2.11 Reports Tools (reports.ts) -- 9 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_evaluation_report | ADMIN | 0 | 2 | 2 | No | Evaluation report |
| ocr_document_report | ADMIN | 1 (document_id) | 0 | 1 | No | Document report |
| ocr_quality_summary | ADMIN | 0 | 0 | 0 | No | Quality summary |
| ocr_cost_summary | ADMIN | 0 | 1 | 1 | No | Cost analytics |
| ocr_pipeline_analytics | ADMIN | 0 | 2 | 2 | No | Pipeline performance |
| ocr_corpus_profile | ADMIN | 0 | 3 | 3 | No | Corpus profile |
| ocr_error_analytics | ADMIN | 0 | 2 | 2 | No | Error analytics |
| ocr_provenance_bottlenecks | ADMIN | 0 | 0 | 0 | No | Processing bottlenecks |
| ocr_quality_trends | ADMIN | 0 | 4 | 4 | No | Quality trends |

### 2.12 Form Fill Tools (form-fill.ts) -- 2 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_form_fill | ADMIN | varies | varies | varies | No | Fill PDF form |
| ocr_form_fill_status | ADMIN | varies | varies | varies | No | Check form fill status |

### 2.13 Structured Extraction Tools (extraction-structured.ts) -- 4 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_extract_structured | PROCESSING | varies | varies | varies | No | Extract structured data |
| ocr_extraction_list | ADMIN | varies | varies | varies | No | List extractions |
| ocr_extraction_get | ADMIN | varies | varies | varies | No | Get extraction |
| ocr_extraction_search | ADMIN | varies | varies | varies | No | Search extractions |

### 2.14 File Management Tools (file-management.ts) -- 6 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_file_upload | ADMIN | varies | varies | varies | **Yes** | Upload to Datalab |
| ocr_file_list | ADMIN | varies | varies | varies | No | List uploaded files |
| ocr_file_get | ADMIN | varies | varies | varies | No | Get file metadata |
| ocr_file_download | ADMIN | varies | varies | varies | No | Get download URL |
| ocr_file_delete | ADMIN | varies | varies | varies | No | Delete uploaded file |
| ocr_file_ingest_uploaded | PROCESSING | varies | varies | varies | No | Ingest uploaded files |

### 2.15 Comparison Tools (comparison.ts) -- 6 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_document_compare | ANALYSIS | varies | varies | varies | No | Compare two documents |
| ocr_comparison_list | ANALYSIS | varies | varies | varies | No | List comparisons |
| ocr_comparison_get | ANALYSIS | varies | varies | varies | No | Get comparison |
| ocr_comparison_discover | ANALYSIS | varies | varies | varies | No | Find similar pairs |
| ocr_comparison_batch | ANALYSIS | varies | varies | varies | No | Batch compare |
| ocr_comparison_matrix | ANALYSIS | varies | varies | varies | No | NxN similarity matrix |

### 2.16 Clustering Tools (clustering.ts) -- 7 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_cluster_documents | PROCESSING | varies | varies | varies | No | Cluster documents |
| ocr_cluster_list | ANALYSIS | varies | varies | varies | No | List clusters |
| ocr_cluster_get | ANALYSIS | varies | varies | varies | No | Get cluster |
| ocr_cluster_assign | ANALYSIS | varies | varies | varies | No | Assign to cluster |
| ocr_cluster_delete | ANALYSIS | varies | varies | varies | No | Delete clusters |
| ocr_cluster_reassign | ANALYSIS | varies | varies | varies | No | Move to cluster |
| ocr_cluster_merge | ANALYSIS | varies | varies | varies | No | Merge clusters |

### 2.17 Chunk Tools (chunks.ts) -- 4 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_chunk_get | CORE | 1 (chunk_id) | varies | varies | No | Get chunk |
| ocr_chunk_list | CORE | 1 (document_id) | varies | varies | No | List chunks |
| ocr_chunk_context | CORE | 1 (chunk_id) | varies | varies | No | Get surrounding chunks |
| ocr_document_page | CORE | 1 (document_id) + 1 (page) | varies | varies | No | Read page |

### 2.18 Embedding Tools (embeddings.ts) -- 4 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_embedding_list | ADMIN | 0 | 5 | 5 | No | Browse embeddings |
| ocr_embedding_stats | ADMIN | 0 | 1 | 1 | No | Embedding coverage |
| ocr_embedding_get | ADMIN | 1 (embedding_id) | 1 | 2 | No | Inspect embedding |
| ocr_embedding_rebuild | ADMIN | 0 (one of 3 required) | 3 | 3 | No | Regenerate embeddings |

### 2.19 Timeline Tools (timeline.ts) -- 2 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_timeline_analytics | ADMIN | 0 | 4 | 4 | No | Volume trends |
| ocr_throughput_analytics | ADMIN | 0 | 3 | 3 | No | Throughput metrics |

### 2.20 Tag Tools (tags.ts) -- 6 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_tag_create | ANALYSIS | 1 (name) | 2 | 3 | No | Create tag |
| ocr_tag_list | ANALYSIS | 0 | 0 | 0 | No | List tags |
| ocr_tag_apply | ANALYSIS | 3 (tag_name, entity_id, entity_type) | 0 | 3 | No | Apply tag |
| ocr_tag_remove | ANALYSIS | 3 (tag_name, entity_id, entity_type) | 0 | 3 | No | Remove tag |
| ocr_tag_search | ANALYSIS | 1 (tags) | 2 | 3 | No | Search by tag |
| ocr_tag_delete | ANALYSIS | 2 (tag_name, confirm) | 0 | 2 | No | Delete tag |

### 2.21 Intelligence Tools (intelligence.ts) -- 4 tools

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_guide | CORE | 0 | 1 (intent) | 1 | **Yes** (rich) | System state + guidance |
| ocr_document_tables | ANALYSIS | 1 (document_id) | 1 | 2 | No | Extract table data |
| ocr_document_recommend | ANALYSIS | 1 (document_id) | 1 | 2 | No | Related documents |
| ocr_document_extras | ANALYSIS | 1 (document_id) | 1 | 2 | No | OCR extras data |

### 2.22 Health Tools (health.ts) -- 1 tool

| Tool | Tier | Req Params | Opt Params | Total | next_steps | Description |
|------|------|-----------|-----------|-------|------------|-------------|
| ocr_health_check | CORE | 0 | varies | varies | No | Data integrity check |

---

## 3. Redundancy Map

### 3.1 CRITICAL: Three Nearly-Identical Search Tools

**ocr_search, ocr_search_semantic, ocr_search_hybrid**

These three tools share **24 identical parameters** (copy-pasted). They differ only in:
- `ocr_search`: adds `phrase_search`, `include_highlight` (2 unique params)
- `ocr_search_semantic`: adds `similarity_threshold` (1 unique param)
- `ocr_search_hybrid`: adds `bm25_weight`, `semantic_weight`, `rrf_k`, `auto_route` (4 unique params)

The description of `ocr_search_hybrid` already says "Prefer this over ocr_search or ocr_search_semantic" -- the system itself acknowledges the other two are secondary.

**Recommendation**: Merge into a single `ocr_search` tool with a `mode` parameter (`keyword`, `semantic`, `hybrid` defaulting to `hybrid`). This eliminates ~50 duplicate parameter definitions and removes 2 tools from the namespace. Agent gets one clear search entry point.

### 3.2 Embedding Regeneration Overlap

**ocr_reembed_document** (ingestion.ts) vs **ocr_embedding_rebuild** (embeddings.ts)

Both regenerate embeddings for a document. The key differences:
- `ocr_reembed_document`: Takes `document_id` + `include_vlm`, deletes ALL embeddings (chunk + VLM), requires doc status "complete"
- `ocr_embedding_rebuild`: Takes one of `document_id`/`chunk_id`/`image_id`, only deletes chunk embeddings when given document_id, does NOT handle VLM

An agent asked to "regenerate embeddings for this document" would reasonably try either tool and get different behavior.

**Recommendation**: Merge into `ocr_embedding_rebuild` with an `include_vlm` parameter. Remove `ocr_reembed_document`.

### 3.3 Document Similarity Overlap

**ocr_document_find_similar** vs **ocr_comparison_discover** vs **ocr_comparison_matrix**

All three compute document-level cosine similarity from embeddings:
- `ocr_document_find_similar`: Single source doc -> ranked similar docs (centroid approach)
- `ocr_comparison_discover`: All pairs above threshold, excludes already-compared pairs
- `ocr_comparison_matrix`: Full NxN matrix

These are genuinely different operations but an agent cannot easily distinguish them.

**Recommendation**: Keep all three but improve descriptions to clearly distinguish use cases. Add cross-references in descriptions.

### 3.4 Document Structure / TOC Overlap

**ocr_document_structure** vs **ocr_document_sections**

Both return document outline/structure:
- `ocr_document_structure`: Returns headings, tables, figures, code blocks with page numbers
- `ocr_document_sections`: Returns hierarchical TOC with heading levels, chunk ranges, outline format

Very confusing for agents. The difference is subtle (structure = content type map, sections = heading hierarchy).

**Recommendation**: Merge into `ocr_document_structure` with a `format` parameter (`structure` or `toc`). Remove `ocr_document_sections`.

### 3.5 Image Extraction Overlap

**ocr_image_extract** (images.ts) vs **ocr_extract_images** (extraction.ts)

The description of `ocr_image_extract` literally says "Prefer ocr_extract_images for file-based extraction." This is actively confusing:
- `ocr_image_extract`: Uses Datalab OCR pipeline, needs pdf_path + ocr_result_id
- `ocr_extract_images`: Uses PyMuPDF/python-docx, needs document_id, works post-OCR

**Recommendation**: Rename `ocr_image_extract` to `ocr_image_extract_datalab` or deprecate it. The description currently steers agents away from it.

### 3.6 Report/Analytics Overlap

Nine report tools with overlapping concerns:

| Tool | What it reports |
|------|----------------|
| ocr_evaluation_report | OCR + VLM metrics (saves to file) |
| ocr_document_report | Single doc detailed report |
| ocr_quality_summary | Aggregate quality scores |
| ocr_cost_summary | Cost analytics |
| ocr_pipeline_analytics | Pipeline performance |
| ocr_corpus_profile | Corpus overview |
| ocr_error_analytics | Error breakdowns |
| ocr_provenance_bottlenecks | Processing bottlenecks |
| ocr_quality_trends | Quality over time |

Plus overlap with:
- `ocr_db_stats` (also returns quality stats, cluster info, recent docs)
- `ocr_timeline_analytics` (also returns processing volume trends)
- `ocr_throughput_analytics` (also returns processing speed)

An agent wanting "give me an overview of this database" could reasonably call `ocr_db_stats`, `ocr_corpus_profile`, `ocr_quality_summary`, or `ocr_pipeline_analytics`. There is no guidance on which one to use.

**Recommendation**: Consolidate into 3 report tools:
1. `ocr_report_overview` (merges db_stats overview, corpus_profile, quality_summary)
2. `ocr_report_performance` (merges pipeline_analytics, throughput_analytics, provenance_bottlenecks)
3. `ocr_report_document` (keeps document_report as-is)

Move cost_summary, error_analytics, quality_trends, evaluation_report, timeline_analytics into parameters of the above.

### 3.7 Saved Search CRUD Overhead

**ocr_search_save, ocr_search_saved_list, ocr_search_saved_get, ocr_search_saved_execute**

Four tools for a feature (saved searches) that most agents will never use. These add 4 tools to the namespace for a marginal feature.

**Recommendation**: Merge into 2 tools: `ocr_search_save` and `ocr_search_saved` (with action parameter: list/get/execute).

### 3.8 Document Get vs Document Report

**ocr_document_get** (with include_text, include_chunks, include_blocks, include_full_provenance) vs **ocr_document_report**

`ocr_document_get` with all flags enabled returns nearly the same information as `ocr_document_report`.

**Recommendation**: `ocr_document_report` should be documented as "aggregate report with images, extractions, comparisons, clusters" to differentiate from the raw data in `ocr_document_get`.

---

## 4. Simplification Recommendations

### Priority 1: Search Tool Unification (HIGH IMPACT)

**Current**: 3 tools x ~27 params each = 82 parameter definitions
**Proposed**: 1 tool with mode parameter + shared params = ~32 parameter definitions

```
ocr_search (unified)
  mode: 'keyword' | 'semantic' | 'hybrid' (default: 'hybrid')
  query: string (required)
  limit: number (default: 10)
  -- Mode-specific (shown contextually) --
  phrase_search: boolean (keyword only)
  similarity_threshold: number (semantic only)
  bm25_weight: number (hybrid only)
  semantic_weight: number (hybrid only)
  rrf_k: number (hybrid only)
  auto_route: boolean (hybrid only)
  -- Common filters --
  document_filter: string[]
  metadata_filter: { doc_title, doc_author, doc_subject }
  cluster_id: string
  content_type_filter: string[]
  page_range_filter: { min_page, max_page }
  section_path_filter: string
  heading_filter: string
  -- Advanced (rarely used) --
  expand_query: boolean
  rerank: boolean
  min_quality_score: number
  quality_boost: boolean
  include_provenance: boolean
  include_cluster_context: boolean
  include_context_chunks: number
  exclude_duplicate_chunks: boolean
  is_atomic_filter: boolean
  heading_level_filter: { min_level, max_level }
  min_page_count: number
  max_page_count: number
  table_columns_contain: string
  include_headers_footers: boolean
  group_by_document: boolean
  include_document_context: boolean
```

Even with all params listed, the agent sees ONE tool instead of THREE. The `mode` parameter provides the only decision point.

### Priority 2: Parameter Pruning on Search Tools (HIGH IMPACT)

Many search parameters have sensible defaults that should ALWAYS be on:

| Parameter | Current Default | Recommended | Reasoning |
|-----------|----------------|-------------|-----------|
| include_highlight | true | Remove param, always true | No agent wants results without highlights |
| include_cluster_context | true | Remove param, always true | Already defaults to true |
| include_headers_footers | false | Remove param, always false | Almost never wanted |
| quality_boost | false | Change default to true | Quality-weighted results are always better |
| expand_query | false (keyword/semantic), true (hybrid) | Always true | No downside; was added for a reason |
| exclude_duplicate_chunks | false | Change default to true | Duplicates waste context window |

This removes 4-6 parameters from the schema that agents never need to think about.

### Priority 3: Merge Redundant Tools (MEDIUM IMPACT)

| Merge | From | Into | Tools Removed |
|-------|------|------|---------------|
| Search unification | ocr_search, ocr_search_semantic | ocr_search_hybrid (renamed ocr_search) | 2 |
| Embedding rebuild | ocr_reembed_document | ocr_embedding_rebuild | 1 |
| Document structure | ocr_document_sections | ocr_document_structure | 1 |
| Saved search | ocr_search_saved_list/get/execute | ocr_search_saved (with action) | 2 |
| **Total tools removed** | | | **6** |

### Priority 4: Tool Removal Candidates (LOW RISK)

Tools that are rarely needed and add namespace clutter:

| Tool | Reason for removal | Alternative |
|------|-------------------|-------------|
| ocr_image_extract | Description says "prefer ocr_extract_images" | ocr_extract_images |
| ocr_extraction_check | Only checks if Python deps are installed | ocr_health_check |
| ocr_vlm_classify | Quick classification; ocr_vlm_describe is superior | ocr_vlm_describe |
| ocr_chunk_complete | Fixes edge case; health_check can do this | ocr_health_check with fix=true |

### Summary of Reductions

| Category | Current | After Changes |
|----------|---------|---------------|
| Total tools | 124 | ~114 (-10) |
| Max params on any tool | 29 | ~32 (but only 1 tool, not 3) |
| Search tools | 12 | 8 |
| Duplicate param definitions | ~50 | 0 |

---

## 5. Parameter Cleanup Recommendations

### 5.1 Search Tool Parameters (Critical)

The 29-parameter `ocr_search_hybrid` is the most-used tool in the system. Every unnecessary parameter increases the chance of agent confusion.

**Parameters to remove entirely (always-on defaults):**
- `include_highlight` -- always true, no agent ever sets this to false
- `include_headers_footers` -- always false, virtually never wanted
- `include_cluster_context` -- always true (already defaults true)

**Parameters to group into a single object:**
```
filters: {
  document_ids: string[]
  metadata: { doc_title, doc_author, doc_subject }
  cluster_id: string
  content_types: string[]
  page_range: { min, max }
  section_path: string
  heading: string
  heading_level: { min, max }
  min_quality_score: number
  page_count: { min, max }
  table_columns: string
  is_atomic: boolean
}
```

This reduces the top-level parameter count from 29 to ~12 while preserving all functionality.

### 5.2 ocr_process_pending Parameters

7 optional parameters including `extras` (an array of enum values) and `additional_config` (a record). These are for advanced users only.

**Recommendation**: Most agents just need `ocr_process_pending` with no params. Consider a `preset` parameter (`quick`, `standard`, `thorough`) that bundles common configurations.

### 5.3 ocr_provenance_query Parameters

12 optional parameters for querying provenance. Most agents will use 1-2 filters.

**Recommendation**: Group filtering params into a `filters` object to reduce visual noise.

---

## 6. Response Format Standardization Recommendations

### 6.1 Current State

All tools use `formatResponse(successResult({...}))` for success and `handleError(error)` for failure. The success wrapper adds `{ success: true, data: {...} }`. The error wrapper adds `{ success: false, error: { category, message, details } }`.

This is **good** -- the envelope is consistent.

### 6.2 Inconsistency: next_steps

**Tools with next_steps** (6 files, ~8 tools):
- `ocr_db_select` -- 3 next_steps (document_list, search_hybrid, db_stats)
- `ocr_document_list` -- 3 next_steps (document_get, search_hybrid, document_structure)
- `ocr_document_get` -- 3 next_steps (document_page, document_structure, search_hybrid)
- `ocr_search_hybrid` -- 3 next_steps (chunk_context, document_get, document_page)
- `ocr_guide` -- dynamic next_steps based on state (rich, excellent)
- `ocr_file_upload` / `ocr_file_ingest_uploaded` -- have next_steps
- `ocr_process_pending` -- partial next_steps

**Tools WITHOUT next_steps** (16 files, ~116 tools):
- All provenance tools (6)
- All report tools (9)
- All evaluation tools (3)
- All extraction tools (7)
- All clustering tools (7)
- All comparison tools (6)
- All tag tools (6)
- All embedding tools (4)
- All timeline tools (2)
- All config tools (2)
- All VLM tools (6)
- All image tools (11)
- All chunk tools (4)
- Health check (1)
- Remaining search tools (8)
- Remaining document tools (6)
- Remaining ingestion tools (7)
- Remaining file management tools (4)
- Remaining database tools (3)

### 6.3 Recommendation: Systematic next_steps

Every tool should return `next_steps` with 1-3 logical follow-up tools. This creates a **navigable graph** instead of a flat list. Key missing next_steps:

| Tool | Should suggest |
|------|---------------|
| ocr_ingest_directory | ocr_process_pending |
| ocr_ingest_files | ocr_process_pending |
| ocr_process_pending | ocr_document_list, ocr_search_hybrid |
| ocr_chunk_get | ocr_chunk_context, ocr_document_page |
| ocr_chunk_context | ocr_document_get, ocr_search_hybrid |
| ocr_document_page | (next/previous page), ocr_document_structure |
| ocr_cluster_documents | ocr_cluster_list |
| ocr_cluster_get | ocr_document_compare, ocr_comparison_batch |
| ocr_document_compare | ocr_comparison_list |
| ocr_extract_images | ocr_vlm_process_pending |
| ocr_vlm_process_document | ocr_image_list |
| ocr_health_check | ocr_process_pending (if pending), ocr_retry_failed (if failed) |
| ocr_tag_create | ocr_tag_apply |
| ocr_tag_apply | ocr_tag_search |

### 6.4 Response Size Concerns

`ocr_db_stats` returns a massive response with overview, quality stats, cluster summaries, recent docs, file type distribution, etc. This is excellent for dashboards but wastes agent context window when the agent just needs to know "how many documents are in this database."

**Recommendation**: Add a `detail_level` parameter (`summary`, `full`) to high-output tools. Default to `summary` for agent-friendly responses.

---

## 7. Agent Navigation Flow Improvements

### 7.1 Current Flow

The `ocr_guide` tool is the intended entry point. It examines system state and returns context-aware next_steps. This is excellent design. However:

1. **ocr_guide is optional** -- an agent can skip it and try any of 124 tools directly
2. **Only works for the first step** -- after ocr_guide, the agent is back to navigating 124 tools
3. **Intent parameter is free-text-ish** -- `explore`, `search`, `ingest`, `analyze`, `status` are the options, but an agent might not know to use them

### 7.2 Recommended Flow Improvements

**A. Make ocr_guide descriptions more prominent**: The description should say "ALWAYS call this first" or be the first tool in the list.

**B. Chain of next_steps**: If every tool returns next_steps, the agent can follow a chain:
```
ocr_guide -> ocr_db_select -> ocr_document_list -> ocr_document_get -> ocr_search_hybrid -> ocr_chunk_context
```

This means agents only need to reason about 1-3 tools at a time, not 124.

**C. Error messages should include recovery tools**: The `databaseNotSelectedError` already says "Use ocr_db_list then ocr_db_select" -- all error messages should include tool suggestions.

**D. Group tools by workflow, not by entity**: The current grouping (database tools, document tools, search tools) is entity-oriented. A workflow-oriented grouping would be:
- **Getting Started**: ocr_guide, ocr_db_list, ocr_db_select, ocr_db_create
- **Loading Data**: ocr_ingest_files, ocr_ingest_directory, ocr_process_pending
- **Finding Information**: ocr_search, ocr_rag_context, ocr_document_list, ocr_document_get
- **Deep Dive**: ocr_chunk_get, ocr_chunk_context, ocr_document_page, ocr_document_structure
- **Analysis**: ocr_cluster_documents, ocr_document_compare, ocr_document_find_similar
- **Administration**: everything else

---

## 8. Tier System Assessment

### 8.1 Current Distribution

| Tier | Count | Percentage |
|------|-------|------------|
| ADMIN | 45 | 36% |
| ANALYSIS | 34 | 27% |
| PROCESSING | 21 | 17% |
| CORE | 15 | 12% |
| SEARCH | 9 | 7% |

### 8.2 Problems

1. **ADMIN is overloaded**: 45 tools tagged ADMIN including ocr_db_stats, ocr_embedding_list, ocr_config_get, all 9 report tools, all 3 evaluation tools, 2 timeline tools. "Admin" has become a catch-all for "not core, not search, not analysis." An agent seeing [ADMIN] learns nothing useful about whether it should call the tool.

2. **ANALYSIS is also overloaded**: 34 tools including provenance querying, clustering management, comparison, tags, document similarity, image listing, and document recommendations. These span very different use cases.

3. **Tier tags don't affect routing**: The tags are just description prefixes. An agent cannot filter by tier, request only CORE tools, or ask "show me SEARCH tools." They are visual-only hints in a flat list.

4. **Missing PIPELINE tier**: The description says "5-tier: CORE, ADMIN, SEARCH, ANALYSIS, PIPELINE" but the actual tags are CORE, ADMIN, SEARCH, ANALYSIS, PROCESSING. PIPELINE != PROCESSING.

### 8.3 Recommended Tier Restructure

Instead of 5 tiers of roughly equal granularity, use 3 tiers of decreasing frequency:

| Tier | Description | Count | Tools |
|------|-------------|-------|-------|
| **ESSENTIAL** | Agent uses these 80%+ of the time | ~12 | ocr_guide, ocr_db_list, ocr_db_select, ocr_search (unified), ocr_rag_context, ocr_document_list, ocr_document_get, ocr_document_page, ocr_chunk_context, ocr_ingest_files, ocr_process_pending, ocr_health_check |
| **EXTENDED** | Agent uses these for specific tasks | ~40 | Search variants, document operations, clustering, comparison, tags, images, VLM, extraction |
| **ADMIN** | Rarely needed by agents | ~70 | All report/analytics, config, embeddings, timeline, file management, evaluation, provenance queries |

The ESSENTIAL tier should be small enough (12-15 tools) that an agent can hold them all in working memory.

---

## 9. Error Handling Assessment

### 9.1 Strengths

- All errors go through `handleError()` -> `MCPError.fromUnknown()` -> `formatErrorResponse()`
- Error responses have consistent shape: `{ success: false, error: { category, message, details } }`
- 14 custom error classes mapped in `ERROR_NAME_TO_CATEGORY`
- `databaseNotSelectedError()` includes actionable guidance

### 9.2 Weaknesses

- Most error messages do NOT include tool suggestions for recovery
- Validation errors from Zod show raw schema messages that may confuse agents
- No `suggested_tool` field in error responses

### 9.3 Recommendations

Add a `recovery` field to error responses:
```json
{
  "success": false,
  "error": {
    "category": "DATABASE_NOT_SELECTED",
    "message": "No database selected.",
    "recovery": {
      "tool": "ocr_db_select",
      "description": "Select a database first",
      "params_hint": { "database_name": "<use ocr_db_list to find names>" }
    }
  }
}
```

---

## 10. Risk Assessment

### 10.1 Risks of NOT simplifying

| Risk | Severity | Impact |
|------|----------|--------|
| Agents select wrong search tool | HIGH | Degraded search quality, wasted API calls |
| Agents overwhelmed by 124 tools | HIGH | Random tool selection, poor user experience |
| Agents hallucinate parameter values on 29-param tools | HIGH | Silent wrong results |
| New agent integrations take longer | MEDIUM | Every LLM needs to learn 124 tool descriptions |
| Context window waste | MEDIUM | Tool descriptions alone consume ~15K tokens |

### 10.2 Risks of simplifying

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking existing agent workflows | MEDIUM | Version the tool API; keep old names as aliases |
| Losing fine-grained control | LOW | All params still available in unified tools |
| Migration effort | LOW | Tool internals unchanged; only registration layer changes |
| Test suite breakage | MEDIUM | Run full test suite after each change |

### 10.3 Tool Description Token Cost

Rough estimate of the token cost of exposing 124 tool descriptions to an agent:

- Average description length: ~120 chars (~30 tokens)
- Average parameter schema: ~10 params x 50 chars = 500 chars (~125 tokens)
- Per tool: ~155 tokens
- Total for 124 tools: **~19,200 tokens** just for tool definitions

For the 3 search tools alone:
- 29 + 27 + 26 = 82 parameters
- ~82 x 50 chars = 4,100 chars per tool
- 3 x ~1,000 tokens = **~3,000 tokens for search tools alone**

Unifying search into 1 tool saves ~2,000 tokens per agent conversation.

---

## 11. Specific File-Level Findings

### search.ts (3,107 lines)

- **Largest tool file** at 3,107 lines
- Contains 12 tools, 3 of which have 26-29 parameters
- 24 parameters are copy-pasted across the three search tools
- The `handleSearch`, `handleSearchSemantic`, and `handleSearchHybrid` functions share ~80% of their logic
- `ocr_search_hybrid` is the only search tool with `next_steps`
- Quality weighting, header/footer exclusion, and VLM enrichment logic is shared but still duplicated in the parameter schemas

### intelligence.ts (875 lines)

- **Best-designed tool file** -- `ocr_guide` dynamically generates next_steps based on system state
- Contains 4 tools but 3 of them (ocr_document_tables, ocr_document_recommend, ocr_document_extras) are thematically unrelated to "intelligence" and should be in documents.ts
- `ocr_guide` is the only tool that understands the full system state

### reports.ts (1,734 lines)

- 9 report tools, ALL tagged [ADMIN], NONE with next_steps
- Heavy overlap with `ocr_db_stats` and timeline tools
- An agent has no guidance on which report to request

### documents.ts (1,824 lines)

- 12 tools, well-structured with good descriptions
- `ocr_document_list` and `ocr_document_get` have `next_steps` -- good
- `ocr_document_structure` and `ocr_document_sections` overlap significantly

### images.ts (1,032 lines)

- 11 tools spanning CRUD, search, and processing -- too many for one entity type
- `ocr_image_extract` description says "prefer ocr_extract_images" -- should be removed or merged

---

## 12. Actionable Implementation Plan

### Phase 1: Quick Wins (1-2 days, zero-risk)

1. Add `next_steps` to all high-traffic tools (ingestion, chunk, cluster, comparison tools)
2. Fix description of `ocr_image_extract` to not say "prefer the other tool"
3. Add `recovery` hints to all error factory functions in errors.ts
4. Rename PIPELINE tier reference to PROCESSING in documentation

### Phase 2: Parameter Reduction (2-3 days, low risk)

1. Remove always-on parameters from search tools (include_highlight, include_headers_footers, include_cluster_context)
2. Change defaults for search params (quality_boost -> true, expand_query -> true, exclude_duplicate_chunks -> true)
3. Group filter params into a `filters` object on search tools

### Phase 3: Tool Consolidation (3-5 days, medium risk)

1. Merge 3 search tools into 1 unified `ocr_search` with `mode` parameter
2. Merge `ocr_reembed_document` into `ocr_embedding_rebuild`
3. Merge `ocr_document_sections` into `ocr_document_structure`
4. Merge saved search tools into 2 (ocr_search_save, ocr_search_saved)
5. Move `ocr_document_tables`, `ocr_document_recommend`, `ocr_document_extras` from intelligence.ts to documents.ts

### Phase 4: Tier Restructure (1 day, low risk)

1. Reclassify all tools into ESSENTIAL/EXTENDED/ADMIN tiers
2. Update `ocr_guide` to use new tier names
3. Add tier-based filtering capability to `ocr_guide`

---

## 13. Conclusion

The OCR Provenance MCP system has excellent core functionality but has grown organically to 124 tools without sufficient attention to the agent experience. The three search tools with 27-29 parameters each are the most urgent problem. The lack of consistent `next_steps` across tools means agents must navigate a flat list of 124 options after every action.

The good news is that the underlying architecture (shared.ts, formatResponse, handleError, MCP registration) is clean and well-structured. Simplification can be done at the tool definition layer without changing business logic.

**Top 3 recommendations by impact:**
1. Unify the 3 search tools into 1 (saves ~2,000 tokens/conversation, removes agent decision paralysis)
2. Add `next_steps` to all tools (creates navigable graph instead of flat list)
3. Reduce search params from 29 to ~15 by removing always-on defaults and grouping filters

**Estimated reduction**: 124 -> ~114 tools, 82 duplicate params -> 0, 8 tools with next_steps -> 124 tools with next_steps.
