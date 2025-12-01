# Knowledge Directory

This directory stores migration artifacts, comparison results, and resolution tracking
for documentation migrations.

## Directory Structure

```text
.knowledge/
├── originals/      # Timestamped copies of source files before migration
├── migrations/     # Migration task metadata (tasks.csv)
├── comparisons/    # Flattened CSV comparison results (replacing JSON .compare files)
├── resolutions/    # Hash-based resolution tracking (resolved.csv)
└── README.md       # This file
```

## CSV Schemas

### resolutions/resolved.csv

Tracks resolved documentation sections using content hashes and file paths.
Duplicate detection is based on (id, source_file, split_file) for path-level uniqueness.

| Column | Type | Description |
|--------|------|-------------|
| resolution_id | string | Unique identifier for this resolution record (UUID) |
| id | string | YAML element identifier being resolved |
| source_file | string | Relative path to the source YAML file |
| split_file | string | Relative path to the split YAML file |
| original_text_hash | string | SHA-256 hash of original text content |
| split_text_hash | string | SHA-256 hash of split text content |
| source_file_hash | string | SHA-256 hash of source file at resolution time |
| split_file_hash | string | SHA-256 hash of split file at resolution time |
| resolved_at | string | ISO 8601 basic format timestamp (YYYYMMDDTHHMMSSZ) |

### comparisons/*.csv

Flattened comparison results (one file per pattern, e.g., `api-patterns.csv`).

**Note**: Comparison CSVs are regenerated on each run of `uv run compare-yml-docs`.
Older data is intentionally discarded to ensure the CSV always reflects the current
state of the YAML files being compared.

| Column | Type | Description |
|--------|------|-------------|
| source_file | string | Path to the source file (original, split, or orphan depending on origin_type) |
| id | string | Section identifier from the source file |
| origin_type | string | Type classification: "original", "split_only", or "orphan" |
| original_text | string | Text content from source_file (see semantics below) |
| split_file | string | Path to the split target file (empty for split_only/orphan entries) |
| split_text | string | Text content in split file (empty for split_only/orphan entries) |

**`original_text` column semantics by `origin_type`**:

- `original`: Text from the original file that differs from or is missing in splits
- `split_only`: Text from a split file for an ID not found in the corresponding original
- `orphan`: Text from a file in a subdirectory with no corresponding original file

For `split_only` and `orphan` entries, `original_text` contains the source text from the
split/orphan file respectively, not from an original file. Query authors should filter by
`origin_type` when the distinction matters.

### migrations/tasks.csv

Migration task metadata for tracking progress.

| Column | Type | Description |
|--------|------|-------------|
| task_id | string | Unique task identifier (UUID) |
| original_file_ref | string | Reference to file in originals/ |
| pattern_name | string | Pattern being migrated (e.g., "api-patterns") |
| status | string | Task status (pending, in_progress, completed, failed) |
| created_at | string | ISO 8601 timestamp of task creation |
| validated_at | string | ISO 8601 timestamp of validation (nullable) |

## Hash Algorithm

All hash fields use **SHA-256** for content hashing.

## Timestamp Format

All timestamps use **ISO 8601** format: `YYYY-MM-DDTHH:MM:SS`

## DuckDB Queries

These CSV files are designed for efficient querying via DuckDB. Example:

```sql
SELECT * FROM read_csv_auto('.knowledge/resolutions/resolved.csv')
WHERE resolved_at > '2025-01-01';
```

## Git Tracking

- Directory structure (via `.gitkeep` files) is tracked
- `README.md` is tracked
- Generated data files (`*.csv`, `*.yml`, `*.yaml`) are ignored via `.gitignore`
- DuckDB database file (`knowledge.duckdb`) is ignored
