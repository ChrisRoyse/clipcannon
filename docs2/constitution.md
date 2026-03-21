<constitution version="2.1">
<metadata>
  <project_name>OCR Provenance MCP</project_name>
  <description>AI Context Engineering Platform — MCP server for document OCR, VLM image analysis, clustering, comparison, hybrid search, and multi-database management with complete provenance tracking</description>
  <spec_version>2.1.0</spec_version>
  <schema_version>33</schema_version>
  <registry_version>1</registry_version>
  <app_version>1.2.38</app_version>
  <last_updated>2026-03-17</last_updated>
  <author>Chris Royse</author>
  <repository>github.com/ChrisRoyse/ocrprovenancelocalmcp</repository>
  <license>Dual (Free Non-Commercial)</license>
  <stats tools="151" modules="30" tables="28+5 FTS5" registry_tables="6+1 FTS5" python_workers="10" tests="3654+" test_files="153" file_types="18 (PDF,DOCX,DOC,PPTX,PPT,XLSX,XLS,PNG,JPG,JPEG,TIFF,TIF,BMP,GIF,WEBP,TXT,CSV,MD)"/>
</metadata>

<!-- SECTION 1: IMMUTABLE RULES — Non-negotiable. Violating any causes data loss, protocol corruption, or security breach. -->
<immutable_rules>
  <rule id="IMM-01" severity="critical">NEVER store data without a provenance record. Every artifact must chain back to source via SHA-256 hash and Merkle parent linking.</rule>
  <rule id="IMM-02" severity="critical">NEVER use console.log() in TypeScript. stdout is JSON-RPC in stdio mode — use console.error().</rule>
  <rule id="IMM-03" severity="critical">NEVER use cloud APIs for OCR, VLM, or embeddings. Local GPU only. No document content leaves the machine.</rule>
  <rule id="IMM-04" severity="critical">NEVER commit secrets, credentials, or .env files.</rule>
  <rule id="IMM-05" severity="critical">NEVER use flash-attn. Incompatible with Blackwell/sm_120 (RTX 5090), MPS (Apple Silicon), CPU. Use standard PyTorch attention.</rule>
  <rule id="IMM-06" severity="high">NEVER modify per-database schema for registry features. Registry (_registry.db) is separate. Per-DB schema stays at v33.</rule>
  <rule id="IMM-07" severity="high">ALWAYS include original_text in search results. Users must never need a follow-up query to see content.</rule>
  <rule id="IMM-08" severity="high">ALWAYS validate tool inputs with Zod via validateInput().</rule>
  <rule id="IMM-09" severity="high">ALWAYS read a file before editing it.</rule>
  <rule id="IMM-10" severity="high">ALWAYS kill stale server before rebuild: pkill -f "dist/bin.js" (separate command), then npm run build &amp;&amp; npm test.</rule>
  <rule id="IMM-11" severity="high">NEVER serve HTML from the MCP server. bin-http.ts = REST API + MCP only. Dashboard is separate Next.js app.</rule>
  <rule id="IMM-12" severity="critical">NEVER use nvidia/cuda as Docker base image. PyTorch pip wheels bundle their own cuBLAS — nvidia/cuda base causes DUAL CUBLAS CONFLICT (CUBLAS_STATUS_NOT_INITIALIZED on Blackwell GPUs). Use python:3.12-slim-bookworm.</rule>
</immutable_rules>

<!-- SECTION 2: FAIL-FAST DOCTRINE — Silent failures are highest-severity bugs. -->
<fail_fast_doctrine>
  <principle>If something is broken, fail immediately with clear error info. Never degrade silently.</principle>
  <prohibited_patterns>
    <pattern>try { X } catch { fallbackY } — silently masks failure</pattern>
    <pattern>Returning default/empty data when real operation fails — throw instead</pattern>
    <pattern>try { newWay } catch { oldWay } — remove old paths entirely</pattern>
    <pattern>Swallowing errors — every catch MUST: re-throw, throw with context, OR console.error() + handleError() at tool boundary only</pattern>
    <pattern>|| defaultValue to mask undefined — check explicitly, throw if unexpected</pattern>
  </prohibited_patterns>
  <error_context>What failed, why, what input caused it. Include file paths, IDs, operation names. Preserve stack traces. MCPError.fromUnknown() preserves .details and .code.</error_context>
  <error_boundary>MCP tool handlers are the ONLY place errors become structured responses: try { ... } catch { return handleError(error); }</error_boundary>
  <no_backwards_compat>No shims, re-exports, _deprecated wrappers, _var renames, or // removed comments. Git is the record.</no_backwards_compat>
</fail_fast_doctrine>

<!-- SECTION 3: TECH STACK — Exact versions. No substitutions without constitution amendment. -->
<tech_stack>
  <runtime>TypeScript 5.5+ (strict, ES2022, ESM) on Node.js >=20 | Python 3.12+ (workers only, 3.10+ bare-metal)</runtime>
  <framework>@modelcontextprotocol/sdk 1.0.0 (MCP). Transport: HTTP/SSE primary (StreamableHTTPServerTransport), stdio deprecated.</framework>
  <database>better-sqlite3 11.0.0 + sqlite-vec 0.1.7-alpha.2 (768-dim vectors) + FTS5 external content</database>
  <models>
    <model name="OCR">Marker-pdf 1.10.2 (with Surya detection)</model>
    <model name="VLM">Chandra 0.1.8</model>
    <model name="Embeddings">nomic-embed-text-v1.5 (768-dim, sentence-transformers)</model>
    <model name="Reranking">ms-marco-MiniLM-L-12-v2</model>
  </models>
  <python_libs>PyTorch (CUDA/MPS/CPU), sentence-transformers, scikit-learn, HDBSCAN, PyMuPDF, Pillow, python-docx, beautifulsoup4, markdownify, weasyprint, mammoth</python_libs>
  <ts_libs>zod 3.25+, uuid 10.0+, diff 8.0+, dotenv 17.2+ ({quiet:true}), python-shell 5.0+</ts_libs>
  <dev_tools>vitest 4.1+, eslint 9.0+, prettier 3.3+, typescript-eslint 8.0+, ruff (Python)</dev_tools>
  <docker base="python:3.12-slim-bookworm" registry="Docker Hub (docker.io)">
    Two-image split: models base leapable/ocr-provenance-models:v1 (~24GB, rare) + app leapable/ocr-provenance-mcp:latest (~500MB, every release).
    Unified GPU/CPU — ONE image. CUDA PyTorch auto-degrades to CPU on non-GPU systems.
  </docker>
  <cloud_billing platform="Cloudflare Workers + D1" package="packages/checkout-worker/">
    Stripe checkout, server-side charge verification, per-machine secrets bootstrap. Deployed at api.ocrprovenance.com.
  </cloud_billing>
</tech_stack>

<!-- SECTION 4: ARCHITECTURE -->
<architecture>

  <!-- 4.1 Four-Service Topology — Docker runs 3 local services. Checkout Worker is external cloud. -->
  <service_topology>
    <service name="MCP Server" port="3366" transport="HTTP/SSE" entry="src/bin-http.ts" auth="X-License-Key (SHA-256)">151 MCP tools + REST API</service>
    <service name="License Server" port="3000" framework="Hono" location="packages/server/" auth="Bearer session token">SQLite + Stripe + Ed25519-signed licenses</service>
    <service name="Dashboard" port="3367" framework="Next.js 15" auth="Magic link via license server">Context engineering UI (separate repo)</service>
    <service name="Checkout Worker" platform="Cloudflare Workers + D1" location="packages/checkout-worker/" url="api.ocrprovenance.com" auth="WORKER_AUTH_SECRET">
      Stripe checkout sessions, server-side charge verification, per-machine secrets bootstrap via SECRETS_MASTER_KEY.
      D1 tables: balances, charges, payments, machine_secrets.
    </service>
    <communication>MCP→License: X-License-Key | Dashboard→License: Bearer token | Dashboard→MCP: Next.js proxy /api/mcp/[...path]→localhost:3366/api/* | Entrypoint→Checkout Worker: POST /v1/secrets/bootstrap (machine_id→5 secrets)</communication>
  </service_topology>

  <!-- 4.2 Provenance Chain -->
  <provenance_chain>
    DOCUMENT(0)→OCR_RESULT(1)→CHUNK(2)/IMAGE(2)→EMBEDDING(3)/VLM_DESC(3)→EMBEDDING(4)
    Fields: SHA-256 hash, chain-hash (Merkle parent), processor, timestamps, quality scores.
    Verify: ocr_provenance_verify tool.
  </provenance_chain>

  <!-- 4.3 Local Model Stack -->
  <model_stack>
    <model name="OCR" engine="Marker-pdf 1.10.2" vram="~4GB" daemon="true" startup="~120s" throughput="~2s/page" cache="~/.cache/datalab/models/ (3.3GB)" env="MODEL_CACHE_DIR"/>
    <model name="VLM" engine="Chandra 0.1.8" vram="~18GB" daemon="true" startup="~120s" throughput="3-8s/img" cache="~/.cache/huggingface/hub/models--datalab-to--chandra/ (17.6GB)" env="CHANDRA_MODEL_PATH"/>
    <model name="Embeddings" engine="nomic-embed-text-v1.5" vram="~1GB" daemon="true" throughput="60-120 chunks/s CUDA, ~20 CPU" cache="./models/nomic-embed-text-v1.5/ (523MB)" env="EMBEDDING_MODEL_PATH"/>
    <model name="Reranking" engine="ms-marco-MiniLM-L-12-v2" vram="~1GB" daemon="false" cache="~/.cache/huggingface/hub/ (260MB)"/>
    <daemon_pattern>Spawn on first request→models loaded once→requests serialized via promise lock→auto-respawn on crash→destroy() frees GPU→kill on shutdown. CRITICAL: After processPending() completes, ALL models (Marker, Chandra, Embeddings) are destroyed to free VRAM.</daemon_pattern>
    <vram_lifecycle>Models load into VRAM on first use during batch processing. After ALL documents are processed, processPending() calls destroy() on Marker, Embedding daemon, and kills VLM workers. VRAM is fully freed between batch jobs.</vram_lifecycle>
    <rule>Models MUST be pre-cached. No runtime downloads. Fail fast if missing.</rule>
  </model_stack>

  <!-- 4.4 License System -->
  <license_system charge="$0.03/file" offline_grace="NONE — license server MUST be reachable for every charge">
    <provisioning>POST /v1/provision → deterministic HMAC(LICENSE_SIGNING_KEY, "provision:"+machine_id). Same machine=same key. Ed25519-signed license_token. $0 balance until Stripe.</provisioning>
    <billing_flow>1. gate.charge(hash)→pending 2. Process(OCR/VLM) 3. gate.confirm(id) or gate.refund(id) 4. $0 balance=402; InsufficientBalanceError→doc stays 'pending'</billing_flow>
    <auth>License Key Auth (SHA-256 via X-License-Key) for MCP | Session Auth (Bearer) for dashboard | Provision rate limit: 3/min/IP + 2/5min/machine_id</auth>
    <secrets count="5" source="Cloudflare Worker or entrypoint-generated">
      SESSION_SECRET (cookie signing), LICENSE_SIGNING_KEY (Ed25519 private), LICENSE_PUBLIC_KEY (Ed25519 public), WORKER_AUTH_SECRET (server-to-server), WEBHOOK_SHARED_SECRET (Stripe HMAC).
      Two-tier: If CHECKOUT_API_URL set, Docker entrypoint bootstraps from Cloudflare Worker (/v1/secrets/bootstrap) with SECRETS_MASTER_KEY derivation. Otherwise entrypoint generates locally.
    </secrets>
  </license_system>

  <!-- 4.5 Data Schema -->
  <data_schema version="33">
    <tables>
      Core: documents, ocr_results, chunks, embeddings, images, provenance |
      Features: extractions, form_fills, comparisons, clusters, document_clusters, tags, entity_tags |
      Infra: schema_version, database_metadata, fts_index_metadata, uploaded_files, saved_searches |
      Collab: users, audit_log, annotations, document_locks |
      Workflow: workflow_states, approval_chains, approval_steps |
      CLM: obligations, playbooks | Events: webhooks |
      Virtual: vec_embeddings (sqlite-vec), chunks_fts, vlm_fts, extractions_fts, documents_fts (FTS5)
    </tables>
    <registry db="_registry.db" version="1" location="~/.ocr-provenance/_registry.db (alongside databases/, NOT inside it)" tables="6+1 FTS5">Startup reconciliation syncs filesystem↔registry. Write-through on all CRUD. ON DELETE/UPDATE CASCADE on all FKs.</registry>
    <fk_delete_order>vec_embeddings→NULL vlm_embedding_id→embeddings→images→clusters→document_clusters→comparisons→chunks→extractions→ocr_results→FTS→document→provenance</fk_delete_order>
    <storage>~/.ocr-provenance/ { _registry.db, _license.db, _license_server.db, .machine_id, .license_key, databases/*.db, images/[doc-id]/ }</storage>
    <internal_dbs>DBs prefixed with _ (_registry.db, _license.db, _license_server.db) are internal — hidden from user-facing tools (getRecent, getDatabaseCount, ocr_guide).</internal_dbs>
  </data_schema>

  <!-- 4.6 Ingestion Pipeline -->
  <ingestion_pipeline>
    1. ocr_ingest_files/ocr_ingest_directory→validate→store docs (status='pending')
    2. ocr_process_pending [max_pages, mode, include_images]→License charge→Marker OCR→provenance→images→chunks→embeddings→(VLM)→confirm/refund
    3. Return: {processed: N, failed: M, details: [...]}
  </ingestion_pipeline>

  <!-- 4.7 Workflow State Machine -->
  <workflow_states>(none)→draft→submitted→in_review→approved→executed→archived | →rejected | →changes_requested→submitted (loop)</workflow_states>

  <!-- 4.8 Error Transience Classification -->
  <error_transience>
    Transient (doc stays 'pending', retryable): OCR_TIMEOUT, OCR_GPU_ERROR, OCR_MODEL_ERROR (env-level — affects all docs equally), InsufficientBalanceError.
    Permanent (doc marked 'failed'): OCR_FILE_ERROR (not found, corrupt, unsupported format).
    Rule: Environment-level errors are ALWAYS transient. Per-document errors (bad file) are permanent.
  </error_transience>

  <!-- 4.9 CLI Entry Point Routing (bin.ts) -->
  <cli_routing>
    Management commands (install, start, stop, etc.) → src/wrapper/cli.ts.
    No args + Docker container running → bridge stdin/stdout to container HTTP /mcp endpoint.
    No args + no container → start local MCP server directly (src/index.ts).
    Docker detection: `docker inspect --format {{.State.Running}} ocr-provenance-mcp` with 3s timeout.
  </cli_routing>
</architecture>

<!-- SECTION 5: DIRECTORY STRUCTURE -->
<directory_structure>
project-root/
+-- src/
|   +-- index.ts                    # stdio entry (deprecated)
|   +-- bin.ts                      # CLI entry point (routes management vs MCP, Docker detection)
|   +-- bin-http.ts                 # HTTP/SSE entry (primary) + REST API
|   +-- server/ { register-tools.ts, startup.ts, state.ts, errors.ts, types.ts }
|   +-- tools/                      # 30 modules (151 tools)
|   |   +-- shared.ts               # formatResponse, handleError, ToolDefinition, successResult
|   |   +-- database.ts (5), database-management.ts (8), ingestion.ts (7), search.ts (7)
|   |   +-- documents.ts (10), provenance.ts (6), images.ts (8), vlm-local.ts (3)
|   |   +-- comparison.ts (6), clustering.ts (7), collaboration.ts (11), workflow.ts (8)
|   |   +-- clm.ts (9), compliance.ts (3), + 16 more modules
|   +-- services/
|   |   +-- ocr/ { processor.ts, errors.ts }  # Marker-pdf daemon bridge + error classification
|   |   +-- vlm/                    # Chandra daemon bridge
|   |   +-- embedding/              # nomic + reranking bridge
|   |   +-- storage/ { database/ (27 op modules), registry/, migrations/ (v1-v33), vector.ts }
|   |   +-- search/                 # BM25 + vector + RRF + rerank
|   |   +-- chunking/, clustering/, comparison/, images/, provenance/, license/, clm/
|   |   +-- audit.ts, python-pool.ts, rate-limiter.ts, webhook-delivery.ts
|   +-- models/                     # TypeScript interfaces (11 files)
|   +-- utils/ { hash.ts (SHA-256), validation.ts (Zod + path sanitization) }
|   +-- wrapper/                    # Docker wrapper logic (mirrored in packages/wrapper/src/)
+-- python/                         # 10 files (9 workers + __init__.py)
|   +-- ocr_worker_local.py (Marker daemon), vlm_worker_local.py (Chandra daemon)
|   +-- embedding_worker.py, image_extractor.py, docx_image_extractor.py
|   +-- image_optimizer.py, clustering_worker.py, reranker_worker.py, gpu_utils.py
+-- tests/ { unit/, integration/, e2e/, gpu/, manual/, helpers/ } — 153 files
+-- packages/server/                # License Server (Hono + SQLite)
+-- packages/wrapper/               # NPM wrapper package (mirrors src/wrapper/)
+-- packages/checkout-worker/       # Cloudflare Worker + D1 (Stripe checkout, secrets bootstrap)
+-- Dockerfile, Dockerfile.models, docker-compose.yml
+-- scripts/ { docker-entrypoint.sh, docker-healthcheck.sh, docker-release.sh, docker-release-models.sh, e2e-manual-test.mjs }
+-- docs2/, tasks/, config/, package.json, tsconfig.json, vitest.config.ts, eslint.config.mjs, CLAUDE.md
</directory_structure>

<!-- SECTION 6: CODING STANDARDS -->
<coding_standards>
  <naming>
    TS files: kebab-case | Variables: camelCase, constants: SCREAMING_SNAKE | Functions: camelCase verb-first |
    Types: PascalCase | MCP tools: snake_case with ocr_ prefix | Python: snake_case + type hints |
    REST paths: kebab-case under /api/ | System DBs: _ prefix (_registry.db, _license.db)
  </naming>
  <file_org>One tool module per file in src/tools/. One service domain per dir in src/services/. Interfaces in src/models/. Files &lt;500 lines. Tests mirror source structure. NEVER save to root folder.</file_org>
  <tool_handler_pattern>
    1. validateInput(ZodSchema, request.params)
    2. Business logic (call services, never inline complex logic)
    3. formatResponse(successResult({ data, next_steps })) OR handleError(error) at boundary only
    Every successResult() includes next_steps: {tool, description}[] with tags: [ESSENTIAL] [CRITICAL] [PROCESSING] [STATUS] [ANALYSIS] [SEARCH] [SETUP] [MANAGE] [DESTRUCTIVE]
  </tool_handler_pattern>
  <python_bridge>
    Python outputs JSON to stdout, logs to stderr. Never hardcode python3 — platform detect: python (Win) vs python3 (Unix).
    resolve_device('auto')→CUDA>MPS>CPU. gpu_utils.py sets os.environ["TORCH_DEVICE"] to resolved device string.
    Daemons: spawn once, serialize via promise lock, auto-respawn. Non-daemons: spawn per call.
    Python deps: marker-pdf and chandra-ocr installed with --no-deps to avoid openai version conflict. Transitive deps listed explicitly in requirements.txt.
  </python_bridge>
  <error_handling>
    Tool boundary = ONLY place errors become structured responses. Every catch: re-throw, throw with context, OR console.error()+handleError().
    MCPError.fromUnknown() preserves .details/.code. withDatabaseOperation() for DB race protection.
    Parse Python stderr with worker name+input. Include: what, why, input, paths, IDs.
  </error_handling>
  <error_classes>
    MCPError (tool-level), VectorError (sqlite-vec), EmbeddingError, OCRError (Marker: OCR_FILE_ERROR|OCR_TIMEOUT|OCR_MODEL_ERROR|OCR_GPU_ERROR), VLMError (Chandra), InsufficientBalanceError ($0→doc stays 'pending').
    isTransientError() classifies: TIMEOUT/GPU/MODEL=transient (doc stays pending), FILE=permanent (doc fails).
  </error_classes>
</coding_standards>

<!-- SECTION 7: ANTI-PATTERNS (FORBIDDEN) -->
<anti_patterns>
  <!-- Data Integrity -->
  <forbidden id="AP-01">Store data without provenance record</forbidden>
  <forbidden id="AP-02">Use cloud APIs for processing — local models only</forbidden>
  <!-- Error Handling -->
  <forbidden id="AP-03">Fallback/degradation in catch blocks — throw with context</forbidden>
  <forbidden id="AP-04">Catch and swallow errors — re-throw or propagate</forbidden>
  <forbidden id="AP-05">Return empty/default data on failure — throw</forbidden>
  <forbidden id="AP-06">try{newWay}catch{oldWay} backwards-compat — remove old paths</forbidden>
  <forbidden id="AP-07">||defaultValue to mask undefined — check explicitly</forbidden>
  <!-- Testing -->
  <forbidden id="AP-08">Mock databases/operations — use real DBs, real ops, real verification</forbidden>
  <!-- Performance -->
  <forbidden id="AP-09">Embed one-at-a-time — batch with batch_size=64 (max 100)</forbidden>
  <forbidden id="AP-10">Process logos/icons with VLM — filter with relevance heuristics first</forbidden>
  <forbidden id="AP-11">Open every .db to list databases — query _registry.db</forbidden>
  <forbidden id="AP-12">VLM concurrency >2 — daemon is single-threaded, >2 just queues</forbidden>
  <!-- Database -->
  <forbidden id="AP-13">Leave FK ON during schema migration — PRAGMA foreign_keys=OFF during table recreation</forbidden>
  <!-- Protocol -->
  <forbidden id="AP-14">console.log() in TypeScript — stdout is JSON-RPC</forbidden>
  <!-- Docker -->
  <forbidden id="AP-15">nvidia/cuda as Docker base — causes dual cuBLAS conflict with PyTorch pip wheels on Blackwell GPUs</forbidden>
</anti_patterns>

<!-- SECTION 8: SECURITY REQUIREMENTS -->
<security_requirements>
  <!-- Input Validation -->
  <rule id="SEC-01">Validate all MCP inputs with Zod via validateInput()</rule>
  <rule id="SEC-02">sanitizePath(): resolve absolute, reject '..', validate against allowed dirs</rule>
  <rule id="SEC-03">Parameterized SQL queries only, never string concat</rule>
  <!-- Auth -->
  <rule id="SEC-04">MCP endpoints require X-License-Key (SHA-256 hash) except /health</rule>
  <rule id="SEC-05">Dashboard endpoints require Authorization: Bearer session token</rule>
  <rule id="SEC-06">MCP binds 127.0.0.1 (localhost); 0.0.0.0 in Docker only</rule>
  <rule id="SEC-07">Provision rate limit: 3/min/IP + 2/5min/machine_id (dual-layer)</rule>
  <!-- Secrets -->
  <rule id="SEC-08">Never hardcode secrets in source</rule>
  <rule id="SEC-09">Never commit .env files</rule>
  <rule id="SEC-10">5 secrets: SESSION_SECRET, LICENSE_SIGNING_KEY, LICENSE_PUBLIC_KEY, WORKER_AUTH_SECRET, WEBHOOK_SHARED_SECRET. Source: Cloudflare Worker bootstrap (/v1/secrets/bootstrap via SECRETS_MASTER_KEY) or Docker entrypoint local generation.</rule>
  <rule id="SEC-11">Dashboard started with `env -i` whitelist — LICENSE_SIGNING_KEY, WORKER_AUTH_SECRET, WEBHOOK_SHARED_SECRET, LICENSE_PUBLIC_KEY stripped from dashboard process</rule>
  <!-- Crypto -->
  <rule id="SEC-12">Ed25519 signed license tokens for offline verification</rule>
  <rule id="SEC-13">HMAC-signed balances — tampered=FATAL on startup. verifyBalance() called at EVERY balance mutation.</rule>
  <rule id="SEC-14">SHA-256 content hashes on all provenance records</rule>
  <rule id="SEC-15">Stripe webhook verification via WEBHOOK_SHARED_SECRET</rule>
  <!-- Privacy -->
  <rule id="SEC-16">All inference runs locally on GPU — zero cloud APIs</rule>
  <rule id="SEC-17">No document content leaves the machine</rule>
  <!-- Infra -->
  <rule id="SEC-18">DB files mode 600</rule>
  <rule id="SEC-19">WAL mode for SQLite</rule>
  <rule id="SEC-20">CORS restricted to localhost</rule>
  <rule id="SEC-21">Docker: OCR_PROVENANCE_ALLOWED_DIRS restricts file access</rule>
</security_requirements>

<!-- SECTION 9: PERFORMANCE BUDGETS -->
<performance_budgets>
  <ocr per_page="~2s" large_doc="~340s/160pg" startup="~120s"/>
  <vlm per_image="3-8s" startup="~120s"/>
  <embedding gpu="60-120 chunks/s" cpu="~20 chunks/s" batch="64 (max 100)"/>
  <search vector="&lt;20ms/100K" bm25="&lt;10ms" hybrid="&lt;500ms (BM25+vector+RRF+rerank)"/>
  <provenance verify="&lt;100ms/chain"/>
  <registry listing="&lt;1ms" fts="&lt;5ms" reconciliation="&lt;100ms/100 DBs"/>
</performance_budgets>

<!-- SECTION 10: TESTING REQUIREMENTS -->
<testing_requirements coverage="80% line (unit)">
  <rules>No mocks — real DBs, real ops. Tests MUST fail when functionality breaks. Clean up temp artifacts. After code change: kill→build→test. Kill daemon processes in resetState() to free GPU.</rules>
  <categories>
    unit (80%): chunking, hashing, provenance, CRUD, registry, Zod, error classes |
    integration: OCR/VLM/GPU embedding pipeline, search, registry reconciliation |
    device: CUDA/MPS/CPU detection, throughput, fallback |
    e2e: ingestion-to-search, multi-database |
    docker: entrypoint, healthcheck, services, ports, secrets |
    license: charge/confirm/refund, $0 rejection, HMAC, rate limiting
  </categories>
  <commands>npm test | npm run test:unit | npm run test:integration | npm run test:gpu | npm run test:manual | npm run check (typecheck+lint:all+test) | npm run lint | npm run lint:py | npm run format:check | npm run typecheck</commands>
</testing_requirements>

<!-- SECTION 11: BUILD & VERIFY -->
<build_and_verify>
  <sequence>1. pkill -f "dist/bin.js" (SEPARATE command) 2. npm run build (0 errors) 3. npm test (0 failures) 4. npm run lint (optional)</sequence>
  <rule>After ANY code change: kill→build→test. If tests fail, fix root cause — never skip.</rule>
  <docker_build>docker build --build-context dashboard=../ocrprovenance-cloud -t leapable/ocr-provenance-mcp:latest . | Release: ./scripts/docker-release.sh | Models: ./scripts/docker-release-models.sh</docker_build>
  <models_build>docker build -f Dockerfile.models --build-context hf_models=$HOME/.cache/huggingface/hub --build-context surya_models=$HOME/.cache/datalab/models -t leapable/ocr-provenance-models:v1 . | Zero network downloads — all models copied from host caches.</models_build>
</build_and_verify>

<!-- SECTION 12: REST API -->
<rest_api>
  <endpoint path="/health" method="GET" auth="none">Health check (probes all 3 services in Docker). Returns {status: "ok"|"operational"|"degraded"}</endpoint>
  <endpoint path="/api/overview" auth="license_key">Database overview</endpoint>
  <endpoint path="/api/databases" auth="license_key">List databases</endpoint>
  <endpoint path="/api/databases/:name/stats" auth="license_key">DB stats</endpoint>
  <endpoint path="/api/databases/:name/documents" auth="license_key">Paginated documents</endpoint>
  <endpoint path="/api/databases/:name/health" auth="license_key">Health gaps</endpoint>
  <endpoint path="/api/databases/:name/provenance-tree" auth="license_key">Provenance chain</endpoint>
  <endpoint path="/api/databases/:name/quality-heatmap" auth="license_key">Quality heatmap</endpoint>
  <endpoint path="/api/databases/:name/embedding-coverage" auth="license_key">Embedding coverage</endpoint>
  <endpoint path="/api/databases/:name/search-readiness" auth="license_key">Search readiness</endpoint>
  <endpoint path="/api/databases/:name/context-composition" auth="license_key">Context breakdown</endpoint>
  <endpoint path="/api/databases/:name/trends" auth="license_key">Processing trends</endpoint>
  <endpoint path="/api/databases/:name/chunks" auth="license_key">Chunk list</endpoint>
  <endpoint path="/api/databases/:name/clusters" auth="license_key">Cluster list</endpoint>
  <endpoint path="/api/databases/:name/images" auth="license_key">Image list</endpoint>
  <endpoint path="/api/activity" auth="license_key">Recent activity</endpoint>
  <endpoint path="/api/status" auth="license_key">System status</endpoint>
  <endpoint path="/api/context-summary" auth="license_key">Cross-database context</endpoint>
  <endpoint path="/api/recommendations" auth="license_key">AI recommendations</endpoint>
  <endpoint path="/api/license" auth="license_key">Billing/license status</endpoint>
  <endpoint path="/api/checkout" method="POST" auth="license_key">Stripe checkout (proxied to checkout worker)</endpoint>
  <endpoint path="/api/checkout/callback" method="GET" auth="none">Stripe success redirect</endpoint>
  <endpoint path="/mcp" method="POST" auth="license_key">MCP protocol (SSE)</endpoint>
</rest_api>

<!-- SECTION 13: MCP TOOL GROUPS -->
<mcp_tools count="151" modules="30">
  <g module="database.ts" n="5">Database (core)</g>
  <g module="database-management.ts" n="8">Database Management</g>
  <g module="portability.ts" n="7">Portability</g>
  <g module="sharing.ts" n="2">Sharing</g>
  <g module="ingestion.ts" n="7">Ingestion</g>
  <g module="search.ts" n="7">Search</g>
  <g module="documents.ts" n="10">Documents</g>
  <g module="provenance.ts" n="6">Provenance</g>
  <g module="vlm-local.ts" n="3">VLM (Local)</g>
  <g module="images.ts" n="8">Images</g>
  <g module="extraction.ts" n="1">Extraction</g>
  <g module="extraction-structured.ts" n="3">Structured Extraction</g>
  <g module="reports.ts" n="8">Reports</g>
  <g module="comparison.ts" n="6">Comparison</g>
  <g module="clustering.ts" n="7">Clustering</g>
  <g module="chunks.ts" n="4">Chunks</g>
  <g module="embeddings.ts" n="4">Embeddings</g>
  <g module="tags.ts" n="6">Tags</g>
  <g module="intelligence.ts" n="5">Intelligence</g>
  <g module="health.ts" n="1">Health</g>
  <g module="maintenance.ts" n="1">Maintenance</g>
  <g module="users.ts" n="2">Users</g>
  <g module="collaboration.ts" n="11">Collaboration</g>
  <g module="workflow.ts" n="8">Workflow</g>
  <g module="clm.ts" n="9">CLM</g>
  <g module="compliance.ts" n="3">Compliance</g>
  <g module="events.ts" n="6">Events</g>
  <g module="config.ts" n="2">Config</g>
  <g module="dashboard.ts" n="2">Dashboard</g>
  <g module="license.ts" n="1">License</g>
</mcp_tools>

<!-- SECTION 14: PYTHON WORKERS -->
<python_workers>
  <w file="ocr_worker_local.py" daemon="true">Marker-pdf OCR</w>
  <w file="vlm_worker_local.py" daemon="true">Chandra VLM</w>
  <w file="embedding_worker.py" daemon="true">nomic-embed-text-v1.5</w>
  <w file="image_extractor.py">PyMuPDF images</w>
  <w file="docx_image_extractor.py">Office doc images</w>
  <w file="image_optimizer.py">PIL compression</w>
  <w file="clustering_worker.py">HDBSCAN/agglom/k-means</w>
  <w file="reranker_worker.py">MS-Marco reranking</w>
  <w file="gpu_utils.py">Device detection+setup (sets TORCH_DEVICE env var to resolved device)</w>
</python_workers>

<!-- SECTION 15: CONFIGURATION -->
<configuration>
  <setting name="MCP_TRANSPORT" default="http">http|stdio. HTTP primary, stdio deprecated.</setting>
  <setting name="MCP_HTTP_PORT" default="3366"/>
  <setting name="MCP_SESSION_TTL" default="3600">seconds</setting>
  <setting name="TORCH_DEVICE" default="auto">auto|cuda|mps|cpu</setting>
  <setting name="EMBEDDING_DEVICE" default="auto">auto|cuda|mps|cpu</setting>
  <setting name="OCR_MAX_CONCURRENT" default="2">1-10</setting>
  <setting name="OCR_TIMEOUT" default="1800000">ms (30 min)</setting>
  <setting name="CHANDRA_METHOD" default="hf">hf|vllm</setting>
  <setting name="VLM_CONCURRENCY" default="2" max="2">Single-threaded daemon; >2 just queues</setting>
  <setting name="MODEL_CACHE_DIR" default="~/.cache/datalab/models"/>
  <setting name="CHANDRA_MODEL_PATH" default="(HuggingFace default)"/>
  <setting name="EMBEDDING_MODEL_PATH" default="./models/nomic-embed-text-v1.5"/>
  <setting name="OCR_LICENSE_KEY" default="(auto-provisioned)"/>
  <setting name="OCR_LICENSE_SERVER" default="https://license.ocrprovenance.com"/>
  <setting name="CHECKOUT_API_URL" default="https://api.ocrprovenance.com">Cloudflare checkout worker URL</setting>
  <setting name="OCR_PROVENANCE_ALLOWED_DIRS">Extra allowed file dirs</setting>
  <setting name="OCR_SPENDING_LIMIT_CENTS">Monthly limit (server-enforced)</setting>
  <setting name="OCR_PROVENANCE_HOST_HOME">Host home for Docker path translation</setting>
  <principle>No required env vars. All defaults sensible. License auto-provisions on first run.</principle>
</configuration>

<!-- SECTION 16: KNOWN GOTCHAS -->
<known_gotchas>
  <g id="01" sev="high">MCP process is dist/bin.js not dist/index.js → pkill -f "dist/bin.js"</g>
  <g id="02" sev="high">pkill+build in one command kills build → run pkill SEPARATELY first</g>
  <g id="03" sev="med">Circular FK: embeddings.image_id↔images.vlm_embedding_id → NULL vlm_embedding_id before deleting embeddings</g>
  <g id="04" sev="med">FTS5 external content join uses rowid → c.rowid=chunks_fts.rowid (NOT c.id UUID)</g>
  <g id="05" sev="med">FTS5 rebuild creates ghost rows → use delete-all+re-insert (NOT rebuild)</g>
  <g id="06" sev="med">Windows: python3 not found → auto-detect: python (Win) vs python3 (Unix)</g>
  <g id="07" sev="low">MCP client caches tool list → new tools need server restart</g>
  <g id="08" sev="high">GPU VRAM exhaustion loading VLM after OCR → getMarkerClient().destroy() before VLM to free ~4GB for Chandra (~18GB)</g>
  <g id="09" sev="med">max_pages vs page_range naming → TS max_pages→Python page_range conversion in bridge</g>
  <g id="10" sev="med">Registry name collision → _prefix (_registry.db), lives outside databases/</g>
  <g id="11" sev="high">dirname('/data') returns '/' in Docker → when env var IS the dir, use directly (not dirname)</g>
  <g id="12" sev="low">dotenv.config() prints to stdout in v17 → use {quiet:true}</g>
  <g id="13" sev="high">nvidia/cuda Docker base + PyTorch pip wheel = dual cuBLAS conflict on Blackwell GPUs → use python:3.12-slim-bookworm base</g>
  <g id="14" sev="med">Wrapper mirrors: src/wrapper/ and packages/wrapper/src/ contain identical code — changes must be synced to both</g>
  <g id="15" sev="med">D1 exec() crashes on multi-statement SQL → use db.batch([db.prepare(...)]) instead</g>
</known_gotchas>

<!-- SECTION 17: DOCKER DEPLOYMENT -->
<docker_deployment>
  <models_base image="leapable/ocr-provenance-models:v1" size="~24GB" build="Dockerfile.models" base="python:3.12-slim-bookworm" push="rare (model updates only)">
    PyTorch+Marker+Surya+Chandra. MODELS_VERSION file at repo root (currently "1"), scripts add "v" prefix.
    Build requires --build-context hf_models=$HOME/.cache/huggingface/hub --build-context surya_models=$HOME/.cache/datalab/models.
    Zero network downloads — all models copied from host caches.
    ONE image for GPU+CPU: CUDA PyTorch auto-degrades to CPU on non-GPU systems. No separate GPU/CPU images.
  </models_base>
  <app image="leapable/ocr-provenance-mcp:latest" size="~500MB" push="every release">
    Node 20+compiled TS+Python venv+license server. FROM models-image (not COPY --from) preserves Docker layer caching.
  </app>
  <gpu_strategy>
    Unified container: docker-compose.yml sets runtime: nvidia + NVIDIA_VISIBLE_DEVICES=all + deploy.resources.reservations.devices.
    Wrapper: tries --gpus all first, falls back to CPU if NVIDIA runtime unavailable. No --gpu CLI flag (removed in v1.2.38).
  </gpu_strategy>
  <entrypoint script="docker-entrypoint.sh">
    Bootstrap secrets (from Cloudflare Worker or generate locally)→stable machine ID at /data/.machine_id→set URL defaults→pre-flight checks→start 3 services→process monitor (FATAL on failure).
    Dashboard started with `env -i` whitelist stripping 4 secrets (LICENSE_SIGNING_KEY, LICENSE_PUBLIC_KEY, WORKER_AUTH_SECRET, WEBHOOK_SHARED_SECRET).
  </entrypoint>
  <healthcheck script="docker-healthcheck.sh">Checks MCP:3366 + License:3000 + Dashboard:3367 independently. Fails if any down.</healthcheck>
  <volumes>$HOME→/host:ro (file ingestion) | ~/ocr-provenance-exports→/export:rw (exports) | ocr-data→/data (persistent state)</volumes>
  <machine_id>Stable, persisted to /data/.machine_id — same key across container recreations</machine_id>
</docker_deployment>

<!-- SECTION 18: AI AGENT NAVIGATION -->
<ai_agent_navigation>
  <protocol>Every tool response includes next_steps: {tool, description}[]. Context-aware suggestions. compact=true = 77% token reduction.</protocol>
  <tags>[ESSENTIAL]=core workflow [CRITICAL]=DB discovery [PROCESSING]=computation/slow [STATUS]=read-only [ANALYSIS]=deep inspect [SEARCH]=search [SETUP]=one-time [MANAGE]=non-destructive [DESTRUCTIVE]=permanent deletion</tags>
</ai_agent_navigation>

</constitution>
