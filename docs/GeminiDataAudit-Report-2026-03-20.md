# GeminiDataAudit — Full Pipeline Audit Report

> **Date**: 2026-03-20 | **Database**: GeminiDataAudit | **Version**: v1.2.64 | **Files**: 17 attempted, 15 ingested

## Executive Summary

17 files covering all supported file types were ingested and processed through the full OCR pipeline. 15 succeeded, 2 were rejected at upload (magic byte mismatch), 1 was deduplicated. Processing completed in 168 seconds. All 544 chunks have embeddings. 8 images analyzed by VLM. Provenance chains intact.

**Critical findings**: 3 red flags identified, 2 are working-as-designed, 1 is a data quality issue in the test files.

---

## 1. Ingestion Results

| Metric | Value |
|--------|-------|
| Files attempted | 17 |
| Successfully uploaded | 14 (+ 1 from prior test) |
| Skipped (dedup) | 1 |
| Rejected (magic byte) | 2 |
| Processing time | 167.8 seconds |
| Final document count | 15 |
| Total chunks | 544 |
| Total embeddings | 544 |
| Total images | 8 |
| VLM descriptions | 8 |
| Database size | 22.5 MB |
| Average quality score | 4.67 / 5.0 |

### File Type Coverage

| Type | File | Status | Pages | Chunks | Embeddings | Images |
|------|------|--------|-------|--------|------------|--------|
| xlsx | Audit Trail Report...COLLEEN BOSTON...xlsx | complete | 228 | 478 | 478 | 0 |
| csv | benchmark_billing_data.csv | complete | 1 | 1 | 1 | 0 |
| txt | benchmark_clinical_report.txt | complete | 3 | 4 | 4 | 0 |
| bmp | benchmark_clinical_scan.bmp | complete | 1 | 5 | 6 | 1 |
| gif | benchmark_clinical_scan.gif | complete | 1 | 5 | 6 | 1 |
| jpeg | benchmark_clinical_scan.jpeg | complete | 1 | 5 | 6 | 1 |
| jpg | benchmark_clinical_scan.jpg | complete | 1 | 5 | 6 | 1 |
| png | benchmark_clinical_scan.png | complete | 1 | 5 | 6 | 1 |
| tif | benchmark_clinical_scan.tif | complete | 1 | 5 | 6 | 1 |
| tiff | benchmark_clinical_scan.tiff | complete | 1 | 5 | 6 | 1 |
| webp | benchmark_clinical_scan.webp | complete | 1 | 5 | 6 | 1 |
| pdf | benchmark_lab_billing.pdf | complete | 4 | 4 | 4 | 0 |
| xls | benchmark_lab_billing.xls | complete | 2 | 2 | 2 | 0 |
| md | benchmark_protocol_spec.md | complete | 3 | 10 | 10 | 0 |
| pptx | benchmark_research_presentation.pptx | complete | 2 | 5 | 5 | 0 |
| **doc** | benchmark_consent_form.doc | **REJECTED** | - | - | - | - |
| **ppt** | benchmark_research_presentation.ppt | **REJECTED** | - | - | - | - |

---

## 2. Red Flags Found

### RED FLAG 1: Deduplication on Re-Upload (WORKING AS DESIGNED)

**What happened**: `benchmark_clinical_report.txt` was uploaded in a prior single-file test, then included again in the batch upload. The system detected the SHA-256 hash duplicate and skipped it.

**Evidence**:
```
SKIPPED: benchmark_clinical_report.txt
Reason: Duplicate content (sha256:05c082c3... already exists as benchmark_clinical_report.txt)
```

**Assessment**: This is **correct behavior**. The dedup system prevents the same file from being ingested twice within the same database. The SHA-256 hash comparison is the right mechanism.

**Note**: This is likely the deduplication the user observed yesterday. If files are uploaded multiple times (e.g., re-running ingestion on the same directory), this dedup will kick in. The system is doing the right thing — preventing duplicate processing and storage.

### RED FLAG 2: Magic Byte Rejection of .doc and .ppt Files (CORRECT REJECTION — BAD TEST DATA)

**What happened**: `benchmark_consent_form.doc` and `benchmark_research_presentation.ppt` were rejected at upload with "File content does not match expected type for .doc/.ppt (magic byte mismatch)."

**Root cause investigation**:
```
$ xxd benchmark_consent_form.doc | head -1
00000000: 504b 0304 ...  (PK header = ZIP format)

$ file benchmark_consent_form.doc
Microsoft Word 2007+
```

Both files start with `PK` (ZIP magic bytes `50 4B 03 04`), which is the Office Open XML format (.docx/.pptx). However, they have legacy `.doc`/`.ppt` extensions. Legacy Office files should start with `D0 CF 11 E0` (OLE2 compound document format).

**Assessment**: The system **correctly rejected** these files. They are mislabeled — they're actually `.docx` and `.pptx` files with wrong extensions. The magic byte validator is working as designed to prevent format confusion.

**Fix**: Rename the files to their correct extensions:
- `benchmark_consent_form.doc` → `benchmark_consent_form.docx`
- `benchmark_research_presentation.ppt` → `benchmark_research_presentation.pptx`

### RED FLAG 3: Embedding Count Mismatch on Image Files (WORKING AS DESIGNED)

**What happened**: All 8 image-type documents show `chunks=5, embeddings=6` — one more embedding than chunks.

**Root cause**: The extra embedding comes from the VLM (Vision Language Model) analysis. The pipeline for image files is:
1. Marker-pdf OCR extracts text from the image → creates chunks (5) → embeds them (5 embeddings)
2. VLM (Chandra) analyzes the image visually → creates a VLM description → embeds that description (1 embedding)

Total: 5 chunk embeddings + 1 VLM description embedding = 6 embeddings.

**Evidence**:
```
BMP document embeddings (6 total):
  chunk      "# ST. AUGUSTINE MEDICAL CENTER  ## CLINICAL ASSESSMENT REPOR..."
  chunk      "## VITAL SIGNS:  | Parameter |               |             |..."
  chunk      "## LABORATORY RESULTS (03/03/2026):  - * BNP: 1,847 pg/mL..."
  chunk      "## MEDICATIONS:  - 1. Lisinopril 20mg PO daily..."
  chunk      "### ASSESSMENT:  - 1. Acute-on-chronic systolic heart failur..."
  image/VLM  "The image displays a standard 12-lead ECG strip, labeled ECG..."
```

**Assessment**: This is **correct behavior**. The VLM embedding is a separate path in the provenance chain (depth 4: IMAGE → VLM_DESCRIPTION → EMBEDDING). The mismatch is expected and documented in the architecture.

---

## 3. Provenance Chain Analysis

### Chain Structure

```
Depth 0: DOCUMENT              15 records (one per file)
Depth 1: OCR_RESULT            15 records (one per file)
Depth 2: CHUNK                544 records
Depth 2: IMAGE                  8 records (one per image file)
Depth 3: EMBEDDING            544 records (chunk embeddings)
Depth 3: VLM_DESCRIPTION       8 records (image descriptions)
Depth 4: EMBEDDING              8 records (VLM text embeddings)

Total provenance records: 1,142
```

### Chain Integrity

- **Orphan records** (parent_id pointing to non-existent provenance): **0**
- **Documents without provenance root**: **0**
- **Chain hash coverage**: All provenance records have `chain_hash` and `content_hash` set
- **Root document linkage**: All records have `root_document_id` set (self-referential at depth 0)

### Naming Convention Note

The `provenance.root_document_id` column references `provenance.id` at depth 0 (the provenance root), NOT `documents.id`. This is by design:
- To get all provenance for a document: `WHERE root_document_id = (SELECT provenance_id FROM documents WHERE id = ?)`
- The depth-0 provenance record is self-referential: `root_document_id = id`

---

## 4. OCR Consistency Across Image Formats

All 8 image files contain the same visual content (a clinical assessment report scan) in different formats. OCR results vary slightly:

| Format | Text Length | Notes |
|--------|------------|-------|
| BMP | 1,907 chars | Baseline |
| GIF | 1,974 chars | +67 chars vs BMP |
| JPEG | 1,938 chars | +31 chars vs BMP |
| JPG | 1,941 chars | +34 chars vs BMP |
| PNG | 1,946 chars | +39 chars vs BMP |
| TIF | 1,946 chars | Identical to PNG |
| TIFF | 1,946 chars | Identical to PNG and TIF |
| WebP | 1,936 chars | +29 chars vs BMP |

**Identical OCR results**: PNG = TIF = TIFF (lossless formats produce identical text)
**Slight variations**: BMP, GIF, JPEG, JPG, WebP differ due to compression artifacts affecting OCR recognition

**All file hashes are unique** — no byte-identical files despite same visual content. This is correct since each format encodes pixels differently.

---

## 5. Spreadsheet Processing

### XLSX (228 pages, 478 chunks)
The Audit Trail Report (1MB XLSX) was processed into 228 pages using the spreadsheet-direct conversion path (50 rows per page). All 478 chunks have embeddings. This is the largest document in the set.

### XLS (2 pages, 2 chunks)
`benchmark_lab_billing.xls` with 2 sheets (Lab Results + Billing Summary) processed correctly via the xlrd direct path.

### CSV (1 page, 1 chunk)
`benchmark_billing_data.csv` with 12 columns processed as a single markdown table chunk. All Unicode characters preserved (María Elena, Thanh-Hà, François, Дмитриев, Анна, 田中, 太郎).

---

## 6. Embedding Coverage

**100% coverage** — all 544 chunks have embeddings. Zero pending, zero failed.

| Document | Chunks | Embedded | Coverage |
|----------|--------|----------|----------|
| Audit Trail XLSX | 478 | 478 | 100% |
| All others | 66 | 66 | 100% |
| **Total** | **544** | **544** | **100%** |

---

## 7. Recommendations

1. **Rename mislabeled test files**: `benchmark_consent_form.doc` → `.docx` and `benchmark_research_presentation.ppt` → `.pptx` to match their actual format.

2. **Consider semantic dedup for image variants**: The 8 image files produce nearly identical OCR text but are stored as separate documents. A future feature could detect visually similar documents and flag them, even when file hashes differ.

3. **The dedup behavior on re-upload is correct** — if users report this as unexpected, the UI should surface a clear message about why a file was skipped (it already does in the upload response).

---

## 8. Test Environment

- **OCR Provenance MCP**: v1.2.64
- **Docker Image**: leapable/ocr-provenance-mcp:1.2.64
- **Schema Version**: 33
- **Tools Count**: 153
- **GPU**: Available (CUDA)
- **Models**: Marker-pdf 1.10.2, Chandra 0.1.8, nomic-embed-text-v1.5
