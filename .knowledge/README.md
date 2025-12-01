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

Tracks resolved documentation sections using content hashes.

| Column | Type | Description |
|--------|------|-------------|
| id | string | Unique identifier (UUID) |
| original_text_hash | string | SHA-256 hash of original text content |
| split_text_hash | string | SHA-256 hash of split text content |
| source_file_hash | string | SHA-256 hash of source file at resolution time |
| split_file_hash | string | SHA-256 hash of split file at resolution time |
| resolved_at | string | ISO 8601 timestamp of resolution |

### comparisons/*.csv

Flattened comparison results (one file per pattern, e.g., `api-patterns.csv`).

| Column | Type | Description |
|--------|------|-------------|
| source_file | string | Path to the original source file |
| id | string | Section identifier from the original |
| origin_type | string | Type classification (e.g., "split", "original") |
| original_text | string | Text content from original file |
| split_file | string | Path to the split target file |
| split_text | string | Text content in split file |

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
