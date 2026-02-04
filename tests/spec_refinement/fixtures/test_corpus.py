from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from spec_manager.schemas.edge_list import (
    EdgeListSchema,
    EdgeSchema,
    build_interface_index,
    write_edge_list_json,
    write_interface_index_json,
)
from spec_manager.schemas.interface_contract import (
    ConsumedInterface,
    InterfaceContractSchema,
    ProvidedInterface,
)

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


INTERFACE_TEST_LIBRARIES = {
    "LIB-0001": {
        "spec": """# Library Spec: LIB-0001

## Requirements
- REQ-LIB-0001-0001: Consume the LIB-0002 provider API for order lookups. [LIB-0001::spec.md::REQ-LIB-0001-0001]
- REQ-LIB-0001-0002: Subscribe to LIB-0003 event streams for status updates. [LIB-0001::spec.md::REQ-LIB-0001-0002]

## Flows
- FLOW-LIB-0001-01: Sync updates from providers. [LIB-0001::spec.md::FLOW-LIB-0001-01]

## Constraints
- INV-LIB-0001-0001: Maintain reliability during peak traffic. [LIB-0001::spec.md::INV-LIB-0001-0001]
""",
        "charter": """# Library Charter: LIB-0001

## Intent
Coordinate consumer workflows and dependencies.

## Boundaries
Orchestrates cross-library consumption.

## Responsibilities
- Maintain consumer integrations

## Evidence
- [LIB-0001::spec.md::REQ-LIB-0001-0001]
- [LIB-0001::spec.md::REQ-LIB-0001-0002]

## Overlap Resolutions
- None
""",
        "decisions": """# Decisions: LIB-0001

- DEC-LIB-0001-0001: Confirm API SLA with LIB-0002.
- DEC-LIB-0001-0002: Decide on event retention from LIB-0003.
""",
        "spec_index": {
            "lib_id": "LIB-0001",
            "generated_at": "2024-01-01T00:00:00",
            "spec_path": "libraries/LIB-0001/spec.md",
            "elements": [
                {
                    "element_id": "REQ-LIB-0001-0001",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Consume the LIB-0002 provider API for order lookups.",
                    "raw_line": "- REQ-LIB-0001-0001: Consume the LIB-0002 provider API for order lookups.",
                    "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
                    "mentions_libs": ["LIB-0002"],
                },
                {
                    "element_id": "REQ-LIB-0001-0002",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Subscribe to LIB-0003 event streams for status updates.",
                    "raw_line": "- REQ-LIB-0001-0002: Subscribe to LIB-0003 event streams for status updates.",
                    "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0002]"],
                    "mentions_libs": ["LIB-0003"],
                },
                {
                    "element_id": "FLOW-LIB-0001-01",
                    "kind": "flow",
                    "section": "Flows",
                    "text": "Sync updates from providers.",
                    "raw_line": "- FLOW-LIB-0001-01: Sync updates from providers.",
                    "citations": ["[LIB-0001::spec.md::FLOW-LIB-0001-01]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "INV-LIB-0001-0001",
                    "kind": "invariant",
                    "section": "Constraints",
                    "text": "Maintain reliability during peak traffic.",
                    "raw_line": "- INV-LIB-0001-0001: Maintain reliability during peak traffic.",
                    "citations": ["[LIB-0001::spec.md::INV-LIB-0001-0001]"],
                    "mentions_libs": [],
                },
            ],
        },
        "decisions_index": {
            "lib_id": "LIB-0001",
            "generated_at": "2024-01-01T00:00:00",
            "decisions_path": "libraries/LIB-0001/decisions.md",
            "decisions": [
                {
                    "decision_id": "DEC-LIB-0001-0001",
                    "status": "open",
                    "question": "Confirm API SLA with LIB-0002.",
                    "context": "Interface reliability requirements.",
                    "options": ["24x7", "business-hours"],
                    "default": None,
                    "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
                },
                {
                    "decision_id": "DEC-LIB-0001-0002",
                    "status": "open",
                    "question": "Decide on event retention from LIB-0003.",
                    "context": "Event replay expectations.",
                    "options": ["7 days", "30 days"],
                    "default": None,
                    "citations": ["[LIB-0001::spec.md::REQ-LIB-0001-0002]"],
                },
            ],
        },
    },
    "LIB-0002": {
        "spec": """# Library Spec: LIB-0002

## Requirements
- REQ-LIB-0002-0001: Provide lookup API for consumers. [LIB-0002::spec.md::REQ-LIB-0002-0001]
- REQ-LIB-0002-0002: Maintain stable request/response contracts. [LIB-0002::spec.md::REQ-LIB-0002-0002]

## Flows
- FLOW-LIB-0002-01: Handle lookup requests. [LIB-0002::spec.md::FLOW-LIB-0002-01]

## Constraints
- INV-LIB-0002-0001: Keep latency under 200ms. [LIB-0002::spec.md::INV-LIB-0002-0001]
""",
        "charter": """# Library Charter: LIB-0002

## Intent
Provide API surfaces for consumer libraries.

## Boundaries
API-focused responsibilities.

## Responsibilities
- Serve provider APIs

## Evidence
- [LIB-0002::spec.md::REQ-LIB-0002-0001]

## Overlap Resolutions
- None
""",
        "decisions": """# Decisions: LIB-0002

- DEC-LIB-0002-0001: Decide on API versioning cadence.
""",
        "spec_index": {
            "lib_id": "LIB-0002",
            "generated_at": "2024-01-01T00:00:00",
            "spec_path": "libraries/LIB-0002/spec.md",
            "elements": [
                {
                    "element_id": "REQ-LIB-0002-0001",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Provide lookup API for consumers.",
                    "raw_line": "- REQ-LIB-0002-0001: Provide lookup API for consumers.",
                    "citations": ["[LIB-0002::spec.md::REQ-LIB-0002-0001]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "REQ-LIB-0002-0002",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Maintain stable request/response contracts.",
                    "raw_line": "- REQ-LIB-0002-0002: Maintain stable request/response contracts.",
                    "citations": ["[LIB-0002::spec.md::REQ-LIB-0002-0002]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "FLOW-LIB-0002-01",
                    "kind": "flow",
                    "section": "Flows",
                    "text": "Handle lookup requests.",
                    "raw_line": "- FLOW-LIB-0002-01: Handle lookup requests.",
                    "citations": ["[LIB-0002::spec.md::FLOW-LIB-0002-01]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "INV-LIB-0002-0001",
                    "kind": "invariant",
                    "section": "Constraints",
                    "text": "Keep latency under 200ms.",
                    "raw_line": "- INV-LIB-0002-0001: Keep latency under 200ms.",
                    "citations": ["[LIB-0002::spec.md::INV-LIB-0002-0001]"],
                    "mentions_libs": [],
                },
            ],
        },
        "decisions_index": {
            "lib_id": "LIB-0002",
            "generated_at": "2024-01-01T00:00:00",
            "decisions_path": "libraries/LIB-0002/decisions.md",
            "decisions": [
                {
                    "decision_id": "DEC-LIB-0002-0001",
                    "status": "open",
                    "question": "Decide on API versioning cadence.",
                    "context": "Release planning for consumers.",
                    "options": ["monthly", "quarterly"],
                    "default": None,
                    "citations": ["[LIB-0002::spec.md::REQ-LIB-0002-0001]"],
                }
            ],
        },
    },
    "LIB-0003": {
        "spec": """# Library Spec: LIB-0003

## Requirements
- REQ-LIB-0003-0001: Emit status events for consumers. [LIB-0003::spec.md::REQ-LIB-0003-0001]
- REQ-LIB-0003-0002: Publish event schema updates. [LIB-0003::spec.md::REQ-LIB-0003-0002]

## Flows
- FLOW-LIB-0003-01: Emit lifecycle events. [LIB-0003::spec.md::FLOW-LIB-0003-01]

## Constraints
- INV-LIB-0003-0001: Deliver events within 1 minute. [LIB-0003::spec.md::INV-LIB-0003-0001]
""",
        "charter": """# Library Charter: LIB-0003

## Intent
Provide event streams to consumer libraries.

## Boundaries
Event-focused responsibilities.

## Responsibilities
- Emit provider events

## Evidence
- [LIB-0003::spec.md::REQ-LIB-0003-0001]

## Overlap Resolutions
- None
""",
        "decisions": """# Decisions: LIB-0003

- DEC-LIB-0003-0001: Define event retention policy.
""",
        "spec_index": {
            "lib_id": "LIB-0003",
            "generated_at": "2024-01-01T00:00:00",
            "spec_path": "libraries/LIB-0003/spec.md",
            "elements": [
                {
                    "element_id": "REQ-LIB-0003-0001",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Emit status events for consumers.",
                    "raw_line": "- REQ-LIB-0003-0001: Emit status events for consumers.",
                    "citations": ["[LIB-0003::spec.md::REQ-LIB-0003-0001]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "REQ-LIB-0003-0002",
                    "kind": "requirement",
                    "section": "Requirements",
                    "text": "Publish event schema updates.",
                    "raw_line": "- REQ-LIB-0003-0002: Publish event schema updates.",
                    "citations": ["[LIB-0003::spec.md::REQ-LIB-0003-0002]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "FLOW-LIB-0003-01",
                    "kind": "flow",
                    "section": "Flows",
                    "text": "Emit lifecycle events.",
                    "raw_line": "- FLOW-LIB-0003-01: Emit lifecycle events.",
                    "citations": ["[LIB-0003::spec.md::FLOW-LIB-0003-01]"],
                    "mentions_libs": [],
                },
                {
                    "element_id": "INV-LIB-0003-0001",
                    "kind": "invariant",
                    "section": "Constraints",
                    "text": "Deliver events within 1 minute.",
                    "raw_line": "- INV-LIB-0003-0001: Deliver events within 1 minute.",
                    "citations": ["[LIB-0003::spec.md::INV-LIB-0003-0001]"],
                    "mentions_libs": [],
                },
            ],
        },
        "decisions_index": {
            "lib_id": "LIB-0003",
            "generated_at": "2024-01-01T00:00:00",
            "decisions_path": "libraries/LIB-0003/decisions.md",
            "decisions": [
                {
                    "decision_id": "DEC-LIB-0003-0001",
                    "status": "open",
                    "question": "Define event retention policy.",
                    "context": "Downstream replay expectations.",
                    "options": ["24 hours", "7 days"],
                    "default": None,
                    "citations": ["[LIB-0003::spec.md::REQ-LIB-0003-0001]"],
                }
            ],
        },
    },
}


def create_interface_test_libraries(fs, run_id: str = "run_001") -> dict[str, Any]:
    """Create interface-focused libraries under runs/<run_id>/libraries."""
    libraries_dir = Path("runs") / run_id / "libraries"
    if not libraries_dir.exists():
        fs.create_dir(libraries_dir)

    manifest: dict[str, Any] = {
        "library_ids": [],
        "element_ids": {},
        "decision_ids": {},
        "expected_edges": [
            {
                "edge_id": "EDGE-LIB-0001-LIB-0002",
                "consumer_lib": "LIB-0001",
                "provider_lib": "LIB-0002",
                "consumer_elements": ["REQ-LIB-0001-0001"],
                "kind": "api",
            },
            {
                "edge_id": "EDGE-LIB-0001-LIB-0003",
                "consumer_lib": "LIB-0001",
                "provider_lib": "LIB-0003",
                "consumer_elements": ["REQ-LIB-0001-0002"],
                "kind": "events",
            },
        ],
    }

    for lib_id, payload in INTERFACE_TEST_LIBRARIES.items():
        lib_dir = libraries_dir / lib_id
        if not lib_dir.exists():
            fs.create_dir(lib_dir)

        (lib_dir / "spec.md").write_text(payload["spec"], encoding="utf-8")
        (lib_dir / "spec_index.json").write_text(
            json.dumps(payload["spec_index"], indent=2), encoding="utf-8"
        )
        (lib_dir / "charter.md").write_text(payload["charter"], encoding="utf-8")
        (lib_dir / "decisions.md").write_text(payload["decisions"], encoding="utf-8")
        (lib_dir / "decisions_index.json").write_text(
            json.dumps(payload["decisions_index"], indent=2), encoding="utf-8"
        )

        manifest["library_ids"].append(lib_id)
        manifest["element_ids"][lib_id] = [
            element["element_id"] for element in payload["spec_index"]["elements"]
        ]
        manifest["decision_ids"][lib_id] = [
            decision["decision_id"] for decision in payload["decisions_index"]["decisions"]
        ]

    return manifest


def create_task_planning_prerequisites(fs, run_id: str, manifest: dict) -> None:
    """Create architecture mapping and interface indexes for task planning tests."""
    run_dir = Path("runs") / run_id
    arch_dir = run_dir / "architecture"
    if not arch_dir.exists():
        fs.create_dir(arch_dir)

    selected = """# Selected Architecture

## Components
- API Layer: Handles API requests
- Event Layer: Handles event processing
"""
    mapping_lines = [
        "# Architecture Mapping",
        "",
        "## Architecture",
        "arch_001",
        "",
        "## Component Mappings",
        "",
        "### Component: API Layer",
    ]

    library_ids = sorted(manifest.get("library_ids", []))
    api_libs = library_ids[:2]
    event_libs = library_ids[2:]
    for lib_id in api_libs:
        mapping_lines.append(f"{lib_id}")

    if event_libs:
        mapping_lines.extend(["", "### Component: Event Layer"])
        for lib_id in event_libs:
            mapping_lines.append(f"{lib_id}")

    (arch_dir / "selected.md").write_text(selected, encoding="utf-8")
    (arch_dir / "mapping.md").write_text("\n".join(mapping_lines).rstrip() + "\n", encoding="utf-8")

    indexes_dir = run_dir / "workspace" / "indexes"
    if not indexes_dir.exists():
        fs.create_dir(indexes_dir)

    edges: list[EdgeSchema] = []
    for edge in manifest.get("expected_edges", []):
        consumer_lib = edge.get("consumer_lib")
        provider_lib = edge.get("provider_lib")
        consumer_elements = edge.get("consumer_elements") or []
        provider_elements = (
            manifest.get("element_ids", {}).get(provider_lib) if provider_lib else None
        ) or []
        provider_requirement = provider_elements[0] if provider_elements else "REQ-LIB-0001-0001"
        consumer_requirement = consumer_elements[0] if consumer_elements else "REQ-LIB-0001-0001"
        edges.append(
            EdgeSchema.model_validate(
                {
                    "edge_id": edge.get("edge_id"),
                    "consumer_lib": consumer_lib,
                    "provider_lib": provider_lib,
                    "kind": edge.get("kind", "api"),
                    "consumer_elements": consumer_elements,
                    "provider_elements": [provider_requirement],
                    "summary": "Test edge for task planning.",
                    "evidence": [f"[{consumer_lib}::spec.md::{consumer_requirement}]"],
                }
            )
        )

        consumer_interfaces_dir = run_dir / "libraries" / consumer_lib / "interfaces"
        if not consumer_interfaces_dir.exists():
            fs.create_dir(consumer_interfaces_dir)

        contract = InterfaceContractSchema(
            edge_id=edge.get("edge_id"),
            consumer_lib=consumer_lib,
            provider_lib=provider_lib,
            provided=[
                ProvidedInterface(
                    name="Primary Interface",
                    type="http",
                    requirements=[provider_requirement],
                    details="Test contract payload.",
                    acceptance=["Returns expected payload"],
                    citations=[f"[{provider_lib}::spec.md::{provider_requirement}]"],
                )
            ],
            consumed_by=[
                ConsumedInterface(
                    consumer_requirement=consumer_requirement,
                    expectations=["Aligned expectations"],
                    citations=[f"[{consumer_lib}::spec.md::{consumer_requirement}]"],
                )
            ],
            open_questions=[],
        )
        contract_json_path = consumer_interfaces_dir / f"{edge.get('edge_id')}.json"
        contract_md_path = consumer_interfaces_dir / f"{edge.get('edge_id')}.md"
        contract_json_path.write_text(json.dumps(contract.model_dump(), indent=2), encoding="utf-8")
        contract_md_path.write_text(
            "\n".join(
                [
                    "# Interface Contract",
                    "",
                    "## Purpose",
                    f"- Edge ID: {edge.get('edge_id')}",
                    "",
                    "## Provided Interfaces",
                    "- Primary Interface",
                    "",
                    "## Consumed By",
                    "- Consumer expectations",
                    "",
                    "## Data Contract",
                    "- Schemas: interface.json",
                    "",
                    "## Operational Concerns",
                    "- Performance: p95 < 200ms",
                    "",
                    "## Open Questions",
                    "- None",
                    "",
                    "## Evidence",
                    "- See citations in JSON",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    edge_list = EdgeListSchema(
        run_id=run_id,
        generated_at="2024-01-01T00:00:00",
        edges=edges,
    )
    write_edge_list_json(edge_list, indexes_dir / "edge_list.json")

    interface_index = build_interface_index(
        edges,
        run_id=run_id,
        contract_base_path=run_dir,
    )
    write_interface_index_json(interface_index, indexes_dir / "interface_index.json")
