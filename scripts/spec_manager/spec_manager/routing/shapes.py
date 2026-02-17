# TODO(single-layer): NEW — Shape parser/loader (Sections 4, 5).
#   - Parse shape docs (controlled markdown format matching design/routing/*.md)
#   - Header fields: Classification, Package, Files, Role
#   - Sections: Systems, Surface API, Dependencies, Consumers, Verifiers
#   - Path→shape ownership mapping: file belongs to most specific shape whose
#     Package prefix contains it (Section 6.3 rule #1)
#   - Shape IDs (typed, stable)
#   - Dual storage (Section 5.1): system shapes in design/routing/ (committed),
#     run shapes in workspace/routing/ or workspace/shapes/ (per-run). Loader must
#     handle both paths.
#   - Derivation: from spec decomposition, design docs, planner decisions (Section 5.2)
#   - LLM may draft shapes as proposals; only active when saved + referenced by verifiers
#   - No function-level shapes — package/component granularity only (Section 4.2)
#   - Embedded contract blocks (Section 4.2/7): parse contract metadata within shape
#     docs as first-class data (EVENT_FLOW, DI_BINDING, etc.) for routing/verification
#   - Update rule (Section 5.3): shapes are used across all 3 phases
#     (Libraries, Architecture, Quality) — each phase may update shapes within its
#     authority scope. Verifiers must be updated alongside structural changes.
#     No auto-regeneration from code — updates are controlled spec-artifact edits.
#   - Skeleton lifecycle: shapes are proposed in Phase 0 as draft (PROPOSAL status),
#     then refined to non-draft (ACTIVE) during Libraries phase skeleton freeze.
#   - Index artifacts: routing/INDEX.md (human-readable) and routing/index.json
#     (machine-readable shape-pack index) generated/maintained on shape changes (Section 5.1)
# ALGORITHM(single-layer):
#   References: response3 Sections 4, 4.2, 5, 5.1, 5.2, 5.3, 6.3; evaluation modifications #1, #3, #5.
#   Phase model: 3 forward-only phases — Libraries → Architecture → Quality.
#     PhaseId = Literal['libraries', 'architecture', 'quality'].
#     Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     No backtracking: phases block (not demote) if they encounter something
#     outside their authority.
#   Skeleton lifecycle: shapes are proposed in Phase 0 as draft (PROPOSAL status).
#     During Libraries phase, library shapes are refined to non-draft (ACTIVE)
#     once verifiers are attached. Architecture phase creates/updates component-level
#     shapes and contracts within its own skeleton; library shapes remain ACTIVE.
#     Quality phase uses all shapes as-is (read-only).
#   Data structures (authoritative shared interface):
#     - ShapeId = NewType('ShapeId', str)  # canonical ID used across routing/work-items.
#     - VerifierSpec: {verifier_id: str, kind: Literal['TEST','IMPORT_BOUNDARY','COMMAND'], params: dict[str, Any], source_ref: str}.
#     - ShapeContract: {contract_id: str, kind: Literal['EVENT_FLOW','DI_BINDING','MIDDLEWARE_ORDERING','CUSTOM'], producer_shape_id: ShapeId|None, consumer_shape_ids: list[ShapeId], payload_schema_ref: str|None, verifier_ids: list[str], metadata: dict[str, Any]}.
#     - Shape: {shape_id: ShapeId, classification: str, package: str, files: list[str], role: str, systems: list[str], surface_api: list[str], dependencies_declared: list[ShapeId|str], consumers_declared: list[ShapeId|str], verifiers: list[VerifierSpec], contracts: list[ShapeContract], status: Literal['PROPOSAL','ACTIVE'], source_path: str, last_updated_phase: PhaseId|None}.
#     - ShapePackIndex: {system_shapes_dir: str, run_shapes_dir: str, shapes: dict[ShapeId, Shape], ownership_prefixes: list[tuple[str, ShapeId]], generated_at: str}.
# IMPL(single-layer): `Shape`/`ShapePackIndex` are shared contracts for matcher, router,
# introduction checks, and orchestrator bootstrap; consumers should not redefine variants.
#   Interface contracts:
#     - def parse_shape_document(path: Path) -> Shape
#     - def load_shape_pack(workspace_root: Path, run_root: Path|None = None) -> ShapePackIndex
#     - def resolve_shape_for_file(path: str, index: ShapePackIndex) -> ShapeId|None
#     - def bootstrap_shapes_from_spec(spec_components: list[dict[str, Any]], workspace_root: Path) -> list[Shape]
#     - def write_shape_index(index: ShapePackIndex) -> tuple[Path, Path]  # INDEX.md and index.json
# IMPL(single-layer): `resolve_shape_for_file` is the canonical ownership API implementing
# Section 6.3 most-specific-prefix matching; routing consumers should call it directly.
#   Control flow:
#     1. Parse markdown deterministically: header keys (Classification/Package/Files/Role), required sections, optional sections, and embedded contract blocks.
#     2. Normalize package prefixes to POSIX-style path prefixes and sort descending by specificity for ownership rule (Section 6.3 rule #1).
#     3. Mark shape status ACTIVE only when verifier list is non-empty; otherwise PROPOSAL (evaluation modification #3).
#     4. Load both storage roots (design/routing and workspace/routing or workspace/shapes), merge by ShapeId with run-shape override, and emit deterministic index artifacts.
#     5. On Phase 0 bootstrap, derive initial shapes from spec decomposition outputs; first Libraries pass can run from spec inputs even if all shapes are PROPOSAL (evaluation modifications #1 and #5).
#     6. When shape document changes, emit metadata flag requires_verifier_refresh=True so Libraries phase can auto-create verifier work items (evaluation modification #3).
# IMPL(single-layer): Merge precedence is run-shape override over committed system shape on
# ShapeId collision; INDEX.md/index.json must reflect the merged view deterministically.
# IMPL(single-layer): `status` is verifier-driven (`ACTIVE` only with verifiers); proposal-only
# packs remain valid bootstrap inputs for first Libraries cycle work.
# IMPL(single-layer): `requires_verifier_refresh=True` is the handoff signal to
# coordination/work_items for verifier-create-or-update follow-up.
#   Error handling:
#     - Invalid header/section: raise ShapeParseError with file and line; caller records blocked ambiguity signal.
#     - Duplicate ShapeId with conflicting package prefix: raise ShapeConflictError.
#     - Unknown contract shape references: keep contract but add diagnostic and mark shape PROPOSAL until resolved.
#     - Missing both storage roots: return empty index plus diagnostic list; do not crash lifecycle.
#   Integration points:
#     - Called by: pdd_orchestrator Phase 0 bootstrap, matcher, monitor executor, planner/implementation scoping.
#     - Calls: config.PhaseId, work_items for verifier-refresh metadata.
# IMPL(single-layer): Phase typing dependency is
# `spec_manager.compliance.promotion.config.PhaseId` (shared forward-only vocabulary).
# IMPL(single-layer): Ownership/parse conflicts are blocking diagnostics for callers; no LLM
# fallback should be used for shape authority decisions.
#   Test requirements:
#     - Parse valid/invalid markdown, including long contract sections.
#     - Ownership chooses most-specific package prefix.
#     - PROPOSAL vs ACTIVE status transition when verifiers are added/removed.
#     - Dual storage merge precedence and deterministic index.json/INDEX.md generation.
#     - Bootstrap creates initial shapes from spec decomposition and leaves first Libraries pass unblocked.

"""Shape document parsing, loading, and ownership mapping."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NewType

from spec_manager.compliance.promotion.config import PhaseId

logger = logging.getLogger(__name__)

ShapeId = NewType("ShapeId", str)
VerifierKind = Literal["TEST", "IMPORT_BOUNDARY", "COMMAND"]
ShapeStatus = Literal["PROPOSAL", "ACTIVE"]
ContractKind = Literal["EVENT_FLOW", "DI_BINDING", "MIDDLEWARE_ORDERING", "CUSTOM"]

_SECTION_LOOKUP: dict[str, str] = {
    "systems": "systems",
    "surface api": "surface_api",
    "dependencies": "dependencies",
    "consumers": "consumers_declared",
    "verifiers": "verifiers",
    "contracts": "contracts",
}


class ShapeParseError(ValueError):
    """Raised for deterministic shape document parse failures."""

    def __init__(self, path: Path, line: int, message: str) -> None:
        super().__init__(f"{path}:{line}: {message}")
        self.path = path
        self.line = line
        self.message = message


class ShapeConflictError(ValueError):
    """Raised when one shape id maps to conflicting package prefixes."""

    def __init__(
        self,
        shape_id: ShapeId,
        first_package: str,
        second_package: str,
    ) -> None:
        super().__init__(
            f"shape_id={shape_id!s} has conflicting package prefixes: "
            f"{first_package!r} vs {second_package!r}"
        )
        self.shape_id = shape_id
        self.first_package = first_package
        self.second_package = second_package


@dataclass
class VerifierSpec:
    verifier_id: str
    kind: VerifierKind
    params: dict[str, Any] = field(default_factory=dict)
    source_ref: str = ""


@dataclass
class ShapeContract:
    contract_id: str
    kind: ContractKind
    producer_shape_id: ShapeId | None
    consumer_shape_ids: list[ShapeId]
    payload_schema_ref: str | None
    verifier_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Shape:
    shape_id: ShapeId
    classification: str
    package: str
    files: list[str]
    role: str
    systems: list[str] = field(default_factory=list)
    surface_api: list[str] = field(default_factory=list)
    dependencies_declared: list[ShapeId | str] = field(default_factory=list)
    consumers_declared: list[ShapeId | str] = field(default_factory=list)
    verifiers: list[VerifierSpec] = field(default_factory=list)
    contracts: list[ShapeContract] = field(default_factory=list)
    status: ShapeStatus = "PROPOSAL"
    source_path: str = ""
    last_updated_phase: PhaseId | None = None
    requires_verifier_refresh: bool = False
    diagnostics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShapePackIndex:
    system_shapes_dir: str
    run_shapes_dir: str
    shapes: dict[ShapeId, Shape] = field(default_factory=dict)
    ownership_prefixes: list[tuple[str, ShapeId]] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: _utcnow().isoformat())
    index_root: str = ""
    diagnostics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _slugify(value: str) -> str:
    value = _normalize_whitespace(value)
    value = value.strip("/\\")
    if not value:
        return ""
    value = value.replace(" ", "-")
    value = re.sub(r"[^A-Za-z0-9_./-]", "-", value)
    value = re.sub(r"[-_/.]{2,}", "-", value)
    return value.strip("-_")


def _normalize_path_prefix(value: str, *, convert_dots: bool = False) -> str:
    value = _normalize_whitespace(value)
    if not value:
        return ""
    value = value.replace("\\", "/")
    if convert_dots:
        value = value.replace(".", "/")
    value = value.strip("/ ")
    value = re.sub(r"/{2,}", "/", value)
    return value.lower()


def _shape_id_from_value(value: str) -> ShapeId:
    normalized = _slugify(value).replace("/", "-").replace(".", "-")
    if not normalized:
        normalized = "shape"
    return ShapeId(normalized)


def _coerce_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""

    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    if stripped.lower() in {"null", "none"}:
        return None

    try:
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(stripped)
        if stripped.startswith(("'", '"')):
            return stripped.strip().strip("'\"")
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"-?\d+\.\d+", stripped):
            return float(stripped)
    except Exception:
        pass

    return stripped


def _coerce_shape_ref(value: Any) -> str:
    if value is None:
        return ""
    return _shape_id_from_value(str(value)).__str__()


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, dict):
        return [_coerce_scalar(json.dumps(value))]

    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [item.strip() for item in raw[1:-1].split(",") if item.strip()]
        return [str(item).strip() for item in parsed if str(item).strip()]
    if "," in raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [raw]


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _clean_markdown_link(value: str) -> str:
    match = re.match(r"^\[[^\]]+\]\(([^)]+)\)$", value.strip())
    if match:
        return match.group(1).strip()
    return value.strip()


def _split_sections(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    sections: dict[str, list[tuple[int, str]]] = {"header": []}
    current = "header"

    for index, line in enumerate(lines):
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if match:
            key = re.sub(r"\s+", " ", match.group(1).strip().lower())
            canonical = _SECTION_LOOKUP.get(key)
            if canonical:
                current = canonical
                sections.setdefault(canonical, [])
                continue
        sections.setdefault(current, []).append((index + 1, line))

    return sections


def _parse_list_value(value: str) -> list[str]:
    return [
        _normalize_whitespace(item)
        for item in _coerce_str_list(value)
        if _normalize_whitespace(item)
    ]


def _parse_header_fields(lines: list[tuple[int, str]], path: Path) -> dict[str, Any]:
    header: dict[str, Any] = {
        "classification": "",
        "package": "",
        "files": [],
        "role": "",
    }
    missing = {"classification", "package", "files", "role"}

    capture_files = False
    for _, line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if capture_files and not re.match(r"^\w+:\s*", stripped):
            for value in _coerce_str_list(stripped):
                clean = _normalize_whitespace(value)
                if clean:
                    header["files"].append(clean)
            continue

        match = re.match(r"^(?P<key>[^:#]+?)\s*:\s*(?P<value>.*)$", stripped)
        if match:
            key = re.sub(r"\s+", " ", match.group("key").strip().lower())
            if key not in header:
                continue

            value = match.group("value").strip()
            if key == "files":
                items = _parse_list_value(value)
                header[key] = items
                missing.discard("files")
                capture_files = not bool(value)
                continue

            if value:
                header[key] = value
                missing.discard(key)
                capture_files = False
            else:
                capture_files = False
            continue

    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ShapeParseError(path, 1, f"missing required header field(s): {missing_fields}")

    if not header["classification"]:
        raise ShapeParseError(path, 1, "classification must be non-empty")
    if not header["package"]:
        raise ShapeParseError(path, 1, "package must be non-empty")
    if not header["role"]:
        raise ShapeParseError(path, 1, "role must be non-empty")

    return header


def _parse_simple_list(lines: list[tuple[int, str]]) -> list[str]:
    entries: list[str] = []
    for _, raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("-") or line.startswith("*"):
            line = line[1:].lstrip(" *")
        if line.startswith(tuple(str(i) + "." for i in range(1, 20))):
            line = line.split(".", 1)[1]
            line = line.strip()
        line = _normalize_whitespace(line)
        if line:
            for value in _coerce_str_list(line):
                cleaned = _clean_markdown_link(value)
                if cleaned:
                    entries.append(cleaned)
    return entries


def _parse_keyed_blocks(lines: list[tuple[int, str]], *, section: str | None = None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_indent = 0
    list_key: str | None = None
    list_indent = 0
    in_fence = False

    def flush() -> None:
        nonlocal current, current_indent, list_key, list_indent
        if current is not None:
            blocks.append(current)
        current = None
        current_indent = 0
        list_key = None
        list_indent = 0

    def start_block(line_no: int) -> None:
        nonlocal current, current_indent
        flush()
        current = {"_line": line_no}
        current_indent = 0

    def set_field(mapping: dict[str, Any], key: str, value: Any) -> None:
        if key not in mapping:
            mapping[key] = value
            return
        existing = mapping[key]
        if isinstance(existing, list):
            existing.append(value)
            return
        mapping[key] = [existing, value]

    for line_no, raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue

        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = re.match(r"^#{2,6}\s+(.*?)\s*$", line)
        if heading and section == "contracts":
            start_block(line_no)
            block = current
            if block is None:
                block = {}
                current = block
            title = heading.group(1).strip()
            if title:
                block["contract_title"] = _normalize_whitespace(title)
                first, *rest = title.split(":", 1)
                first_u = first.strip().upper()
                if first_u in {"EVENT_FLOW", "DI_BINDING", "MIDDLEWARE_ORDERING", "CUSTOM"}:
                    block["kind"] = first_u
                    if rest:
                        block["contract_id"] = _normalize_whitespace(rest[0])
            continue

        indent = len(line) - len(line.lstrip(" \t"))
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("-") or stripped.startswith("*"):
            bullet_text = stripped[1:].lstrip()
            if list_key and isinstance(current.get(list_key), list) and indent > current_indent:
                current[list_key].append(_coerce_scalar(bullet_text))  # type: ignore[arg-type]
                continue

            if ":" in bullet_text:
                key, value = bullet_text.split(":", 1)
                key = _normalize_whitespace(key).lower()
                value = value.strip()
                if current is None or (section != "contracts" and indent <= current_indent):
                    start_block(line_no)
                assert current is not None
                if value:
                    current[key] = _coerce_scalar(value)
                    list_key = None
                else:
                    current[key] = []
                    list_key = key
                    list_indent = indent
                current_indent = max(current_indent, indent)
                continue

            if current is None:
                start_block(line_no)
            current.setdefault("_items", []).append(bullet_text)
            continue

        if ":" in stripped and (
            current is not None
            or (section == "verifiers" and stripped[0].isalpha())
            or (section == "contracts" and stripped[0].isalpha())
        ):
            if current is None:
                start_block(line_no)
            key, value = stripped.split(":", 1)
            key = _normalize_whitespace(key).lower()
            value = value.strip()
            if value:
                set_field(current, key, _coerce_scalar(value))
                list_key = None
            else:
                current[key] = []
                list_key = key
                list_indent = indent
            current_indent = max(current_indent, indent)
            continue

        if current is not None and list_key is not None:
            current_value = current.get(list_key)
            if isinstance(current_value, list) and indent > list_indent:
                current_value.append(_coerce_scalar(stripped))
                continue

        if current is not None:
            current.setdefault("_text", "")
            tail = current["_text"]
            if tail:
                current["_text"] = f"{tail}\n{stripped}"
            else:
                current["_text"] = stripped

    if current is not None:
        blocks.append(current)

    cleaned_blocks: list[dict[str, Any]] = []
    for block in blocks:
        normalized: dict[str, Any] = {}
        for key, value in block.items():
            if key in {"_items", "_text"}:
                continue
            normalized[key] = value
        if not normalized:
            continue
        if set(normalized.keys()) == {"_line"}:
            continue
        cleaned_blocks.append(normalized)

    return cleaned_blocks


def _coerce_verifier_spec(block: dict[str, Any], path: Path, line: int) -> VerifierSpec:
    verifier_id = str(block.get("verifier_id") or block.get("id") or block.get("name") or "").strip()
    if not verifier_id:
        raise ShapeParseError(path, line, "verifier entry requires verifier_id")

    kind = str(block.get("kind", "COMMAND")).strip().upper()
    if kind not in {"TEST", "IMPORT_BOUNDARY", "COMMAND"}:
        raise ShapeParseError(path, line, f"unknown verifier kind: {kind}")

    params = _coerce_dict(block.get("params"))
    source_ref = _clean_markdown_link(str(block.get("source_ref", "").strip()))
    return VerifierSpec(verifier_id=verifier_id, kind=kind, params=params, source_ref=source_ref)


def _coerce_contract(block: dict[str, Any], shape_id: ShapeId, path: Path, line: int, fallback_index: int) -> ShapeContract:
    contract_id = str(block.get("contract_id") or block.get("id") or block.get("name") or "").strip()
    if not contract_id:
        contract_id = f"{shape_id}-{fallback_index}"

    kind = str(block.get("kind", "CUSTOM")).strip().upper()
    if kind not in {"EVENT_FLOW", "DI_BINDING", "MIDDLEWARE_ORDERING", "CUSTOM"}:
        raise ShapeParseError(path, line, f"unknown contract kind: {kind}")

    producer = str(block.get("producer_shape_id", "")).strip()
    producer_shape_id: ShapeId | None
    if producer:
        producer_shape_id = ShapeId(_coerce_shape_ref(producer))
    else:
        producer_shape_id = None

    consumer_values = block.get("consumer_shape_ids", block.get("consumers", []))
    consumer_shape_ids = [_coerce_shape_ref(item) for item in _coerce_str_list(consumer_values)]
    consumer_shape_ids = [cid for cid in consumer_shape_ids if cid]

    verifier_ids = [_normalize_whitespace(str(v)) for v in _coerce_str_list(block.get("verifier_ids", [])) if _normalize_whitespace(str(v))]

    payload_schema_ref = str(block.get("payload_schema_ref", "")).strip() or None
    payload_schema_ref = payload_schema_ref.strip() if payload_schema_ref else None

    metadata = {
        key: value
        for key, value in block.items()
        if key
        not in {
            "contract_id",
            "kind",
            "producer_shape_id",
            "consumer_shape_ids",
            "consumers",
            "_line",
            "payload_schema_ref",
            "verifier_ids",
        }
    }
    metadata.setdefault("contract_title", block.get("contract_title", ""))

    return ShapeContract(
        contract_id=contract_id,
        kind=kind,
        producer_shape_id=producer_shape_id,
        consumer_shape_ids=[ShapeId(consumer) for consumer in consumer_shape_ids],
        payload_schema_ref=payload_schema_ref,
        verifier_ids=verifier_ids,
        metadata=metadata,
    )


def parse_shape_document(path: Path) -> Shape:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    sections = _split_sections(lines)

    header = _parse_header_fields(sections.get("header", []), path)

    shape_id = _shape_id_from_value(_normalize_whitespace(header["package"]))
    package = _normalize_path_prefix(header["package"], convert_dots=True)

    systems = _parse_simple_list(sections.get("systems", []))
    surface_api = _parse_simple_list(sections.get("surface_api", []))
    dependencies_declared = _parse_simple_list(sections.get("dependencies", []))
    if isinstance(dependencies_declared, list):
        dependencies_declared = [_coerce_shape_ref(dep) if _coerce_shape_ref(dep) else dep for dep in dependencies_declared]
    consumers_declared = _parse_simple_list(sections.get("consumers_declared", []))
    if isinstance(consumers_declared, list):
        consumers_declared = [_coerce_shape_ref(dep) if _coerce_shape_ref(dep) else dep for dep in consumers_declared]

    files = _parse_list_value(",".join(header["files"]))

    verifier_blocks = _parse_keyed_blocks(sections.get("verifiers", []), section="verifiers")
    verifiers: list[VerifierSpec] = []
    for block in verifier_blocks:
        verifiers.append(_coerce_verifier_spec(block, path, block.get("_line", 1)))

    contract_blocks = _parse_keyed_blocks(sections.get("contracts", []), section="contracts")
    contracts: list[ShapeContract] = []
    for idx, block in enumerate(contract_blocks, start=1):
        contracts.append(_coerce_contract(block, shape_id, path, block.get("_line", 1), idx))

    status: ShapeStatus = "ACTIVE" if verifiers else "PROPOSAL"

    source_mtime = str(int(path.stat().st_mtime))
    shape = Shape(
        shape_id=shape_id,
        classification=_normalize_whitespace(header["classification"]),
        package=package,
        files=[_normalize_whitespace(_clean_markdown_link(file)) for file in files],
        role=_normalize_whitespace(header["role"]),
        systems=[_normalize_whitespace(item) for item in systems],
        surface_api=[_normalize_whitespace(item) for item in surface_api],
        dependencies_declared=[
            ShapeId(_coerce_shape_ref(item)) if _coerce_shape_ref(item) else item
            for item in dependencies_declared
            if str(item).strip()
        ],
        consumers_declared=[
            ShapeId(_coerce_shape_ref(item)) if _coerce_shape_ref(item) else item
            for item in consumers_declared
            if str(item).strip()
        ],
        verifiers=verifiers,
        contracts=contracts,
        status=status,
        source_path=str(path),
        requires_verifier_refresh=(status == "PROPOSAL"),
        metadata={"source_mtime": source_mtime},
    )

    return shape


def _ownership_prefix_candidates(shape: Shape) -> list[str]:
    prefixes = {_normalize_path_prefix(shape.package, convert_dots=True)}
    for file in shape.files:
        normalized = _normalize_path_prefix(file)
        if not normalized:
            continue
        normalized = normalized.lstrip("/")
        if "*" in normalized:
            normalized = normalized.split("*")[0].rstrip("/")
        if normalized:
            prefixes.add(normalized)
    return sorted(prefix for prefix in prefixes if prefix)


def _normalize_for_lookup(path: str) -> str:
    if not path:
        return ""
    normalized = path.replace("\\", "/").replace(" ", "-").lower()
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[2:]
    normalized = normalized.strip()
    if normalized.startswith("/"):
        normalized = normalized.lstrip("/")
    if normalized.startswith("workspace/"):
        normalized = normalized[len("workspace/"):]
    if normalized.startswith("runs/"):
        normalized = normalized[len("runs/"):]
    if normalized.startswith("routing/"):
        normalized = normalized[len("routing/"):]
    return normalized


def _path_belongs_to_prefix(path: str, prefix: str) -> bool:
    if not path or not prefix:
        return False
    return path == prefix or path.startswith(f"{prefix}/")


def resolve_shape_for_file(path: str, index: ShapePackIndex) -> ShapeId | None:
    normalized_path = _normalize_for_lookup(path)
    if not normalized_path:
        return None

    best_shape: ShapeId | None = None
    best_prefix_len = -1
    for prefix, shape_id in index.ownership_prefixes:
        if _path_belongs_to_prefix(normalized_path, prefix):
            prefix_len = len(prefix)
            if prefix_len > best_prefix_len:
                best_shape = shape_id
                best_prefix_len = prefix_len
    return best_shape


def _validate_contract_references(shape: Shape, known_ids: set[str]) -> list[str]:
    diagnostics: list[str] = []
    for contract in shape.contracts:
        unknown: list[str] = []
        if contract.producer_shape_id and str(contract.producer_shape_id) not in known_ids:
            unknown.append(f"producer={contract.producer_shape_id}")
        unknown.extend(
            consumer_id
            for consumer_id in contract.consumer_shape_ids
            if str(consumer_id) not in known_ids
        )
        if unknown:
            diagnostics.append(
                f"{shape.shape_id}: contract '{contract.contract_id}' references unknown shape(s): "
                + ", ".join(unknown)
            )
    return diagnostics


def load_shape_pack(workspace_root: Path, run_root: Path | None = None) -> ShapePackIndex:
    workspace_root = Path(workspace_root)
    system_root = workspace_root / "design" / "routing"
    run_search_roots = [
        *(
            [Path(run_root) / "routing", Path(run_root) / "shapes"]
            if run_root is not None
            else []
        ),
        workspace_root / "workspace" / "routing",
        workspace_root / "workspace" / "shapes",
        workspace_root / "runs" / "routing",
        workspace_root / "runs" / "shapes",
    ]

    index_root = workspace_root / "routing"
    system_shapes: dict[ShapeId, Shape] = {}
    run_shapes: dict[ShapeId, Shape] = {}
    diagnostics: list[str] = []

    def load_root(root: Path, *, target: dict[ShapeId, Shape], tag: str) -> None:
        if not root.exists():
            return
        for shape_path in sorted(root.rglob("*.md")):
            if not shape_path.is_file():
                continue
            shape = parse_shape_document(shape_path)
            shape.metadata["origin"] = tag
            if shape.shape_id in target:
                existing = target[shape.shape_id]
                if _normalize_path_prefix(existing.package, convert_dots=True) != _normalize_path_prefix(
                    shape.package, convert_dots=True
                ):
                    raise ShapeConflictError(
                        shape.shape_id,
                        existing.package,
                        shape.package,
                    )
            target[shape.shape_id] = shape

    load_root(system_root, target=system_shapes, tag="system")

    run_shapes_dir = ""
    for candidate in run_search_roots:
        if candidate.exists() and candidate.is_dir():
            if not run_shapes_dir:
                run_shapes_dir = str(candidate)
            load_root(candidate, target=run_shapes, tag="run")

    merged: dict[ShapeId, Shape] = dict(system_shapes)
    for shape_id, shape in run_shapes.items():
        if shape_id in merged:
            existing = merged[shape_id]
            if _normalize_path_prefix(existing.package, convert_dots=True) != _normalize_path_prefix(
                shape.package, convert_dots=True
            ):
                raise ShapeConflictError(shape_id, existing.package, shape.package)
        merged[shape_id] = shape

    previous: dict[str, Any] = {}
    previous_index = index_root / "index.json"
    if previous_index.exists():
        try:
            loaded = json.loads(previous_index.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (json.JSONDecodeError, OSError):
            previous = {}

    known_ids = {str(shape_id) for shape_id in merged}
    for shape in merged.values():
        shape.metadata.setdefault("package", shape.package)
        shape.metadata.setdefault("generated_from", shape.source_path)
        previous_shape = previous.get(str(shape.shape_id))
        if isinstance(previous_shape, dict):
            prev_metadata = previous_shape.get("metadata", {})
            if isinstance(prev_metadata, dict):
                previous_mtime = prev_metadata.get("source_mtime", "")
                current_mtime = shape.metadata.get("source_mtime", "")
                if str(current_mtime) != str(previous_mtime):
                    shape.requires_verifier_refresh = True

        shape_diagnostics = _validate_contract_references(shape, known_ids)
        shape.diagnostics.extend(shape_diagnostics)
        if shape_diagnostics:
            shape.status = "PROPOSAL"
            shape.requires_verifier_refresh = True

    ordered_shapes = {
        ShapeId(shape_id): shape
        for shape_id, shape in sorted(
            ((str(shape_id), shape) for shape_id, shape in merged.items()),
            key=lambda item: item[0],
        )
    }

    ownership_prefixes = sorted(
        {
            (prefix, shape_id)
            for shape_id, shape in ordered_shapes.items()
            for prefix in _ownership_prefix_candidates(shape)
            if prefix
        },
        key=lambda item: (-len(item[0]), item[0], item[1]),
    )

    if not system_root.exists() and not run_shapes_dir:
        diagnostics.append("no shape roots found under design/routing, workspace/routing, or workspace/shapes")

    return ShapePackIndex(
        system_shapes_dir=str(system_root),
        run_shapes_dir=run_shapes_dir,
        shapes=ordered_shapes,
        ownership_prefixes=ownership_prefixes,
        index_root=str(index_root),
        generated_at=_utcnow().isoformat(),
        diagnostics=diagnostics,
        metadata={"loaded_count": len(ordered_shapes)},
    )


def _serialize_shape_id(value: ShapeId | str) -> str:
    return str(value)


def _serialize_shape(shape: Shape) -> dict[str, Any]:
    payload = asdict(shape)
    payload["shape_id"] = str(shape.shape_id)
    payload["dependencies_declared"] = [
        _serialize_shape_id(item) for item in shape.dependencies_declared
    ]
    payload["consumers_declared"] = [
        _serialize_shape_id(item) for item in shape.consumers_declared
    ]
    payload["contracts"] = [
        {
            **asdict(contract),
            "producer_shape_id": _serialize_shape_id(contract.producer_shape_id)
            if contract.producer_shape_id
            else None,
            "consumer_shape_ids": [_serialize_shape_id(cid) for cid in contract.consumer_shape_ids],
        }
        for contract in shape.contracts
    ]
    return payload


def write_shape_index(index: ShapePackIndex) -> tuple[Path, Path]:
    index_dir = Path(index.index_root or index.run_shapes_dir or index.system_shapes_dir or ".")
    if index_dir.name != "routing":
        index_dir = index_dir / "routing"
    index_dir.mkdir(parents=True, exist_ok=True)

    index_json_path = index_dir / "index.json"
    index_md_path = index_dir / "INDEX.md"

    payload = {
        "system_shapes_dir": index.system_shapes_dir,
        "run_shapes_dir": index.run_shapes_dir,
        "generated_at": index.generated_at,
        "ownership_prefixes": [[prefix, str(shape_id)] for prefix, shape_id in index.ownership_prefixes],
        "shapes": {str(shape_id): _serialize_shape(shape) for shape_id, shape in index.shapes.items()},
        "diagnostics": list(index.diagnostics),
    }

    index_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    lines = ["# Routing Shape Index", ""]
    lines.append(f"Generated: {index.generated_at}")
    lines.append(f"System shapes root: {index.system_shapes_dir or 'N/A'}")
    lines.append(f"Run shapes root: {index.run_shapes_dir or 'N/A'}")
    lines.append("")

    for shape_id, shape in index.shapes.items():
        lines.append(f"- Shape: {shape_id}")
        lines.append(f"  - Package: {shape.package}")
        lines.append(f"  - Status: {shape.status}")
        lines.append(f"  - Classification: {shape.classification}")
        lines.append(f"  - Source: {shape.source_path}")
        lines.append(f"  - Requires verifier refresh: {shape.requires_verifier_refresh}")

    index_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return index_md_path, index_json_path


def bootstrap_shapes_from_spec(
    spec_components: list[dict[str, Any]],
    workspace_root: Path,
) -> list[Shape]:
    shapes: list[Shape] = []
    seen: set[str] = set()

    if not isinstance(spec_components, list):
        return shapes

    workspace_root = Path(workspace_root)

    for component in spec_components:
        if not isinstance(component, dict):
            continue

        classification = str(component.get("classification", "library")).strip() or "library"
        package = str(
            component.get("package")
            or component.get("module")
            or component.get("id")
            or component.get("name")
            or "shape"
        ).strip()
        files = _coerce_str_list(
            component.get("files")
            or component.get("ownership_paths")
            or component.get("file_paths")
            or component.get("paths")
        )
        role = str(component.get("role", "unknown")).strip() or "unknown"

        dependencies = _coerce_str_list(component.get("dependencies") or component.get("depends_on"))
        consumers = _coerce_str_list(component.get("consumers") or component.get("consumed_by"))
        systems = _coerce_str_list(component.get("systems") or component.get("components"))
        surface_api = _coerce_str_list(component.get("surface_api") or component.get("public_apis"))

        raw_verifiers = component.get("verifiers")
        verifiers: list[VerifierSpec] = []
        if isinstance(raw_verifiers, list):
            for item in raw_verifiers:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("verifier_id") or item.get("id") or item.get("name") or "").strip()
                if not vid:
                    continue
                kind = str(item.get("kind", "COMMAND")).strip().upper()
                if kind not in {"TEST", "IMPORT_BOUNDARY", "COMMAND"}:
                    kind = "COMMAND"
                verifiers.append(
                    VerifierSpec(
                        verifier_id=vid,
                        kind=kind,
                        params=_coerce_dict(item.get("params")),
                        source_ref=_clean_markdown_link(str(item.get("source_ref", "")).strip()),
                    )
                )

        raw_contracts = component.get("contracts")
        contracts: list[ShapeContract] = []
        if isinstance(raw_contracts, list):
            for idx, item in enumerate(raw_contracts, start=1):
                if not isinstance(item, dict):
                    continue
                contract_id = str(item.get("contract_id") or f"{package}-{idx}").strip()
                kind = str(item.get("kind", "CUSTOM")).strip().upper()
                if kind not in {"EVENT_FLOW", "DI_BINDING", "MIDDLEWARE_ORDERING", "CUSTOM"}:
                    kind = "CUSTOM"
                producer = str(item.get("producer_shape_id") or "").strip()
                consumers_for_contract = _coerce_str_list(
                    item.get("consumer_shape_ids") or item.get("consumers")
                )
                contracts.append(
                    ShapeContract(
                        contract_id=contract_id,
                        kind=kind,
                        producer_shape_id=ShapeId(_coerce_shape_ref(producer)) if producer else None,
                        consumer_shape_ids=[ShapeId(_coerce_shape_ref(c)) for c in consumers_for_contract],
                        payload_schema_ref=str(item.get("payload_schema_ref", "")).strip() or None,
                        verifier_ids=_coerce_str_list(item.get("verifier_ids") or item.get("verifiers")),
                        metadata={
                            "source": "spec_decomposition",
                        },
                    )
                )

        shape_id = _shape_id_from_value(_shape_id_from_value(package + "-shape").__str__())
        normalized_shape_id = str(shape_id)
        unique_shape_id = normalized_shape_id
        suffix = 1
        while unique_shape_id in seen:
            unique_shape_id = f"{normalized_shape_id}-{suffix}"
            suffix += 1

        status: ShapeStatus = "ACTIVE" if verifiers else "PROPOSAL"
        shape = Shape(
            shape_id=ShapeId(unique_shape_id),
            classification=classification,
            package=_normalize_path_prefix(package, convert_dots=True),
            files=[_normalize_whitespace(file_) for file_ in files],
            role=role,
            systems=[_normalize_whitespace(item) for item in systems],
            surface_api=[_normalize_whitespace(item) for item in surface_api],
            dependencies_declared=[
                ShapeId(_coerce_shape_ref(item)) if _coerce_shape_ref(item) else item
                for item in dependencies
                if str(item).strip()
            ],
            consumers_declared=[
                ShapeId(_coerce_shape_ref(item)) if _coerce_shape_ref(item) else item
                for item in consumers
                if str(item).strip()
            ],
            verifiers=verifiers,
            contracts=contracts,
            status=status,
            source_path=str(workspace_root / "routing" / f"{unique_shape_id}.md"),
            last_updated_phase="libraries",
            requires_verifier_refresh=True,
            metadata={"bootstrap": True},
        )
        seen.add(unique_shape_id)
        shapes.append(shape)

    return shapes


__all__ = [
    "Shape",
    "ShapeConflictError",
    "ShapeContract",
    "ShapeId",
    "ShapePackIndex",
    "ShapeParseError",
    "VerifierSpec",
    "bootstrap_shapes_from_spec",
    "load_shape_pack",
    "parse_shape_document",
    "resolve_shape_for_file",
    "write_shape_index",
]
