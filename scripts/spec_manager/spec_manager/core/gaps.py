"""Enhanced gap detection using evidence extraction + gap synthesis.

This module provides detector output types and gap synthesis functionality.

Type naming (canonical v2.0 types):
- DetectorFinding: Raw output from detectors (this module)
- GapElement: Synthesized first-class gap element (this module)

v2.0 types from data_structures.py:
- GapEvidence: v2.0 evidence with invariant families (data_structures.py)
- Gap: v2.0 first-class gap with evidence-based ID (data_structures.py)

Import from the appropriate module:
- from spec_manager.core.gaps import DetectorFinding, GapElement  # detector output
- from spec_manager.core.data_structures import Gap, GapEvidence  # v2.0 state schema

Evidence categories (invariant-driven):
- Coverage: unaccounted atoms, membership failures
- Format: pattern violations, duplicates, missing annotations
- Sequence: duplicate IDs, holes, conflicts
- Content: plan/library drift, content mismatches
- Proof: broken Algorithm->Claim->Proof->Lean chains
- Uncertainty: sorry, TODO, ?, hedging markers
"""

from __future__ import annotations

import logging
import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from .annotations import AnnotationParser
from .ids import IdValidator
from .sections import SectionExtractor

logger = logging.getLogger(__name__)

# =============================================================================
# Evidence Data Structures (Detector Output)
# =============================================================================


class Severity(Enum):
    """Severity levels for evidence and gaps."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class DetectorFinding:
    """Raw finding produced by a detector - NOT a gap itself.

    Gaps are synthesized by clustering findings.

    Named DetectorFinding (not GapEvidence) to avoid collision with
    the v2.0 GapEvidence in data_structures.py which has different fields.
    """

    severity: Severity  # error, warning, info
    message: str  # Human-readable description
    location: str  # Where found (file:line)
    element_id: str | None = None  # Related element ID
    detector: str = ""  # Which detector found this
    details: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Gap Element (First-Class, Synthesized)
# =============================================================================


@dataclass
class GapElement:
    """A synthesized gap - first-class spec element.

    Multiple DetectorFinding objects cluster into a single gap.

    This is a UnitType.GAP element, written to gaps.md with ID like GAP-0001.

    Note: Uses DetectorFinding (not GapEvidence from data_structures.py)
    because the evidence here is raw detector output, not v2.0 evidence.
    """

    id: str  # e.g., GAP-0001
    severity: Severity  # Highest severity from evidence
    summary: str  # What's wrong (synthesized from evidence)
    affects: list[str]  # Element IDs and/or source refs
    evidence: list[DetectorFinding]  # All findings supporting this gap
    patch_origin: str | None = None  # Which patch introduced this (if known)
    bypassed: bool = False  # Whether this gap was intentionally bypassed
    drop_reason: str | None = None  # Reason for bypass/drop


# =============================================================================
# Format Compliance (from lint_patterns.py)
# =============================================================================


class FormatComplianceDetector:
    """Detects format violations - patterns that don't match canonical forms.

    Based on lint_patterns.py from gen3 rag scripts.
    """

    # Canonical patterns
    PATTERNS: ClassVar[dict[str, re.Pattern[str]]] = {
        "goal": re.compile(r"^G([1-9]|[1-4]\d|50)$"),  # G1-G50
        "invariant": re.compile(r"^P\d+I\d+$"),  # P#I#
        "claim": re.compile(r"^P\d+C\d+$"),  # P#C#
        "algorithm": re.compile(r"^Algorithm \d+$"),  # Algorithm #
        "math": re.compile(r"^P\d+\.\d+$"),  # P#.#
        "lean": re.compile(r"^Lean\d+$"),  # Lean#
        "data": re.compile(r"^D\d+$"),  # D#
    }

    # Legacy patterns to flag
    LEGACY_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"^I\d+$"), "Use P#I# for invariants, not I#"),
        (re.compile(r"^P\d+\.M\d+$"), "Use P#.# for math sections, not P#.M#"),
        (re.compile(r"^Algorithm P\d+\.\d+$"), 'Use "Algorithm #" not "Algorithm P#.#"'),
        (re.compile(r"^Track [AB]"), "Legacy track format - use Lean#"),
        (re.compile(r"^Lean [AB]"), "Legacy lean format - use Lean#"),
    ]

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect format violations in content."""
        gaps = []

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Check for legacy patterns
            for pattern, message in self.LEGACY_PATTERNS:
                if pattern.search(line):
                    gaps.append(
                        DetectorFinding(
                            detector="format_violation",
                            severity=Severity.WARNING,
                            message=message,
                            location=f"{file_path}:{line_num}",
                            details={"line": line.strip(), "pattern": pattern.pattern},
                        )
                    )

            # Check for unescaped LaTeX
            if re.search(r"(?<!\\)\$[^$]+\$", line) and "\\" not in line:
                # Could be intentional, so just info
                gaps.append(
                    DetectorFinding(
                        detector="format_violation",
                        severity=Severity.INFO,
                        message="Possible unescaped LaTeX",
                        location=f"{file_path}:{line_num}",
                        details={"line": line.strip()},
                    )
                )

        return gaps


# =============================================================================
# Duplicate Detection (from check_duplicate_declarations.py)
# =============================================================================


class DuplicateDetector:
    """Detects duplicate declarations and headers.

    Based on check_duplicate_declarations.py and find_duplicate_headers.py.
    """

    def detect_duplicate_declarations(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Find ([=ID]) declarations that appear more than once."""
        gaps = []
        parser = AnnotationParser()

        # Track declarations
        declarations: dict[str, list[int]] = defaultdict(list)

        for decl in parser.parse_declarations(content):
            declarations[decl.id_value].append(decl.line_number)

        # Flag duplicates
        for id_value, lines in declarations.items():
            if len(lines) > 1:
                gaps.append(
                    DetectorFinding(
                        severity=Severity.ERROR,
                        message=f"ID '{id_value}' declared {len(lines)} times",
                        location=file_path,
                        element_id=id_value,
                        detector="duplicate_declaration",
                        details={"lines": lines, "suggestion": "Remove duplicate declarations"},
                    )
                )

        return gaps

    def detect_duplicate_headers(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Find exact and near-duplicate headers."""
        gaps = []

        # Extract headers
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        headers: dict[str, list[tuple[int, str]]] = defaultdict(list)

        for match in header_pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            text = match.group(2).strip()

            # Normalize for comparison
            normalized = re.sub(r"\s+", " ", text.lower())
            normalized = re.sub(r"[^\w\s]", "", normalized)

            headers[normalized].append((line_num, text))

        # Flag duplicates
        for occurrences in headers.values():
            if len(occurrences) > 1:
                # Check if exact duplicates or near-duplicates
                texts = [t for _, t in occurrences]
                if len(set(texts)) == 1:
                    severity = Severity.ERROR
                    msg = f"Exact duplicate header: '{texts[0]}'"
                else:
                    severity = Severity.WARNING
                    msg = f"Near-duplicate headers: {texts}"

                gaps.append(
                    DetectorFinding(
                        detector="duplicate_header",
                        severity=severity,
                        message=msg,
                        location=file_path,
                        details={
                            "lines": [line_num for line_num, _ in occurrences],
                            "texts": texts,
                        },
                    )
                )

        return gaps


# =============================================================================
# Undefined Functions (from find_undefined_functions.py)
# =============================================================================


class UndefinedFunctionDetector:
    """Detects function calls in pseudocode without definitions.

    Based on find_undefined_functions.py.

    Gap 12 fix: Word lists are configurable via YAML and treated as WEAK EVIDENCE,
    not definitive failure conditions.
    """

    DEFAULT_BUILTINS: ClassVar[set[str]] = {
        "if",
        "else",
        "for",
        "while",
        "return",
        "break",
        "continue",
        "true",
        "false",
        "null",
        "none",
        "and",
        "or",
        "not",
        "min",
        "max",
        "abs",
        "len",
        "sum",
        "range",
        "enumerate",
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "get",
        "set",
        "keys",
        "values",
        "items",
        "print",
        "log",
        "error",
        "warn",
        "debug",
    }

    # DEFAULT Categories for undefined functions - CONFIGURABLE VIA YAML (Gap 12 fix)
    DEFAULT_CATEGORIES: ClassVar[dict[str, str]] = {
        "PATTERN_": "PATTERN",
        "FIELD_": "FIELD",
        "EMBED_": "EMBED",
        "GRAPH_": "GRAPH",
        "PARSE_": "PARSE",
        "WORKSPACE_": "WORKSPACE",
        "HYPOTHESIS_": "HYPOTHESIS",
        "INDEX_": "INDEX",
        "STATE_": "STATE",
    }

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize detector with optional config.

        Gap 12 fix: Word lists loaded from YAML config if provided.
        """
        self.builtins = set(self.DEFAULT_BUILTINS)
        self.categories = dict(self.DEFAULT_CATEGORIES)

        if config_path and config_path.exists():
            self._load_config(config_path)

    def _load_config(self, config_path: Path) -> None:
        """Load word lists from YAML config (Gap 12 fix)."""
        try:
            import yaml

            with open(config_path) as f:
                config = yaml.safe_load(f)

            if "undefined_functions" in config:
                uf_config = config["undefined_functions"]

                # Load builtins (additive)
                if "builtins" in uf_config:
                    self.builtins.update(uf_config["builtins"])

                # Load categories (additive)
                if "categories" in uf_config:
                    self.categories.update(uf_config["categories"])

                # Load exclusions (remove from builtins)
                if "exclude_builtins" in uf_config:
                    self.builtins -= set(uf_config["exclude_builtins"])

        except Exception as e:
            # Config load failure is non-fatal - use defaults
            logger.debug(f"Failed to load config from {config_path}: {e}")

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect undefined function calls in pseudocode.

        Gap 12 fix: Detections are WEAK EVIDENCE (confidence-weighted),
        not definitive failure conditions.
        """
        evidence = []

        # Find all pseudocode blocks
        pseudo_pattern = re.compile(r"```pseudo\n(.*?)```", re.DOTALL)

        # Extract function definitions
        definitions = set()
        def_pattern = re.compile(r"function\s+(\w+)\s*\(")
        for match in def_pattern.finditer(content):
            definitions.add(match.group(1).upper())

        # Also treat Algorithm headers as definitions
        alg_pattern = re.compile(r"^##\s+Algorithm\s+\d+[:\s]+(\w+)", re.MULTILINE)
        for match in alg_pattern.finditer(content):
            definitions.add(match.group(1).upper())

        # Find all function calls in pseudo blocks
        call_pattern = re.compile(r"\b([A-Z][A-Z_0-9]+)\s*\(")
        calls: dict[str, list[int]] = defaultdict(list)

        for block_match in pseudo_pattern.finditer(content):
            block_start = content[: block_match.start()].count("\n") + 1
            block_content = block_match.group(1)

            for call_match in call_pattern.finditer(block_content):
                func_name = call_match.group(1)
                line_in_block = block_content[: call_match.start()].count("\n")
                line_num = block_start + line_in_block

                # Skip builtins and already-defined (using instance vars - Gap 12 fix)
                if func_name.lower() in self.builtins:
                    continue
                if func_name in definitions:
                    continue

                calls[func_name].append(line_num)

        # Create evidence for undefined functions (Gap 12: weak evidence with confidence)
        for func_name, lines in calls.items():
            # Categorize (using instance vars - Gap 12 fix)
            category = "OTHER"
            for prefix, cat in self.categories.items():
                if func_name.startswith(prefix):
                    category = cat
                    break

            # Gap 12: Confidence is lower for unknown categories (may be external)
            confidence = 0.8 if category != "OTHER" else 0.5

            evidence.append(
                DetectorFinding(
                    severity=Severity.WARNING,
                    message=f"Undefined function: {func_name}",
                    location=file_path,
                    element_id=None,
                    detector="undefined_function",
                    details={
                        "function": func_name,
                        "function_name": func_name,  # Alias for format_gaps_md
                        "category": category,
                        "call_lines": lines,
                        "call_count": len(lines),
                        "confidence": confidence,  # Gap 12: weak evidence
                        "suggestion": f"Define {func_name} or mark as external dependency",
                    },
                )
            )

        return evidence


# =============================================================================
# Sequence Analysis (from check_sequences.py)
# =============================================================================


class SequenceAnalyzer:
    """Analyzes numbered sequences for duplicates, holes, and conflicts.

    Based on check_sequences.py.
    """

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect sequence issues."""
        gaps = []

        # Analyze different sequence types
        gaps.extend(self._analyze_algorithms(content, file_path))
        gaps.extend(self._analyze_goals(content, file_path))
        gaps.extend(self._analyze_data_structures(content, file_path))

        return gaps

    def _analyze_algorithms(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Analyze Algorithm # sequence."""
        gaps = []
        pattern = re.compile(r"^##\s+Algorithm\s+(\d+)", re.MULTILINE)

        numbers: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for match in pattern.finditer(content):
            num = int(match.group(1))
            line = content[: match.start()].count("\n") + 1
            # Get a preview of the section
            preview = content[match.start() : match.start() + 200].split("\n")[0]
            numbers[num].append((line, preview))

        # Check for duplicates
        for num, occurrences in numbers.items():
            if len(occurrences) > 1:
                # Check if same content (true duplicate) or different (conflict)
                previews = [p for _, p in occurrences]
                if len(set(previews)) == 1:
                    severity = Severity.WARNING
                    msg = f"Duplicate Algorithm {num} (same content)"
                else:
                    severity = Severity.ERROR
                    msg = f"Conflicting Algorithm {num} (different content)"

                gaps.append(
                    DetectorFinding(
                        detector="duplicate_id" if len(set(previews)) == 1 else "conflict",
                        severity=severity,
                        message=msg,
                        location=file_path,
                        element_id=f"Algorithm {num}",
                        details={
                            "lines": [line_num for line_num, _ in occurrences],
                            "previews": previews,
                        },
                    )
                )

        # Check for holes (if we have enough for a sequence)
        if len(numbers) > 3:
            all_nums = sorted(numbers.keys())
            expected = set(range(min(all_nums), max(all_nums) + 1))
            holes = expected - set(all_nums)

            if holes and len(holes) < len(all_nums):  # Some holes, not mostly holes
                gaps.append(
                    DetectorFinding(
                        detector="sequence_hole",
                        severity=Severity.INFO,
                        message=f"Algorithm sequence has holes: {sorted(holes)}",
                        location=file_path,
                        details={"missing": sorted(holes)},
                    )
                )

        return gaps

    def _analyze_goals(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Analyze G# sequence."""
        # Similar to algorithms
        gaps = []
        pattern = re.compile(r"\bG(\d+)\b")

        numbers: dict[int, int] = defaultdict(int)
        for match in pattern.finditer(content):
            numbers[int(match.group(1))] += 1

        # Goals should be G1-G50
        out_of_range = [n for n in numbers if n < 1 or n > 50]
        if out_of_range:
            gaps.append(
                DetectorFinding(
                    detector="format_violation",
                    severity=Severity.WARNING,
                    message=f"Goals out of range (should be G1-G50): {out_of_range}",
                    location=file_path,
                    details={"out_of_range": out_of_range},
                )
            )

        return gaps

    def _analyze_data_structures(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Analyze D# sequence."""
        gaps = []
        pattern = re.compile(r"^##\s+(D\d+)", re.MULTILINE)

        ids: dict[str, list[int]] = defaultdict(list)
        for match in pattern.finditer(content):
            id_value = match.group(1)
            line = content[: match.start()].count("\n") + 1
            ids[id_value].append(line)

        for id_value, lines in ids.items():
            if len(lines) > 1:
                gaps.append(
                    DetectorFinding(
                        detector="duplicate_id",
                        severity=Severity.WARNING,
                        message=f"Duplicate data structure: {id_value}",
                        location=file_path,
                        element_id=id_value,
                        details={"lines": lines},
                    )
                )

        return gaps


# =============================================================================
# Content Verification (from verify_content.py)
# =============================================================================


class ContentVerifier:
    """Verifies content matches between plan.md and libraries.

    Based on verify_content.py.
    """

    def verify(
        self, plan_content: str, library_content: str, library_name: str
    ) -> list[DetectorFinding]:
        """Compare content between plan and library."""
        gaps = []
        AnnotationParser()

        # Extract sections from both
        plan_sections = self._extract_sections(plan_content)
        library_sections = self._extract_sections(library_content)

        plan_ids = set(plan_sections.keys())
        library_ids = set(library_sections.keys())

        # Missing in library
        for id_value in plan_ids - library_ids:
            gaps.append(
                DetectorFinding(
                    severity=Severity.WARNING,
                    message=f"'{id_value}' in plan but not in library",
                    location=library_name,
                    element_id=id_value,
                    detector="missing_in_library",
                    details={"suggestion": f"Add {id_value} to {library_name}"},
                )
            )

        # Missing in plan
        for id_value in library_ids - plan_ids:
            gaps.append(
                DetectorFinding(
                    detector="missing_in_plan",
                    severity=Severity.INFO,
                    message=f"'{id_value}' in library but not in plan",
                    location=library_name,
                    element_id=id_value,
                )
            )

        # Content mismatches
        for id_value in plan_ids & library_ids:
            plan_body = plan_sections[id_value]
            lib_body = library_sections[id_value]

            similarity = SequenceMatcher(
                None, self._normalize(plan_body), self._normalize(lib_body)
            ).ratio()

            if similarity < 0.95:
                if similarity < 0.5:
                    severity = Severity.ERROR
                elif similarity < 0.8:
                    severity = Severity.WARNING
                else:
                    severity = Severity.INFO

                gaps.append(
                    DetectorFinding(
                        detector="content_mismatch",
                        severity=severity,
                        message=f"'{id_value}' content differs ({similarity:.0%} similar)",
                        location=library_name,
                        element_id=id_value,
                        details={
                            "similarity": similarity,
                            "plan_length": len(plan_body),
                            "library_length": len(lib_body),
                        },
                    )
                )

        return gaps

    def _extract_sections(self, content: str) -> dict[str, str]:
        """Extract sections by ([=ID]) declaration."""
        sections = {}
        parser = AnnotationParser()

        lines = content.splitlines()
        current_id = None
        current_lines = []

        for line in lines:
            decl = parser.extract_id_from_header(line)
            if decl:
                if current_id:
                    sections[current_id] = "\n".join(current_lines)
                current_id = decl
                current_lines = [line]
            elif current_id:
                current_lines.append(line)

        if current_id:
            sections[current_id] = "\n".join(current_lines)

        return sections

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        return " ".join(text.lower().split())


# =============================================================================
# Proof Chain Detection (with LLM inference for prose)
# =============================================================================


class ProofChainDetector:
    """Detects broken proof chains: Algorithm->Claim->Proof->Lean.

    CRITICAL: In messy states, claims/proofs may exist only as prose fragments.
    This detector uses:
    1. Structure when present (IDs, math sections, Lean blocks)
    2. LLM inference when structure is absent

    Output is grouped by patch (which patch introduced broken chains).
    """

    def __init__(self, llm_client: Any = None) -> None:
        """Initialize detector with optional LLM for inference.

        Args:
            llm_client: Optional LLM client for prose inference
        """
        self._llm = llm_client

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect broken proof chains.

        Chain requirements:
        - Algorithm # must reference Claim(s) (P#C# / C#)
        - Claim must have Proof Sketch (or Math section P#.#)
        - Proof Sketch must have Lean skeleton (or explicit non-lean acceptance)
        """
        evidence = []

        # Extract structured elements
        algorithms = self._extract_algorithms(content)
        claims = self._extract_claims(content)
        proofs = self._extract_proofs(content)
        lean_blocks = self._extract_lean(content)

        # Check each algorithm
        for alg_id, alg_content in algorithms.items():
            chain_evidence = self._check_algorithm_chain(
                alg_id, alg_content, claims, proofs, lean_blocks, content, file_path
            )
            evidence.extend(chain_evidence)

        return evidence

    def _extract_algorithms(self, content: str) -> dict[str, str]:
        """Extract Algorithm # sections."""
        algorithms = {}
        pattern = re.compile(
            r"^##\s+(Algorithm\s+\d+).*?\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
        )
        for match in pattern.finditer(content):
            algorithms[match.group(1)] = match.group(2)
        return algorithms

    def _extract_claims(self, content: str) -> dict[str, str]:
        """Extract Claim sections (C#, P#C#)."""
        claims = {}
        # Direct claims
        pattern = re.compile(r"\(\[=(P?\d*C\d+)\]\)", re.MULTILINE)
        for match in pattern.finditer(content):
            claim_id = match.group(1)
            # Extract surrounding content
            start = max(0, match.start() - 200)
            end = min(len(content), match.end() + 500)
            claims[claim_id] = content[start:end]
        return claims

    def _extract_proofs(self, content: str) -> dict[str, str]:
        """Extract Proof Sketch sections."""
        proofs = {}
        pattern = re.compile(
            r"^###\s+Proof\s+Sketch\s*\(?([^)]*)\)?\s*\n(.*?)(?=^###\s|\Z)",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(content):
            proof_id = match.group(1).strip() or f"proof_{len(proofs)}"
            proofs[proof_id] = match.group(2)
        return proofs

    def _extract_lean(self, content: str) -> list[str]:
        """Extract Lean code blocks."""
        pattern = re.compile(r"```lean[4]?\n(.*?)```", re.DOTALL)
        return [match.group(1) for match in pattern.finditer(content)]

    def _check_algorithm_chain(
        self,
        alg_id: str,
        alg_content: str,
        claims: dict[str, str],
        proofs: dict[str, str],
        lean_blocks: list[str],
        full_content: str,
        file_path: str,
    ) -> list[DetectorFinding]:
        """Check proof chain for a single algorithm."""
        evidence = []

        # Look for claim references in algorithm
        claim_refs = re.findall(r"\(@\[\+?(P?\d*C\d+)\]\)", alg_content)
        claim_refs.extend(re.findall(r"\b(P?\d*C\d+)\b", alg_content))

        if not claim_refs:
            # No explicit claims - try LLM inference for prose-based claims
            if self._llm:
                inferred_claims = self._infer_claims_from_prose(alg_content)
                if inferred_claims:
                    evidence.append(
                        DetectorFinding(
                            severity=Severity.WARNING,
                            message=(
                                f"{alg_id} has no explicit claim references, but LLM infers possible claims"
                            ),
                            location=file_path,
                            element_id=alg_id,
                            detector="proof_chain",
                            details={
                                "inferred_claims": inferred_claims,
                                "method": "llm_inference",
                            },
                        )
                    )
                else:
                    evidence.append(
                        DetectorFinding(
                            severity=Severity.WARNING,
                            message=f"{alg_id} has no claims (explicit or inferred)",
                            location=file_path,
                            element_id=alg_id,
                            detector="proof_chain",
                        )
                    )
            else:
                evidence.append(
                    DetectorFinding(
                        severity=Severity.WARNING,
                        message=f"{alg_id} has no claim references",
                        location=file_path,
                        element_id=alg_id,
                        detector="proof_chain",
                    )
                )
            return evidence

        # Check each referenced claim
        for claim_id in set(claim_refs):
            if claim_id not in claims:
                # Claim referenced but not defined - try LLM inference
                if self._llm:
                    prose_claim = self._find_prose_claim(claim_id, full_content)
                    if prose_claim:
                        evidence.append(
                            DetectorFinding(
                                severity=Severity.INFO,
                                message=f"{claim_id} may exist as prose (LLM inferred)",
                                location=file_path,
                                element_id=claim_id,
                                detector="proof_chain",
                                details={"prose_location": prose_claim, "method": "llm_inference"},
                            )
                        )
                    else:
                        evidence.append(
                            DetectorFinding(
                                severity=Severity.WARNING,
                                message=f"{alg_id} references undefined claim {claim_id}",
                                location=file_path,
                                element_id=alg_id,
                                detector="proof_chain",
                            )
                        )
                else:
                    evidence.append(
                        DetectorFinding(
                            severity=Severity.WARNING,
                            message=f"{alg_id} references undefined claim {claim_id}",
                            location=file_path,
                            element_id=alg_id,
                            detector="proof_chain",
                        )
                    )
                continue

            # Claim exists - check for proof
            claim_content = claims[claim_id]
            has_proof = any(claim_id in p or claim_content[:50] in p for p in proofs.values())
            has_math = bool(re.search(r"P\d+\.\d+", claim_content))

            if not has_proof and not has_math:
                # Try LLM inference for prose-based proof
                if self._llm:
                    prose_proof = self._find_prose_proof(claim_id, full_content)
                    if prose_proof:
                        evidence.append(
                            DetectorFinding(
                                severity=Severity.INFO,
                                message=f"{claim_id} may have prose proof sketch (LLM inferred)",
                                location=file_path,
                                element_id=claim_id,
                                detector="proof_chain",
                                details={"prose_proof": prose_proof, "method": "llm_inference"},
                            )
                        )
                    else:
                        evidence.append(
                            DetectorFinding(
                                severity=Severity.WARNING,
                                message=f"{claim_id} has no proof sketch or math section",
                                location=file_path,
                                element_id=claim_id,
                                detector="proof_chain",
                            )
                        )
                else:
                    evidence.append(
                        DetectorFinding(
                            severity=Severity.WARNING,
                            message=f"{claim_id} has no proof sketch or math section",
                            location=file_path,
                            element_id=claim_id,
                            detector="proof_chain",
                        )
                    )

        # Check for Lean skeletons
        if not lean_blocks:
            # All algorithms flagged non-authoritative
            evidence.append(
                DetectorFinding(
                    severity=Severity.INFO,
                    message=f"{alg_id} has no Lean skeleton (flagged non-authoritative)",
                    location=file_path,
                    element_id=alg_id,
                    detector="proof_chain",
                    details={"non_authoritative": True},
                )
            )

        return evidence

    def _infer_claims_from_prose(self, content: str) -> list[str]:
        """Use LLM to infer claims from prose."""
        if not self._llm:
            return []

        prompt = f"""Analyze this algorithm content and identify any implicit claims or assertions that should be proven.

Content:
{content[:1000]}

List any claims you find as JSON: ["claim 1 description", "claim 2 description"]"""

        try:
            response = self._llm.complete(prompt)
            import json

            return json.loads(response)
        except Exception:
            return []

    def _find_prose_claim(self, claim_id: str, content: str) -> str | None:
        """Use LLM to find prose that might be a claim."""
        if not self._llm:
            return None

        prompt = f"""Search this content for prose that might be describing claim {claim_id}.
Return the relevant prose snippet if found, or null if not found.

Content:
{content[:2000]}

Output: Just the prose snippet or "null"."""

        try:
            response = self._llm.complete(prompt)
            return response if response.lower() != "null" else None
        except Exception:
            return None

    def _find_prose_proof(self, claim_id: str, content: str) -> str | None:
        """Use LLM to find prose that might be a proof."""
        if not self._llm:
            return None

        prompt = f"""Search this content for prose that might be a proof or justification for {claim_id}.
Return the relevant prose snippet if found, or null if not found.

Content:
{content[:2000]}

Output: Just the prose snippet or "null"."""

        try:
            response = self._llm.complete(prompt)
            return response if response.lower() != "null" else None
        except Exception:
            return None


# =============================================================================
# PROSE FRAGMENT INFERENCE DETECTION (Gap 6 fix)
# =============================================================================


class ProseFragmentInferenceDetector:
    """FIRST-CLASS inference detector for requirements/claims hidden in prose.

    This is NOT an afterthought - it's a primary detection method for messy inputs
    where meaning is scattered across prose fragments rather than structured elements.

    Outputs DetectorFinding with confidence scores, linking back to source text.
    """

    def __init__(self, llm_client: Any = None) -> None:
        """Initialize detector with optional LLM for inference.

        Args:
            llm_client: Optional LLM client for prose inference
        """
        self._llm = llm_client

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect candidate requirements/claims in prose fragments.

        Returns evidence with confidence scores that can be:
        1. Promoted to structured elements if high confidence
        2. Flagged for manual review if medium confidence
        3. Ignored if low confidence
        """
        evidence = []

        # Find prose sections (not inside code blocks, not structured headers)
        prose_sections = self._extract_prose_sections(content)

        for section in prose_sections:
            # Detect requirement-like statements
            req_candidates = self._detect_requirement_patterns(section, file_path)
            evidence.extend(req_candidates)

            # Detect claim-like statements
            claim_candidates = self._detect_claim_patterns(section, file_path)
            evidence.extend(claim_candidates)

            # LLM inference for complex/scattered prose
            if self._llm:
                llm_candidates = self._infer_via_llm(section, file_path)
                evidence.extend(llm_candidates)

        return evidence

    def _extract_prose_sections(self, content: str) -> list[dict]:
        """Extract prose sections (not code, not structured headers)."""
        sections = []

        # Split by code blocks
        parts = re.split(r"```[\s\S]*?```", content)

        for _i, part in enumerate(parts):
            # Skip if it's mostly headers/structured content
            lines = part.strip().split("\n")
            prose_lines = [line for line in lines if not line.startswith("#") and line.strip()]

            if len(prose_lines) >= 3:  # At least 3 prose lines
                start_line = content[: content.find(part)].count("\n") + 1 if part in content else 1
                sections.append(
                    {
                        "content": "\n".join(prose_lines),
                        "start_line": start_line,
                        "end_line": start_line + len(prose_lines),
                    }
                )

        return sections

    def _detect_requirement_patterns(self, section: dict, file_path: str) -> list[DetectorFinding]:
        """Detect requirement-like patterns in prose."""
        evidence = []

        # Requirement indicators
        patterns = [
            (r"\b(must|shall|should|will)\s+(\w+)", 0.8, "modal_verb"),
            (r"\b(required|mandatory|necessary)\b", 0.7, "requirement_keyword"),
            (r"\b(ensure|guarantee|maintain)\s+that\b", 0.75, "assurance_verb"),
            (r"\b(always|never)\s+(\w+)", 0.6, "absolute_adverb"),
        ]

        for pattern, base_confidence, pattern_type in patterns:
            for match in re.finditer(pattern, section["content"], re.IGNORECASE):
                # Get context around match
                start = max(0, match.start() - 50)
                end = min(len(section["content"]), match.end() + 100)
                context = section["content"][start:end]

                evidence.append(
                    DetectorFinding(
                        severity=Severity.INFO,
                        message=f"Candidate requirement in prose: '{match.group(0)}...'",
                        location=f"{file_path}:{section['start_line']}",
                        element_id=None,  # Not yet promoted to element
                        detector="prose_fragment_inference",
                        details={
                            "pattern_type": pattern_type,
                            "confidence": base_confidence,
                            "matched_text": match.group(0),
                            "context": context,
                            "can_promote": True,  # Flag for strategy to promote
                            "method": "pattern_match",
                        },
                    )
                )

        return evidence

    def _detect_claim_patterns(self, section: dict, file_path: str) -> list[DetectorFinding]:
        """Detect claim-like patterns in prose."""
        evidence = []

        # Claim indicators
        patterns = [
            (r"\b(converges?|stable|bounded)\b", 0.7, "convergence_claim"),
            (r"\b(correct|sound|complete)\b", 0.65, "correctness_claim"),
            (r"\b(invariant|preserved|maintained)\b", 0.75, "invariant_claim"),
            (r"\b(theorem|lemma|proposition)\b", 0.85, "formal_claim"),
        ]

        for pattern, base_confidence, pattern_type in patterns:
            for match in re.finditer(pattern, section["content"], re.IGNORECASE):
                start = max(0, match.start() - 50)
                end = min(len(section["content"]), match.end() + 100)
                context = section["content"][start:end]

                evidence.append(
                    DetectorFinding(
                        severity=Severity.INFO,
                        message=f"Candidate claim in prose: '{match.group(0)}...'",
                        location=f"{file_path}:{section['start_line']}",
                        element_id=None,
                        detector="prose_fragment_inference",
                        details={
                            "pattern_type": pattern_type,
                            "confidence": base_confidence,
                            "matched_text": match.group(0),
                            "context": context,
                            "can_promote": True,
                            "method": "pattern_match",
                        },
                    )
                )

        return evidence

    def _infer_via_llm(self, section: dict, file_path: str) -> list[DetectorFinding]:
        """Use LLM to infer requirements/claims from complex prose."""
        if not self._llm:
            return []

        evidence = []

        prompt = f"""Analyze this prose text and identify any implicit requirements, claims, or invariants
that should be made explicit as structured spec elements.

For each finding, provide:
1. The type (requirement/claim/invariant)
2. A confidence score (0.0-1.0)
3. The relevant text span
4. A suggested structured form

Text:
{section["content"][:1500]}

Output as JSON list: [{{"type": "...", "confidence": 0.X, "text": "...", "structured_form": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json

            findings = json.loads(response)

            for finding in findings:
                evidence.append(
                    DetectorFinding(
                        severity=Severity.INFO,
                        message=f"LLM-inferred {finding['type']}: {finding['text'][:50]}...",
                        location=f"{file_path}:{section['start_line']}",
                        element_id=None,
                        detector="prose_fragment_inference",
                        details={
                            "pattern_type": f"llm_inferred_{finding['type']}",
                            "confidence": finding["confidence"],
                            "matched_text": finding["text"],
                            "structured_form": finding.get("structured_form"),
                            "can_promote": finding["confidence"] >= 0.7,
                            "method": "llm_inference",
                        },
                    )
                )
        except Exception as e:
            pass  # LLM failures are non-fatal
            logger.debug(f"LLM inference failed: {e}")

        return evidence


class InferredClaimPromotionStrategy:
    """Strategy to promote high-confidence inferred claims to structured elements.

    This pairs with ProseFragmentInferenceDetector - detects -> evidence -> promotes.
    """

    def should_apply(self, evidence: list[DetectorFinding]) -> bool:
        """Check if there are promotable inferences."""
        return any(
            e.detector == "prose_fragment_inference"
            and e.details.get("can_promote", False)
            and e.details.get("confidence", 0) >= 0.7
            for e in evidence
        )

    def apply(self, evidence: list[DetectorFinding], units: list) -> list:
        """Promote high-confidence inferences to structured elements.

        Returns new TrackedUnits for promoted elements.
        """
        new_units = []

        for e in evidence:
            if e.detector != "prose_fragment_inference":
                continue
            if not e.details.get("can_promote", False):
                continue
            if e.details.get("confidence", 0) < 0.7:
                continue

            # Create new unit based on pattern type
            pattern_type = e.details.get("pattern_type", "")

            if "requirement" in pattern_type or "modal_verb" in pattern_type:
                # Promote to requirement/goal
                unit_id = f"InferredReq_{len(new_units) + 1}"
                content = e.details.get("structured_form") or e.details.get("context", "")

                new_units.append(
                    {
                        "id": unit_id,
                        "content": content,
                        "unit_type": "goal",  # Requirements become goals
                        "source": e.location,
                        "introduced_by": "inference",
                        "confidence": e.details["confidence"],
                        "provenance": {
                            "method": e.details.get("method"),
                            "original_text": e.details.get("matched_text"),
                            "detector": "prose_fragment_inference",
                        },
                    }
                )

            elif "claim" in pattern_type or "invariant" in pattern_type:
                # Promote to claim/invariant
                unit_id = f"InferredClaim_{len(new_units) + 1}"
                content = e.details.get("structured_form") or e.details.get("context", "")

                new_units.append(
                    {
                        "id": unit_id,
                        "content": content,
                        "unit_type": "claim",
                        "source": e.location,
                        "introduced_by": "inference",
                        "confidence": e.details["confidence"],
                        "provenance": {
                            "method": e.details.get("method"),
                            "original_text": e.details.get("matched_text"),
                            "detector": "prose_fragment_inference",
                        },
                    }
                )

        return new_units


# =============================================================================
# Uncertainty Detection (new)
# =============================================================================


class UncertaintyDetector:
    """Detects unresolved uncertainty markers in content."""

    UNCERTAINTY_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"\?(?:\s|$)", re.MULTILINE), "question"),
        (re.compile(r"\bTODO\b", re.IGNORECASE), "todo"),
        (re.compile(r"\bTBD\b", re.IGNORECASE), "tbd"),
        (re.compile(r"\bFIXME\b", re.IGNORECASE), "fixme"),
        (re.compile(r"\bXXX\b"), "xxx"),
        (re.compile(r"\bsorry\b"), "lean_sorry"),  # Lean proof incomplete
        (re.compile(r"\bmay\s+need\b", re.IGNORECASE), "hedging"),
        (re.compile(r"\bpossibly\b", re.IGNORECASE), "hedging"),
        (re.compile(r"\bunclear\b", re.IGNORECASE), "unclear"),
    ]

    def detect(self, content: str, file_path: str) -> list[DetectorFinding]:
        """Detect uncertainty markers."""
        gaps = []

        lines = content.splitlines()
        for pattern, marker_type in self.UNCERTAINTY_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                line = lines[line_num - 1] if line_num <= len(lines) else ""

                # Skip if in code block (except sorry in lean)
                if marker_type != "lean_sorry" and self._in_code_block(content, match.start()):
                    continue

                severity = (
                    Severity.WARNING if marker_type in ("todo", "lean_sorry") else Severity.INFO
                )

                gaps.append(
                    DetectorFinding(
                        detector="unresolved_uncertainty",
                        severity=severity,
                        message=f"Unresolved {marker_type}: {line.strip()[:50]}...",
                        location=f"{file_path}:{line_num}",
                        details={"marker_type": marker_type, "line": line.strip()},
                    )
                )

        return gaps

    def _in_code_block(self, content: str, position: int) -> bool:
        """Check if position is inside a code block."""
        before = content[:position]
        opens = before.count("```")
        return opens % 2 == 1  # Odd number means inside block


# =============================================================================
# STRUCTURAL HEALTH DETECTORS (Gap 7 fix)
# =============================================================================


class StructuralHealthDetector:
    """Detects structural health issues: coupling, cohesion, relations, underspecified elements.

    These are the "newer gaps.md" style diagnostics that must be preserved while
    also adding completeness/proof-obligation tracking.

    Gap 7 fix: Ensure these remain as evidence extractors, not just formatting buckets.
    """

    def detect(
        self, units: list, libraries: dict[str, list[str]] | None = None
    ) -> list[DetectorFinding]:
        """Run all structural health checks.

        Args:
            units: List of TrackedUnit objects
            libraries: Optional mapping of library_name -> element_ids
        """
        evidence = []

        evidence.extend(self._detect_coupling_issues(units, libraries))
        evidence.extend(self._detect_cohesion_issues(units, libraries))
        evidence.extend(self._detect_missing_relations(units))
        evidence.extend(self._detect_underspecified_elements(units))
        evidence.extend(self._detect_unpinned_elements(units))
        evidence.extend(self._detect_unsatisfied_invariants(units))

        return evidence

    def _detect_coupling_issues(
        self, units: list, libraries: dict[str, list[str]] | None = None
    ) -> list[DetectorFinding]:
        """Detect excessive coupling between elements/libraries."""
        evidence = []

        if not libraries:
            return evidence

        # Count cross-library references
        cross_refs: dict[tuple[str, str], int] = {}

        for unit in units:
            unit_lib = getattr(unit, "primary_library", None)
            if not unit_lib:
                continue

            # Check references in content
            for ref in getattr(unit, "references", []):
                ref_id = getattr(ref, "id_value", str(ref))
                ref_lib = self._find_library_for_element(ref_id, libraries)
                if ref_lib and ref_lib != unit_lib:
                    key = tuple(sorted([unit_lib, ref_lib]))
                    cross_refs[key] = cross_refs.get(key, 0) + 1

        # Flag high coupling
        for (lib1, lib2), count in cross_refs.items():
            if count > 10:  # Threshold
                evidence.append(
                    DetectorFinding(
                        severity=Severity.WARNING,
                        message=f"High coupling between {lib1} and {lib2}: {count} cross-references",
                        location=f"libraries/{lib1}.md <-> libraries/{lib2}.md",
                        element_id=None,
                        detector="structural_health",
                        details={
                            "issue_type": "coupling",
                            "libraries": [lib1, lib2],
                            "count": count,
                        },
                    )
                )

        return evidence

    def _detect_cohesion_issues(
        self, units: list, libraries: dict[str, list[str]] | None = None
    ) -> list[DetectorFinding]:
        """Detect low cohesion within libraries."""
        evidence = []

        if not libraries:
            return evidence

        for lib_name, element_ids in libraries.items():
            if len(element_ids) < 3:
                continue

            # Check if elements in same library reference each other
            lib_units = [u for u in units if getattr(u, "primary_library", None) == lib_name]
            internal_refs = 0
            total_refs = 0

            for unit in lib_units:
                for ref in getattr(unit, "references", []):
                    total_refs += 1
                    ref_id = getattr(ref, "id_value", str(ref))
                    if ref_id in element_ids:
                        internal_refs += 1

            if total_refs > 5 and internal_refs / total_refs < 0.3:  # Low cohesion
                evidence.append(
                    DetectorFinding(
                        severity=Severity.INFO,
                        message=f"Low cohesion in {lib_name}: {internal_refs}/{total_refs} internal references ({internal_refs / total_refs:.0%})",
                        location=f"libraries/{lib_name}.md",
                        element_id=None,
                        detector="structural_health",
                        details={
                            "issue_type": "cohesion",
                            "library": lib_name,
                            "internal_refs": internal_refs,
                            "total_refs": total_refs,
                            "ratio": internal_refs / total_refs if total_refs > 0 else 0,
                        },
                    )
                )

        return evidence

    def _detect_missing_relations(self, units: list) -> list[DetectorFinding]:
        """Detect elements that should have relations but don't."""
        evidence = []

        for unit in units:
            unit_type = getattr(unit, "unit_type", None)
            has_relations = bool(getattr(unit, "relation_libraries", []))

            # Algorithms and Claims often relate to multiple libraries
            if unit_type in ("algorithm", "claim", "ALGORITHM", "CLAIM"):
                # Check if content suggests cross-cutting concern
                content = getattr(unit, "content", "")
                cross_cutting_keywords = [
                    "graph",
                    "field",
                    "embed",
                    "pattern",
                    "index",
                    "workspace",
                ]
                matches = sum(1 for kw in cross_cutting_keywords if kw in content.lower())

                if matches >= 2 and not has_relations:
                    unit_id = getattr(unit, "id", "unknown")
                    evidence.append(
                        DetectorFinding(
                            severity=Severity.INFO,
                            message=f"{unit_id} appears cross-cutting but has no relation annotations",
                            location=getattr(unit, "source", "unknown"),
                            element_id=unit_id,
                            detector="structural_health",
                            details={
                                "issue_type": "missing_relations",
                                "keyword_matches": matches,
                                "suggestion": "Add (@[+rel:library_name]) annotations",
                            },
                        )
                    )

        return evidence

    def _detect_underspecified_elements(self, units: list) -> list[DetectorFinding]:
        """Detect elements that lack sufficient specification."""
        evidence = []

        for unit in units:
            content = getattr(unit, "content", "")
            unit_type = getattr(unit, "unit_type", None)
            unit_id = getattr(unit, "id", "unknown")

            # Check for stub-like content
            if len(content.strip()) < 50:
                evidence.append(
                    DetectorFinding(
                        severity=Severity.WARNING,
                        message=f"{unit_id} appears underspecified ({len(content)} chars)",
                        location=getattr(unit, "source", "unknown"),
                        element_id=unit_id,
                        detector="structural_health",
                        details={
                            "issue_type": "underspecified",
                            "content_length": len(content),
                            "unit_type": str(unit_type),
                        },
                    )
                )

            # Check for TODO/TBD in body
            if "TODO" in content or "TBD" in content or "???" in content:
                evidence.append(
                    DetectorFinding(
                        severity=Severity.WARNING,
                        message=f"{unit_id} contains TODO/TBD markers",
                        location=getattr(unit, "source", "unknown"),
                        element_id=unit_id,
                        detector="structural_health",
                        details={"issue_type": "incomplete", "markers_found": True},
                    )
                )

        return evidence

    def _detect_unpinned_elements(self, units: list) -> list[DetectorFinding]:
        """Detect elements not pinned to a library."""
        evidence = []

        for unit in units:
            primary_lib = getattr(unit, "primary_library", None)
            unit_id = getattr(unit, "id", "unknown")
            if not primary_lib:
                evidence.append(
                    DetectorFinding(
                        severity=Severity.WARNING,
                        message=f"{unit_id} has no primary library assignment",
                        location=getattr(unit, "source", "unknown"),
                        element_id=unit_id,
                        detector="structural_health",
                        details={
                            "issue_type": "unpinned",
                            "candidate_libraries": list(
                                getattr(unit, "candidate_libraries", {}).keys()
                            )[:5],
                        },
                    )
                )

        return evidence

    def _detect_unsatisfied_invariants(self, units: list) -> list[DetectorFinding]:
        """Detect invariants that aren't referenced by any algorithm."""
        evidence = []

        # Collect all invariants and their references
        invariants = {
            getattr(u, "id", "")
            for u in units
            if str(getattr(u, "unit_type", "")).lower() in ("invariant", "p#i#")
        }
        referenced = set()

        for unit in units:
            content = getattr(unit, "content", "")
            for inv_id in invariants:
                if inv_id in content:
                    referenced.add(inv_id)

        # Unreferenced invariants
        unreferenced = invariants - referenced
        for inv_id in unreferenced:
            evidence.append(
                DetectorFinding(
                    severity=Severity.INFO,
                    message=f"Invariant {inv_id} is not referenced by any algorithm",
                    location="plan.md",
                    element_id=inv_id,
                    detector="structural_health",
                    details={
                        "issue_type": "unsatisfied_invariant",
                        "suggestion": "Either add reference in relevant algorithm or mark as deprecated",
                    },
                )
            )

        return evidence

    def _find_library_for_element(
        self, element_id: str, libraries: dict[str, list[str]]
    ) -> str | None:
        """Find which library contains an element."""
        for lib_name, element_ids in libraries.items():
            if element_id in element_ids:
                return lib_name
        return None


# =============================================================================
# Evidence Extractor (Consolidated Interface)
# =============================================================================


class EvidenceExtractor:
    """Consolidated evidence extraction from multiple sources.

    This class provides a unified interface for extracting evidence from:
    - Content files (plan.md, patches, libraries)
    - TrackedUnits (for structural health)
    - Cross-file comparisons
    """

    def __init__(self, llm_client=None, config_path: Path | None = None) -> None:
        self.format_detector = FormatComplianceDetector()
        self.duplicate_detector = DuplicateDetector()
        self.function_detector = UndefinedFunctionDetector(config_path)
        self.sequence_analyzer = SequenceAnalyzer()
        self.content_verifier = ContentVerifier()
        self.uncertainty_detector = UncertaintyDetector()
        self.proof_chain_detector = ProofChainDetector(llm_client)
        self.prose_inference_detector = ProseFragmentInferenceDetector(llm_client)
        self.structural_health_detector = StructuralHealthDetector()

    def extract_from_content(
        self, content: str, file_path: str, detectors: list[str] | None = None
    ) -> list[DetectorFinding]:
        """Extract evidence from a single content string.

        Args:
            content: The content to analyze
            file_path: Path/name for location reporting
            detectors: Optional list of detector names to run (default: all)
        """
        evidence = []
        all_detectors = detectors is None

        if all_detectors or "format" in (detectors or []):
            evidence.extend(self.format_detector.detect(content, file_path))

        if all_detectors or "duplicate" in (detectors or []):
            evidence.extend(
                self.duplicate_detector.detect_duplicate_declarations(content, file_path)
            )
            evidence.extend(self.duplicate_detector.detect_duplicate_headers(content, file_path))

        if all_detectors or "function" in (detectors or []):
            evidence.extend(self.function_detector.detect(content, file_path))

        if all_detectors or "sequence" in (detectors or []):
            evidence.extend(self.sequence_analyzer.detect(content, file_path))

        if all_detectors or "uncertainty" in (detectors or []):
            evidence.extend(self.uncertainty_detector.detect(content, file_path))

        if all_detectors or "proof_chain" in (detectors or []):
            evidence.extend(self.proof_chain_detector.detect(content, file_path))

        if all_detectors or "prose_inference" in (detectors or []):
            evidence.extend(self.prose_inference_detector.detect(content, file_path))

        return evidence

    def extract_from_comparison(
        self, plan_content: str, library_content: str, library_name: str
    ) -> list[DetectorFinding]:
        """Extract evidence from plan/library comparison."""
        return self.content_verifier.verify(plan_content, library_content, library_name)

    def extract_from_units(
        self, units: list, libraries: dict[str, list[str]] | None = None
    ) -> list[DetectorFinding]:
        """Extract structural health evidence from TrackedUnits."""
        return self.structural_health_detector.detect(units, libraries)


# =============================================================================
# Gap Synthesizer
# =============================================================================


class GapSynthesizer:
    """Synthesizes GapElement objects from DetectorFinding by clustering.

    Clustering criteria:
    - Same element_id
    - Same root cause (inferred from detector + message)
    - Same patch origin
    """

    def __init__(self) -> None:
        self._gap_counter = 0

    def reset_counter(self) -> None:
        """Reset the gap ID counter."""
        self._gap_counter = 0

    def synthesize(self, evidence: list[DetectorFinding]) -> list[GapElement]:
        """Synthesize gaps by clustering related evidence."""
        if not evidence:
            return []

        # Group by element_id first
        by_element: dict[str, list[DetectorFinding]] = defaultdict(list)
        orphan_evidence: list[DetectorFinding] = []

        for e in evidence:
            if e.element_id:
                by_element[e.element_id].append(e)
            else:
                orphan_evidence.append(e)

        gaps = []

        # Create gap for each element with evidence
        for element_id, element_evidence in by_element.items():
            gap = self._create_gap(element_evidence, element_id)
            gaps.append(gap)

        # Create gaps for orphan evidence (grouped by detector)
        by_detector: dict[str, list[DetectorFinding]] = defaultdict(list)
        for e in orphan_evidence:
            by_detector[e.detector].append(e)

        for _detector, detector_evidence in by_detector.items():
            # Sub-group by location file
            by_file: dict[str, list[DetectorFinding]] = defaultdict(list)
            for e in detector_evidence:
                file_part = e.location.split(":")[0] if ":" in e.location else e.location
                by_file[file_part].append(e)

            for _file_part, file_evidence in by_file.items():
                gap = self._create_gap(file_evidence, None)
                gaps.append(gap)

        return gaps

    def _create_gap(self, evidence: list[DetectorFinding], element_id: str | None) -> GapElement:
        """Create a GapElement from evidence."""
        self._gap_counter += 1

        # Determine severity (highest from evidence)
        severities = [e.severity for e in evidence]
        if Severity.ERROR in severities:
            severity = Severity.ERROR
        elif Severity.WARNING in severities:
            severity = Severity.WARNING
        else:
            severity = Severity.INFO

        # Generate summary
        if len(evidence) == 1:
            summary = evidence[0].message
        else:
            summary = f"{len(evidence)} issues: {evidence[0].message[:50]}..."

        # Collect affected elements
        affects = []
        if element_id:
            affects.append(element_id)
        for e in evidence:
            if e.element_id and e.element_id not in affects:
                affects.append(e.element_id)
            if e.location not in affects:
                affects.append(e.location)

        return GapElement(
            id=f"GAP-{self._gap_counter:04d}",
            severity=severity,
            summary=summary,
            affects=affects[:10],  # Limit
            evidence=evidence,
            patch_origin=self._infer_patch_origin(evidence),
        )

    def _infer_patch_origin(self, evidence: list[DetectorFinding]) -> str | None:
        """Infer which patch introduced this gap."""
        for e in evidence:
            if "patches/" in e.location:
                # Extract patch name
                parts = e.location.split("/")
                for part in parts:
                    if part.startswith("p") and ".md" in part:
                        return part.replace(".md", "")
        return None


# =============================================================================
# Unified Gap Detector
# =============================================================================


class UnifiedGapDetector:
    """Unified gap detection: evidence collection -> gap synthesis.

    This is the main entry point. It:
    1. Collects evidence from all detectors
    2. Synthesizes gaps by clustering related evidence
    3. Formats output as multi-section gaps.md
    """

    def __init__(self, llm_client=None, config_path: Path | None = None) -> None:
        self.evidence_extractor = EvidenceExtractor(llm_client, config_path)
        self.gap_synthesizer = GapSynthesizer()

    def collect_evidence(self, spec_folder: Path) -> list[DetectorFinding]:
        """Collect all evidence from all detectors.

        This is the first phase - pure evidence collection.
        """
        evidence = []

        # Read main files
        plan_path = spec_folder / "plan.md"
        plan_content = plan_path.read_text() if plan_path.exists() else ""

        # Detect in plan.md
        if plan_content:
            evidence.extend(self.evidence_extractor.extract_from_content(plan_content, "plan.md"))

        # Detect in patches
        patches_dir = spec_folder / "patches"
        if patches_dir.exists():
            for patch_file in patches_dir.glob("*.md"):
                patch_content = patch_file.read_text()
                # Only run format and uncertainty detectors on patches
                evidence.extend(
                    self.evidence_extractor.extract_from_content(
                        patch_content,
                        f"patches/{patch_file.name}",
                        detectors=["format", "uncertainty"],
                    )
                )

        # Detect in libraries and verify against plan
        libraries_dir = spec_folder / "libraries"
        if libraries_dir.exists() and plan_content:
            for lib_file in libraries_dir.glob("*.md"):
                lib_content = lib_file.read_text()
                lib_name = f"libraries/{lib_file.name}"

                # Duplicate detection in libraries
                evidence.extend(
                    self.evidence_extractor.extract_from_content(
                        lib_content, lib_name, detectors=["duplicate"]
                    )
                )

                # Content verification against plan
                evidence.extend(
                    self.evidence_extractor.extract_from_comparison(
                        plan_content, lib_content, lib_name
                    )
                )

        return evidence

    def synthesize_gaps(self, evidence: list[DetectorFinding]) -> list[GapElement]:
        """Synthesize gaps by clustering related evidence."""
        return self.gap_synthesizer.synthesize(evidence)

    def detect_all(self, spec_folder: Path, include_info: bool = True) -> list[GapElement]:
        """Run full detection: collect evidence -> synthesize gaps.

        Returns first-class GapElement objects.
        """
        evidence = self.collect_evidence(spec_folder)

        # Filter by severity if requested
        if not include_info:
            evidence = [e for e in evidence if e.severity != Severity.INFO]

        gaps = self.synthesize_gaps(evidence)
        return gaps

    def format_gaps_md(
        self, gaps: list[GapElement], previous_gaps: list[GapElement] | None = None
    ) -> str:
        """Format gaps as multi-section markdown report.

        Gap 7 fix: Added Gap Lifecycle section (new/persisting/resolved/bypassed).
        Gap 8 fix: Expanded to include ALL promised sections.

        Sections (matching EVOLUTION_PLAN):
        - Gap Lifecycle (Gap 7 fix)
        - Patch Ledger
        - Proof Obligations
        - Undefined Functions
        - Structural Health
        - Unresolved Elements
        - Summary
        """
        lines = ["# Gaps\n"]
        lines.append(f"\nGenerated: {datetime.now().isoformat()}\n")

        # =================================================================
        # GAP LIFECYCLE SECTION (Gap 7 fix)
        # =================================================================
        lines.append("\n## Gap Lifecycle\n")

        if previous_gaps:
            prev_ids = {g.id for g in previous_gaps}
            curr_ids = {g.id for g in gaps}

            # Categorize gaps
            new_gaps = [g for g in gaps if g.id not in prev_ids]
            persisting_gaps = [g for g in gaps if g.id in prev_ids]
            resolved_ids = prev_ids - curr_ids
            bypassed_gaps = [g for g in gaps if g.bypassed or g.drop_reason]

            lines.append("\n### New This Pass\n")
            if new_gaps:
                for g in new_gaps[:10]:
                    lines.append(f"- **{g.id}**: {g.summary}")
                if len(new_gaps) > 10:
                    lines.append(f"- ... and {len(new_gaps) - 10} more")
            else:
                lines.append("- None")

            lines.append("\n### Persisting\n")
            if persisting_gaps:
                for g in persisting_gaps[:10]:
                    lines.append(f"- **{g.id}**: {g.summary}")
                if len(persisting_gaps) > 10:
                    lines.append(f"- ... and {len(persisting_gaps) - 10} more")
            else:
                lines.append("- None")

            lines.append("\n### Resolved Since Last Pass\n")
            if resolved_ids:
                for gid in sorted(resolved_ids)[:10]:
                    lines.append(f"- [RESOLVED] **{gid}**")
                if len(resolved_ids) > 10:
                    lines.append(f"- ... and {len(resolved_ids) - 10} more")
            else:
                lines.append("- None")

            lines.append("\n### Bypassed / Intentionally Dropped\n")
            if bypassed_gaps:
                for g in bypassed_gaps[:10]:
                    reason = g.drop_reason or "intentional bypass"
                    lines.append(f"- [BYPASSED] **{g.id}**: {reason}")
                if len(bypassed_gaps) > 10:
                    lines.append(f"- ... and {len(bypassed_gaps) - 10} more")
            else:
                lines.append("- None")
        else:
            lines.append("*No previous pass available for lifecycle comparison.*\n")

        # =================================================================
        # PATCH LEDGER SECTION
        # =================================================================
        by_patch: dict[str, list[GapElement]] = defaultdict(list)
        no_patch: list[GapElement] = []
        for gap in gaps:
            if gap.patch_origin:
                by_patch[gap.patch_origin].append(gap)
            else:
                no_patch.append(gap)

        lines.append("\n## Patch Ledger\n")
        if by_patch:
            for patch_id in sorted(by_patch.keys()):
                patch_gaps = by_patch[patch_id]
                lines.append(f"\n### {patch_id}\n")
                for gap in patch_gaps:
                    icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                        gap.severity.value, "-"
                    )
                    lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                    lines.append(f"  - Affects: {', '.join(gap.affects[:5])}")
                    lines.append(f"  - Evidence: {len(gap.evidence)} pieces")
                    lines.append("")
        else:
            lines.append("*No patch-specific gaps.*\n")

        # =================================================================
        # PROOF OBLIGATIONS SECTION (Gap 8 fix - was missing)
        # =================================================================
        lines.append("\n## Proof Obligations\n")
        proof_gaps = [
            g
            for g in gaps
            if "proof" in g.id.lower()
            or "claim" in g.id.lower()
            or any(
                "proof" in str(e.message).lower() or e.detector == "proof_chain" for e in g.evidence
            )
        ]
        if proof_gaps:
            for gap in proof_gaps:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                    gap.severity.value, "-"
                )
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                claim_affects = [a for a in gap.affects if "C" in a]
                if claim_affects:
                    lines.append(f"  - Related claims: {', '.join(claim_affects[:5])}")
                lines.append("")
        else:
            lines.append("*No proof obligation issues detected.*\n")

        # =================================================================
        # UNDEFINED FUNCTIONS SECTION (Gap 8 fix - was missing)
        # =================================================================
        lines.append("\n## Undefined Functions\n")
        undefined_gaps = [
            g
            for g in gaps
            if "undefined" in g.id.lower()
            or "function" in g.id.lower()
            or any(e.detector == "undefined_function" for e in g.evidence)
        ]
        if undefined_gaps:
            for gap in undefined_gaps:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                    gap.severity.value, "-"
                )
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                # Extract function names from evidence
                func_names = []
                for ev in gap.evidence:
                    if ev.details.get("function_name"):
                        func_names.append(ev.details["function_name"])
                if func_names:
                    lines.append(f"  - Functions: `{', '.join(func_names[:5])}`")
                lines.append("")
        else:
            lines.append("*No undefined functions detected.*\n")

        # =================================================================
        # STRUCTURAL HEALTH SECTION
        # =================================================================
        lines.append("\n## Structural Health\n")
        structural_gaps = [
            g
            for g in no_patch
            if "structural" in g.id.lower()
            or "coupling" in g.id.lower()
            or "cohesion" in g.id.lower()
            or "relation" in g.id.lower()
            or any(e.detector == "structural_health" for e in g.evidence)
        ]
        other_no_patch = [g for g in no_patch if g not in structural_gaps]

        if structural_gaps:
            for gap in structural_gaps:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                    gap.severity.value, "-"
                )
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                lines.append(f"  - Affects: {', '.join(gap.affects[:5])}")
                lines.append("")
        else:
            lines.append("*No structural health issues detected.*\n")

        # =================================================================
        # UNRESOLVED ELEMENTS SECTION (Gap 8 fix - was missing)
        # =================================================================
        lines.append("\n## Unresolved Elements\n")
        unresolved_gaps = [
            g
            for g in gaps
            if "unresolved" in g.id.lower()
            or "vague" in g.id.lower()
            or "entity_resolution" in g.id.lower()
            or any("resolution" in str(e.detector).lower() for e in g.evidence)
        ]
        if unresolved_gaps:
            for gap in unresolved_gaps:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                    gap.severity.value, "-"
                )
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                # Show what couldn't be resolved
                for ev in gap.evidence[:3]:
                    if ev.details.get("original_text"):
                        lines.append(f"  - Unresolved: `{ev.details['original_text'][:50]}`")
                lines.append("")
        else:
            lines.append("*No unresolved elements detected.*\n")

        # =================================================================
        # OTHER GAPS SECTION (catch-all for uncategorized)
        # =================================================================
        categorized = set(
            g.id for g in proof_gaps + undefined_gaps + structural_gaps + unresolved_gaps
        )
        other_gaps = [g for g in other_no_patch if g.id not in categorized]
        if other_gaps:
            lines.append("\n## Other Issues\n")
            for gap in other_gaps:
                icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                    gap.severity.value, "-"
                )
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                lines.append(f"  - Affects: {', '.join(gap.affects[:5])}")
                lines.append("")

        # =================================================================
        # SUMMARY SECTION
        # =================================================================
        lines.append("\n## Summary\n")
        lines.append(f"- Total gaps: {len(gaps)}")
        lines.append(f"- Total evidence: {sum(len(g.evidence) for g in gaps)}")
        lines.append(f"- Errors: {sum(1 for g in gaps if g.severity == Severity.ERROR)}")
        lines.append(f"- Warnings: {sum(1 for g in gaps if g.severity == Severity.WARNING)}")
        lines.append(f"- Info: {sum(1 for g in gaps if g.severity == Severity.INFO)}")

        # Gap 7 lifecycle summary
        if previous_gaps:
            prev_ids = {g.id for g in previous_gaps}
            curr_ids = {g.id for g in gaps}
            lines.append("")
            lines.append("### Lifecycle Summary")
            lines.append(f"- New gaps: {len([g for g in gaps if g.id not in prev_ids])}")
            lines.append(f"- Persisting gaps: {len([g for g in gaps if g.id in prev_ids])}")
            lines.append(f"- Resolved gaps: {len(prev_ids - curr_ids)}")

        return "\n".join(lines)


# =============================================================================
# LEGACY API SUPPORT - Keep existing detect_gaps and format_gaps_md functions
# =============================================================================


def detect_gaps(
    content: str,
    registry,  # LibsRegistry
    libraries_dir: Path,
    artifact_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Detect gaps in the spec that need resolution.

    LEGACY API: This function maintains backward compatibility with the original
    dict-based gap format. For new code, use UnifiedGapDetector instead.

    Args:
        content: Combined content from all inputs
        registry: The library registry (derived from scanning)
        libraries_dir: Path to libraries directory
        artifact_root: Optional root path for artifact drift detection

    Returns:
        List of gap records (dicts)
    """
    warnings.warn(
        "detect_gaps() is deprecated. Use UnifiedGapDetector instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    gaps = []

    # Detect undefined references
    gaps.extend(_detect_undefined_references(content, registry))

    # Detect underspecified features
    gaps.extend(_detect_underspecified(content))

    # Detect unknown dependencies
    gaps.extend(_detect_unknown_dependencies(content))

    # Detect conflicting definitions
    gaps.extend(_detect_conflicts(content))

    # Detect missing integration points
    gaps.extend(_detect_missing_integrations(content, registry))

    # Detect unsatisfied invariants/goals (no referencing elements)
    gaps.extend(_detect_unsatisfied_invariants(content, registry))

    # Detect TODOs that need to be resolved and removed
    gaps.extend(_detect_todos(content))

    # Detect invalid library organization (type-based instead of subsystem)
    gaps.extend(_detect_invalid_libraries(libraries_dir))

    # Detect vague invariants
    gaps.extend(_detect_vague_invariants(content))

    # Detect pin-related gaps (broken pins, unpinned specs)
    gaps.extend(_detect_pin_gaps(content, artifact_root))

    # Detect subsystem cohesion issues
    gaps.extend(_detect_cohesion_issues(content, registry, libraries_dir))

    return gaps


def _detect_undefined_references(content: str, registry) -> list[dict[str, Any]]:
    """Find references to IDs that aren't declared."""
    gaps = []
    parser = AnnotationParser()
    IdValidator()

    # Get all declared IDs
    extractor = SectionExtractor()
    result = extractor.extract(content)
    declared_ids = set(result.sections.keys())
    registry_ids = set(registry.entries.keys())
    all_known_ids = declared_ids | registry_ids

    # Find references
    references = parser.parse_references(content)
    for ref in references:
        if ref.id_value not in all_known_ids:
            gaps.append(
                {
                    "type": "undefined_reference",
                    "id": ref.id_value,
                    "line": ref.line_number,
                    "description": f"Reference to undefined ID: {ref.id_value}",
                    "severity": "error",
                }
            )

    # Also find bare ID mentions in prose
    lines = content.split("\n")
    id_patterns = [
        (r"\bAlgorithm\s+(\d+)\b", lambda m: f"Algorithm {m.group(1)}"),
        (r"\b(D\d+)\b", lambda m: m.group(1)),
        (r"\b(G\d+)\b", lambda m: m.group(1)),  # Legacy goals
        (r"\b(I\d+)\b", lambda m: m.group(1)),  # Invariants
        (r"\b(P\d+I\d+)\b", lambda m: m.group(1)),
        (r"\b(P\d+C\d+)\b", lambda m: m.group(1)),
    ]

    for i, line in enumerate(lines):
        if line.strip().startswith("#"):  # Skip headers
            continue
        for pattern, id_builder in id_patterns:
            for match in re.finditer(pattern, line):
                id_value = id_builder(match)
                if id_value not in all_known_ids:
                    # Check it's not already captured
                    existing = any(g["id"] == id_value and g["line"] == i + 1 for g in gaps)
                    if not existing:
                        gaps.append(
                            {
                                "type": "undefined_reference",
                                "id": id_value,
                                "line": i + 1,
                                "description": f"Reference to undefined ID: {id_value}",
                                "severity": "warning",
                            }
                        )

    return gaps


def _detect_underspecified(content: str) -> list[dict[str, Any]]:
    """Find features that are declared but lack substance."""
    gaps = []
    extractor = SectionExtractor()
    result = extractor.extract(content)

    for id_value, section in result.sections.items():
        # Check for short/empty content
        body = section.body.strip()
        if len(body) < 50:
            gaps.append(
                {
                    "type": "underspecified",
                    "id": id_value,
                    "description": f"{id_value} has minimal content (<50 chars)",
                    "severity": "warning",
                }
            )
            continue

        # Check for question marks indicating uncertainty
        questions = re.findall(r"[^?]+\?", body)
        if len(questions) >= 2:
            gaps.append(
                {
                    "type": "uncertain",
                    "id": id_value,
                    "description": f"{id_value} contains {len(questions)} questions - needs clarification",
                    "severity": "info",
                }
            )

    return gaps


def _detect_unknown_dependencies(content: str) -> list[dict[str, Any]]:
    """Find references to external functions/systems not defined."""
    gaps = []
    extractor = SectionExtractor()
    result = extractor.extract(content)

    # Patterns that suggest external dependencies (function calls only)
    dependency_patterns = [
        (r"calls?\s+(\w+)\(\)", "function_call"),
        (r"via\s+(\w+)\(\)", "function_call"),
        (r"from\s+(\w+)\(\)", "function_call"),
        (r"to\s+(\w+)\(\)", "function_call"),
        (r"in\s+(\w+)\(\)", "function_call"),
        (r"uses?\s+(\w+)(?:\s+API|\s+service|\s+library)", "external_service"),
        (r"integrates?\s+with\s+(\w+)", "integration"),
    ]

    # Skip common words
    skip_words = {"the", "a", "an", "it", "this", "that", "we", "they", "be", "is", "are"}

    for id_value, section in result.sections.items():
        for pattern, dep_type in dependency_patterns:
            for match in re.finditer(pattern, section.body, re.IGNORECASE):
                name = match.group(1)
                if name.lower() in skip_words:
                    continue
                gaps.append(
                    {
                        "type": f"unknown_{dep_type}",
                        "name": name,
                        "source_id": id_value,
                        "description": f"Unknown {dep_type.replace('_', ' ')}: {name}",
                        "severity": "info",
                    }
                )

    return gaps


def _detect_conflicts(content: str) -> list[dict[str, Any]]:
    """Find conflicting definitions or decisions."""
    gaps = []
    extractor = SectionExtractor()
    result = extractor.extract(content)

    # ID pattern - only flag conflicts that reference actual spec IDs
    id_pattern = r"(Algorithm\s+\d+|D\d+|G\d+|I\d+|P\d+[IC]\d+|Lean\s+\d+)"

    # Patterns that suggest conflict or superseding - must reference a real ID
    conflict_patterns = [
        rf"(?:this\s+)?replaces?\s+{id_pattern}",
        rf"(?:this\s+)?supersedes?\s+{id_pattern}",
        rf"obsoletes?\s+{id_pattern}",
        rf"conflicts?\s+with\s+{id_pattern}",
        rf"instead\s+of\s+{id_pattern}",
    ]

    # Check each section for conflicts
    for id_value, section in result.sections.items():
        for pattern in conflict_patterns:
            for match in re.finditer(pattern, section.body, re.IGNORECASE):
                target = match.group(1).strip()
                gaps.append(
                    {
                        "type": "conflict",
                        "target": target,
                        "source_id": id_value,
                        "description": f"{id_value} may supersede {target}",
                        "severity": "warning",
                    }
                )

    return gaps


def _detect_missing_integrations(content: str, registry) -> list[dict[str, Any]]:
    """Find IDs that reference each other but aren't linked in registry."""
    gaps = []
    parser = AnnotationParser()
    extractor = SectionExtractor()

    result = extractor.extract(content)

    for id_value, section in result.sections.items():
        # Find what this section references
        refs_in_section = parser.parse_references(section.full_content)
        ref_ids = {r.id_value for r in refs_in_section}

        # Check if registry has these as related
        if id_value in registry.entries:
            entry = registry.entries[id_value]
            related = set(entry.related)

            # Find refs not in related
            missing_related = ref_ids - related - {id_value}
            for missing in missing_related:
                if missing in registry.entries:
                    gaps.append(
                        {
                            "type": "missing_relation",
                            "source_id": id_value,
                            "target": missing,
                            "description": f"{id_value} references {missing} but {missing} not in related",
                            "severity": "info",
                        }
                    )

    return gaps


def _detect_unsatisfied_invariants(content: str, registry) -> list[dict[str, Any]]:
    """Find invariants/goals that have no elements referencing them."""
    gaps = []
    extractor = SectionExtractor()
    parser = AnnotationParser()
    result = extractor.extract(content)

    # Find all invariant IDs (I1, I2, etc.) and legacy goal IDs (G1, G2, etc.)
    invariant_ids = set()
    for id_value in result.sections:
        if re.match(r"^[GI]\d+$", id_value):
            invariant_ids.add(id_value)

    # Also check registry for invariant/goal IDs
    for entry in registry.iter_entries():
        if re.match(r"^[GI]\d+$", entry.id_value):
            invariant_ids.add(entry.id_value)

    if not invariant_ids:
        return gaps

    # Find all references to invariants from non-invariant sections
    referenced: set[str] = set()
    for id_value, section in result.sections.items():
        if id_value in invariant_ids:
            continue  # Skip invariants referencing other invariants

        # Find invariant references in this section
        refs = parser.parse_references(section.full_content)
        for ref in refs:
            if ref.id_value in invariant_ids:
                referenced.add(ref.id_value)

    # Invariants not referenced are unsatisfied
    unsatisfied = invariant_ids - referenced
    for inv_id in sorted(unsatisfied):
        # Determine if it's a legacy goal or invariant
        is_goal = inv_id.startswith("G")
        type_name = "goal" if is_goal else "invariant"
        gaps.append(
            {
                "type": "unsatisfied_invariant",
                "id": inv_id,
                "is_legacy_goal": is_goal,
                "description": f"{type_name.title()} {inv_id} has no elements that enforce it",
                "severity": "warning",
            }
        )

    return gaps


def _detect_todos(content: str) -> list[dict[str, Any]]:
    """Find TODO/TBD/FIXME markers in specs."""
    gaps = []
    extractor = SectionExtractor()
    result = extractor.extract(content)

    todo_pattern = re.compile(r"\b(TODO|TBD|FIXME|XXX)[:;]?\s*(.{0,100})", re.IGNORECASE)

    for id_value, section in result.sections.items():
        for match in todo_pattern.finditer(section.body):
            marker = match.group(1).upper()
            context = match.group(2).strip()
            # Truncate context at sentence end or 80 chars
            if "." in context[:80]:
                context = context[: context.index(".") + 1]
            elif len(context) > 80:
                context = context[:77] + "..."

            gaps.append(
                {
                    "type": "todo",
                    "source_id": id_value,
                    "marker": marker,
                    "description": f"{marker} in {id_value}: {context}"
                    if context
                    else f"{marker} marker in {id_value}",
                    "severity": "warning",
                }
            )

    return gaps


def _detect_invalid_libraries(libraries_dir: Path) -> list[dict[str, Any]]:
    """Detect libraries organized by type rather than subsystem/domain."""
    gaps = []

    if not libraries_dir.exists():
        return gaps

    # Patterns that indicate type-based (invalid) organization
    invalid_patterns = [
        (r"^#\s*(?:data\s+)?structures?\s+(?:for|of)\s+", "type_based_data"),
        (r"^#\s*(?:extra\s+)?algorithms?\s+(?:for|of|that)\s+", "type_based_algorithm"),
        (r"^#\s*goals?\s+(?:for|of)\s+", "goals_in_library"),
        (r"^#\s*invariants?\s+(?:for|of)\s+", "invariants_in_library"),
        (r"^#\s*(?:helper|utility|misc|common)\s+", "organizational_bucket"),
    ]

    # Patterns in description that indicate type-based organization
    desc_invalid_patterns = [
        (r"data\s+structures\s+for\s+the\s+", "type_based_data"),
        (r"extra\s+algorithms\s+", "type_based_algorithm"),
        (r"additional\s+(?:data|algorithms)\s+", "organizational_bucket"),
        (r"miscellaneous\s+", "organizational_bucket"),
    ]

    for lib_file in libraries_dir.glob("*.md"):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Check header (first # line)
        header = ""
        description = ""
        for line in lines:
            if line.strip().startswith("# "):
                header = line.strip()
            elif header and line.strip() and not line.strip().startswith("#"):
                description = line.strip()
                break

        # Check header for invalid patterns
        for pattern, issue_type in invalid_patterns:
            if re.search(pattern, header, re.IGNORECASE):
                gaps.append(
                    {
                        "type": "invalid_library",
                        "library": lib_name,
                        "issue": issue_type,
                        "description": f"Library '{lib_name}' is organized by type, not system goal",
                        "header": header,
                        "severity": "warning",
                        "suggestion": "Refactor into domain/subsystem libraries with clear system capabilities",
                    }
                )
                break

        # Check description for invalid patterns
        for pattern, issue_type in desc_invalid_patterns:
            if re.search(pattern, description, re.IGNORECASE):
                # Don't double-report if header already caught
                existing = any(
                    g.get("library") == lib_name and g.get("type") == "invalid_library"
                    for g in gaps
                )
                if not existing:
                    gaps.append(
                        {
                            "type": "invalid_library",
                            "library": lib_name,
                            "issue": issue_type,
                            "description": f"Library '{lib_name}' description suggests type-based organization",
                            "header": header,
                            "severity": "warning",
                            "suggestion": "Refactor into domain/subsystem libraries with clear system capabilities",
                        }
                    )
                break

        # Check if library name suggests type-based organization
        type_based_names = [
            "data",
            "algorithms",
            "goals",
            "invariants",
            "helpers",
            "utils",
            "common",
            "misc",
        ]
        if lib_name.lower() in type_based_names:
            existing = any(
                g.get("library") == lib_name and g.get("type") == "invalid_library" for g in gaps
            )
            if not existing:
                gaps.append(
                    {
                        "type": "invalid_library",
                        "library": lib_name,
                        "issue": "type_based_name",
                        "description": f"Library name '{lib_name}' suggests type-based organization",
                        "severity": "warning",
                        "suggestion": "Rename to describe the subsystem/domain capability, not the content type",
                    }
                )

        # Check if library contains invariants/goals (should be at root level)
        extractor = SectionExtractor()
        result = extractor.extract(content)
        invariant_ids = [id_val for id_val in result.sections if re.match(r"^[GI]\d+", id_val)]
        if invariant_ids:
            gaps.append(
                {
                    "type": "misplaced_invariant",
                    "library": lib_name,
                    "ids": invariant_ids,
                    "description": f"Library '{lib_name}' contains invariants/goals: {', '.join(invariant_ids)}",
                    "severity": "warning",
                    "suggestion": "Move invariants to root-level invariants.md file (not under libraries/)",
                }
            )

    return gaps


def _detect_vague_invariants(content: str) -> list[dict[str, Any]]:
    """Detect invariants that are too vague to verify."""
    gaps = []
    extractor = SectionExtractor()
    result = extractor.extract(content)

    # Patterns that indicate vague/unmeasurable invariants
    vague_patterns = [
        (r"\bshould\s+be\s+(fast|quick|efficient|good|nice|proper)", "subjective_quality"),
        (r"\b(appropriate|reasonable|adequate|sufficient)\b", "subjective_term"),
        (r"\b(some|few|many|several)\s+(?!specific)", "vague_quantity"),
        (r"\bwhen\s+(?:possible|appropriate|needed)", "conditional_vague"),
        (r"\b(?:try|attempt)\s+to\b", "non_committal"),
        (r"\bmight\s+(?:need|require|want)", "uncertain_requirement"),
    ]

    for id_value, section in result.sections.items():
        # Only check invariants (I#) and legacy goals (G#)
        if not re.match(r"^[GI]\d+$", id_value):
            continue

        body = section.body.lower()

        for pattern, issue_type in vague_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                gaps.append(
                    {
                        "type": "vague_invariant",
                        "id": id_value,
                        "issue": issue_type,
                        "matched": match.group(0),
                        "description": f"Invariant {id_value} uses vague/unmeasurable language: '{match.group(0)}'",
                        "severity": "warning",
                        "suggestion": "Replace with measurable criteria (e.g., 'latency < 10ms' instead of 'should be fast')",
                    }
                )
                break  # One issue per invariant is enough

    return gaps


def _detect_cohesion_issues(content: str, registry, libraries_dir: Path) -> list[dict[str, Any]]:
    """Detect subsystem cohesion issues."""
    gaps = []
    parser = AnnotationParser()
    extractor = SectionExtractor()

    if not libraries_dir.exists():
        return gaps

    # Build reference graph: id -> set of ids it references
    reference_graph: dict[str, set[str]] = {}

    # Map id -> library name
    id_to_library: dict[str, str] = {}

    # Process each library file
    for lib_file in libraries_dir.glob("*.md"):
        lib_name = lib_file.stem
        lib_content = lib_file.read_text(encoding="utf-8")
        result = extractor.extract(lib_content)

        for id_value, section in result.sections.items():
            id_to_library[id_value] = lib_name

            # Find references in this section
            refs = parser.parse_references(section.full_content)
            ref_ids = {r.id_value for r in refs}

            # Also find bare ID mentions
            bare_refs = set()
            patterns = [
                r"\bAlgorithm\s+(\d+)\b",
                r"\b(D\d+)\b",
                r"\b(G\d+)\b",
                r"\b(I\d+)\b",
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, section.body):
                    if pattern.startswith(r"\bAlgorithm"):
                        bare_refs.add(f"Algorithm {match.group(1)}")
                    else:
                        bare_refs.add(match.group(1))

            reference_graph[id_value] = ref_ids | bare_refs

    if not id_to_library:
        return gaps

    # Analyze cohesion per library
    libraries: dict[str, set[str]] = {}
    for id_value, lib_name in id_to_library.items():
        libraries.setdefault(lib_name, set()).add(id_value)

    for lib_name, lib_ids in libraries.items():
        if len(lib_ids) < 2:
            continue  # Need at least 2 elements to measure cohesion

        # Count internal vs external references
        internal_refs = 0
        external_refs = 0
        external_targets: dict[str, int] = {}  # library -> count

        for id_value in lib_ids:
            refs = reference_graph.get(id_value, set())
            for ref in refs:
                if ref == id_value:
                    continue  # Skip self-references
                if ref in lib_ids:
                    internal_refs += 1
                else:
                    external_refs += 1
                    ref_lib = id_to_library.get(ref, "unknown")
                    external_targets[ref_lib] = external_targets.get(ref_lib, 0) + 1

        total_refs = internal_refs + external_refs
        if total_refs == 0:
            continue  # No references to analyze

        # Cohesion ratio: internal / total
        cohesion = internal_refs / total_refs if total_refs > 0 else 0

        # Flag low cohesion (less than 30% internal references)
        if cohesion < 0.3 and total_refs >= 3:
            gaps.append(
                {
                    "type": "low_cohesion",
                    "library": lib_name,
                    "cohesion_ratio": round(cohesion, 2),
                    "internal_refs": internal_refs,
                    "external_refs": external_refs,
                    "description": f"Library '{lib_name}' has low internal cohesion ({int(cohesion * 100)}%)",
                    "severity": "info",
                    "suggestion": "Consider splitting library or reorganizing elements by their actual dependencies",
                }
            )

        # Flag high coupling to specific external library (>50% of refs to one other lib)
        for target_lib, count in external_targets.items():
            if target_lib == "unknown":
                continue
            coupling = count / total_refs
            if coupling > 0.5 and count >= 3:
                gaps.append(
                    {
                        "type": "high_coupling",
                        "library": lib_name,
                        "target_library": target_lib,
                        "coupling_ratio": round(coupling, 2),
                        "reference_count": count,
                        "description": f"Library '{lib_name}' is tightly coupled to '{target_lib}' ({int(coupling * 100)}% of refs)",
                        "severity": "info",
                        "suggestion": f"Consider merging '{lib_name}' and '{target_lib}' or refactoring shared concerns",
                    }
                )

    # Detect orphan clusters (elements that reference each other across libraries)
    # Find bidirectional reference pairs across libraries
    cross_lib_clusters: list[tuple[str, str]] = []
    for id_a, refs_a in reference_graph.items():
        lib_a = id_to_library.get(id_a)
        for ref in refs_a:
            lib_b = id_to_library.get(ref)
            if lib_a and lib_b and lib_a != lib_b and id_a in reference_graph.get(ref, set()):
                # Check if ref also references id_a (bidirectional)
                pair = tuple(sorted([id_a, ref]))
                if pair not in cross_lib_clusters:
                    cross_lib_clusters.append(pair)

    for id_a, id_b in cross_lib_clusters:
        lib_a = id_to_library.get(id_a)
        lib_b = id_to_library.get(id_b)
        gaps.append(
            {
                "type": "cross_library_coupling",
                "id_a": id_a,
                "id_b": id_b,
                "library_a": lib_a,
                "library_b": lib_b,
                "description": f"{id_a} ({lib_a}) and {id_b} ({lib_b}) reference each other but are in different libraries",
                "severity": "info",
                "suggestion": "Consider moving to same library if they represent a cohesive subsystem",
            }
        )

    return gaps


def _detect_pin_gaps(content: str, artifact_root: Path | None) -> list[dict[str, Any]]:
    """Detect pin-related gaps:
    - broken_pin: Pin points to non-existent file
    - unpinned_spec: Spec element (Algorithm, D#) has no pins.
    """
    gaps = []
    extractor = SectionExtractor()
    parser = AnnotationParser()
    result = extractor.extract(content)

    # Collect all pins in the content
    all_pins = list(parser.parse_pins(content))
    pinned_sections: set[str] = set()

    # Check each pin for validity
    for pin in all_pins:
        # Find which section this pin belongs to
        for id_value, section in result.sections.items():
            if pin.line_number >= section.start_line:
                # Assume this pin belongs to the nearest preceding section
                pinned_sections.add(id_value)

        # Check if artifact file exists (if artifact_root provided)
        if artifact_root:
            artifact_path = artifact_root / pin.file_path
            if not artifact_path.exists():
                gaps.append(
                    {
                        "type": "broken_pin",
                        "file_path": pin.file_path,
                        "symbol": pin.symbol,
                        "line": pin.line_number,
                        "description": f"Pin target does not exist: {pin.full_location}",
                        "severity": "error",
                    }
                )

    # Check for unpinned implementation specs (Algorithms, D# data structures)
    implementation_patterns = [
        r"^Algorithm \d+$",
        r"^D\d+$",
    ]

    for id_value, _section in result.sections.items():
        is_implementation = any(re.match(pattern, id_value) for pattern in implementation_patterns)
        if is_implementation and id_value not in pinned_sections:
            gaps.append(
                {
                    "type": "unpinned_spec",
                    "id": id_value,
                    "description": f"Spec element {id_value} has no artifact pin",
                    "severity": "info",
                    "suggestion": "Add (@pin path:symbol) to link to implementation",
                }
            )

    return gaps


def format_gaps_md(gaps: list[dict[str, Any]]) -> str:
    """Format gaps as markdown for gaps.md file.

    LEGACY API: This function maintains backward compatibility with dict-based gaps.
    For new code using GapElement objects, use UnifiedGapDetector.format_gaps_md().

    Uses IDs for stable references instead of line numbers which change.
    """
    warnings.warn(
        "format_gaps_md() is deprecated. Use UnifiedGapDetector.format_gaps_md() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    lines = [
        "# Gaps and Proof Obligations",
        "",
        "This file tracks unresolved gaps, ambiguities, and proof obligations.",
        "",
    ]

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for gap in gaps:
        gap_type = gap["type"]
        by_type.setdefault(gap_type, []).append(gap)

    # Error severity first
    severity_order = {"error": 0, "warning": 1, "info": 2}

    for gap_type in sorted(by_type.keys()):
        type_gaps = by_type[gap_type]
        type_gaps.sort(key=lambda g: severity_order.get(g.get("severity", "info"), 2))

        lines.append(f"## {gap_type.replace('_', ' ').title()}")
        lines.append("")

        for gap in type_gaps:
            severity = gap.get("severity", "info")
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(severity, "-")
            lines.append(f"- {icon} {gap['description']}")

            # Prefer ID-based references over line numbers
            if "source_id" in gap:
                lines.append(f"  - In: {gap['source_id']}")
            if "id" in gap:
                lines.append(f"  - ID: {gap['id']}")
            if "target" in gap:
                lines.append(f"  - Target: {gap['target']}")
            if "name" in gap:
                lines.append(f"  - Name: {gap['name']}")
            if "marker" in gap:
                lines.append(f"  - Marker: {gap['marker']}")
            if "library" in gap:
                lines.append(f"  - Library: {gap['library']}")
            # Cohesion analysis fields
            if "cohesion_ratio" in gap:
                lines.append(f"  - Cohesion: {int(gap['cohesion_ratio'] * 100)}%")
            if "coupling_ratio" in gap:
                lines.append(f"  - Coupling: {int(gap['coupling_ratio'] * 100)}%")
            if "target_library" in gap:
                lines.append(f"  - Target Library: {gap['target_library']}")
            if "id_a" in gap and "id_b" in gap:
                lines.append(f"  - Elements: {gap['id_a']} <-> {gap['id_b']}")
            if "library_a" in gap and "library_b" in gap:
                lines.append(f"  - Libraries: {gap['library_a']} / {gap['library_b']}")
            if "suggestion" in gap:
                lines.append(f"  - Suggestion: {gap['suggestion']}")
            if gap.get("is_legacy_goal"):
                lines.append("  - Note: Consider migrating G# to I# (invariant)")
            lines.append("")

    if not gaps:
        lines.append("*No gaps detected.*")

    return "\n".join(lines)
