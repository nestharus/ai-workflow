"""Sub-library detection workflow for Phase 5 spec refinement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import json
import re

from scripts.dev.agent_runner import AgentRunner
from scripts.spec_refinement.core.gap import Gap, GapEvidence, GapSynthesizer, parse_gaps_markdown
from scripts.spec_refinement.workspace import Phase, PhaseStatus, WorkspaceManager

from . import evidence_expansion as evidence_utils
from .formats import parse_file_summary, parse_gap_judge_output
from .progress import ProgressTracker
from .spec_building import (
    MAX_ITERATIONS_DEFAULT,
    SEVERITY_MAP,
    VALID_GAP_SEVERITIES,
    _build_gap_prompt,
    _build_integration_prompt,
    _gap_signature,
    _initialize_spec,
    _normalize_evidence_sources,
    _read_evidence_sources,
    _update_decisions,
    _validate_spec_citations,
)


def detect_sublibraries(
    run_id: str,
    config_path: Path,
    max_depth: int = 3,
    min_overlap_threshold: float = 0.2,
) -> dict[str, Any]:
    """Detect sub-libraries and recursively refine (Phase 5)."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    spec_building_status = manager.state.phases[Phase.SPEC_BUILDING.value].status
    if spec_building_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Spec building must be completed before sub-library detection.")

    manager.start_phase(Phase.SUBLIBRARY_DETECTION)

    libraries_dir = manager.structure.libraries_dir
    lib_dirs = [lib_dir for lib_dir in sorted(libraries_dir.iterdir()) if lib_dir.is_dir()]

    tracker = ProgressTracker(
        total=len(lib_dirs),
        description="Detecting sub-libraries",
        manager=manager,
    )

    total_sublibraries_created = 0
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for lib_dir in lib_dirs:
        result = _detect_library_sublibraries(
            manager, lib_dir, config_path, max_depth, min_overlap_threshold
        )
        total_sublibraries_created += result.get("sublibraries_created", 0)
        errors.extend(result.get("errors", []))
        issues.extend(result.get("issues", []))
        tracker.update(status=lib_dir.name)

    tracker.finish()

    if total_sublibraries_created > 0:
        _recursive_refinement(manager, config_path, max_depth, current_depth=1)

    phase_result = manager.state.phases[Phase.SUBLIBRARY_DETECTION.value]
    phase_result.issues = errors + issues

    outputs = {"sublibraries_created": total_sublibraries_created}
    manager.complete_phase(Phase.SUBLIBRARY_DETECTION, outputs=outputs)

    return {
        "sublibraries_created": total_sublibraries_created,
        "errors": errors,
        "issues": issues,
        "outputs": outputs,
    }


def _detect_library_sublibraries(
    manager: WorkspaceManager,
    lib_dir: Path,
    config_path: Path,
    max_depth: int,
    min_overlap_threshold: float,
) -> dict[str, Any]:
    """Detect sub-libraries for a single library."""
    lib_id = lib_dir.name
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    spec_path = lib_dir / "spec.md"
    charter_path = lib_dir / "charter.md"
    evidence_path = lib_dir / "evidence.json"

    if not spec_path.exists():
        errors.append({"lib_id": lib_id, "error": "Missing spec.md"})
        return {"lib_id": lib_id, "errors": errors, "sublibraries_created": 0}

    spec_content = spec_path.read_text(encoding="utf-8")
    charter_content = charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""
    evidence_content = evidence_path.read_text(encoding="utf-8") if evidence_path.exists() else "{}"

    prompt = _build_sublibrary_prompt(lib_id, spec_content, charter_content, evidence_content)

    runner = AgentRunner.from_agent_name(
        "opus-sublibrary-planner", config_path, prompt_chars=len(prompt)
    )

    try:
        output = runner.run(prompt)
    except RuntimeError as exc:
        errors.append({"lib_id": lib_id, "error": f"Agent execution failed: {exc}"})
        return {"lib_id": lib_id, "errors": errors, "sublibraries_created": 0}

    try:
        data = parse_sublibrary_output(output)
    except Exception as exc:
        errors.append({"lib_id": lib_id, "error": f"Failed to parse output: {exc}"})
        return {"lib_id": lib_id, "errors": errors, "sublibraries_created": 0}

    sub_libraries = data.get("sub_libraries", [])
    if not sub_libraries:
        return {"lib_id": lib_id, "errors": errors, "sublibraries_created": 0}

    overlap_issues, invalid_overlap_ids = _validate_sublibrary_overlap(
        lib_id, sub_libraries, min_overlap_threshold
    )
    issues.extend(overlap_issues)

    sublibraries_created = 0
    for sub_lib in sub_libraries:
        validation_issues = _validate_sublibrary_proposal(
            manager, lib_id, sub_lib, min_overlap_threshold
        )
        issues.extend(validation_issues)

        sub_lib_id = sub_lib.get("sub_lib_id")
        if validation_issues or not sub_lib_id or sub_lib_id in invalid_overlap_ids:
            continue

        _create_sublibrary(manager, lib_dir, sub_lib)
        sublibraries_created += 1

    return {
        "lib_id": lib_id,
        "errors": errors,
        "issues": issues,
        "sublibraries_created": sublibraries_created,
    }


def _recursive_refinement(
    manager: WorkspaceManager,
    config_path: Path,
    max_depth: int,
    current_depth: int,
) -> None:
    """Recursively refine sub-libraries until no more candidates or max depth."""
    if current_depth >= max_depth:
        return

    sublibrary_dirs = _find_sublibraries_at_depth(manager, current_depth)

    if not sublibrary_dirs:
        return

    for sub_lib_dir in sublibrary_dirs:
        _expand_sublibrary_evidence(manager, sub_lib_dir, config_path)
        _build_sublibrary_spec(manager, sub_lib_dir, config_path)

    for sub_lib_dir in sublibrary_dirs:
        result = _detect_library_sublibraries(
            manager, sub_lib_dir, config_path, max_depth, min_overlap_threshold=0.2
        )
        if result.get("sublibraries_created", 0) > 0:
            _recursive_refinement(manager, config_path, max_depth, current_depth + 1)


def _build_sublibrary_prompt(
    lib_id: str,
    spec_content: str,
    charter_content: str,
    evidence_content: str,
) -> str:
    """Build prompt for Opus sub-library planner."""
    lines = [
        "Analyze the library spec to detect internal boundaries for sub-libraries.",
        "Return JSON with sub_libraries list (empty if no splits recommended).",
        "",
        f"Library ID: {lib_id}",
        "",
        "Library Charter:",
        charter_content.strip(),
        "",
        "Library Spec:",
        spec_content.strip(),
        "",
        "Evidence Sources:",
        evidence_content.strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def parse_sublibrary_output(output: str) -> dict[str, Any]:
    """Parse Opus sub-library planner output."""
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", output, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    return json.loads(output)


def _validate_sublibrary_proposal(
    manager: WorkspaceManager,
    parent_lib_id: str,
    sub_lib: dict[str, Any],
    min_overlap_threshold: float,
) -> list[dict[str, Any]]:
    """Validate sub-library proposal."""
    issues: list[dict[str, Any]] = []

    sub_lib_id = sub_lib.get("sub_lib_id")
    if not sub_lib_id:
        issues.append(
            {
                "type": "missing_sub_lib_id",
                "parent_lib_id": parent_lib_id,
                "message": "Sub-library missing ID",
            }
        )

    if not sub_lib.get("charter"):
        issues.append(
            {
                "type": "missing_charter",
                "parent_lib_id": parent_lib_id,
                "sub_lib_id": sub_lib_id,
                "message": "Sub-library missing charter",
            }
        )

    evidence_partition = sub_lib.get("evidence_partition", [])
    if not isinstance(evidence_partition, list):
        evidence_partition = []
    if not evidence_partition:
        issues.append(
            {
                "type": "empty_evidence_partition",
                "parent_lib_id": parent_lib_id,
                "sub_lib_id": sub_lib_id,
                "message": "Sub-library has no evidence",
            }
        )

    for pointer in evidence_partition:
        if not isinstance(pointer, str) or "::" not in pointer:
            issues.append(
                {
                    "type": "invalid_evidence_pointer",
                    "parent_lib_id": parent_lib_id,
                    "sub_lib_id": sub_lib_id,
                    "pointer": pointer,
                    "message": "Evidence pointer missing section",
                }
            )
            continue

        file_id, section_id = pointer.split("::", 1)
        if file_id not in manager.state.file_manifest:
            issues.append(
                {
                    "type": "unknown_file_reference",
                    "parent_lib_id": parent_lib_id,
                    "sub_lib_id": sub_lib_id,
                    "pointer": pointer,
                    "message": f"Unknown file: {file_id}",
                }
            )
        elif section_id not in manager.state.section_manifest.get(file_id, []):
            issues.append(
                {
                    "type": "unknown_section_reference",
                    "parent_lib_id": parent_lib_id,
                    "sub_lib_id": sub_lib_id,
                    "pointer": pointer,
                    "message": f"Unknown section: {section_id}",
                }
            )

    return issues


def _validate_sublibrary_overlap(
    parent_lib_id: str,
    sub_libraries: list[dict[str, Any]],
    min_overlap_threshold: float,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Validate evidence overlap across sub-library proposals."""
    issues: list[dict[str, Any]] = []
    invalid_ids: set[str] = set()

    partitions: dict[str, set[str]] = {}
    for sub_lib in sub_libraries:
        sub_lib_id = sub_lib.get("sub_lib_id")
        if not sub_lib_id:
            continue
        evidence_partition = sub_lib.get("evidence_partition", [])
        if not isinstance(evidence_partition, list):
            evidence_partition = []
        partitions[sub_lib_id] = {
            pointer for pointer in evidence_partition if isinstance(pointer, str) and "::" in pointer
        }

    ids = sorted(partitions.keys())
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1 :]:
            left_set = partitions[left_id]
            right_set = partitions[right_id]
            if not left_set or not right_set:
                continue
            overlap = left_set & right_set
            if not overlap:
                continue
            overlap_ratio = len(overlap) / min(len(left_set), len(right_set))
            if overlap_ratio >= min_overlap_threshold:
                issues.append(
                    {
                        "type": "evidence_overlap",
                        "parent_lib_id": parent_lib_id,
                        "sub_lib_ids": [left_id, right_id],
                        "overlap_ratio": overlap_ratio,
                        "overlap": sorted(overlap),
                        "message": "Evidence overlap exceeds threshold.",
                    }
                )
                invalid_ids.update({left_id, right_id})

    return issues, invalid_ids


def _create_sublibrary(
    manager: WorkspaceManager,
    parent_lib_dir: Path,
    sub_lib: dict[str, Any],
) -> None:
    """Create sub-library directory structure."""
    sub_lib_id = sub_lib["sub_lib_id"]
    sublibraries_dir = parent_lib_dir / "sublibraries"
    sublibraries_dir.mkdir(exist_ok=True)

    sub_lib_dir = sublibraries_dir / sub_lib_id
    sub_lib_dir.mkdir(exist_ok=True)

    charter_content = _format_sublibrary_charter(sub_lib)
    (sub_lib_dir / "charter.md").write_text(charter_content, encoding="utf-8")

    evidence_payload = {
        "sources": [
            {
                "file_id": pointer.split("::")[0],
                "sections": [pointer.split("::")[1]],
                "confidence": 1.0,
                "rationale": f"Partitioned from parent library {parent_lib_dir.name}",
            }
            for pointer in sub_lib.get("evidence_partition", [])
            if isinstance(pointer, str) and "::" in pointer
        ]
    }
    (sub_lib_dir / "evidence.json").write_text(
        json.dumps(evidence_payload, indent=2), encoding="utf-8"
    )

    interface_impact = sub_lib.get("interface_impact", "")
    if interface_impact:
        (sub_lib_dir / "interface_notes.md").write_text(
            f"## Interface Impact\n\n{interface_impact}\n", encoding="utf-8"
        )

    (sub_lib_dir / "gaps.md").write_text("", encoding="utf-8")
    (sub_lib_dir / "decisions.md").write_text("", encoding="utf-8")


def _format_sublibrary_charter(sub_lib: dict[str, Any]) -> str:
    """Format sub-library charter."""
    charter = sub_lib.get("charter", {})
    lines = [
        f"# Sub-Library Charter: {sub_lib['sub_lib_id']}",
        "",
        "## Intent",
        charter.get("intent", ""),
        "",
        "## Boundaries",
        charter.get("boundaries", ""),
        "",
        "## Responsibilities",
    ]
    for resp in charter.get("responsibilities", []):
        lines.append(f"- {resp}")
    lines.append("")
    lines.append("## Justification")
    lines.append(sub_lib.get("justification", ""))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _find_sublibraries_at_depth(manager: WorkspaceManager, depth: int) -> list[Path]:
    """Find all sub-libraries at a specific depth."""
    sublibrary_dirs: list[Path] = []

    def _traverse(current_dir: Path, current_depth: int) -> None:
        if current_depth == depth:
            sublibrary_dirs.append(current_dir)
            return

        sublibraries_dir = current_dir / "sublibraries"
        if not sublibraries_dir.exists():
            return

        for sub_dir in sorted(sublibraries_dir.iterdir()):
            if sub_dir.is_dir():
                _traverse(sub_dir, current_depth + 1)

    for lib_dir in sorted(manager.structure.libraries_dir.iterdir()):
        if lib_dir.is_dir():
            _traverse(lib_dir, 0)

    return sublibrary_dirs


def _expand_sublibrary_evidence(
    manager: WorkspaceManager, sub_lib_dir: Path, config_path: Path
) -> None:
    """Run evidence expansion for a sub-library (Phase 3)."""
    charter_path = sub_lib_dir / "charter.md"
    if not charter_path.exists():
        return
    charter_content = charter_path.read_text(encoding="utf-8")
    charter = evidence_utils._parse_charter(charter_content)

    summary_dir = manager.structure.summaries_dir
    summaries: dict[str, dict[str, Any]] = {}
    for summary_path in sorted(summary_dir.glob("*.what.md")):
        file_id = summary_path.stem.replace(".what", "")
        content = summary_path.read_text(encoding="utf-8")
        parsed = None
        try:
            parsed = parse_file_summary(content)
        except Exception:
            parsed = None
        summaries[file_id] = {"content": content, "parsed": parsed}

    pairs: list[tuple[str, str, str, str]] = []
    for file_id, summary_info in summaries.items():
        parsed = summary_info["parsed"]
        raw_summary = summary_info["content"]
        if not evidence_utils._summary_mentions_charter(parsed, raw_summary, charter, sub_lib_dir.name):
            continue
        pairs.append((sub_lib_dir.name, charter_content, file_id, raw_summary))

    if not pairs:
        return

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=evidence_utils.MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                evidence_utils._process_pair, lib_id, charter, file_id, summary, config_path
            )
            for lib_id, charter, file_id, summary in pairs
        ]
        for future in as_completed(futures):
            result = future.result()
            if "data" in result:
                results.append(result["data"])

    if not results:
        return

    evidence_path = sub_lib_dir / "evidence.json"
    payload = evidence_utils._load_evidence_payload(evidence_path)
    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        sources = []
        payload["sources"] = sources

    lib_added = False
    for entry in results:
        candidate_entry = {
            "file_id": entry.get("file_id"),
            "sections": entry.get("relevant_sections", []),
            "confidence": entry.get("confidence"),
            "rationale": entry.get("rationale", ""),
        }
        _entry_issues, normalized = evidence_utils._validate_evidence_entry(
            candidate_entry, manager, sub_lib_dir.name
        )
        if normalized is None:
            continue
        confidence_value = normalized.get("confidence")
        if confidence_value is None or confidence_value < 0.5:
            continue

        added_source, added_sections = evidence_utils._merge_evidence_sources(sources, normalized)
        if added_source or added_sections:
            lib_added = True

    if lib_added:
        evidence_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_sublibrary_spec(
    manager: WorkspaceManager, sub_lib_dir: Path, config_path: Path
) -> None:
    """Run spec building for a sub-library (Phase 4)."""
    lib_id = sub_lib_dir.name
    errors: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    charter_path = sub_lib_dir / "charter.md"
    if not charter_path.exists():
        return

    charter_content = charter_path.read_text(encoding="utf-8")
    spec_path = _initialize_spec(sub_lib_dir, charter_content, lib_id)

    sources = _read_evidence_sources(sub_lib_dir)
    evidence_map = _normalize_evidence_sources(sources)
    if not evidence_map:
        return

    existing_gaps = _read_sublibrary_gaps(sub_lib_dir)
    gap_history: list[tuple[str, ...]] = []

    target_path = _sublibrary_target_path(manager, sub_lib_dir)

    for iteration in range(MAX_ITERATIONS_DEFAULT):
        gap_focus = existing_gaps if iteration > 0 else None

        for file_id, sections in evidence_map.items():
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": "Source file not found.",
                    }
                )
                continue

            file_content = file_path.read_text(encoding="utf-8")
            current_spec = spec_path.read_text(encoding="utf-8")
            prompt = _build_integration_prompt(
                lib_id,
                charter_content,
                current_spec,
                file_id,
                file_content,
                sections,
                gaps=gap_focus,
            )
            runner = AgentRunner.from_agent_name(
                "glm-library-spec-integrator", config_path, prompt_chars=len(prompt)
            )

            try:
                output = runner.run(prompt)
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Agent execution failed: {exc}",
                    }
                )
                continue

            if current_spec.strip() and current_spec.strip() not in output:
                issues.append(
                    {
                        "type": "non_monotonic_integration",
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "message": "Integrator output removed existing spec content.",
                    }
                )
                output = current_spec

            spec_path.write_text(output, encoding="utf-8")
            issues.extend(_validate_spec_citations(output, manager, lib_id))
            _update_decisions(sub_lib_dir, output)

        spec_content = spec_path.read_text(encoding="utf-8")
        evidence_list: list[GapEvidence] = []

        for file_id in evidence_map:
            file_path = manager.get_file_path(file_id)
            if file_path is None or not file_path.exists():
                continue
            file_content = file_path.read_text(encoding="utf-8")
            prompt = _build_gap_prompt(spec_content, file_id, file_content)
            runner = AgentRunner.from_agent_name(
                "chatgpt-library-spec-gap-judge", config_path, prompt_chars=len(prompt)
            )
            try:
                output = runner.run(prompt)
            except RuntimeError as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Gap judge failed: {exc}",
                    }
                )
                continue

            try:
                data = parse_gap_judge_output(output)
            except Exception as exc:
                errors.append(
                    {
                        "lib_id": lib_id,
                        "file_id": file_id,
                        "error": f"Failed to parse gap output: {exc}",
                    }
                )
                continue

            raw_gaps = data.get("gaps", [])
            evidence_list.extend(
                _build_sublibrary_gaps_from_judge(
                    lib_id, file_id, raw_gaps, target_path, issues
                )
            )

        synthesizer = GapSynthesizer()
        new_gaps = synthesizer.cluster_evidence(evidence_list) if evidence_list else []
        existing_gaps = synthesizer.merge_gaps(existing_gaps, new_gaps)

        _write_sublibrary_gaps(manager, sub_lib_dir, existing_gaps)

        if not new_gaps:
            existing_gaps = []
            _write_sublibrary_gaps(manager, sub_lib_dir, existing_gaps)
            break

        signature = _gap_signature(existing_gaps)
        gap_history.append(signature)
        if len(gap_history) >= 3 and signature and signature == gap_history[-2] == gap_history[-3]:
            return

        if iteration + 1 >= MAX_ITERATIONS_DEFAULT:
            break

        if len(gap_history) >= 2 and gap_history[-1] == gap_history[-2]:
            break


def _read_sublibrary_gaps(sub_lib_dir: Path) -> list[Gap]:
    """Read sub-library gaps.md into Gap objects."""
    gaps_path = sub_lib_dir / "gaps.md"
    if not gaps_path.exists():
        return []
    return parse_gaps_markdown(gaps_path.read_text(encoding="utf-8"))


def _write_sublibrary_gaps(
    manager: WorkspaceManager, sub_lib_dir: Path, gaps: list[Gap]
) -> None:
    """Write gaps.md for a sub-library."""
    gaps_path = sub_lib_dir / "gaps.md"
    gaps_path.write_text(manager._format_gaps_md(gaps), encoding="utf-8")


def _sublibrary_target_path(manager: WorkspaceManager, sub_lib_dir: Path) -> str:
    """Compute derived artifact target path for a sub-library spec."""
    try:
        relative = sub_lib_dir.relative_to(manager.structure.root)
    except ValueError:
        relative = sub_lib_dir
    return str(relative / "spec.md")


def _build_sublibrary_gaps_from_judge(
    lib_id: str,
    file_id: str,
    raw_gaps: list[dict[str, Any]],
    target_path: str,
    issues: list[dict[str, Any]],
) -> list[GapEvidence]:
    """Build gap evidence for a sub-library from gap judge output."""
    evidence_list: list[GapEvidence] = []
    for gap_finding in raw_gaps:
        if not isinstance(gap_finding, dict):
            continue
        severity_raw = str(gap_finding.get("severity", "")).strip().lower()
        if severity_raw not in VALID_GAP_SEVERITIES:
            issues.append(
                {
                    "type": "invalid_gap_severity",
                    "lib_id": lib_id,
                    "file_id": file_id,
                    "severity": severity_raw,
                    "message": "Gap severity must be must/should/nice-to-have.",
                }
            )
            severity_raw = "nice-to-have"
        mapped_severity = SEVERITY_MAP[severity_raw]
        evidence_list.append(
            GapEvidence(
                invariant_family="content",
                description=gap_finding.get("missing_content", ""),
                details={
                    "source": gap_finding.get("source", file_id),
                    "derived_artifact_target": target_path,
                    "where_in_spec": gap_finding.get("where_in_spec", ""),
                    "severity": mapped_severity,
                    "reported_severity": severity_raw,
                    "gap_type": "missing_detail",
                },
                confidence=1.0,
                location=gap_finding.get("source", file_id),
                detector="chatgpt-library-spec-gap-judge",
            )
        )
    return evidence_list
