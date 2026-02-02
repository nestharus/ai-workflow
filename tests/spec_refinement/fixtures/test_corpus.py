from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CORPUS_CONTENT = {
    "alpha.md": """# Alpha Workflow

[INTRO]
## Intro
Alpha defines the baseline workflow for intake, validation, and routing. (LIB-0001)

[USER_REQUIREMENTS]
## User Requirements
- Provide stable intake contracts.
- Ensure audit trail visibility.

[REQS]
## Requirements
- Must validate incoming payloads before processing.
- Must record audit trail entries.

[CONSTRAINTS]
## Constraints
- Keep latency under 200ms.
- Avoid blocking IO in request path.

[DECISIONS]
## Decisions Needed
- Confirm retention period for audit logs.
""",
    "beta.md": """# Beta Processing Pipeline

[OVERVIEW]
## Overview
Beta handles batch ingestion and transformation with multiple stages. (LIB-0001)

[PIPELINE]
## Pipeline
1. Stage input files
2. Normalize headers
3. Validate schema

### Stage Details
- Use streaming parsers
- Emit telemetry events

[API]
## API
```http
POST /beta/ingest
```

| Field | Type | Notes |
| --- | --- | --- |
| source | string | Required |
| mode | string | Optional |

[DATA]
## Data Layout
- Store payloads in chunked storage.
- Keep lineage metadata for replay.
""",
    "gamma.md": """# Gamma Integrations

## User Requirements / Constraints
Gamma integrates with external partners and must honor contract limits. (LIB-0002)

## API & Integrations
- Supports partner callbacks.
- Requires signed payload verification.

## Edge-Case Notes (v2)
Ensure graceful degradation when partner endpoints timeout.
""",
    "delta.md": """# Delta Operations

[LONGFORM]
## Longform Notes
Delta includes extensive operational guidance for scaling and reliability. (LIB-0002)
This section repeats to simulate a long spec.
Delta includes extensive operational guidance for scaling and reliability.
This section repeats to simulate a long spec.
Delta includes extensive operational guidance for scaling and reliability.
This section repeats to simulate a long spec.
Delta includes extensive operational guidance for scaling and reliability.
This section repeats to simulate a long spec.
Delta includes extensive operational guidance for scaling and reliability.
This section repeats to simulate a long spec.

[RUNBOOK]
## Runbook
- Rotate credentials quarterly.
- Validate backups weekly.
- Document incident response.
""",
    "epsilon.md": """# Epsilon Minimal

[OVERVIEW]
## Overview
Single-section placeholder for minimal content. (LIB-0002)
""",
}

EDGE_CASE_CONTENT = {
    "invalid_pointers.md": """# Invalid Pointers

[INTRO]
## Intro
Evidence reference to invalid pointer [F0999::MISSING] should trigger repair.

[REQS]
## Requirements
- Should handle invalid pointer gracefully.
""",
    "compound_citations.md": """# Compound Citations

[INTRO]
## Intro
Evidence: [F0001::INTRO, F0001::REQS]
""",
}

DEFAULT_LIBRARY_MAP = {
    "alpha.md": ["LIB-0001"],
    "beta.md": ["LIB-0001"],
    "gamma.md": ["LIB-0002"],
    "delta.md": ["LIB-0002"],
    "epsilon.md": ["LIB-0002"],
}


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _extract_section_labels(content: str) -> list[str]:
    explicit = [match.group(1) for match in re.finditer(r"\[([A-Z_]+)\]", content)]
    explicit = [item.strip() for item in explicit if item and item.strip()]
    explicit = _dedupe_keep_order(explicit)
    if explicit:
        return explicit

    headings: list[str] = []
    for match in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE):
        heading = match.group(1).strip()
        if not heading:
            continue
        headings.append(heading.upper().replace(" ", "_"))
    return _dedupe_keep_order(headings)


def _write_files(fs, base_path: Path, files: dict[str, str]) -> None:
    fs.create_dir(base_path)
    for filename, content in files.items():
        file_path = base_path / filename
        file_path.write_text(content, encoding="utf-8")


def create_test_corpus(
    fs,
    base_path: Path,
    *,
    file_count: int | None = None,
    include_edge_cases: bool = False,
) -> dict[str, dict[str, Any]]:
    """Create a markdown test corpus and return a manifest.

    Args:
        fs: pyfakefs filesystem fixture.
        base_path: Directory to populate with markdown files.
        file_count: Optional total file count for scaling; extra files are cloned.
        include_edge_cases: Include edge case fixture files if True.
    """
    files = dict(CORPUS_CONTENT)
    library_map = dict(DEFAULT_LIBRARY_MAP)

    if include_edge_cases:
        files.update(EDGE_CASE_CONTENT)

    if file_count is not None and file_count > len(files):
        extra_needed = file_count - len(files)
        for idx in range(1, extra_needed + 1):
            name = f"extra_{idx:03d}.md"
            content = CORPUS_CONTENT["alpha.md"].replace(
                "Alpha Workflow", f"Extra Workflow {idx:03d}"
            )
            files[name] = content
            library_map[name] = ["LIB-0001"]

    _write_files(fs, base_path, files)

    manifest: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(sorted(base_path.glob("*.md")), start=1):
        file_id = f"F{index:04d}"
        content = path.read_text(encoding="utf-8")
        labels = _extract_section_labels(content)
        section_ids = [f"SEC-{file_id}-{i:04d}" for i in range(1, len(labels) + 1)]
        expected_libraries = library_map.get(path.name, ["LIB-0001"])
        manifest[file_id] = {
            "path": str(path),
            "sections": section_ids,
            "section_labels": labels,
            "expected_libraries": expected_libraries,
            "expected_evidence_count": len(labels),
        }

    return manifest
