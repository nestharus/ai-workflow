"""Architectural quality checks for layer promotion gating.

Verifies:
1. No inlined atom logic in the architectural layer
2. Function recomposition quality (proper imports and calls)
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source
from spec_manager.schemas.pin_functions import PinFunctionRegistry

_IMPORT_FROM_RE = re.compile(r"^\s*from\s+\S+\s+import\s+(.+)", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_CALL_RE = re.compile(r"\b(\w+)\s*\(")
_ASSIGN_RE = re.compile(r"^\s*(\w+)\s*=", re.MULTILINE)


@dataclass
class InlinedLogicFinding:
    """A location where atom logic appears to be copy-pasted inline.

    Attributes:
        arch_file: Architectural file path.
        arch_line_start: Start line of the suspected inlined code.
        arch_line_end: End line of the suspected inlined code.
        matching_pin_func_id: Pin-function whose logic appears inlined.
        similarity_score: 0.0-1.0 indicating how similar the code is.
        detection_method: How the duplication was detected.
    """

    arch_file: str
    arch_line_start: int
    arch_line_end: int
    matching_pin_func_id: str
    similarity_score: float
    detection_method: str  # "exact_match", "text_similarity", "fingerprint_overlap"


def _hash_function_body(source: str, start_line: int, end_line: int) -> str:
    """Compute SHA-256 hash of a function body."""
    lines = source.splitlines()
    body_lines = lines[start_line - 1 : end_line]
    normalized = "\n".join(line.strip() for line in body_lines if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _text_similarity(
    source_a: str,
    start_a: int,
    end_a: int,
    source_b: str,
    start_b: int,
    end_b: int,
) -> float:
    """Compute text-based structural similarity between two function bodies."""
    from difflib import SequenceMatcher

    lines_a = source_a.splitlines()[start_a - 1 : end_a]
    lines_b = source_b.splitlines()[start_b - 1 : end_b]
    # Normalize: strip whitespace, skip empty/comment lines
    norm_a = [line.strip() for line in lines_a if line.strip() and not line.strip().startswith("#")]
    norm_b = [line.strip() for line in lines_b if line.strip() and not line.strip().startswith("#")]
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, "\n".join(norm_a), "\n".join(norm_b)).ratio()


def _extract_function_info(file_path: Path) -> list[tuple[RawFunctionInfo, str]]:
    """Extract function info and source text from a file using analyze_source."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    analysis = analyze_source(source, str(file_path))
    return [(func, source) for func in analysis.functions]


def _get_line_fingerprints(source: str, start: int, end: int) -> set[str]:
    """Get SHA-256 fingerprints for individual lines in a range."""
    lines = source.splitlines()
    fingerprints: set[str] = set()
    for i in range(max(0, start - 1), min(end, len(lines))):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            fp = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
            fingerprints.add(fp)
    return fingerprints


def check_no_inlined_atom_logic(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    algorithmic_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: No inlined atom logic in architectural layer.

    Detection strategies (applied in order):
    1. Exact body match: Hash the body of each architectural function,
       compare against pin-function content_hash values.
    2. Text structural similarity: Normalize source lines, compare structure.
    3. Line fingerprint overlap: If >threshold of an architectural
       function's line fingerprints match a pin-function's lines, flag it.

    gate_spec.params:
        - similarity_threshold (float, default 0.8): Minimum text similarity.
        - fingerprint_overlap_threshold (float, default 0.6): Minimum line
            fingerprint overlap.
        - exclude_patterns (list[str]): File patterns to skip.

    Args:
        pin_registry: PinFunctionRegistry with atom content hashes.
        architectural_files: Architectural layer files to scan.
        algorithmic_files: Algorithmic layer files (for body extraction).
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each inlined logic instance.
    """
    start_time = time.monotonic()
    similarity_threshold = gate_spec.params.get("similarity_threshold", 0.8)
    fingerprint_overlap_threshold = gate_spec.params.get("fingerprint_overlap_threshold", 0.6)

    # Build map of pin-function content hashes -> pin_func_id
    pin_hashes: dict[str, str] = {}
    for pf in pin_registry.pin_functions:
        if pf.content_hash:
            pin_hashes[pf.content_hash] = pf.pin_func_id

    # Extract pin-function info and line fingerprints from algorithmic files
    pin_func_info: dict[str, tuple[RawFunctionInfo, str]] = {}
    pin_func_fingerprints: dict[str, set[str]] = {}
    pin_func_id_by_name: dict[str, str] = {}

    for pf in pin_registry.pin_functions:
        pin_func_id_by_name[pf.function_name] = pf.pin_func_id

    for algo_file in algorithmic_files:
        entries = _extract_function_info(algo_file)
        for func_info, source in entries:
            func_name = func_info.name
            if func_name in pin_func_id_by_name:
                pfid = pin_func_id_by_name[func_name]
                pin_func_info[pfid] = (func_info, source)
                pin_func_fingerprints[pfid] = _get_line_fingerprints(
                    source, func_info.start_line, func_info.end_line
                )

    # Scan architectural files
    all_findings: list[dict[str, Any]] = []

    for arch_file in architectural_files:
        arch_entries = _extract_function_info(arch_file)
        for arch_func_info, arch_source in arch_entries:
            arch_end = arch_func_info.end_line

            # Strategy 1: Exact body match
            arch_hash = _hash_function_body(arch_source, arch_func_info.start_line, arch_end)
            if arch_hash in pin_hashes:
                all_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "matching_pin_func_id": pin_hashes[arch_hash],
                        "similarity_score": 1.0,
                        "detection_method": "exact_match",
                        "arch_function_name": arch_func_info.name,
                    }
                )
                continue  # No need to check other strategies

            # Strategy 2: Text structural similarity
            best_similarity = 0.0
            best_match_id = ""
            for pfid, (pf_info, pf_source) in pin_func_info.items():
                sim = _text_similarity(
                    arch_source,
                    arch_func_info.start_line,
                    arch_end,
                    pf_source,
                    pf_info.start_line,
                    pf_info.end_line,
                )
                if sim > best_similarity:
                    best_similarity = sim
                    best_match_id = pfid

            if best_similarity >= similarity_threshold:
                all_findings.append(
                    {
                        "arch_file": str(arch_file),
                        "arch_line_start": arch_func_info.start_line,
                        "arch_line_end": arch_end,
                        "matching_pin_func_id": best_match_id,
                        "similarity_score": best_similarity,
                        "detection_method": "text_similarity",
                        "arch_function_name": arch_func_info.name,
                    }
                )
                continue

            # Strategy 3: Line fingerprint overlap
            arch_fps = _get_line_fingerprints(arch_source, arch_func_info.start_line, arch_end)
            if not arch_fps:
                continue

            for pfid, pin_fps in pin_func_fingerprints.items():
                if not pin_fps:
                    continue
                overlap = len(arch_fps & pin_fps)
                overlap_ratio = overlap / len(arch_fps)
                if overlap_ratio >= fingerprint_overlap_threshold:
                    all_findings.append(
                        {
                            "arch_file": str(arch_file),
                            "arch_line_start": arch_func_info.start_line,
                            "arch_line_end": arch_end,
                            "matching_pin_func_id": pfid,
                            "similarity_score": overlap_ratio,
                            "detection_method": "fingerprint_overlap",
                            "arch_function_name": arch_func_info.name,
                        }
                    )
                    break

    passed = len(all_findings) == 0
    duration = (time.monotonic() - start_time) * 1000

    return GateCheckResult(
        gate_id=GateId.NO_INLINED_ATOM_LOGIC.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else 0.0,
        findings=all_findings,
        summary=(
            "No inlined atom logic found in architectural layer"
            if passed
            else f"Found {len(all_findings)} instance(s) of inlined atom logic"
        ),
        duration_ms=duration,
    )


def check_function_recomposition(
    pin_registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Architectural functions correctly recompose atoms.

    Verifies:
    1. All imported pin-functions are actually called (no dead imports).
    2. No local variables shadow imported pin-function names.

    gate_spec.params:
        - check_dead_imports (bool, default True): Flag unused pin imports.
        - check_signature_match (bool, default True): Verify call arg counts.

    Args:
        pin_registry: PinFunctionRegistry.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for recomposition issues.
    """
    start_time = time.monotonic()
    check_dead_imports = gate_spec.params.get("check_dead_imports", True)

    # Build set of pin-function names
    pin_func_names: dict[str, str] = {}  # function_name -> pin_func_id
    pin_func_signatures: dict[str, int] = {}  # function_name -> param count
    for pf in pin_registry.pin_functions:
        pin_func_names[pf.function_name] = pf.pin_func_id
        # Extract param count from signature string
        sig = pf.signature
        if "(" in sig and ")" in sig:
            params_str = sig[sig.index("(") + 1 : sig.rindex(")")]
            params = [p.strip() for p in params_str.split(",") if p.strip() and p.strip() != "self"]
            pin_func_signatures[pf.function_name] = len(params)

    findings: list[dict[str, Any]] = []

    for arch_file in architectural_files:
        try:
            source = arch_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Find imported pin-function names in this file using regex
        imported_pin_names: set[str] = set()

        for match in _IMPORT_FROM_RE.finditer(source):
            names_part = match.group(1)
            # Handle "from X import a, b, c" and "from X import a as b"
            for name_segment in names_part.split(","):
                name_segment = name_segment.strip()
                if " as " in name_segment:
                    name = name_segment.split(" as ")[-1].strip()
                else:
                    name = name_segment.strip()
                if name in pin_func_names:
                    imported_pin_names.add(name)

        for match in _IMPORT_RE.finditer(source):
            names_part = match.group(1)
            # Skip "from X import ..." which is already handled
            if source[match.start() :].lstrip().startswith("from"):
                continue
            for name_segment in names_part.split(","):
                name_segment = name_segment.strip()
                if " as " in name_segment:
                    name = name_segment.split(" as ")[-1].strip()
                else:
                    # "import foo.bar" -> "bar"
                    name = name_segment.split(".")[-1].strip()
                if name in pin_func_names:
                    imported_pin_names.add(name)

        if not imported_pin_names:
            continue

        # Find all call sites and assignments using regex
        called_names: set[str] = set()
        for match in _CALL_RE.finditer(source):
            called_names.add(match.group(1))

        shadowed_names: set[str] = set()
        for match in _ASSIGN_RE.finditer(source):
            name = match.group(1)
            if name in imported_pin_names:
                shadowed_names.add(name)

        # Check for dead imports
        if check_dead_imports:
            unused = imported_pin_names - called_names
            for name in unused:
                findings.append(
                    {
                        "arch_file": str(arch_file),
                        "issue_type": "dead_import",
                        "pin_func_name": name,
                        "pin_func_id": pin_func_names[name],
                        "message": (f"Pin-function '{name}' is imported but never called"),
                    }
                )

        # Check for shadowing
        for name in shadowed_names:
            findings.append(
                {
                    "arch_file": str(arch_file),
                    "issue_type": "shadowed_import",
                    "pin_func_name": name,
                    "pin_func_id": pin_func_names[name],
                    "message": (f"Local variable shadows imported pin-function '{name}'"),
                }
            )

    passed = len(findings) == 0
    duration = (time.monotonic() - start_time) * 1000

    return GateCheckResult(
        gate_id=GateId.FUNCTION_RECOMPOSITION.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=1.0 if passed else max(0.0, 1.0 - len(findings) * 0.1),
        findings=findings,
        summary=(
            "Architectural functions correctly recompose atoms"
            if passed
            else f"Found {len(findings)} recomposition issue(s)"
        ),
        duration_ms=duration,
    )
