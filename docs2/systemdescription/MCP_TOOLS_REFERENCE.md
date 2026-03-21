# MCP Tools Reference — Complete Catalog (153 Tools)

## Registration Architecture

All tools registered in `src/server/register-tools.ts` via 31 tool modules (version 1.2.66). Each tool has:
- Zod schema validation on inputs
- Rate limiting by category (search: 50/min, ingestion: 10/min, destructive: 5/min, default: 100/min)
- Audit logging
- License checking (for billable operations)
- Response truncation at 700 KB

---

## Database (5 tools)

| Tool | Description |
|------|-------------|
| `ocr_db_create` | Create new SQLite database |
| `ocr_db_delete` | Permanently delete database (rate limited: 5/min) |
| `ocr_db_list` | List all databases with pagination |
| `ocr_db_select` | Switch active database (supports `force` parameter to clear stuck operation locks) |
| `ocr_db_stats` | Get database statistics (size, counts, quality) |

## Database Management (8 tools)

| Tool | Description |
|------|-------------|
| `ocr_db_archive` | Archive database (hide from default list) |
| `ocr_db_recent` | Show recently accessed databases |
| `ocr_db_rename` | Rename database |
| `ocr_db_search` | Find databases by name/description/tags |
| `ocr_db_summary` | AI-readable database profile |
| `ocr_db_tag` | Add/remove/set tags and metadata |
| `ocr_db_unarchive` | Restore archived database |
| `ocr_db_workspace` | Create/list/manage database workspaces |

## Portability (7 tools)

| Tool | Description |
|------|-------------|
| `ocr_db_backup` | Create atomic backup (VACUUM INTO) |
| `ocr_db_clone` | Clone database to new name |
| `ocr_db_import` | Import documents from JSON export |
| `ocr_db_merge` | Merge source database into current |
| `ocr_db_restore` | Restore database from backup |
| `ocr_db_snapshot` | Create/list/restore/delete point-in-time snapshots |
| `ocr_export_stream` | Stream export as JSON-Lines for large databases |

## Sharing (4 tools)

| Tool | Description |
|------|-------------|
| `ocr_db_share` | Export database to shared folder |
| `ocr_db_import_shared` | Import database from shared folder |
| `ocr_db_transfer` | Package database for transfer to another system |
| `ocr_db_receive` | Import transfer bundle |

## Ingestion (7 tools)

| Tool | Description |
|------|-------------|
| `ocr_ingest_files` | Ingest specific files (rate limited: 10/min) |
| `ocr_ingest_directory` | Bulk ingest directory (rate limited: 10/min) |
| `ocr_process_pending` | Run full OCR pipeline on pending documents |
| `ocr_convert_raw` | Quick OCR preview without creating records |
| `ocr_reprocess` | Re-run OCR with different settings |
| `ocr_retry_failed` | Reset failed documents to pending |
| `ocr_status` | Check processing status |

## Search (7 tools)

| Tool | Description |
|------|-------------|
| `ocr_search` | Unified search — keyword, semantic, or hybrid with cross-encoder reranking enabled by default. Use natural language queries, not keyword lists. (rate limited: 50/min) |
| `ocr_search_cross_db` | Search across multiple databases (rate limited: 50/min) |
| `ocr_rag_context` | Assemble search context for RAG. Natural language queries strongly recommended. (rate limited: 50/min) |
| `ocr_benchmark_compare` | Compare search quality across databases |
| `ocr_fts_manage` | FTS5 index maintenance (rebuild/status) |
| `ocr_search_export` | Export search results to CSV/JSON |
| `ocr_search_saved` | Manage saved searches (save/list/get/execute) |

## Documents (10 tools)

| Tool | Description |
|------|-------------|
| `ocr_document_get` | Get full document details |
| `ocr_document_list` | Browse documents with cursor pagination |
| `ocr_document_delete` | Permanently delete document (rate limited: 5/min) |
| `ocr_document_find_similar` | Find similar documents by embedding |
| `ocr_document_duplicates` | Find duplicate documents |
| `ocr_document_structure` | Get document outline/tree structure |
| `ocr_document_update_metadata` | Update title/author/subject |
| `ocr_document_versions` | Find all versions of re-ingested document |
| `ocr_document_workflow` | Track document review states |
| `ocr_export` | Export document as JSON/markdown/CSV |

## Chunks (4 tools)

| Tool | Description |
|------|-------------|
| `ocr_chunk_get` | Inspect specific chunk by ID |
| `ocr_chunk_list` | Browse all chunks in document |
| `ocr_chunk_context` | Expand result with surrounding text |
| `ocr_document_page` | Read specific page of document |

## Embeddings (4 tools)

| Tool | Description |
|------|-------------|
| `ocr_embedding_get` | Get specific embedding details |
| `ocr_embedding_list` | List embeddings with filtering |
| `ocr_embedding_rebuild` | Rebuild embeddings for chunk/image/document |
| `ocr_embedding_stats` | Get embedding coverage statistics |

## Images (8 tools)

| Tool | Description |
|------|-------------|
| `ocr_image_get` | Get full image details |
| `ocr_image_list` | List images with VLM status |
| `ocr_image_search` | Search images by keyword or semantic similarity |
| `ocr_image_pending` | List images needing VLM processing |
| `ocr_image_reanalyze` | Re-run VLM with custom prompt |
| `ocr_image_reset_failed` | Reset failed VLM images to pending |
| `ocr_image_delete` | Delete images permanently |
| `ocr_image_stats` | Get image processing statistics |

## Extraction (1 tool)

| Tool | Description |
|------|-------------|
| `ocr_extract_images` | Extract images from PDF/DOCX files |

## Structured Extraction (2 tools)

| Tool | Description |
|------|-------------|
| `ocr_extraction_get` | Get extraction results by ID |
| `ocr_extraction_list` | List structured extractions with filtering |

## VLM — Vision Language Model (3 tools)

| Tool | Description |
|------|-------------|
| `ocr_vlm_describe` | Generate AI description of image (Chandra VLM) |
| `ocr_vlm_process` | Run VLM analysis on all document images |
| `ocr_vlm_status` | Check VLM processing status |

## Provenance (6 tools)

| Tool | Description |
|------|-------------|
| `ocr_provenance_get` | Get provenance chain with descendants |
| `ocr_provenance_query` | Query provenance with filters |
| `ocr_provenance_timeline` | Processing timeline for document |
| `ocr_provenance_verify` | Verify data integrity via hash chains |
| `ocr_provenance_export` | Export provenance (JSON/W3C-PROV/CSV) |
| `ocr_provenance_processor_stats` | Per-processor performance stats |

## Reports (7 tools)

| Tool | Description |
|------|-------------|
| `ocr_report_overview` | Quality and corpus overview |
| `ocr_report_performance` | Pipeline performance analytics |
| `ocr_document_report` | Detailed report for single document |
| `ocr_cost_summary` | Cost analytics by document/mode/month |
| `ocr_error_analytics` | Error and recovery analytics |
| `ocr_evaluation_report` | Comprehensive evaluation report |
| `ocr_trends` | Time-series trends (quality/volume) |

## Intelligence (5 tools)

| Tool | Description |
|------|-------------|
| `ocr_guide` | System state overview with prioritized next steps |
| `ocr_document_extras` | Supplementary OCR data (charts, links, tracked changes) |
| `ocr_document_tables` | Extract table data from document |
| `ocr_table_export` | Export table data as CSV/JSON/markdown |
| `ocr_document_recommend` | Related document recommendations |

## Comparison (6 tools)

| Tool | Description |
|------|-------------|
| `ocr_document_compare` | Diff two documents (text + structural) |
| `ocr_comparison_get` | Retrieve full diff data |
| `ocr_comparison_list` | List past comparisons |
| `ocr_comparison_batch` | Compare multiple document pairs |
| `ocr_comparison_discover` | Find likely-similar document pairs |
| `ocr_comparison_matrix` | NxN pairwise cosine similarity matrix |

## Clustering (7 tools)

| Tool | Description |
|------|-------------|
| `ocr_cluster_documents` | Group documents by similarity (HDBSCAN/agglomerative/k-means) |
| `ocr_cluster_list` | Browse existing clusters |
| `ocr_cluster_get` | Inspect cluster details |
| `ocr_cluster_assign` | Auto-classify document into existing cluster |
| `ocr_cluster_merge` | Merge two clusters |
| `ocr_cluster_reassign` | Move document to different cluster |
| `ocr_cluster_delete` | Delete all clusters for a run |

## Tags (6 tools)

| Tool | Description |
|------|-------------|
| `ocr_tag_create` | Create reusable tag with color |
| `ocr_tag_list` | List tags with usage counts |
| `ocr_tag_apply` | Attach tag to entity (document/chunk/image/extraction/cluster) |
| `ocr_tag_remove` | Detach tag from entity |
| `ocr_tag_search` | Find entities by tag |
| `ocr_tag_delete` | Delete tag permanently (rate limited: 5/min) |

## Collaboration (11 tools)

| Tool | Description |
|------|-------------|
| `ocr_annotation_create` | Create annotation (comment/correction/question/highlight/flag/approval) |
| `ocr_annotation_get` | Get annotation with threaded replies |
| `ocr_annotation_list` | List annotations with filters |
| `ocr_annotation_update` | Edit annotation or change status |
| `ocr_annotation_delete` | Delete annotation and replies |
| `ocr_annotation_summary` | Get annotation statistics |
| `ocr_document_lock` | Acquire exclusive/shared lock |
| `ocr_document_lock_status` | Check lock status |
| `ocr_document_unlock` | Release document lock |
| `ocr_search_alert_check` | Check for new docs matching saved search |
| `ocr_search_alert_enable` | Enable/disable search alerts |

## Workflow & Approval (8 tools)

| Tool | Description |
|------|-------------|
| `ocr_workflow_submit` | Submit document for review |
| `ocr_workflow_assign` | Assign reviewer |
| `ocr_workflow_review` | Review (approve/reject/changes_requested) |
| `ocr_workflow_status` | Get workflow state and history |
| `ocr_workflow_queue` | List documents in workflow queue |
| `ocr_approval_chain_create` | Create reusable approval chain |
| `ocr_approval_chain_apply` | Apply approval chain to document |
| `ocr_approval_step_decide` | Decide on approval step |

## Contract / CLM (9 tools)

| Tool | Description |
|------|-------------|
| `ocr_contract_extract` | Extract contract-specific information |
| `ocr_document_summarize` | Generate structured summary from chunks |
| `ocr_corpus_summarize` | Summarize entire corpus |
| `ocr_obligation_list` | List contract obligations with filters |
| `ocr_obligation_update` | Update obligation status |
| `ocr_obligation_calendar` | Calendar view of deadlines |
| `ocr_playbook_create` | Create playbook with preferred terms |
| `ocr_playbook_list` | List all playbooks |
| `ocr_playbook_compare` | Compare document against playbook |

## Compliance (3 tools)

| Tool | Description |
|------|-------------|
| `ocr_compliance_report` | Generate compliance overview |
| `ocr_compliance_hipaa` | HIPAA-specific compliance report |
| `ocr_compliance_export` | Export audit trail (SOC 2/HIPAA/SOX format) |

## Events & Webhooks (6 tools)

| Tool | Description |
|------|-------------|
| `ocr_webhook_create` | Register webhook URL for event notifications |
| `ocr_webhook_list` | List registered webhooks |
| `ocr_webhook_delete` | Remove webhook registration |
| `ocr_export_annotations` | Export annotations as CSV/JSON |
| `ocr_export_audit_log` | Export audit log as CSV/JSON |
| `ocr_export_obligations_csv` | Export obligations as RFC 4180 CSV |

## Users & Audit (2 tools)

| Tool | Description |
|------|-------------|
| `ocr_user_info` | Get/create user with roles |
| `ocr_audit_query` | Query audit log with filters |

## Config (2 tools)

| Tool | Description |
|------|-------------|
| `ocr_config_get` | View system configuration |
| `ocr_config_set` | Change configuration setting |

## Health & Maintenance (2 tools)

| Tool | Description |
|------|-------------|
| `ocr_health_check` | Diagnose data integrity issues |
| `ocr_db_maintenance` | Database maintenance (analyze/vacuum/wal_checkpoint) |

## License (1 tool)

| Tool | Description |
|------|-------------|
| `ocr_license_status` | Check license status and balance |

## Dashboard (2 tools)

| Tool | Description |
|------|-------------|
| `ocr_dashboard_open` | Open dashboard in browser |
| `ocr_dashboard_status` | Check health of all 3 services |

---

## REST API Endpoints (Non-MCP)

In addition to the 153 MCP tools, the HTTP server exposes REST endpoints:

### File Upload
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Multipart file upload with staging, dedup, provenance |
| `/api/upload/staged` | DELETE | Cleanup staged files |

### Document Viewer
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/viewer/prepare/{id}?db={name}` | GET | Prepare document for viewing (convert if needed) |
| `/api/viewer/file/{id}` | GET | Stream cached document file |
| `/api/viewer/close/{id}` | POST | Start 24h cache cleanup timer |

### Health & MCP
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server health check |
| `/mcp` | POST | MCP JSON-RPC endpoint |
| `/sse` | GET | Server-Sent Events transport |
