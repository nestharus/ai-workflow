"""Phase 0: Mechanical extraction from prose specs into PDD workspace format.

Converts prose specification text into structured workspace artifacts that
later PDD phases and the eval framework can consume:

- manifest/sections.json — section labels per file
- summaries/*.md — section-level bullet-point summaries
- libraries/*/charter.md — library charter with intent and responsibilities
- libraries/*/spec.md — extracted requirement sentences per library
- libraries/*/evidence/*.md — evidence mappings to source sections

The extraction is fully mechanical (regex + markdown parsing).  No LLM
calls, no NLP heuristics, no fuzzy matching.  The LLM judge handles
semantic matching at eval time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.refinement.workspace.manager import WorkspaceManager

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# CamelCase identifiers: at least two segments (SettlementProcessor, RiskEngine)
_CAMEL_CASE_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b")

# Sentence boundary: period/exclamation/question followed by whitespace + uppercase
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Normative indicators — sentences matching ANY of these are requirement candidates
_NORMATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$[\d,]+(?:\.\d+)?[MBKk]?\b"),  # Dollar amounts
    re.compile(r"\b\d+(?:\.\d+)?%"),  # Percentages
    re.compile(
        r"\b\d+\s*(?:ms|millisecond|second|minute|hour|day|year|business\s+day)s?\b",
        re.IGNORECASE,
    ),
    # Written-out time durations (five-minute, twenty-four-hour, seven years)
    re.compile(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|"
        r"thirty|forty|fifty|sixty|ninety)[\s-]*"
        r"(?:ms|millisecond|second|minute|hour|day|year|business[\s-]+day)s?\b",
        re.IGNORECASE,
    ),
    # Settlement date references (T-1, T+0, T+2)
    re.compile(r"\bT[+-]\d+\b"),
    re.compile(r"\b(?:must|shall|required|guarantee[ds]?)\b", re.IGNORECASE),
    re.compile(r"\b(?:threshold|limit|cap(?:ped)?|tolerance|window|band)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:exceed|breach|trigger|block|reject|escalat|purg|retain)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:rout(?:e[ds]?|ing)|publish|emit|dispatch|forward|deliver)\b",
        re.IGNORECASE,
    ),
    # Prefix match (no trailing \b) to catch "matching", "reconciliation", etc.
    re.compile(r"\b(?:detect|monitor|match|reconcil|resolv)", re.IGNORECASE),
    re.compile(r"\w+\.\w+"),  # Dotted names (settlement.confirmed)
    re.compile(
        r"\b(?:flag|snapshot|override|hold|backoff|retry|dead-letter|batch)\b",
        re.IGNORECASE,
    ),
]

# Minimum fragment length to keep (skip very short fragments)
_MIN_FRAGMENT_LEN = 25


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LibraryInfo:
    """Extracted library information."""

    name: str
    lib_id: str
    primary_section: str
    intent: str = ""
    requirements: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prose extractor
# ---------------------------------------------------------------------------


class ProseExtractor:
    """Mechanical extraction of structured workspace data from prose specs.

    Usage::

        extractor = ProseExtractor(workspace_manager)
        result = extractor.extract()
    """

    def __init__(self, manager: WorkspaceManager) -> None:
        self.manager = manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> dict[str, Any]:
        """Run full extraction pipeline.

        Returns:
            Summary dict with extraction statistics.
        """
        # Step 1: Read sections from spec snapshot
        sections = self._read_sections()
        if not sections:
            return {"error": "No sections found in spec snapshot", "sections_found": 0}

        # Step 2: Identify libraries from CamelCase entities
        libraries = self._identify_libraries(sections)

        # Step 3: Extract requirements and metadata per library
        for lib in libraries.values():
            section_text = sections.get(lib.primary_section, "")
            lib.requirements = self._extract_requirements(section_text)
            lib.responsibilities = lib.requirements  # all requirements
            lib.intent = self._extract_intent(section_text)

        # Step 4: Write outputs to workspace directories
        self._write_summaries(sections, libraries)
        self._write_libraries(libraries, sections)

        return {
            "sections_found": len(sections),
            "libraries_found": len(libraries),
            "libraries": [lib.name for lib in libraries.values()],
            "total_requirements": sum(len(lib.requirements) for lib in libraries.values()),
        }

    # ------------------------------------------------------------------
    # Section discovery
    # ------------------------------------------------------------------

    def _read_sections(self) -> dict[str, str]:
        """Read sections from spec snapshot files.

        Tries the ``sections/`` subdirectory first (written by eval fixtures),
        then falls back to parsing the main markdown file.

        Returns:
            Mapping of ``SECTION_LABEL`` → prose text.
        """
        sections: dict[str, str] = {}
        snapshot_dir = self.manager.structure.spec_snapshot_dir

        # Strategy 1: sections/ subdirectory (eval fixtures write here)
        sections_subdir = snapshot_dir / "sections"
        if sections_subdir.exists():
            for section_file in sorted(sections_subdir.glob("*.md")):
                content = section_file.read_text(encoding="utf-8")
                lines = content.splitlines()
                if lines and lines[0].startswith("# "):
                    label = lines[0][2:].strip().upper().replace(" ", "_")
                    content = "\n".join(lines[1:]).strip()
                else:
                    label = section_file.stem.upper()
                sections[label] = content

        # Strategy 2: parse headings from main markdown files
        if not sections:
            for md_file in sorted(snapshot_dir.glob("*.md")):
                if md_file.name == "rules.md":
                    continue
                content = md_file.read_text(encoding="utf-8")
                parsed = self._parse_markdown_sections(content)
                sections.update(parsed)

        return sections

    @staticmethod
    def _parse_markdown_sections(content: str) -> dict[str, str]:
        """Parse markdown content into sections by top-level headings."""
        sections: dict[str, str] = {}
        current_label = ""
        current_lines: list[str] = []

        for line in content.splitlines():
            if line.startswith("# ") and not line.startswith("## "):
                if current_label and current_lines:
                    sections[current_label] = "\n".join(current_lines).strip()
                current_label = line[2:].strip().upper().replace(" ", "_")
                current_lines = []
            else:
                current_lines.append(line)

        if current_label and current_lines:
            sections[current_label] = "\n".join(current_lines).strip()

        return sections

    # ------------------------------------------------------------------
    # Library identification
    # ------------------------------------------------------------------

    def _identify_libraries(self, sections: dict[str, str]) -> dict[str, LibraryInfo]:
        """Identify libraries using a section-first approach.

        For each non-OVERVIEW section, finds the best-matching CamelCase
        entity name from the OVERVIEW section (or all sections).  This
        correctly handles the common pattern where OVERVIEW names all
        libraries but dedicated sections discuss them using short forms
        like "the processor" instead of "SettlementProcessor".

        Fallback: if no CamelCase match is found, uses the most frequent
        CamelCase name within the section itself.

        Returns:
            Mapping of library name → :class:`LibraryInfo`.
        """
        # Collect CamelCase candidates from OVERVIEW (primary source of names)
        overview_text = sections.get("OVERVIEW", "")
        candidates: set[str] = set(_CAMEL_CASE_RE.findall(overview_text))

        # Also collect from all sections as fallback pool
        all_candidates: set[str] = set(candidates)
        section_local_names: dict[str, dict[str, int]] = {}
        for label, text in sections.items():
            names = _CAMEL_CASE_RE.findall(text)
            all_candidates.update(names)
            if label != "OVERVIEW":
                counter: dict[str, int] = {}
                for n in names:
                    counter[n] = counter.get(n, 0) + 1
                section_local_names[label] = counter

        non_overview_labels = [section for section in sections if section != "OVERVIEW"]

        # For each non-OVERVIEW section, find the best library name
        libraries: dict[str, LibraryInfo] = {}
        used_names: set[str] = set()
        lib_counter = 0

        for label in non_overview_labels:
            # Strategy 1: match section name to an OVERVIEW CamelCase entity
            best = self._best_candidate_for_section(label, candidates - used_names)

            # Strategy 2: most frequent CamelCase in this section (not yet used)
            if not best:
                local = section_local_names.get(label, {})
                available = {n: c for n, c in local.items() if n not in used_names}
                if available:
                    best = max(available, key=lambda n: available[n])

            # Strategy 3: match against all CamelCase names
            if not best:
                best = self._best_candidate_for_section(label, all_candidates - used_names)

            if best:
                lib_counter += 1
                libraries[best] = LibraryInfo(
                    name=best,
                    lib_id=f"LIB-{lib_counter:04d}",
                    primary_section=label,
                )
                used_names.add(best)

        return libraries

    @staticmethod
    def _best_candidate_for_section(section_label: str, candidates: set[str]) -> str | None:
        """Find the CamelCase candidate that best matches a section label.

        Splits both into word stems and counts 4-char prefix matches.
        ``SETTLEMENT_PROCESSING`` → ``["settlement", "processing"]`` matches
        ``SettlementProcessor`` → ``["settlement", "processor"]`` on the
        ``sett`` prefix.

        Returns:
            Best matching candidate name, or ``None``.
        """
        section_words = [w.lower() for w in section_label.split("_")]

        best_match: str | None = None
        best_score = 0

        for candidate in candidates:
            cand_words = [w.lower() for w in re.findall(r"[A-Z][a-z]+", candidate)]
            if not cand_words:
                continue

            score = 0
            for sec_word in section_words:
                sec_prefix = sec_word[:4]
                for cand_word in cand_words:
                    if cand_word.startswith(sec_prefix) or sec_word.startswith(cand_word[:4]):
                        score += 1
                        break

            if score > best_score:
                best_score = score
                best_match = candidate

        return best_match if best_score > 0 else None

    # ------------------------------------------------------------------
    # Sentence / requirement extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _split_into_fragments(text: str) -> list[str]:
        """Split prose text into sentence-level fragments.

        Splits on sentence boundaries, semicolons, and colons (when both
        parts are substantial) to produce fragments that each map to
        roughly one requirement.
        """
        # Normalise whitespace
        text = re.sub(r"\s+", " ", text.strip())

        # Split on sentence boundaries
        sentences = _SENTENCE_BOUNDARY_RE.split(text)

        # Further split on semicolons
        stage2: list[str] = []
        for sentence in sentences:
            if ";" in sentence:
                parts = sentence.split(";")
                stage2.extend(p.strip() for p in parts if p.strip())
            else:
                stage2.append(sentence.strip())

        # Further split on colons when both parts are substantial
        fragments: list[str] = []
        for fragment in stage2:
            if ":" in fragment:
                idx = fragment.index(":")
                before = fragment[:idx].strip()
                after = fragment[idx + 1 :].strip()
                if len(before) >= _MIN_FRAGMENT_LEN and len(after) >= _MIN_FRAGMENT_LEN:
                    fragments.append(before)
                    fragments.append(after)
                    continue
            fragments.append(fragment)

        return [f for f in fragments if len(f) >= _MIN_FRAGMENT_LEN]

    @staticmethod
    def _is_normative(fragment: str) -> bool:
        """Return True if the fragment matches any normative indicator."""
        return any(pat.search(fragment) for pat in _NORMATIVE_PATTERNS)

    def _extract_requirements(self, text: str) -> list[str]:
        """Extract normative requirement sentences from section text."""
        fragments = self._split_into_fragments(text)
        return [f for f in fragments if self._is_normative(f)]

    @staticmethod
    def _extract_intent(text: str) -> str:
        """Extract intent — first substantial sentence from section text."""
        text = re.sub(r"\s+", " ", text.strip())
        sentences = _SENTENCE_BOUNDARY_RE.split(text)
        for sentence in sentences:
            s = sentence.strip()
            if len(s) >= _MIN_FRAGMENT_LEN:
                return s[:200] + ("..." if len(s) > 200 else "")
        return ""

    # ------------------------------------------------------------------
    # Workspace output writers
    # ------------------------------------------------------------------

    def _write_summaries(
        self,
        sections: dict[str, str],
        libraries: dict[str, LibraryInfo] | None = None,
    ) -> None:
        """Write summary files (``summaries/*.md``) with bullet-point fragments.

        Also writes ``libraries_summary.md`` with per-library intent lines
        so the summarization eval phase can match library-level descriptions.
        """
        summaries_dir = self.manager.structure.summaries_dir
        summaries_dir.mkdir(parents=True, exist_ok=True)

        for label, text in sections.items():
            summary_file = summaries_dir / f"{label.lower()}.md"
            fragments = self._split_into_fragments(text)

            lines = [f"# {label}\n"]
            for fragment in fragments:
                if len(fragment) > 200:
                    fragment = fragment[:197] + "..."
                lines.append(f"- {fragment}")

            summary_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Library-level summary for summarization eval matching
        if libraries:
            lib_lines = ["# Libraries\n"]
            for lib in libraries.values():
                if lib.intent:
                    lib_lines.append(f"- {lib.intent}")
                else:
                    lib_lines.append(f"- {lib.name}")
            lib_summary = summaries_dir / "libraries_summary.md"
            lib_summary.write_text("\n".join(lib_lines) + "\n", encoding="utf-8")

    def _write_libraries(
        self,
        libraries: dict[str, LibraryInfo],
        sections: dict[str, str],
    ) -> None:
        """Write library directories (charter, spec, evidence)."""
        libraries_dir = self.manager.structure.libraries_dir
        libraries_dir.mkdir(parents=True, exist_ok=True)

        for lib in libraries.values():
            lib_dir = libraries_dir / lib.name
            lib_dir.mkdir(parents=True, exist_ok=True)

            self._write_charter(lib_dir, lib)
            self._write_spec(lib_dir, lib)
            self._write_evidence(lib_dir, lib)

    @staticmethod
    def _write_charter(lib_dir: Path, lib: LibraryInfo) -> None:
        """Write ``charter.md`` for a library."""
        lines = [
            f"# {lib.name}",
            f"Library ID: {lib.lib_id}",
            "",
            "## Intent",
            "",
            lib.intent or f"Manages {lib.name} functionality.",
            "",
            "## Responsibilities",
            "",
        ]
        for req in lib.responsibilities:
            lines.append(f"- {req}")

        (lib_dir / "charter.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _write_spec(lib_dir: Path, lib: LibraryInfo) -> None:
        """Write ``spec.md`` for a library."""
        lines = [f"# {lib.name} Specification", ""]
        for req in lib.requirements:
            lines.append(f"- {req}")

        (lib_dir / "spec.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _write_evidence(lib_dir: Path, lib: LibraryInfo) -> None:
        """Write ``evidence/*.md`` for a library."""
        evidence_dir = lib_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        lines = [f"## {lib.primary_section}", ""]
        for req in lib.requirements:
            lines.append(f"- {req}")

        evidence_file = evidence_dir / f"{lib.primary_section.lower()}.md"
        evidence_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
