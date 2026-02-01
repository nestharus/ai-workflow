"""Structured formats and parsers for spec refinement workflows."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts.spec_refinement.workspace import WorkspaceManager

EVIDENCE_POINTER_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+?)\]")
EVIDENCE_POINTER_NEW_RE = re.compile(r"\[spec_snapshot/([^:]+)::([^\]]+)\]")

logger = logging.getLogger(__name__)


def normalize_compound_pointers(text: str) -> str:
    """Normalize accidental comma-separated pointers inside a single bracket.

    Some agents occasionally emit pointers like:
      [F0001::INTRO, F0001::REQS]
      [spec_snapshot/requirements/core.md::SEC-F0001-0001, SEC-F0001-0002]
    which break the `[FILE_ID::SECTION]` parser/validator. We normalize these into:
      [F0001::INTRO] [F0001::REQS]
    """

    def _rewrite(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "," not in inner or "::" not in inner:
            return match.group(0)
        parts = [part.strip() for part in inner.split(",") if part.strip()]
        if len(parts) < 2:
            return match.group(0)

        inferred_prefix: str | None = None
        if "::" in parts[0]:
            inferred_prefix = parts[0].split("::", 1)[0].strip()

        pointers: list[str] = []
        for part in parts:
            if "::" in part:
                pointers.append(part)
                continue
            if inferred_prefix is None:
                return match.group(0)
            pointers.append(f"{inferred_prefix}::{part}")

        return " ".join(f"[{pointer}]" for pointer in pointers)

    # This targets bracketed constructs containing at least one `::` and a comma.
    return re.sub(r"\[([^\[\]]*?::[^\[\]]*?)\]", _rewrite, text)


def parse_evidence_pointer(pointer: str) -> dict[str, str] | None:
    """Parse evidence pointer into file/section refs and format type."""
    cleaned = pointer.strip()
    if not cleaned:
        return None
    if "::" in cleaned and not cleaned.startswith("["):
        cleaned = f"[{cleaned}]"
    match = EVIDENCE_POINTER_NEW_RE.fullmatch(cleaned)
    if match:
        return {
            "file_ref": match.group(1).strip(),
            "section_ref": match.group(2).strip(),
            "format": "new",
        }
    match = EVIDENCE_POINTER_RE.fullmatch(cleaned)
    if match:
        return {
            "file_ref": match.group(1).strip(),
            "section_ref": match.group(2).strip(),
            "format": "legacy",
        }
    return None


def extract_pointer_components(pointer: str) -> tuple[str, str, str] | None:
    """Extract file reference, section reference, and format from an evidence pointer."""
    parsed = parse_evidence_pointer(pointer)
    if not parsed:
        return None
    return parsed["file_ref"], parsed["section_ref"], parsed["format"]


def build_evidence_pointer(
    file_id: str,
    section_id: str,
    file_manifest: dict[str, dict[str, str]],
) -> str:
    """Construct a new-format evidence pointer from manifest data."""
    file_entry = file_manifest.get(file_id)
    if not file_entry or "relpath" not in file_entry:
        raise KeyError(f"Missing relpath for file_id '{file_id}'.")
    relpath = file_entry["relpath"]
    return f"[spec_snapshot/{relpath}::{section_id}]"


def migrate_pointers_to_new_format(content: str, manager: WorkspaceManager) -> str:
    """Migrate legacy evidence pointers to the new spec_snapshot format."""
    if not content:
        return content

    from .validation_utils import build_file_id_lookup, build_section_id_lookup

    file_lookup = build_file_id_lookup(
        manager.state.file_manifest, manager.structure.spec_snapshot_dir
    )

    def _replace(match: re.Match[str]) -> str:
        pointer = match.group(0)
        parsed = parse_evidence_pointer(pointer)
        if not parsed or parsed["format"] != "legacy":
            return pointer

        file_ref = parsed["file_ref"]
        section_ref = parsed["section_ref"]
        resolved_file_id = file_lookup.get(file_ref)
        if resolved_file_id is None:
            return pointer

        sections_data = manager.read_file_sections(resolved_file_id)
        if not sections_data:
            return pointer

        section_lookup = build_section_id_lookup(resolved_file_id, sections_data)
        section_id = section_lookup.get(section_ref)
        if not section_id:
            normalized = section_ref.strip().lower().replace(" ", "_").replace("-", "_")
            section_id = section_lookup.get(normalized)
        if not section_id:
            return pointer

        file_entry = manager.state.file_manifest.get(resolved_file_id, {})
        relpath = file_entry.get("relpath") if isinstance(file_entry, dict) else file_entry
        if not relpath:
            return pointer

        return f"[spec_snapshot/{relpath}::{section_id}]"

    return EVIDENCE_POINTER_RE.sub(_replace, content)


@dataclass(frozen=True)
class FileSummary:
    """Summary of a file's algorithms, components, workflows, and responsibilities."""

    file_id: str
    algorithms: list[dict[str, Any]]
    components: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    candidate_responsibilities: list[dict[str, Any]]
    dependencies: list[str]
    evidence_map: dict[str, list[str]]


@dataclass(frozen=True)
class LibraryCharter:
    """Charter defining a library's intent, boundaries, and responsibilities."""

    lib_id: str
    intent: str
    boundaries: str
    responsibilities: list[str]
    evidence_sources: list[dict[str, Any]]
    overlap_resolutions: list[dict[str, str]]


@dataclass(frozen=True)
class ArchitectureCandidate:
    """Architecture candidate proposal with components and tradeoffs."""

    arch_id: str
    pattern: str
    description: str
    components: list[dict[str, Any]]
    communication: str
    deployment: str
    citations: list[str]
    tradeoffs: dict[str, list[str]]


def _extract_sections(content: str, level: int) -> dict[str, str]:
    pattern = re.compile(rf"^{'#' * level}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[title] = content[start:end].strip()
    return sections


def _extract_file_id(content: str) -> str:
    for line in content.splitlines():
        if "file id" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    match = re.search(r"File Summary:\s*([\w\-\.]+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown"


def _extract_pointers(text: str) -> list[str]:
    pointers: list[str] = []
    for match in EVIDENCE_POINTER_RE.finditer(text):
        pointer = match.group(0)
        parsed = parse_evidence_pointer(pointer)
        if not parsed:
            continue
        if parsed["format"] == "legacy":
            logger.info("Legacy evidence pointer detected: %s", pointer)
            pointers.append(f"[{parsed['file_ref']}::{parsed['section_ref']}]")
            continue
        pointers.append(f"[spec_snapshot/{parsed['file_ref']}::{parsed['section_ref']}]")
    return pointers


def _strip_evidence(text: str) -> str:
    without_pointers = EVIDENCE_POINTER_RE.sub("", text)
    without_label = re.sub(r"(?i)\bEvidence\s*:\s*", "", without_pointers)
    return without_label.strip(" -|\t")


def _split_name_intent(text: str) -> tuple[str, str]:
    if "|" in text:
        parts = [part.strip() for part in text.split("|") if part.strip()]
        if len(parts) >= 2:
            return parts[0], " | ".join(parts[1:])
        if parts:
            return parts[0], ""
    for delimiter in (" -- ", " - ", ": "):
        if delimiter in text:
            name, intent = text.split(delimiter, 1)
            return name.strip(), intent.strip()
    return text.strip(), ""


def _parse_named_items(section_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        evidence = _extract_pointers(raw)
        cleaned = _strip_evidence(raw)
        name, intent = _split_name_intent(cleaned)
        items.append({"name": name, "intent": intent, "evidence": evidence})
    return items


def _parse_responsibilities(section_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        evidence = _extract_pointers(raw)
        description = _strip_evidence(raw)
        if description:
            items.append({"description": description, "evidence": evidence})
    return items


def _parse_dependencies(section_text: str) -> list[str]:
    deps = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            deps.append(stripped.lstrip("-* ").strip())
    if not deps and section_text.strip():
        deps = [part.strip() for part in section_text.split(",") if part.strip()]
    return deps


def _parse_evidence_map(section_text: str) -> dict[str, list[str]]:
    evidence_map: dict[str, list[str]] = {}
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ")
        if ":" not in raw:
            continue
        section_label, rest = raw.split(":", 1)
        pointers = EVIDENCE_POINTER_RE.findall(rest)
        file_ids = [file_id for file_id, _ in pointers]
        if file_ids:
            evidence_map[section_label.strip()] = file_ids
    return evidence_map


def parse_file_summary(content: str) -> FileSummary:
    """Parse a file summary markdown string into a structured FileSummary."""
    file_id = _extract_file_id(content)
    sections = _extract_sections(content, level=2)

    def _get_section(*names: str) -> str:
        for name in names:
            if name in sections:
                return sections[name]
        return ""

    algorithms = _parse_named_items(_get_section("Algorithms", "ALGORITHMS"))
    components = _parse_named_items(_get_section("Components", "COMPONENTS"))
    workflows = _parse_named_items(_get_section("Workflows", "WORKFLOWS"))
    responsibilities = _parse_responsibilities(
        _get_section("Candidate Responsibilities", "CANDIDATE RESPONSIBILITIES")
    )
    dependencies = _parse_dependencies(_get_section("Dependencies", "DEPENDENCIES"))
    evidence_map = _parse_evidence_map(_get_section("Evidence Map", "EVIDENCE MAP"))

    return FileSummary(
        file_id=file_id,
        algorithms=algorithms,
        components=components,
        workflows=workflows,
        candidate_responsibilities=responsibilities,
        dependencies=dependencies,
        evidence_map=evidence_map,
    )


def _split_library_blocks(content: str) -> list[tuple[str, str]]:
    header_re = re.compile(r"^###\s+(lib_\d{3})\b.*$", re.MULTILINE)
    matches = list(header_re.finditer(content))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        lib_id = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        blocks.append((lib_id, content[start:end].strip()))
    return blocks


def _parse_overlap_resolutions(section_text: str) -> list[dict[str, str]]:
    resolutions: list[dict[str, str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        raw = stripped.lstrip("-* ").strip()
        if not raw:
            # Ignore empty bullets (common LLM formatting artifact).
            continue
        if raw.lower() in {"none", "n/a", "no overlaps"}:
            continue
        if "->" in raw:
            description, decision = [part.strip() for part in raw.split("->", 1)]
        elif ":" in raw:
            description, decision = [part.strip() for part in raw.split(":", 1)]
        else:
            description, decision = raw, ""
        resolutions.append({"description": description, "decision": decision})
    return resolutions


def _extract_text_field(block: str, field: str) -> str:
    sections = _extract_sections(block, level=4)
    if field in sections and sections[field].strip():
        return sections[field].strip()
    for line in block.splitlines():
        if line.lower().startswith(f"{field.lower()}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _extract_list_field(block: str, field: str) -> list[str]:
    sections = _extract_sections(block, level=4)
    text = sections.get(field, "")
    if not text:
        return []
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            items.append(stripped.lstrip("-* ").strip())
    return items


def _extract_evidence_sources(block: str) -> list[dict[str, Any]]:
    sections = _extract_sections(block, level=4)
    evidence_text = sections.get("Evidence", "")
    pointers = EVIDENCE_POINTER_RE.findall(evidence_text)
    grouped: dict[str, set[str]] = {}
    for file_id, section in pointers:
        grouped.setdefault(file_id, set()).add(section)
    return [
        {"file_id": file_id, "sections": sorted(sections)} for file_id, sections in grouped.items()
    ]


def parse_library_synthesis(content: str) -> tuple[list[LibraryCharter], str]:
    """Parse a library synthesis markdown string into charters and index content."""
    sections = _extract_sections(content, level=2)
    index_section = sections.get("Library Index", "")
    index_entries: list[str] = []
    if index_section:
        for line in index_section.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*")):
                continue
            raw = stripped.lstrip("-* ")
            index_entries.append(raw)

    charters: list[LibraryCharter] = []
    for lib_id, block in _split_library_blocks(content):
        intent = _extract_text_field(block, "Intent")
        boundaries = _extract_text_field(block, "Boundaries")
        responsibilities = _extract_list_field(block, "Responsibilities")
        evidence_sources = _extract_evidence_sources(block)
        overlap_text = _extract_sections(block, level=4).get("Overlap Resolutions", "")
        overlap_resolutions = _parse_overlap_resolutions(overlap_text)
        charters.append(
            LibraryCharter(
                lib_id=lib_id,
                intent=intent,
                boundaries=boundaries,
                responsibilities=responsibilities,
                evidence_sources=evidence_sources,
                overlap_resolutions=overlap_resolutions,
            )
        )

    if index_entries:
        index_lines = ["# Library Index", ""]
        for entry in index_entries:
            index_lines.append(f"- {entry}")
        index_content = "\n".join(index_lines).strip() + "\n"
    else:
        index_lines = ["# Library Index", ""]
        for charter in charters:
            intent = charter.intent or "Intent not provided"
            index_lines.append(f"- {charter.lib_id}: {intent}")
        index_content = "\n".join(index_lines).strip() + "\n"

    return charters, index_content


def parse_evidence_mapper_output(json_str: str) -> dict[str, Any]:
    """Parse glm-library-evidence-mapper JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import EvidenceMapperOutput

    try:
        return EvidenceMapperOutput.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for evidence mapper output; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = ["file_id", "relevant_sections", "confidence", "rationale"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    # priority and priority_rationale are optional fields added by the workflow
    return data


def parse_gap_judge_output(json_str: str) -> dict[str, Any]:
    """Parse chatgpt-library-spec-gap-judge JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import GapJudgeOutput

    try:
        return GapJudgeOutput.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for gap judge output; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = ["gaps", "total_gaps", "file_id"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_evidence_spotcheck_output(json_str: str) -> dict[str, Any]:
    """Parse chatgpt-evidence-gap-judge JSON output."""
    import json

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = ["missing_sections", "scan_complete"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def _extract_json_payload(output: str) -> str:
    """Extract the first valid JSON object/array from an agent output string.

    This is intentionally tolerant of:
    - leading/trailing commentary
    - fenced code blocks
    - bracket characters appearing *after* the JSON payload
    """
    cleaned = output.strip()
    if not cleaned:
        return cleaned

    # Drop agent-exec noise lines (if any).
    lines = [line for line in cleaned.splitlines() if not line.startswith("[agent-exec]")]
    cleaned = "\n".join(lines).strip()

    # If the output is a fenced block, prefer the first fenced payload.
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            fence_end = cleaned.find("```", first_newline + 1)
            if fence_end != -1:
                cleaned = cleaned[first_newline + 1 : fence_end].strip()

    decoder = json.JSONDecoder()

    # Find the first plausible JSON start and attempt raw_decode from there.
    first_obj = cleaned.find("{")
    first_list = cleaned.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if not starts:
        return cleaned

    for start in sorted(starts):
        # Scan forward to the next '{' or '[' and try to decode.
        idx = start
        while idx < len(cleaned):
            ch = cleaned[idx]
            if ch not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(cleaned[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return cleaned[idx : idx + end]

    # Fallback: return from earliest start if we cannot decode (caller will raise).
    return cleaned[min(starts) :]


def _validate_architecture_candidate(candidate: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    required_fields = [
        "arch_id",
        "pattern",
        "description",
        "components",
        "communication",
        "deployment",
        "citations",
        "tradeoffs",
    ]
    for field in required_fields:
        if field not in candidate:
            issues.append(f"missing_{field}")
    if not isinstance(candidate.get("components", []), list):
        issues.append("components_not_list")
    if not isinstance(candidate.get("citations", []), list):
        issues.append("citations_not_list")
    tradeoffs = candidate.get("tradeoffs")
    if not isinstance(tradeoffs, dict):
        issues.append("tradeoffs_not_object")
    else:
        if not isinstance(tradeoffs.get("advantages", []), list):
            issues.append("tradeoffs_advantages_not_list")
        if not isinstance(tradeoffs.get("disadvantages", []), list):
            issues.append("tradeoffs_disadvantages_not_list")
    return issues


def parse_architecture_proposal(json_str: str) -> list[ArchitectureCandidate]:
    """Parse opus-architecture-proposer JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import ArchitectureProposal as ArchitectureProposalSchema

    try:
        proposal = ArchitectureProposalSchema.model_validate_json(json_str)
        return [
            ArchitectureCandidate(**candidate.model_dump()) for candidate in proposal.candidates
        ]
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for architecture proposal; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, list):
        raise TypeError("Architecture proposal must be a JSON array.")

    candidates: list[ArchitectureCandidate] = []
    errors: list[str] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"candidate_{index}_not_object")
            continue
        issues = _validate_architecture_candidate(item)
        if issues:
            errors.extend([f"candidate_{index}:{issue}" for issue in issues])
            continue
        candidates.append(
            ArchitectureCandidate(
                arch_id=str(item.get("arch_id", "")).strip(),
                pattern=str(item.get("pattern", "")).strip(),
                description=str(item.get("description", "")).strip(),
                components=item.get("components", []),
                communication=str(item.get("communication", "")).strip(),
                deployment=str(item.get("deployment", "")).strip(),
                citations=item.get("citations", []),
                tradeoffs=item.get("tradeoffs", {}),
            )
        )

    if errors:
        raise ValueError("; ".join(errors))
    return candidates


def parse_architecture_selection(json_str: str) -> dict[str, Any]:
    """Parse chatgpt-architecture-tradeoff-judge JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import ArchitectureSelection

    try:
        return ArchitectureSelection.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for architecture selection; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = [
        "selected_arch_id",
        "rationale",
        "rejected_architectures",
        "implementation_risks",
        "evolution_notes",
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_library_labeler_output(json_str: str) -> dict[str, Any]:
    """Parse glm-file-library-labeler JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import LibraryLabelerOutput

    try:
        return LibraryLabelerOutput.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for library labeler output; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = ["file_id", "candidate_labels", "uncertain_labels"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_spec_patch_output(json_str: str) -> dict[str, Any]:
    """Parse glm-library-spec-integrator JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import SpecPatchOutput

    try:
        return SpecPatchOutput.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for spec patch output; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = ["file_id", "lib_id", "patches"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def parse_architecture_brief_output(json_str: str) -> dict[str, Any]:
    """Parse glm-architecture-brief-extractor JSON output."""
    from pydantic import ValidationError

    from scripts.spec_refinement.schemas import ArchitectureBrief

    try:
        return ArchitectureBrief.model_validate_json(json_str).model_dump()
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Structured parsing failed for architecture brief output; falling back: %s",
            exc,
        )

    data = json.loads(_extract_json_payload(json_str))
    if not isinstance(data, dict):
        raise TypeError("Expected JSON object.")
    required_fields = [
        "lib_id",
        "intent",
        "boundaries",
        "dependencies",
        "constraints",
        "interfaces",
    ]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    return data


def _extract_component_mappings(content: str) -> dict[str, list[str]]:
    component_map: dict[str, list[str]] = {}
    current_component: str | None = None
    in_libraries = False

    for line in content.splitlines():
        component_match = re.match(r"^###\s+Component:\s*(.+)$", line.strip())
        if component_match:
            component_name = component_match.group(1).strip()
            current_component = component_name
            component_map.setdefault(component_name, [])
            in_libraries = False
            continue

        if line.strip().startswith("## "):
            current_component = None
            in_libraries = False
            continue

        if current_component is None:
            continue

        if line.strip().lower().startswith("**libraries**"):
            in_libraries = True
            continue

        if in_libraries and line.strip().startswith(("-", "*")):
            raw = line.strip().lstrip("-* ").strip()

            # Only accept `- lib_###: ...` lines; ignore freeform bullets like `- None (...)`.
            if ":" not in raw:
                continue
            lib_id = raw.split(":", 1)[0].strip()
            if not lib_id:
                continue
            lowered = lib_id.lower()
            if lowered in {"none", "n/a"} or lowered.startswith("none"):
                continue
            if not lowered.startswith("lib_"):
                continue
            component_map[current_component].append(lib_id)

    return component_map


def parse_architecture_mapping(content: str) -> dict[str, Any]:
    """Parse glm-architecture-mapper markdown output."""
    component_map = _extract_component_mappings(content)

    component_lines: dict[str, list[str]] = {name: [] for name in component_map}
    current_component: str | None = None
    in_libraries = False
    for line in content.splitlines():
        component_match = re.match(r"^###\s+Component:\s*(.+)$", line.strip())
        if component_match:
            component_name = component_match.group(1).strip()
            current_component = component_name
            component_lines.setdefault(component_name, [])
            in_libraries = False
            continue

        if line.strip().startswith("## "):
            current_component = None
            in_libraries = False
            continue

        if current_component is None:
            continue

        if line.strip().lower().startswith("**libraries**"):
            in_libraries = True
            continue

        if in_libraries and line.strip().startswith(("-", "*")) and current_component is not None:
            raw = line.strip().lstrip("-* ").strip()
            if ":" not in raw:
                continue
            lib_id = raw.split(":", 1)[0].strip()
            if not lib_id or not lib_id.lower().startswith("lib_"):
                continue
            component_lines[current_component].append(line.strip())

    sections = _extract_sections(content, level=2)
    dependencies = _parse_dependencies(sections.get("Cross-Component Dependencies", ""))
    unmapped_lines = sections.get("Unmapped Libraries", "").splitlines()
    unmapped: list[str] = []
    for line in unmapped_lines:
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            item = stripped.lstrip("-* ").strip()
            lowered = item.lower()
            if item and lowered not in {"none", "n/a"} and not lowered.startswith("none"):
                unmapped.append(item)
        elif stripped:
            lowered = stripped.lower()
            if lowered in {"none", "n/a"} or lowered.startswith("none"):
                continue
            unmapped.append(stripped)

    return {
        "component_mappings": component_map,
        "component_lines": component_lines,
        "dependencies": dependencies,
        "unmapped_libraries": unmapped,
    }
