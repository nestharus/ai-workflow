# Test Reorganization Process

This document describes the process for reorganizing test files from `scripts/tests/` into
`scripts/tests/unit/`, `scripts/tests/component/`, and `scripts/tests/integration/` based on
call graph analysis.

## Overview

The reorganization uses call graph analysis to classify tests:

- **Unit tests**: 0-1 project functions in the unmocked call graph → `unit/`
- **Component tests**: >1 project functions in the unmocked call graph → `component/`
- **Integration tests**: Unmocked calls to I/O modules (anyio, httpx, redis, etc.) → `integration/`
- **Mixed files**: Split into separate files per classification
- **Original files are NEVER deleted** - they remain for comparison and rollback

### Classification Rules

1. **Integration** (checked first): Test has unmocked calls to integration modules
   - I/O: `anyio`, `trio`, `curio`
   - HTTP: `httpx`, `requests`, `aiohttp`
   - Database: `redis`, `sqlalchemy`, `asyncpg`
   - Cloud: `boto3`, `google.cloud`
2. **Unit**: 0-1 project functions called (after excluding mocked calls)
3. **Component**: >1 project functions called (after excluding mocked calls)

## Step 1: Get Baseline Counts

Before reorganizing, record the baseline line count:

```bash
uv run python -m scripts.dev.count_test_lines scripts/tests/ --verify-syntax --json > baseline.json
```

Expected output:
```json
{
  "path": "scripts/tests",
  "total_lines": <number>,
  "total_functions": <number>,
  "syntax_valid": true,
  "syntax_errors": []
}
```

Save this for comparison.

## Step 2: Dry Run

Preview what the reorganization will do:

```bash
uv run python -m scripts.dev.test_reorganizer scripts/tests/ --dry-run
```

Review the output to understand:
- Which files will be copied to `unit/`
- Which files will be copied to `component/`
- Which files will be copied to `integration/`
- Which files will be split

## Step 3: Execute Reorganization

Run the actual reorganization (originals are preserved):

```bash
uv run python -m scripts.dev.test_reorganizer scripts/tests/ --execute
```

This creates new files in `scripts/tests/unit/`, `scripts/tests/component/`, and
`scripts/tests/integration/` but keeps all original files intact.

## Step 4: Verify Syntax

Check that all new files have valid Python syntax:

```bash
uv run python -m scripts.dev.count_test_lines scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --verify-syntax
```

If syntax errors are reported, proceed to debugging.

## Step 5: Verify Line Counts

Compare the new line count to the baseline:

```bash
uv run python -m scripts.dev.count_test_lines scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --json
```

The `total_lines` should match the baseline. If not, functions were lost or duplicated.

## Step 6: Function Diff

Compare functions between original and new folders:

```bash
uv run python -m scripts.dev.diff_test_functions scripts/tests/ --new scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --verbose
```

This will report:
- **Matching functions**: Functions that transferred correctly
- **Differing functions**: Functions with content changes
- **Missing in new**: Functions that weren't transferred
- **Extra in new**: Functions that appeared unexpectedly

For detailed diffs of differing functions:

```bash
uv run python -m scripts.dev.diff_test_functions scripts/tests/ --new scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --show-diffs
```

## Debugging

### If Syntax Errors Occur

1. Check which files have errors:
   ```bash
   uv run python -m scripts.dev.count_test_lines scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --verify-syntax
   ```

2. Compare the problematic file with its original:
   ```bash
   diff original_file.py new_file.py
   ```

3. The original files are preserved, so you can examine what went wrong.

### If Line Counts Don't Match

1. Run the function diff to identify missing/extra functions:
   ```bash
   uv run python -m scripts.dev.diff_test_functions scripts/tests/ --new scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/
   ```

2. Check for:
   - Missing helper functions (dependencies not resolved)
   - Missing fixtures
   - Missing imports
   - Functions in unexpected locations

### If Functions Differ

1. Use `--show-diffs` to see actual content differences:
   ```bash
   uv run python -m scripts.dev.diff_test_functions scripts/tests/ --new scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/ --show-diffs --max-diffs 20
   ```

2. Common causes:
   - Whitespace/indentation changes
   - Missing decorators
   - Block context (class) not properly copied

### Rolling Back

Since originals are never deleted, to roll back:

```bash
rm -rf scripts/tests/unit/ scripts/tests/component/ scripts/tests/integration/
```

The original files remain in their original locations.

## Success Criteria

The reorganization is successful when:

1. `syntax_valid: true` for all new files
2. `total_lines` in new folders equals baseline `total_lines`
3. `total_functions` in new folders equals baseline `total_functions`
4. Function diff reports 100% match rate with no missing functions

## Commands Summary

| Command | Purpose |
|---------|---------|
| `count_test_lines <path> --verify-syntax` | Count lines and check syntax |
| `count_test_lines <path> --json` | Machine-readable output |
| `test_reorganizer <path> --dry-run` | Preview reorganization |
| `test_reorganizer <path> --execute` | Execute reorganization |
| `diff_test_functions <orig> --new <new>` | Compare functions |
| `diff_test_functions <orig> --new <new> --show-diffs` | Show actual diffs |
