# Phase D: Evidence Extraction + Gap Synthesis

## Overview

**CRITICAL DESIGN CHANGE**: Gap is a **first-class spec element**, not a taxonomy of "gap types".

The gen3 rag scripts produce **evidence** (findings, violations, issues). Gaps are **synthesized** from evidence by clustering related issues. This separates detection from classification.

The scripts are in `/mnt/c/Users/xteam/IdeaProjects/ai-workflow/.tasks/plans/gen3 rag/scripts/`

## Design Principles

1. **Scripts produce GapEvidence** - each detector outputs evidence objects, not "gap types"
2. **Gap synthesis clusters evidence** - related evidence becomes a single GapElement
3. **GapElement is first-class** - unit_type=GAP, with ID like GAP-0001
4. **No hardcoded labels** - we don't scan for "dragon" or "GAP-P#.#"
5. **Invariant-driven detection** - evidence comes from violations, not pattern matching

## Scripts → Evidence Mapping

### Staging Phase (Format Compliance Evidence)

| Script | Evidence Category | Priority |
|--------|-------------------|----------|
| `lint_patterns.py` | format_violation | High |
| `check_duplicate_declarations.py` | duplicate_declaration | High |
| `find_headers_missing_declarations.py` | missing_declaration | Medium |
| `find_duplicate_headers.py` | duplicate_header | Medium |
| `find_references.py` | unannotated_reference | Medium |
| `find_undefined_functions.py` | undefined_function | High |

### Planning Phase (Coverage Evidence)

| Script | Evidence Category | Priority |
|--------|-------------------|----------|
| `compare_ids.py` | coverage_violation (missing_in_plan, missing_in_library) | High |
| `find_missing.py` | unassigned_content | Medium |
| `find_missing_assignments.py` | missing_assignment | Medium |
| `check_sequences.py` | sequence_violation (duplicate, hole, conflict) | High |

### Verification Phase (Content Evidence)

| Script | Evidence Category | Priority |
|--------|-------------------|----------|
| `verify_content.py` | content_mismatch | High |
| `detect_duplicates_conflicts.py` | cross_library_duplicate | Medium |
| `find_empty_stubs.py` | empty_stub | Medium |
| `find_unique_library_lines.py` | library_only_content | Low (info) |

## Implementation Strategy

Rather than importing the scripts directly (they're standalone), we'll extract the core logic into evidence extractors, then synthesize gaps.

### File: `spec_manager/core/gaps.py` (Enhanced)

```python
"""
Enhanced gap detection using evidence extraction + gap synthesis.

CRITICAL: Gap is a FIRST-CLASS spec element.
- Detectors produce GapEvidence objects (findings)
- Gaps are synthesized by clustering related evidence
- GapElement has unit_type=GAP, ID like GAP-0001

Evidence categories (invariant-driven):
- Coverage: unaccounted atoms, membership failures
- Format: pattern violations, duplicates, missing annotations
- Sequence: duplicate IDs, holes, conflicts
- Content: plan/library drift, content mismatches
- Proof: broken Algorithm→Claim→Proof→Lean chains
- Uncertainty: sorry, TODO, ?, hedging markers
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .annotations import AnnotationParser, AnnotationType
from .ids import IdValidator, IdCategory


# =============================================================================
# Evidence Data Structures (Detector Output)
# =============================================================================

class Severity(Enum):
    """Severity levels for evidence and gaps."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class GapEvidence:
    """
    Evidence produced by a detector - NOT a gap itself.
    Gaps are synthesized by clustering evidence.

    This replaces the old "Gap" class with gap_type.
    """
    severity: Severity          # error, warning, info
    message: str                # Human-readable description
    location: str               # Where found (file:line)
    element_id: str | None = None  # Related element ID
    detector: str = ""          # Which detector found this
    details: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# BACKWARD COMPATIBILITY (Internal consistency fix)
# =============================================================================
# Old code used Gap(gap_type=..., severity=...) - provide compatibility wrapper

@dataclass
class Gap:
    """
    DEPRECATED: Use GapEvidence instead.

    This wrapper exists for backward compatibility with old code patterns.
    Maps gap_type to detector, normalizes severity to Severity enum.
    """
    gap_type: str               # Maps to detector field
    severity: str               # "error", "warning", "info"
    message: str
    location: str
    element_id: str | None = None
    suggestion: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_evidence(self) -> GapEvidence:
        """Convert to GapEvidence."""
        sev_map = {'error': Severity.ERROR, 'warning': Severity.WARNING, 'info': Severity.INFO}
        return GapEvidence(
            severity=sev_map.get(self.severity.lower(), Severity.INFO),
            message=self.message,
            location=self.location,
            element_id=self.element_id,
            detector=self.gap_type,
            details={**self.details, 'suggestion': self.suggestion} if self.suggestion else self.details
        )


def normalize_to_evidence(gaps: list[Gap | GapEvidence]) -> list[GapEvidence]:
    """Convert mixed Gap/GapEvidence lists to uniform GapEvidence list."""
    result = []
    for g in gaps:
        if isinstance(g, Gap):
            result.append(g.to_evidence())
        else:
            result.append(g)
    return result


# =============================================================================
# Gap Element (First-Class, Synthesized)
# =============================================================================

@dataclass
class GapElement:
    """
    A synthesized gap - first-class spec element.
    Multiple evidence objects cluster into a single gap.

    This is a UnitType.GAP element, written to gaps.md with ID like GAP-0001.
    """
    id: str                     # e.g., GAP-0001
    severity: Severity          # Highest severity from evidence
    summary: str                # What's wrong (synthesized from evidence)
    affects: list[str]          # Element IDs and/or source refs
    evidence: list[GapEvidence] # All evidence supporting this gap
    patch_origin: str | None = None  # Which patch introduced this (if known)


# Backward compatibility alias
Gap = GapEvidence  # Detectors can still use Gap, it's now GapEvidence


# =============================================================================
# Format Compliance (from lint_patterns.py)
# =============================================================================

class FormatComplianceDetector:
    """
    Detects format violations - patterns that don't match canonical forms.

    Based on lint_patterns.py from gen3 rag scripts.
    """

    # Canonical patterns
    PATTERNS = {
        'goal': re.compile(r'^G([1-9]|[1-4]\d|50)$'),  # G1-G50
        'invariant': re.compile(r'^P\d+I\d+$'),         # P#I#
        'claim': re.compile(r'^P\d+C\d+$'),             # P#C#
        'algorithm': re.compile(r'^Algorithm \d+$'),    # Algorithm #
        'math': re.compile(r'^P\d+\.\d+$'),             # P#.#
        'lean': re.compile(r'^Lean\d+$'),               # Lean#
        'data': re.compile(r'^D\d+$'),                  # D#
    }

    # Legacy patterns to flag
    LEGACY_PATTERNS = [
        (re.compile(r'^I\d+$'), 'Use P#I# for invariants, not I#'),
        (re.compile(r'^P\d+\.M\d+$'), 'Use P#.# for math sections, not P#.M#'),
        (re.compile(r'^Algorithm P\d+\.\d+$'), 'Use "Algorithm #" not "Algorithm P#.#"'),
        (re.compile(r'^Track [AB]'), 'Legacy track format - use Lean#'),
        (re.compile(r'^Lean [AB]'), 'Legacy lean format - use Lean#'),
    ]

    def detect(self, content: str, file_path: str) -> list[Gap]:
        """Detect format violations in content."""
        gaps = []

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Check for legacy patterns
            for pattern, message in self.LEGACY_PATTERNS:
                if pattern.search(line):
                    gaps.append(Gap(
                        gap_type='format_violation',
                        severity='warning',
                        message=message,
                        location=f"{file_path}:{line_num}",
                        details={'line': line.strip(), 'pattern': pattern.pattern}
                    ))

            # Check for unescaped LaTeX
            if re.search(r'(?<!\\)\$[^$]+\$', line):
                # Could be intentional, so just info
                if '\\' not in line:
                    gaps.append(Gap(
                        gap_type='format_violation',
                        severity='info',
                        message='Possible unescaped LaTeX',
                        location=f"{file_path}:{line_num}",
                        details={'line': line.strip()}
                    ))

        return gaps


# =============================================================================
# Duplicate Detection (from check_duplicate_declarations.py)
# =============================================================================

class DuplicateDetector:
    """
    Detects duplicate declarations and headers.

    Based on check_duplicate_declarations.py and find_duplicate_headers.py.
    """

    def detect_duplicate_declarations(
        self,
        content: str,
        file_path: str
    ) -> list[Gap]:
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
                gaps.append(Gap(
                    gap_type='duplicate_declaration',
                    severity='error',
                    message=f"ID '{id_value}' declared {len(lines)} times",
                    location=file_path,
                    element_id=id_value,
                    suggestion='Remove duplicate declarations',
                    details={'lines': lines}
                ))

        return gaps

    def detect_duplicate_headers(
        self,
        content: str,
        file_path: str
    ) -> list[Gap]:
        """Find exact and near-duplicate headers."""
        gaps = []

        # Extract headers
        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        headers: dict[str, list[tuple[int, str]]] = defaultdict(list)

        for match in header_pattern.finditer(content):
            line_num = content[:match.start()].count('\n') + 1
            level = len(match.group(1))
            text = match.group(2).strip()

            # Normalize for comparison
            normalized = re.sub(r'\s+', ' ', text.lower())
            normalized = re.sub(r'[^\w\s]', '', normalized)

            headers[normalized].append((line_num, text))

        # Flag duplicates
        for normalized, occurrences in headers.items():
            if len(occurrences) > 1:
                # Check if exact duplicates or near-duplicates
                texts = [t for _, t in occurrences]
                if len(set(texts)) == 1:
                    severity = 'error'
                    msg = f"Exact duplicate header: '{texts[0]}'"
                else:
                    severity = 'warning'
                    msg = f"Near-duplicate headers: {texts}"

                gaps.append(Gap(
                    gap_type='duplicate_header',
                    severity=severity,
                    message=msg,
                    location=file_path,
                    details={
                        'lines': [l for l, _ in occurrences],
                        'texts': texts
                    }
                ))

        return gaps


# =============================================================================
# Undefined Functions (from find_undefined_functions.py)
# =============================================================================

class UndefinedFunctionDetector:
    """
    Detects function calls in pseudocode without definitions.

    Based on find_undefined_functions.py.

    Gap 12 fix: Word lists are configurable via YAML and treated as WEAK EVIDENCE,
    not definitive failure conditions.
    """

    # DEFAULT Built-in functions to ignore - CONFIGURABLE VIA YAML (Gap 12 fix)
    DEFAULT_BUILTINS = {
        'if', 'else', 'for', 'while', 'return', 'break', 'continue',
        'true', 'false', 'null', 'none', 'and', 'or', 'not',
        'min', 'max', 'abs', 'len', 'sum', 'range', 'enumerate',
        'append', 'extend', 'insert', 'remove', 'pop', 'clear',
        'get', 'set', 'keys', 'values', 'items',
        'print', 'log', 'error', 'warn', 'debug',
    }

    # DEFAULT Categories for undefined functions - CONFIGURABLE VIA YAML (Gap 12 fix)
    DEFAULT_CATEGORIES = {
        'PATTERN_': 'PATTERN',
        'FIELD_': 'FIELD',
        'EMBED_': 'EMBED',
        'GRAPH_': 'GRAPH',
        'PARSE_': 'PARSE',
        'WORKSPACE_': 'WORKSPACE',
        'HYPOTHESIS_': 'HYPOTHESIS',
        'INDEX_': 'INDEX',
        'STATE_': 'STATE',
    }

    def __init__(self, config_path: Path | None = None):
        """
        Initialize detector with optional config.

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

            if 'undefined_functions' in config:
                uf_config = config['undefined_functions']

                # Load builtins (additive)
                if 'builtins' in uf_config:
                    self.builtins.update(uf_config['builtins'])

                # Load categories (additive)
                if 'categories' in uf_config:
                    self.categories.update(uf_config['categories'])

                # Load exclusions (remove from builtins)
                if 'exclude_builtins' in uf_config:
                    self.builtins -= set(uf_config['exclude_builtins'])

        except Exception as e:
            # Config load failure is non-fatal - use defaults
            pass

    def detect(
        self,
        content: str,
        file_path: str
    ) -> list[GapEvidence]:
        """
        Detect undefined function calls in pseudocode.

        Gap 12 fix: Detections are WEAK EVIDENCE (confidence-weighted),
        not definitive failure conditions.
        """
        evidence = []

        # Find all pseudocode blocks
        pseudo_pattern = re.compile(r'```pseudo\n(.*?)```', re.DOTALL)

        # Extract function definitions
        definitions = set()
        def_pattern = re.compile(r'function\s+(\w+)\s*\(')
        for match in def_pattern.finditer(content):
            definitions.add(match.group(1).upper())

        # Also treat Algorithm headers as definitions
        alg_pattern = re.compile(r'^##\s+Algorithm\s+\d+[:\s]+(\w+)', re.MULTILINE)
        for match in alg_pattern.finditer(content):
            definitions.add(match.group(1).upper())

        # Find all function calls in pseudo blocks
        call_pattern = re.compile(r'\b([A-Z][A-Z_0-9]+)\s*\(')
        calls: dict[str, list[int]] = defaultdict(list)

        for block_match in pseudo_pattern.finditer(content):
            block_start = content[:block_match.start()].count('\n') + 1
            block_content = block_match.group(1)

            for call_match in call_pattern.finditer(block_content):
                func_name = call_match.group(1)
                line_in_block = block_content[:call_match.start()].count('\n')
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
            category = 'OTHER'
            for prefix, cat in self.categories.items():
                if func_name.startswith(prefix):
                    category = cat
                    break

            # Gap 12: Confidence is lower for unknown categories (may be external)
            confidence = 0.8 if category != 'OTHER' else 0.5

            evidence.append(GapEvidence(
                severity=Severity.WARNING,
                message=f"Undefined function: {func_name}",
                location=file_path,
                element_id=None,
                detector="undefined_function",
                details={
                    'function': func_name,
                    'category': category,
                    'call_lines': lines,
                    'call_count': len(lines),
                    'confidence': confidence,  # Gap 12: weak evidence
                    'suggestion': f"Define {func_name} or mark as external dependency"
                }
            ))

        return evidence


# =============================================================================
# Sequence Analysis (from check_sequences.py)
# =============================================================================

class SequenceAnalyzer:
    """
    Analyzes numbered sequences for duplicates, holes, and conflicts.

    Based on check_sequences.py.
    """

    def detect(
        self,
        content: str,
        file_path: str
    ) -> list[Gap]:
        """Detect sequence issues."""
        gaps = []

        # Analyze different sequence types
        gaps.extend(self._analyze_algorithms(content, file_path))
        gaps.extend(self._analyze_goals(content, file_path))
        gaps.extend(self._analyze_data_structures(content, file_path))

        return gaps

    def _analyze_algorithms(
        self,
        content: str,
        file_path: str
    ) -> list[Gap]:
        """Analyze Algorithm # sequence."""
        gaps = []
        pattern = re.compile(r'^##\s+Algorithm\s+(\d+)', re.MULTILINE)

        numbers: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for match in pattern.finditer(content):
            num = int(match.group(1))
            line = content[:match.start()].count('\n') + 1
            # Get a preview of the section
            preview = content[match.start():match.start()+200].split('\n')[0]
            numbers[num].append((line, preview))

        # Check for duplicates
        for num, occurrences in numbers.items():
            if len(occurrences) > 1:
                # Check if same content (true duplicate) or different (conflict)
                previews = [p for _, p in occurrences]
                if len(set(previews)) == 1:
                    severity = 'warning'
                    msg = f"Duplicate Algorithm {num} (same content)"
                else:
                    severity = 'error'
                    msg = f"Conflicting Algorithm {num} (different content)"

                gaps.append(Gap(
                    gap_type='duplicate_id' if len(set(previews)) == 1 else 'conflict',
                    severity=severity,
                    message=msg,
                    location=file_path,
                    element_id=f"Algorithm {num}",
                    details={
                        'lines': [l for l, _ in occurrences],
                        'previews': previews
                    }
                ))

        # Check for holes (if we have enough for a sequence)
        if len(numbers) > 3:
            all_nums = sorted(numbers.keys())
            expected = set(range(min(all_nums), max(all_nums) + 1))
            holes = expected - set(all_nums)

            if holes and len(holes) < len(all_nums):  # Some holes, not mostly holes
                gaps.append(Gap(
                    gap_type='sequence_hole',
                    severity='info',
                    message=f"Algorithm sequence has holes: {sorted(holes)}",
                    location=file_path,
                    details={'missing': sorted(holes)}
                ))

        return gaps

    def _analyze_goals(self, content: str, file_path: str) -> list[Gap]:
        """Analyze G# sequence."""
        # Similar to algorithms
        gaps = []
        pattern = re.compile(r'\bG(\d+)\b')

        numbers: dict[int, int] = defaultdict(int)
        for match in pattern.finditer(content):
            numbers[int(match.group(1))] += 1

        # Goals should be G1-G50
        out_of_range = [n for n in numbers if n < 1 or n > 50]
        if out_of_range:
            gaps.append(Gap(
                gap_type='format_violation',
                severity='warning',
                message=f"Goals out of range (should be G1-G50): {out_of_range}",
                location=file_path,
                details={'out_of_range': out_of_range}
            ))

        return gaps

    def _analyze_data_structures(self, content: str, file_path: str) -> list[Gap]:
        """Analyze D# sequence."""
        gaps = []
        pattern = re.compile(r'^##\s+(D\d+)', re.MULTILINE)

        ids: dict[str, list[int]] = defaultdict(list)
        for match in pattern.finditer(content):
            id_value = match.group(1)
            line = content[:match.start()].count('\n') + 1
            ids[id_value].append(line)

        for id_value, lines in ids.items():
            if len(lines) > 1:
                gaps.append(Gap(
                    gap_type='duplicate_id',
                    severity='warning',
                    message=f"Duplicate data structure: {id_value}",
                    location=file_path,
                    element_id=id_value,
                    details={'lines': lines}
                ))

        return gaps


# =============================================================================
# Content Verification (from verify_content.py)
# =============================================================================

class ContentVerifier:
    """
    Verifies content matches between plan.md and libraries.

    Based on verify_content.py.
    """

    def verify(
        self,
        plan_content: str,
        library_content: str,
        library_name: str
    ) -> list[Gap]:
        """Compare content between plan and library."""
        gaps = []
        parser = AnnotationParser()

        # Extract sections from both
        plan_sections = self._extract_sections(plan_content)
        library_sections = self._extract_sections(library_content)

        plan_ids = set(plan_sections.keys())
        library_ids = set(library_sections.keys())

        # Missing in library
        for id_value in plan_ids - library_ids:
            gaps.append(Gap(
                gap_type='missing_in_library',
                severity='warning',
                message=f"'{id_value}' in plan but not in library",
                location=library_name,
                element_id=id_value,
                suggestion=f"Add {id_value} to {library_name}"
            ))

        # Missing in plan
        for id_value in library_ids - plan_ids:
            gaps.append(Gap(
                gap_type='missing_in_plan',
                severity='info',
                message=f"'{id_value}' in library but not in plan",
                location=library_name,
                element_id=id_value
            ))

        # Content mismatches
        for id_value in plan_ids & library_ids:
            plan_body = plan_sections[id_value]
            lib_body = library_sections[id_value]

            similarity = SequenceMatcher(
                None,
                self._normalize(plan_body),
                self._normalize(lib_body)
            ).ratio()

            if similarity < 0.95:
                if similarity < 0.5:
                    severity = 'error'
                elif similarity < 0.8:
                    severity = 'warning'
                else:
                    severity = 'info'

                gaps.append(Gap(
                    gap_type='content_mismatch',
                    severity=severity,
                    message=f"'{id_value}' content differs ({similarity:.0%} similar)",
                    location=library_name,
                    element_id=id_value,
                    details={
                        'similarity': similarity,
                        'plan_length': len(plan_body),
                        'library_length': len(lib_body)
                    }
                ))

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
                    sections[current_id] = '\n'.join(current_lines)
                current_id = decl
                current_lines = [line]
            elif current_id:
                current_lines.append(line)

        if current_id:
            sections[current_id] = '\n'.join(current_lines)

        return sections

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        return ' '.join(text.lower().split())


# =============================================================================
# Proof Chain Detection (with LLM inference for prose)
# =============================================================================

class ProofChainDetector:
    """
    Detects broken proof chains: Algorithm→Claim→Proof→Lean.

    CRITICAL: In messy states, claims/proofs may exist only as prose fragments.
    This detector uses:
    1. Structure when present (IDs, math sections, Lean blocks)
    2. LLM inference when structure is absent

    Output is grouped by patch (which patch introduced broken chains).
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def detect(self, content: str, file_path: str) -> list[GapEvidence]:
        """
        Detect broken proof chains.

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
        pattern = re.compile(r'^##\s+(Algorithm\s+\d+).*?\n(.*?)(?=^##\s|\Z)', re.MULTILINE | re.DOTALL)
        for match in pattern.finditer(content):
            algorithms[match.group(1)] = match.group(2)
        return algorithms

    def _extract_claims(self, content: str) -> dict[str, str]:
        """Extract Claim sections (C#, P#C#)."""
        claims = {}
        # Direct claims
        pattern = re.compile(r'\(\[=(P?\d*C\d+)\]\)', re.MULTILINE)
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
        pattern = re.compile(r'^###\s+Proof\s+Sketch\s*\(?([^)]*)\)?\s*\n(.*?)(?=^###\s|\Z)', re.MULTILINE | re.DOTALL | re.IGNORECASE)
        for match in pattern.finditer(content):
            proof_id = match.group(1).strip() or f"proof_{len(proofs)}"
            proofs[proof_id] = match.group(2)
        return proofs

    def _extract_lean(self, content: str) -> list[str]:
        """Extract Lean code blocks."""
        pattern = re.compile(r'```lean[4]?\n(.*?)```', re.DOTALL)
        return [match.group(1) for match in pattern.finditer(content)]

    def _check_algorithm_chain(
        self,
        alg_id: str,
        alg_content: str,
        claims: dict[str, str],
        proofs: dict[str, str],
        lean_blocks: list[str],
        full_content: str,
        file_path: str
    ) -> list[GapEvidence]:
        """Check proof chain for a single algorithm."""
        evidence = []

        # Look for claim references in algorithm
        claim_refs = re.findall(r'\(@\[\+?(P?\d*C\d+)\]\)', alg_content)
        claim_refs.extend(re.findall(r'\b(P?\d*C\d+)\b', alg_content))

        if not claim_refs:
            # No explicit claims - try LLM inference for prose-based claims
            if self._llm:
                inferred_claims = self._infer_claims_from_prose(alg_content)
                if inferred_claims:
                    evidence.append(GapEvidence(
                        severity=Severity.WARNING,
                        message=f"{alg_id} has no explicit claim references, but LLM infers possible claims",
                        location=file_path,
                        element_id=alg_id,
                        detector="proof_chain",
                        details={'inferred_claims': inferred_claims, 'method': 'llm_inference'}
                    ))
                else:
                    evidence.append(GapEvidence(
                        severity=Severity.WARNING,
                        message=f"{alg_id} has no claims (explicit or inferred)",
                        location=file_path,
                        element_id=alg_id,
                        detector="proof_chain"
                    ))
            else:
                evidence.append(GapEvidence(
                    severity=Severity.WARNING,
                    message=f"{alg_id} has no claim references",
                    location=file_path,
                    element_id=alg_id,
                    detector="proof_chain"
                ))
            return evidence

        # Check each referenced claim
        for claim_id in set(claim_refs):
            if claim_id not in claims:
                # Claim referenced but not defined - try LLM inference
                if self._llm:
                    prose_claim = self._find_prose_claim(claim_id, full_content)
                    if prose_claim:
                        evidence.append(GapEvidence(
                            severity=Severity.INFO,
                            message=f"{claim_id} may exist as prose (LLM inferred)",
                            location=file_path,
                            element_id=claim_id,
                            detector="proof_chain",
                            details={'prose_location': prose_claim, 'method': 'llm_inference'}
                        ))
                    else:
                        evidence.append(GapEvidence(
                            severity=Severity.WARNING,
                            message=f"{alg_id} references undefined claim {claim_id}",
                            location=file_path,
                            element_id=alg_id,
                            detector="proof_chain"
                        ))
                else:
                    evidence.append(GapEvidence(
                        severity=Severity.WARNING,
                        message=f"{alg_id} references undefined claim {claim_id}",
                        location=file_path,
                        element_id=alg_id,
                        detector="proof_chain"
                    ))
                continue

            # Claim exists - check for proof
            claim_content = claims[claim_id]
            has_proof = any(claim_id in p or claim_content[:50] in p for p in proofs.values())
            has_math = bool(re.search(r'P\d+\.\d+', claim_content))

            if not has_proof and not has_math:
                # Try LLM inference for prose-based proof
                if self._llm:
                    prose_proof = self._find_prose_proof(claim_id, full_content)
                    if prose_proof:
                        evidence.append(GapEvidence(
                            severity=Severity.INFO,
                            message=f"{claim_id} may have prose proof sketch (LLM inferred)",
                            location=file_path,
                            element_id=claim_id,
                            detector="proof_chain",
                            details={'prose_proof': prose_proof, 'method': 'llm_inference'}
                        ))
                    else:
                        evidence.append(GapEvidence(
                            severity=Severity.WARNING,
                            message=f"{claim_id} has no proof sketch or math section",
                            location=file_path,
                            element_id=claim_id,
                            detector="proof_chain"
                        ))
                else:
                    evidence.append(GapEvidence(
                        severity=Severity.WARNING,
                        message=f"{claim_id} has no proof sketch or math section",
                        location=file_path,
                        element_id=claim_id,
                        detector="proof_chain"
                    ))

        # Check for Lean skeletons
        if not lean_blocks:
            # All algorithms flagged non-authoritative
            evidence.append(GapEvidence(
                severity=Severity.INFO,
                message=f"{alg_id} has no Lean skeleton (flagged non-authoritative)",
                location=file_path,
                element_id=alg_id,
                detector="proof_chain",
                details={'non_authoritative': True}
            ))

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
        except:
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
        except:
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
        except:
            return None


# =============================================================================
# PROSE FRAGMENT INFERENCE DETECTION (Gap 6 fix)
# =============================================================================

class ProseFragmentInferenceDetector:
    """
    FIRST-CLASS inference detector for requirements/claims hidden in prose.

    This is NOT an afterthought - it's a primary detection method for messy inputs
    where meaning is scattered across prose fragments rather than structured elements.

    Outputs GapEvidence with confidence scores, linking back to source text.
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def detect(self, content: str, file_path: str) -> list[GapEvidence]:
        """
        Detect candidate requirements/claims in prose fragments.

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
        import re

        # Split by code blocks
        parts = re.split(r'```[\s\S]*?```', content)

        for i, part in enumerate(parts):
            # Skip if it's mostly headers/structured content
            lines = part.strip().split('\n')
            prose_lines = [l for l in lines if not l.startswith('#') and l.strip()]

            if len(prose_lines) >= 3:  # At least 3 prose lines
                start_line = content[:content.find(part)].count('\n') + 1
                sections.append({
                    'content': '\n'.join(prose_lines),
                    'start_line': start_line,
                    'end_line': start_line + len(prose_lines)
                })

        return sections

    def _detect_requirement_patterns(self, section: dict, file_path: str) -> list[GapEvidence]:
        """Detect requirement-like patterns in prose."""
        evidence = []
        import re

        # Requirement indicators
        patterns = [
            (r'\b(must|shall|should|will)\s+(\w+)', 0.8, 'modal_verb'),
            (r'\b(required|mandatory|necessary)\b', 0.7, 'requirement_keyword'),
            (r'\b(ensure|guarantee|maintain)\s+that\b', 0.75, 'assurance_verb'),
            (r'\b(always|never)\s+(\w+)', 0.6, 'absolute_adverb'),
        ]

        for pattern, base_confidence, pattern_type in patterns:
            for match in re.finditer(pattern, section['content'], re.IGNORECASE):
                # Get context around match
                start = max(0, match.start() - 50)
                end = min(len(section['content']), match.end() + 100)
                context = section['content'][start:end]

                evidence.append(GapEvidence(
                    severity=Severity.INFO,
                    message=f"Candidate requirement in prose: '{match.group(0)}...'",
                    location=f"{file_path}:{section['start_line']}",
                    element_id=None,  # Not yet promoted to element
                    detector="prose_fragment_inference",
                    details={
                        'pattern_type': pattern_type,
                        'confidence': base_confidence,
                        'matched_text': match.group(0),
                        'context': context,
                        'can_promote': True,  # Flag for strategy to promote
                        'method': 'pattern_match'
                    }
                ))

        return evidence

    def _detect_claim_patterns(self, section: dict, file_path: str) -> list[GapEvidence]:
        """Detect claim-like patterns in prose."""
        evidence = []
        import re

        # Claim indicators
        patterns = [
            (r'\b(converges?|stable|bounded)\b', 0.7, 'convergence_claim'),
            (r'\b(correct|sound|complete)\b', 0.65, 'correctness_claim'),
            (r'\b(invariant|preserved|maintained)\b', 0.75, 'invariant_claim'),
            (r'\b(theorem|lemma|proposition)\b', 0.85, 'formal_claim'),
        ]

        for pattern, base_confidence, pattern_type in patterns:
            for match in re.finditer(pattern, section['content'], re.IGNORECASE):
                start = max(0, match.start() - 50)
                end = min(len(section['content']), match.end() + 100)
                context = section['content'][start:end]

                evidence.append(GapEvidence(
                    severity=Severity.INFO,
                    message=f"Candidate claim in prose: '{match.group(0)}...'",
                    location=f"{file_path}:{section['start_line']}",
                    element_id=None,
                    detector="prose_fragment_inference",
                    details={
                        'pattern_type': pattern_type,
                        'confidence': base_confidence,
                        'matched_text': match.group(0),
                        'context': context,
                        'can_promote': True,
                        'method': 'pattern_match'
                    }
                ))

        return evidence

    def _infer_via_llm(self, section: dict, file_path: str) -> list[GapEvidence]:
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
{section['content'][:1500]}

Output as JSON list: [{{"type": "...", "confidence": 0.X, "text": "...", "structured_form": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json
            findings = json.loads(response)

            for finding in findings:
                evidence.append(GapEvidence(
                    severity=Severity.INFO,
                    message=f"LLM-inferred {finding['type']}: {finding['text'][:50]}...",
                    location=f"{file_path}:{section['start_line']}",
                    element_id=None,
                    detector="prose_fragment_inference",
                    details={
                        'pattern_type': f"llm_inferred_{finding['type']}",
                        'confidence': finding['confidence'],
                        'matched_text': finding['text'],
                        'structured_form': finding.get('structured_form'),
                        'can_promote': finding['confidence'] >= 0.7,
                        'method': 'llm_inference'
                    }
                ))
        except Exception:
            pass  # LLM failures are non-fatal

        return evidence


class InferredClaimPromotionStrategy:
    """
    Strategy to promote high-confidence inferred claims to structured elements.

    This pairs with ProseFragmentInferenceDetector - detects → evidence → promotes.
    """

    def should_apply(self, evidence: list[GapEvidence]) -> bool:
        """Check if there are promotable inferences."""
        return any(
            e.detector == "prose_fragment_inference" and
            e.details.get('can_promote', False) and
            e.details.get('confidence', 0) >= 0.7
            for e in evidence
        )

    def apply(self, evidence: list[GapEvidence], units: list) -> list:
        """
        Promote high-confidence inferences to structured elements.

        Returns new TrackedUnits for promoted elements.
        """
        new_units = []

        for e in evidence:
            if e.detector != "prose_fragment_inference":
                continue
            if not e.details.get('can_promote', False):
                continue
            if e.details.get('confidence', 0) < 0.7:
                continue

            # Create new unit based on pattern type
            pattern_type = e.details.get('pattern_type', '')

            if 'requirement' in pattern_type or 'modal_verb' in pattern_type:
                # Promote to requirement/goal
                unit_id = f"InferredReq_{len(new_units)+1}"
                content = e.details.get('structured_form') or e.details.get('context', '')

                new_units.append({
                    'id': unit_id,
                    'content': content,
                    'unit_type': 'goal',  # Requirements become goals
                    'source': e.location,
                    'introduced_by': 'inference',
                    'confidence': e.details['confidence'],
                    'provenance': {
                        'method': e.details.get('method'),
                        'original_text': e.details.get('matched_text'),
                        'detector': 'prose_fragment_inference'
                    }
                })

            elif 'claim' in pattern_type or 'invariant' in pattern_type:
                # Promote to claim/invariant
                unit_id = f"InferredClaim_{len(new_units)+1}"
                content = e.details.get('structured_form') or e.details.get('context', '')

                new_units.append({
                    'id': unit_id,
                    'content': content,
                    'unit_type': 'claim',
                    'source': e.location,
                    'introduced_by': 'inference',
                    'confidence': e.details['confidence'],
                    'provenance': {
                        'method': e.details.get('method'),
                        'original_text': e.details.get('matched_text'),
                        'detector': 'prose_fragment_inference'
                    }
                })

        return new_units


# =============================================================================
# Uncertainty Detection (new)
# =============================================================================

class UncertaintyDetector:
    """Detects unresolved uncertainty markers in content."""

    UNCERTAINTY_PATTERNS = [
        (re.compile(r'\?(?:\s|$)', re.MULTILINE), 'question'),
        (re.compile(r'\bTODO\b', re.IGNORECASE), 'todo'),
        (re.compile(r'\bTBD\b', re.IGNORECASE), 'tbd'),
        (re.compile(r'\bFIXME\b', re.IGNORECASE), 'fixme'),
        (re.compile(r'\bXXX\b'), 'xxx'),
        (re.compile(r'\bsorry\b'), 'lean_sorry'),  # Lean proof incomplete
        (re.compile(r'\bmay\s+need\b', re.IGNORECASE), 'hedging'),
        (re.compile(r'\bpossibly\b', re.IGNORECASE), 'hedging'),
        (re.compile(r'\bunclear\b', re.IGNORECASE), 'unclear'),
    ]

    def detect(self, content: str, file_path: str) -> list[Gap]:
        """Detect uncertainty markers."""
        gaps = []

        for pattern, marker_type in self.UNCERTAINTY_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                line = content.splitlines()[line_num - 1] if line_num <= len(content.splitlines()) else ""

                # Skip if in code block (except sorry in lean)
                if marker_type != 'lean_sorry' and self._in_code_block(content, match.start()):
                    continue

                severity = 'warning' if marker_type in ('todo', 'lean_sorry') else 'info'

                gaps.append(Gap(
                    gap_type='unresolved_uncertainty',
                    severity=severity,
                    message=f"Unresolved {marker_type}: {line.strip()[:50]}...",
                    location=f"{file_path}:{line_num}",
                    details={
                        'marker_type': marker_type,
                        'line': line.strip()
                    }
                ))

        return gaps

    def _in_code_block(self, content: str, position: int) -> bool:
        """Check if position is inside a code block."""
        before = content[:position]
        opens = before.count('```')
        return opens % 2 == 1  # Odd number means inside block


# =============================================================================
# STRUCTURAL HEALTH DETECTORS (Gap 7 fix)
# =============================================================================

class StructuralHealthDetector:
    """
    Detects structural health issues: coupling, cohesion, relations, underspecified elements.

    These are the "newer gaps.md" style diagnostics that must be preserved while
    also adding completeness/proof-obligation tracking.

    Gap 7 fix: Ensure these remain as evidence extractors, not just formatting buckets.
    """

    def detect(self, units: list, libraries: dict[str, list[str]] = None) -> list[GapEvidence]:
        """
        Run all structural health checks.

        Args:
            units: List of TrackedUnit objects
            libraries: Optional mapping of library_name → element_ids
        """
        evidence = []

        evidence.extend(self._detect_coupling_issues(units, libraries))
        evidence.extend(self._detect_cohesion_issues(units, libraries))
        evidence.extend(self._detect_missing_relations(units))
        evidence.extend(self._detect_underspecified_elements(units))
        evidence.extend(self._detect_unpinned_elements(units))
        evidence.extend(self._detect_unsatisfied_invariants(units))

        return evidence

    def _detect_coupling_issues(self, units: list, libraries: dict[str, list[str]] = None) -> list[GapEvidence]:
        """Detect excessive coupling between elements/libraries."""
        evidence = []

        if not libraries:
            return evidence

        # Count cross-library references
        cross_refs: dict[tuple[str, str], int] = {}

        for unit in units:
            unit_lib = getattr(unit, 'primary_library', None)
            if not unit_lib:
                continue

            # Check references in content
            for ref in getattr(unit, 'references', []):
                ref_lib = self._find_library_for_element(ref.id_value, libraries)
                if ref_lib and ref_lib != unit_lib:
                    key = tuple(sorted([unit_lib, ref_lib]))
                    cross_refs[key] = cross_refs.get(key, 0) + 1

        # Flag high coupling
        for (lib1, lib2), count in cross_refs.items():
            if count > 10:  # Threshold
                evidence.append(GapEvidence(
                    severity=Severity.WARNING,
                    message=f"High coupling between {lib1} and {lib2}: {count} cross-references",
                    location=f"libraries/{lib1}.md ↔ libraries/{lib2}.md",
                    element_id=None,
                    detector="structural_health",
                    details={
                        'issue_type': 'coupling',
                        'libraries': [lib1, lib2],
                        'count': count
                    }
                ))

        return evidence

    def _detect_cohesion_issues(self, units: list, libraries: dict[str, list[str]] = None) -> list[GapEvidence]:
        """Detect low cohesion within libraries."""
        evidence = []

        if not libraries:
            return evidence

        for lib_name, element_ids in libraries.items():
            if len(element_ids) < 3:
                continue

            # Check if elements in same library reference each other
            lib_units = [u for u in units if getattr(u, 'primary_library', None) == lib_name]
            internal_refs = 0
            total_refs = 0

            for unit in lib_units:
                for ref in getattr(unit, 'references', []):
                    total_refs += 1
                    if ref.id_value in element_ids:
                        internal_refs += 1

            if total_refs > 5 and internal_refs / total_refs < 0.3:  # Low cohesion
                evidence.append(GapEvidence(
                    severity=Severity.INFO,
                    message=f"Low cohesion in {lib_name}: {internal_refs}/{total_refs} internal references ({internal_refs/total_refs:.0%})",
                    location=f"libraries/{lib_name}.md",
                    element_id=None,
                    detector="structural_health",
                    details={
                        'issue_type': 'cohesion',
                        'library': lib_name,
                        'internal_refs': internal_refs,
                        'total_refs': total_refs,
                        'ratio': internal_refs / total_refs if total_refs > 0 else 0
                    }
                ))

        return evidence

    def _detect_missing_relations(self, units: list) -> list[GapEvidence]:
        """Detect elements that should have relations but don't."""
        evidence = []

        for unit in units:
            unit_type = getattr(unit, 'unit_type', None)
            has_relations = bool(getattr(unit, 'relation_libraries', []))

            # Algorithms and Claims often relate to multiple libraries
            if unit_type in ('algorithm', 'claim', 'ALGORITHM', 'CLAIM'):
                # Check if content suggests cross-cutting concern
                content = getattr(unit, 'content', '')
                cross_cutting_keywords = ['graph', 'field', 'embed', 'pattern', 'index', 'workspace']
                matches = sum(1 for kw in cross_cutting_keywords if kw in content.lower())

                if matches >= 2 and not has_relations:
                    evidence.append(GapEvidence(
                        severity=Severity.INFO,
                        message=f"{unit.id} appears cross-cutting but has no relation annotations",
                        location=getattr(unit, 'source', 'unknown'),
                        element_id=unit.id,
                        detector="structural_health",
                        details={
                            'issue_type': 'missing_relations',
                            'keyword_matches': matches,
                            'suggestion': 'Add (@[+rel:library_name]) annotations'
                        }
                    ))

        return evidence

    def _detect_underspecified_elements(self, units: list) -> list[GapEvidence]:
        """Detect elements that lack sufficient specification."""
        evidence = []

        for unit in units:
            content = getattr(unit, 'content', '')
            unit_type = getattr(unit, 'unit_type', None)

            # Check for stub-like content
            if len(content.strip()) < 50:
                evidence.append(GapEvidence(
                    severity=Severity.WARNING,
                    message=f"{unit.id} appears underspecified ({len(content)} chars)",
                    location=getattr(unit, 'source', 'unknown'),
                    element_id=unit.id,
                    detector="structural_health",
                    details={
                        'issue_type': 'underspecified',
                        'content_length': len(content),
                        'unit_type': str(unit_type)
                    }
                ))

            # Check for TODO/TBD in body
            if 'TODO' in content or 'TBD' in content or '???' in content:
                evidence.append(GapEvidence(
                    severity=Severity.WARNING,
                    message=f"{unit.id} contains TODO/TBD markers",
                    location=getattr(unit, 'source', 'unknown'),
                    element_id=unit.id,
                    detector="structural_health",
                    details={
                        'issue_type': 'incomplete',
                        'markers_found': True
                    }
                ))

        return evidence

    def _detect_unpinned_elements(self, units: list) -> list[GapEvidence]:
        """Detect elements not pinned to a library."""
        evidence = []

        for unit in units:
            primary_lib = getattr(unit, 'primary_library', None)
            if not primary_lib:
                evidence.append(GapEvidence(
                    severity=Severity.WARNING,
                    message=f"{unit.id} has no primary library assignment",
                    location=getattr(unit, 'source', 'unknown'),
                    element_id=unit.id,
                    detector="structural_health",
                    details={
                        'issue_type': 'unpinned',
                        'candidate_libraries': list(getattr(unit, 'candidate_libraries', {}).keys())[:5]
                    }
                ))

        return evidence

    def _detect_unsatisfied_invariants(self, units: list) -> list[GapEvidence]:
        """Detect invariants that aren't referenced by any algorithm."""
        evidence = []

        # Collect all invariants and their references
        invariants = {u.id for u in units if str(getattr(u, 'unit_type', '')).lower() in ('invariant', 'p#i#')}
        referenced = set()

        for unit in units:
            content = getattr(unit, 'content', '')
            for inv_id in invariants:
                if inv_id in content:
                    referenced.add(inv_id)

        # Unreferenced invariants
        unreferenced = invariants - referenced
        for inv_id in unreferenced:
            evidence.append(GapEvidence(
                severity=Severity.INFO,
                message=f"Invariant {inv_id} is not referenced by any algorithm",
                location="plan.md",
                element_id=inv_id,
                detector="structural_health",
                details={
                    'issue_type': 'unsatisfied_invariant',
                    'suggestion': 'Either add reference in relevant algorithm or mark as deprecated'
                }
            ))

        return evidence

    def _find_library_for_element(self, element_id: str, libraries: dict[str, list[str]]) -> str | None:
        """Find which library contains an element."""
        for lib_name, element_ids in libraries.items():
            if element_id in element_ids:
                return lib_name
        return None


# =============================================================================
# Unified Gap Detector
# =============================================================================

class UnifiedGapDetector:
    """
    Unified gap detection: evidence collection → gap synthesis.

    This is the main entry point. It:
    1. Collects evidence from all detectors
    2. Synthesizes gaps by clustering related evidence
    3. Formats output as multi-section gaps.md
    """

    def __init__(self, llm_client=None):
        self.format_detector = FormatComplianceDetector()
        self.duplicate_detector = DuplicateDetector()
        self.function_detector = UndefinedFunctionDetector()
        self.sequence_analyzer = SequenceAnalyzer()
        self.content_verifier = ContentVerifier()
        self.uncertainty_detector = UncertaintyDetector()
        self.proof_chain_detector = ProofChainDetector(llm_client)
        self.prose_inference_detector = ProseFragmentInferenceDetector(llm_client)  # Gap 6 fix
        self.structural_health_detector = StructuralHealthDetector()  # Gap 7 fix
        self._gap_counter = 0

    def collect_evidence(
        self,
        spec_folder: Path
    ) -> list[GapEvidence]:
        """
        Collect all evidence from all detectors.

        This is the first phase - pure evidence collection.
        """
        evidence = []

        # Read main files
        plan_path = spec_folder / "plan.md"
        plan_content = plan_path.read_text() if plan_path.exists() else ""

        # Detect in plan.md
        if plan_content:
            evidence.extend(self.format_detector.detect(plan_content, "plan.md"))
            evidence.extend(self.duplicate_detector.detect_duplicate_declarations(plan_content, "plan.md"))
            evidence.extend(self.duplicate_detector.detect_duplicate_headers(plan_content, "plan.md"))
            evidence.extend(self.function_detector.detect(plan_content, "plan.md"))
            evidence.extend(self.sequence_analyzer.detect(plan_content, "plan.md"))
            evidence.extend(self.uncertainty_detector.detect(plan_content, "plan.md"))
            evidence.extend(self.proof_chain_detector.detect(plan_content, "plan.md"))  # Proof chains with LLM

        # Detect in patches
        patches_dir = spec_folder / "patches"
        if patches_dir.exists():
            for patch_file in patches_dir.glob("*.md"):
                patch_content = patch_file.read_text()
                evidence.extend(self.format_detector.detect(patch_content, f"patches/{patch_file.name}"))
                evidence.extend(self.uncertainty_detector.detect(patch_content, f"patches/{patch_file.name}"))

        # Detect in libraries and verify against plan
        libraries_dir = spec_folder / "libraries"
        if libraries_dir.exists() and plan_content:
            for lib_file in libraries_dir.glob("*.md"):
                lib_content = lib_file.read_text()
                lib_name = f"libraries/{lib_file.name}"

                evidence.extend(self.duplicate_detector.detect_duplicate_declarations(lib_content, lib_name))
                evidence.extend(self.content_verifier.verify(plan_content, lib_content, lib_name))

        return evidence

    def synthesize_gaps(
        self,
        evidence: list[GapEvidence]
    ) -> list[GapElement]:
        """
        Synthesize gaps by clustering related evidence.

        Clustering criteria:
        - Same element_id
        - Same root cause (inferred from detector + message)
        - Same patch origin
        """
        if not evidence:
            return []

        # Group by element_id first
        by_element: dict[str, list[GapEvidence]] = defaultdict(list)
        orphan_evidence: list[GapEvidence] = []

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
        by_detector: dict[str, list[GapEvidence]] = defaultdict(list)
        for e in orphan_evidence:
            by_detector[e.detector].append(e)

        for detector, detector_evidence in by_detector.items():
            # Sub-group by location file
            by_file: dict[str, list[GapEvidence]] = defaultdict(list)
            for e in detector_evidence:
                file_part = e.location.split(':')[0] if ':' in e.location else e.location
                by_file[file_part].append(e)

            for file_part, file_evidence in by_file.items():
                gap = self._create_gap(file_evidence, None)
                gaps.append(gap)

        return gaps

    def _create_gap(
        self,
        evidence: list[GapEvidence],
        element_id: str | None
    ) -> GapElement:
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
            patch_origin=self._infer_patch_origin(evidence)
        )

    def _infer_patch_origin(self, evidence: list[GapEvidence]) -> str | None:
        """Infer which patch introduced this gap."""
        for e in evidence:
            if 'patches/' in e.location:
                # Extract patch name
                parts = e.location.split('/')
                for part in parts:
                    if part.startswith('p') and '.md' in part:
                        return part.replace('.md', '')
        return None

    def detect_all(
        self,
        spec_folder: Path,
        include_info: bool = True
    ) -> list[GapElement]:
        """
        Run full detection: collect evidence → synthesize gaps.

        Returns first-class GapElement objects.
        """
        evidence = self.collect_evidence(spec_folder)

        # Filter by severity if requested
        if not include_info:
            evidence = [e for e in evidence if e.severity != Severity.INFO]

        gaps = self.synthesize_gaps(evidence)
        return gaps

    def format_gaps_md(
        self,
        gaps: list[GapElement],
        previous_gaps: list[GapElement] | None = None
    ) -> str:
        """
        Format gaps as multi-section markdown report.

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
            bypassed_gaps = [g for g in gaps if getattr(g, 'bypassed', False) or getattr(g, 'drop_reason', None)]

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
                    lines.append(f"- ✅ **{gid}**")
                if len(resolved_ids) > 10:
                    lines.append(f"- ... and {len(resolved_ids) - 10} more")
            else:
                lines.append("- None")

            lines.append("\n### Bypassed / Intentionally Dropped\n")
            if bypassed_gaps:
                for g in bypassed_gaps[:10]:
                    reason = getattr(g, 'drop_reason', 'intentional bypass')
                    lines.append(f"- 🚫 **{g.id}**: {reason}")
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
                    icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
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
        proof_gaps = [g for g in gaps if 'proof' in g.id.lower() or 'claim' in g.id.lower() or
                      any('proof' in str(e.message).lower() for e in g.evidence)]
        if proof_gaps:
            for gap in proof_gaps:
                icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                lines.append(f"  - Related claims: {', '.join(a for a in gap.affects if 'C' in a)[:5]}")
                lines.append("")
        else:
            lines.append("*No proof obligation issues detected.*\n")

        # =================================================================
        # UNDEFINED FUNCTIONS SECTION (Gap 8 fix - was missing)
        # =================================================================
        lines.append("\n## Undefined Functions\n")
        undefined_gaps = [g for g in gaps if 'undefined' in g.id.lower() or 'function' in g.id.lower() or
                         any('undefined' in str(e.detector).lower() for e in g.evidence)]
        if undefined_gaps:
            for gap in undefined_gaps:
                icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                # Extract function names from evidence
                func_names = []
                for ev in gap.evidence:
                    if hasattr(ev, 'details') and 'function_name' in ev.details:
                        func_names.append(ev.details['function_name'])
                if func_names:
                    lines.append(f"  - Functions: `{', '.join(func_names[:5])}`")
                lines.append("")
        else:
            lines.append("*No undefined functions detected.*\n")

        # =================================================================
        # STRUCTURAL HEALTH SECTION
        # =================================================================
        lines.append("\n## Structural Health\n")
        structural_gaps = [g for g in no_patch if 'structural' in g.id.lower() or 'coupling' in g.id.lower() or
                          'cohesion' in g.id.lower() or 'relation' in g.id.lower() or
                          any('structural' in str(e.detector).lower() for e in g.evidence)]
        other_no_patch = [g for g in no_patch if g not in structural_gaps]

        if structural_gaps:
            for gap in structural_gaps:
                icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                lines.append(f"  - Affects: {', '.join(gap.affects[:5])}")
                lines.append("")
        else:
            lines.append("*No structural health issues detected.*\n")

        # =================================================================
        # UNRESOLVED ELEMENTS SECTION (Gap 8 fix - was missing)
        # =================================================================
        lines.append("\n## Unresolved Elements\n")
        unresolved_gaps = [g for g in gaps if 'unresolved' in g.id.lower() or 'vague' in g.id.lower() or
                          'entity_resolution' in g.id.lower() or
                          any('resolution' in str(e.detector).lower() for e in g.evidence)]
        if unresolved_gaps:
            for gap in unresolved_gaps:
                icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
                lines.append(f"- {icon} **{gap.id}**: {gap.summary}")
                # Show what couldn't be resolved
                for ev in gap.evidence[:3]:
                    if hasattr(ev, 'details') and 'original_text' in ev.details:
                        lines.append(f"  - Unresolved: `{ev.details['original_text'][:50]}`")
                lines.append("")
        else:
            lines.append("*No unresolved elements detected.*\n")

        # =================================================================
        # OTHER GAPS SECTION (catch-all for uncategorized)
        # =================================================================
        categorized = set(g.id for g in proof_gaps + undefined_gaps + structural_gaps + unresolved_gaps)
        other_gaps = [g for g in other_no_patch if g.id not in categorized]
        if other_gaps:
            lines.append("\n## Other Issues\n")
            for gap in other_gaps:
                icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}.get(gap.severity.value, '•')
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

        return '\n'.join(lines)
```

## Testing

```python
def test_format_compliance():
    detector = FormatComplianceDetector()
    content = "## I5 Some invariant\n"  # Legacy format
    gaps = detector.detect(content, "test.md")
    assert any(g.gap_type == 'format_violation' for g in gaps)


def test_undefined_functions():
    detector = UndefinedFunctionDetector()
    content = '''
```pseudo
function KNOWN():
    UNKNOWN_FUNC(x)
    ANOTHER_UNKNOWN(y)
```
'''
    gaps = detector.detect(content, "test.md")
    assert len(gaps) == 2
    assert all(g.gap_type == 'undefined_function' for g in gaps)


def test_sequence_holes():
    analyzer = SequenceAnalyzer()
    content = '''
## Algorithm 1
## Algorithm 2
## Algorithm 5
'''
    gaps = analyzer.detect(content, "test.md")
    assert any(g.gap_type == 'sequence_hole' for g in gaps)
```

## Success Criteria

1. All script logic integrated into gap detection
2. Format violations detected (legacy patterns)
3. Duplicate declarations and headers detected
4. Undefined functions detected with categories
5. Sequence issues detected (duplicates, holes, conflicts)
6. Content mismatches between plan and libraries detected
7. Uncertainty markers detected (TODO, sorry, questions)
8. Unified gaps.md output with all gap types
