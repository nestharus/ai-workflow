# Document Ingestion Pipeline

This document describes the document ingestion pipeline for the atomic fact
extraction system. The pipeline converts raw documents into canonical UTF-8
strings with work region tracking, preparing them for Phase 3 Haiku
extraction.

## Overview

The document ingestion pipeline is **Phase 2** of the atomic fact extraction
system. It takes raw documents in various formats and produces:

1. A normalized **canonical UTF-8 string** suitable for fact extraction
2. **Work regions** tracking unprocessed text intervals
3. **Validation results** confirming ingestion quality

The pipeline ensures consistent text representation across all document types,
enabling reliable character offset tracking throughout the extraction
process.

## Supported Formats

### Text Files (.txt)

- Primary encoding: UTF-8
- Fallback encoding: latin-1 (for legacy files)
- Preserves original text content with normalization

### PDF Files (.pdf)

- Uses `pypdf` library for text extraction
- Extracts text from all pages, joining with newlines
- Removes PDF artifacts:
  - Form feed characters (`\f`)
  - Page numbers at line starts

### JSON Files (.json)

- Parses JSON structure using streaming parser (ijson)
- Extracts all scalar values (strings, numbers, booleans, nulls) with field
  names
- Removes braces, brackets, and JSON structural quotation marks; rewrites
  content as `key: value` lines
- Preserves quotation marks that are part of text content within string values
- Supports deeply nested structures (dicts and lists)

## Canonical String Normalization

The canonical string undergoes the following transformations to ensure
consistent representation:

| Transformation | Description |
|---|---|
| **Unicode NFC** | Text is normalized to NFC (Canonical Decomposition,
  followed by Canonical Composition) |
| **Whitespace normalization** | Multiple consecutive spaces and tabs
  collapse to a single space |
| **Line ending normalization** | `\r\n` (Windows) and `\r` (old Mac)
  convert to `\n` (Unix) |
| **Control character removal** | All control characters removed except
  `\n` (newline) and `\t` (tab) |
| **Trim whitespace** | Leading and trailing whitespace stripped from
  entire document |

These normalizations ensure that character offsets remain stable and
reproducible across different systems and processing runs.

## Work Regions

Work regions track which portions of the canonical string have been
processed for fact extraction.

### Initial State

Upon ingestion, `initialize_work_regions` creates `WorkRegion` entries based
on document size:

- **Empty documents** (canonical string is empty): Returns an empty list with
  no regions. This avoids creating zero-length regions where `start_char ==
  end_char`.
- **Small documents** (below `chunk_size`, default `DEFAULT_CHUNK_SIZE` =
  32000 chars): Creates a single WorkRegion covering [0,
  len(canonical_string))
- **Large documents**: Creates multiple contiguous, non-overlapping
  WorkRegion entries covering [0, len(canonical_string))

For large documents, regions are split at sentence boundaries to avoid
exceeding model context limits. Each region ID is suffixed with an index
(e.g., `{doc_id}_region_0`, `{doc_id}_region_1`, etc.).

**Note**: Anchoring and reconstruction validation operate across the entire
document and are not affected by chunk boundaries. Only the extraction phase
(searching for details) respects chunk boundaries for memory safety.

**Single region example** (small document):

```python
{
    "region_id": "text_sample_20250115T103000Z_region_0",
    "doc_id": "text_sample_20250115T103000Z",
    "start_char": 0,
    "end_char": 5000,  # Length of canonical string
    "is_processed": False,
    "created_at": "2025-01-15T10:30:00Z"
}
```

**Multiple region example** (large document with 80000 chars):

```python
[
    {
        "region_id": "text_sample_20250115T103000Z_region_0",
        "doc_id": "text_sample_20250115T103000Z",
        "start_char": 0,
        "end_char": 32000,      # First chunk: 0 to ~32000 (split at sentence boundary)
        "is_processed": False,
        "created_at": "2025-01-15T10:30:00Z"
    },
    {
        "region_id": "text_sample_20250115T103000Z_region_1",
        "doc_id": "text_sample_20250115T103000Z",
        "start_char": 32000,
        "end_char": 64000,      # Second chunk: contiguous with first
        "is_processed": False,
        "created_at": "2025-01-15T10:30:00Z"
    },
    {
        "region_id": "text_sample_20250115T103000Z_region_2",
        "doc_id": "text_sample_20250115T103000Z",
        "start_char": 64000,
        "end_char": 80000,      # Final chunk: may be smaller than chunk_size
        "is_processed": False,
        "created_at": "2025-01-15T10:30:00Z"
    }
]
```

**Chunking invariants:**

These invariants apply to **non-empty documents** only. Empty canonical
strings yield no regions (an empty list), avoiding zero-length entries where
`start_char == end_char`.

| Invariant | Description |
|---|---|
| **Non-empty output** | Non-empty documents always produce one or more
  regions |
| **Contiguous** | Each region's `start_char` equals the previous region's
  `end_char` |
| **Non-overlapping** | Regions never overlap; `end_char` is exclusive |
| **Complete coverage** | First region starts at 0, last region ends at
  `len(canonical_string)`, covering [0, len(canonical_string)) |
| **Positive length** | Every region has `start_char < end_char` (no
  zero-length regions) |
| **Sentence-aware** | Splits occur at sentence boundaries when possible
  (detected via stanza's neural tokenizer). If no sentence boundaries are
  found, falls back to splitting at `chunk_size` intervals |
| **Size-limited** | Each region is at most `chunk_size` characters (default
  32000). Set `chunk_size=0` to disable chunking |

### WorkRegion Fields

| Field | Type | Description |
|---|---|---|
| `region_id` | string | Unique identifier in format
  `{doc_id}_region_{index}` (e.g.,
  `text_sample_20250115T103000Z_region_0`) |
| `doc_id` | string | Document identifier this region belongs to |
| `start_char` | int | Inclusive start character offset into canonical
  string |
| `end_char` | int | Exclusive end character offset (must be greater
  than `start_char`) |
| `is_processed` | bool | False initially, True after extraction attempt |
| `created_at` | string | ISO 8601 timestamp when region was created |

Work regions enable iterative extraction and tracking of extraction progress
across the document.

## Validation

Four validation checks are performed per QA Strategy Step 1:

### encoding_valid

Verifies that the canonical string can successfully round-trip through UTF-8
encoding and decoding:

```python
encoded = canonical_string.encode("utf-8")
decoded = encoded.decode("utf-8")
encoding_valid = decoded == canonical_string
```

### offsets_valid

Confirms that all work region offsets fall within valid bounds:

- `0 <= start_char < end_char <= len(canonical_string)`
- `start_char` must be strictly less than `end_char` (zero-length regions
  are invalid)

### artifacts_removed

Checks that no problematic artifacts remain in the canonical string.

**Base checks (always performed):**

- No form feed characters (`\f`)
- No null bytes (`\x00`)

**Format-specific checks:**

When `source_is_json=True`, the validation also flags residual JSON structural syntax:

- Quoted keys with colons (e.g., `"key":`)
- Empty structures (`{}` or `[]`)
- Line-initial braces/brackets (lines starting with `{` or `[`)
- Comma-adjacent braces/brackets (e.g., `},{`, `],[`)

When `source_is_pdf=True`, the validation also flags PDF-specific artifacts:

- "Page X" or "Page X of Y" patterns (case-insensitive)
- Delimited page numbers (e.g., `- 5 -`, `[ 5 ]`, `( 5 )`)
- Isolated digit-only page numbers (1-4 digits) that are not part of
  consecutive numbered lists
- Repeated headers/footers that appear across multiple pages

These format flags (`source_is_json`/`source_is_pdf`) are set automatically
based on file extension during ingestion. They enable additional artifact
detection specific to each format, ensuring format-specific remnants are
surfaced via `artifacts_removed`.

### offset_mapping_valid

Verifies that the character-to-offset mapping used for canonicalization is
consistent and covers all region offsets without overlaps or gaps:

- The offset mapping array has the correct length (matches raw input length).
  **Note:** This length check is only enforced when `expected_raw_length` is
  provided to `validate_ingestion`; otherwise, the mapping length is not
  validated against the raw input.
- All non-negative values in the mapping are monotonically increasing
- The mapping covers the full canonical string range as a half-open interval
  `[0, len(canonical_string))`, meaning indices 0 through
  `len(canonical_string) - 1` must appear in the mapping values. The minimum
  mapped offset must be 0 and the maximum must be at least
  `len(canonical_string) - 1`.
- All work region `start_char` offsets must exist in the mapping's output
  values. Work region `end_char` offsets must either exist in the mapping
  values OR equal `len(canonical_string)`. This special case allows
  `end_char` to point one past the last character (the exclusive boundary)
  even when that position does not appear in the mapping.
- **Non-empty canonical strings must have at least one mapped offset.** If
  the canonical string is non-empty and every entry in the offset mapping is
  -1 (all characters removed), validation fails. This check applies even when
  `expected_raw_length` is provided and lengths match, ensuring that mapped
  content actually exists for non-empty output.

**Validation status when offset_mapping is None:**

When no offset mapping is provided, validation is **bypassed entirely**. The
Python API returns `True` for backward compatibility, but this should be
interpreted as **SKIPPED**, not as successful validation. CLI and diagnostic
output should display:

```text
offset_mapping_valid: SKIPPED (no mapping provided)
```

This explicitly indicates that validation was not performed, rather than
passed. The following checks are skipped when `offset_mapping=None`:

- **Length check**: Mapping length vs. expected raw input length (skipped)
- **Monotonicity check**: Non-removed entries must be non-decreasing (skipped)
- **Coverage check**: Mapping must span the half-open interval
  `[0, len(canonical_string))`, i.e., indices 0 through
  `len(canonical_string) - 1` (skipped)
- **Work region offset check**: All region `start_char` offsets must exist in
  mapping values; `end_char` must exist in mapping values OR equal
  `len(canonical_string)` (skipped)

Consumers should not assume these validations run without providing a
mapping. A `True` value when no mapping is provided does **not** indicate
successful validation; it only indicates that no validation was performed
(SKIPPED).

**Important:** Always provide the offset mapping to `validate_ingestion` to
enable full validation. The default `True` value when mapping is `None` is
for backward compatibility only and should be treated as SKIPPED, not as
successful validation.

## Usage Examples

### Basic Ingestion

```bash
# Ingest a text file
uv run knowledge.ingest-document --input docs/sample.txt --output .tmp/ingestion

# Ingest a PDF document
uv run knowledge.ingest-document --input docs/manual.pdf --output .tmp/ingestion

# Ingest a JSON file
uv run knowledge.ingest-document --input data/config.json --output .tmp/ingestion
```

### Dry Run Mode

Show what would be done without writing any files:

```bash
uv run knowledge.ingest-document --input docs/sample.txt --dry-run
```

Output:

```text
Would ingest: /path/to/docs/sample.txt
Format: .txt
Output directory: /path/to/.tmp/ingestion
Files to create:
  - {doc_id}_canonical.txt
  - {doc_id}_work_regions.json
  - {doc_id}_offset_mapping.json
  - {doc_id}_validation.json
```

### Validate Only Mode

Run validation checks without writing output files:

```bash
uv run knowledge.ingest-document --input docs/sample.txt --validate-only
```

Output:

```text
Validation Results:
  encoding_valid: PASS
  offsets_valid: PASS
  artifacts_removed: PASS
  offset_mapping_valid: PASS
```

### Custom Output Directory

```bash
uv run knowledge.ingest-document --input docs/sample.txt --output .tmp/custom_output
```

## Output Files

For each ingested document, the pipeline creates four files in the output directory:

### {doc_id}_canonical.txt

The normalized canonical string in UTF-8 encoding. This is the authoritative
text representation used for all character offset calculations.

Example content:

```text
This is the normalized document text.
All whitespace has been normalized.
Control characters have been removed.
```

### {doc_id}_work_regions.json

Work regions as a JSON array, ready for fact extraction processing. For
small documents, contains a single region; for large documents, contains
multiple contiguous regions (see [Initial State](#initial-state) for chunking
details):

```json
[
  {
    "region_id": "text_sample_20250115T103000Z_region_0",
    "doc_id": "text_sample_20250115T103000Z",
    "start_char": 0,
    "end_char": 32000,
    "is_processed": false,
    "created_at": "2025-01-15T10:30:00Z"
  },
  {
    "region_id": "text_sample_20250115T103000Z_region_1",
    "doc_id": "text_sample_20250115T103000Z",
    "start_char": 32000,
    "end_char": 45000,
    "is_processed": false,
    "created_at": "2025-01-15T10:30:00Z"
  }
]
```

### {doc_id}_offset_mapping.json

A JSON array mapping raw character offsets to canonical string offsets. Each
index in the array corresponds to a character position in the raw input text,
and the value at that index is the corresponding position in the canonical
string (or -1 if the character was removed during normalization).

This mapping enables tracing character positions from the original document
to the normalized canonical string, which is essential for maintaining source
attribution when facts are extracted.

Example content (for a short document):

```json
[0, 1, 2, 3, -1, 4, 5, 6, 7, 8]
```

In this example:
- Raw positions 0-3 map directly to canonical positions 0-3
- Raw position 4 was removed (e.g., collapsed whitespace), indicated by -1
- Raw positions 5-9 map to canonical positions 4-8

**Note:** When validating ingestion results, if no offset mapping is
provided, `offset_mapping_valid` defaults to `True` for backward
compatibility. However, this should be interpreted as **SKIPPED (no mapping
provided)**, not as successful validation. CLI output displays "SKIPPED (no
mapping provided)" to make this explicit. Always provide the offset mapping
for full validation. See the [offset_mapping_valid](#offset_mapping_valid)
section for details.

### {doc_id}_validation.json

Validation results confirming ingestion quality:

```json
{
  "encoding_valid": true,
  "offsets_valid": true,
  "artifacts_removed": true,
  "offset_mapping_valid": true
}
```

## Document ID Format

Document IDs follow the pattern: `{format}_{stem}_{timestamp}`

- `format`: File type indicator (`text`, `pdf`, `json`)
- `stem`: Original filename without extension
- `timestamp`: Generation timestamp in format `YYYYMMDDTHHMMSSZ`

Examples:
- `text_requirements_20250115T103000Z`
- `pdf_user_manual_20250115T103500Z`
- `json_config_20250115T104000Z`

## Integration

### Phase 1 Models

The pipeline uses data models from `atomic_fact_models.py`:

- `WorkRegion` dataclass for work region structure (provides `to_dict()`,
  `to_span()`, and dict-like `__getitem__` access)
- `work_region_to_json()` for JSON serialization (calls
  `WorkRegion.to_dict()`)

```python
from scripts.knowledge.atomic_fact_models import WorkRegion, work_region_to_json
```

### Phase 3 Extraction

Output from this pipeline feeds directly into Phase 3 Haiku extraction:

1. Read `{doc_id}_canonical.txt` as the source text
2. Load `{doc_id}_work_regions.json` to track extraction progress
3. Use character offsets from work regions for span creation

### CLI Pattern

The CLI follows the same pattern as `extraction_pipeline.py`:

- Uses `argparse` for command-line argument parsing
- Supports `--dry-run` for preview without changes
- Returns exit code 0 on success, 1 on error
- Paths can be absolute or relative to repository root

## References

- **Requirements**: `.tasks/plans/information extraction/requirements.md` lines 348-432
- **QA Strategy**: `.tasks/plans/information extraction/QA_strategy.md` lines 80-91
- **Phase 1 Models**: `scripts/knowledge/atomic_fact_models.py`
