"""Integration with hollowed-out spec evidence for ambiguity resolution.

When planning hits an ambiguity, the evidence store is searched for answers.
Uses lazy loading: structure is indexed upfront, content is loaded on demand.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spec_manager.planning.models import FunctionInfo


@dataclass(frozen=True)
class EvidenceHit:
    """A single search result from the evidence store."""

    lib_id: str
    section_heading: str
    element_id: str | None
    excerpt: str  # Relevant excerpt from spec
    relevance_score: float  # 0.0 to 1.0
    source_path: str  # Path to source spec file


@dataclass(frozen=True)
class AmbiguityResolution:
    """Result of ambiguity resolution."""

    resolved: bool  # Whether the ambiguity was resolved
    answer: str | None  # Synthesized answer if resolved
    evidence_refs: list[str]  # References to evidence used
    gap_description: str | None  # If not resolved, description of the spec gap
    refined_comments: list[str]  # Updated comment texts with resolved details


class EvidenceStore:
    """Interface to hollowed-out spec evidence for ambiguity resolution.

    When planning hits an ambiguity ("validate payment against fraud rules" --
    but what fraud rules?), the evidence store is searched for answers.
    """

    def __init__(
        self,
        spec_snapshot_dir: Path,
        libraries_dir: Path,
    ) -> None:
        """Initialize from workspace directories.

        Loads spec indexes and library charters for search.
        Does NOT load full spec content upfront (lazy/hollowed approach).

        Args:
            spec_snapshot_dir: Path to spec snapshot directory.
            libraries_dir: Path to libraries directory.
        """
        self._spec_snapshot_dir = spec_snapshot_dir
        self._libraries_dir = libraries_dir
        self._section_index: dict[str, _SectionEntry] = {}
        self._content_cache: dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Build section-level index from spec files.

        Scans library files for section headings and element IDs
        without loading full content. This is the "hollowed out" approach.
        """
        # Index libraries directory
        if self._libraries_dir.is_dir():
            for lib_file in sorted(self._libraries_dir.glob("*.md")):
                self._index_markdown_file(lib_file, source="library")

        # Index spec snapshot directory
        if self._spec_snapshot_dir.is_dir():
            for spec_file in sorted(self._spec_snapshot_dir.glob("*.md")):
                self._index_markdown_file(spec_file, source="spec_snapshot")

    def _index_markdown_file(self, file_path: Path, source: str) -> None:
        """Index a markdown file by extracting headings and element IDs.

        Args:
            file_path: Path to the markdown file.
            source: Source type ("library" or "spec_snapshot").
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return

        lib_id = file_path.stem
        current_heading = ""
        current_line = 0

        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()

            # Track headings
            if stripped.startswith("#"):
                current_heading = stripped.lstrip("#").strip()
                current_line = i

            # Extract element IDs (patterns like LIB-xxxx, ATOM-xxxx, etc.)
            element_ids = re.findall(
                r"\b((?:LIB|ATOM|PIN|SEC|DEC|EDGE)-[A-Z0-9-]+)\b", stripped
            )

            # Build keywords from the heading
            keywords = set(current_heading.lower().split())
            keywords.update(stripped.lower().split())

            for element_id in element_ids:
                key = f"{lib_id}::{element_id}"
                self._section_index[key] = _SectionEntry(
                    lib_id=lib_id,
                    section_heading=current_heading,
                    element_id=element_id,
                    file_path=str(file_path),
                    line_no=i,
                    keywords=keywords,
                    source=source,
                )

            # Also index by heading (without element ID)
            if current_heading and current_line == i:
                key = f"{lib_id}::{current_heading}"
                self._section_index[key] = _SectionEntry(
                    lib_id=lib_id,
                    section_heading=current_heading,
                    element_id=None,
                    file_path=str(file_path),
                    line_no=i,
                    keywords=keywords,
                    source=source,
                )

    def search(
        self,
        query: str,
        context: str | None = None,
        max_results: int = 5,
    ) -> list[EvidenceHit]:
        """Search spec evidence for details matching a query.

        Uses keyword matching and section-level indexing.
        Loads full spec content only for matching sections (needle-in-haystack).

        Args:
            query: Search query (e.g. "fraud rules payment validation").
            context: Optional function/code context to narrow results.
            max_results: Maximum number of results to return.

        Returns:
            List of EvidenceHit objects sorted by relevance.
        """
        query_words = set(query.lower().split())
        if context:
            query_words.update(context.lower().split())

        # Score each indexed section
        scored: list[tuple[float, _SectionEntry]] = []
        for entry in self._section_index.values():
            overlap = len(query_words & entry.keywords)
            if overlap == 0:
                continue

            # Normalize score
            max_possible = max(len(query_words), 1)
            score = overlap / max_possible
            scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Take top results and load content on demand
        results: list[EvidenceHit] = []
        for score, entry in scored[:max_results]:
            excerpt = self._load_section_content(entry)
            results.append(
                EvidenceHit(
                    lib_id=entry.lib_id,
                    section_heading=entry.section_heading,
                    element_id=entry.element_id,
                    excerpt=excerpt,
                    relevance_score=min(score, 1.0),
                    source_path=entry.file_path,
                )
            )

        return results

    def _load_section_content(self, entry: _SectionEntry) -> str:
        """Load section content on demand (lazy loading).

        Args:
            entry: Section index entry.

        Returns:
            Excerpt text from the section.
        """
        file_path = entry.file_path

        # Use cache
        if file_path not in self._content_cache:
            try:
                self._content_cache[file_path] = Path(file_path).read_text(
                    encoding="utf-8"
                )
            except OSError:
                return ""

        content = self._content_cache[file_path]
        lines = content.splitlines()

        # Extract a window around the indexed line
        start = max(0, entry.line_no - 1)
        end = min(len(lines), entry.line_no + 10)
        excerpt_lines = lines[start:end]

        return "\n".join(excerpt_lines)

    def resolve_ambiguity(
        self,
        comment_text: str,
        function_context: FunctionInfo,
        agent_name: str = "opus-ambiguity-resolver",
    ) -> AmbiguityResolution:
        """Resolve an ambiguity in a pseudocode comment using spec evidence.

        1. Extract keywords from comment and function context
        2. Search evidence store
        3. If evidence found: use LLM to synthesize answer
        4. If no evidence: flag as genuine spec gap

        Args:
            comment_text: The ambiguous comment text.
            function_context: Context of the function being planned.
            agent_name: Agent name for LLM synthesis.

        Returns:
            AmbiguityResolution with answer or gap flag.
        """
        # Build search query from comment and function context
        query_parts = [comment_text]
        if function_context.docstring:
            query_parts.append(function_context.docstring)
        query = " ".join(query_parts)

        context = (
            f"function: {function_context.name}, "
            f"params: {', '.join(function_context.parameters)}"
        )

        # Search evidence
        hits = self.search(query, context=context, max_results=5)

        if not hits:
            return AmbiguityResolution(
                resolved=False,
                answer=None,
                evidence_refs=[],
                gap_description=(
                    f"No spec evidence found for: {comment_text}. "
                    f"Context: {function_context.name}"
                ),
                refined_comments=[comment_text],
            )

        # Try to synthesize answer via LLM
        evidence_refs = [
            f"{hit.lib_id}::{hit.element_id or hit.section_heading}"
            for hit in hits
        ]

        try:
            answer, refined = self._synthesize_answer(
                comment_text, hits, function_context, agent_name
            )
            return AmbiguityResolution(
                resolved=True,
                answer=answer,
                evidence_refs=evidence_refs,
                gap_description=None,
                refined_comments=refined,
            )
        except Exception:
            # LLM not available - return evidence refs without synthesis
            excerpts = [hit.excerpt for hit in hits if hit.excerpt]
            combined = "; ".join(excerpts[:3])
            return AmbiguityResolution(
                resolved=bool(combined),
                answer=combined if combined else None,
                evidence_refs=evidence_refs,
                gap_description=(
                    None
                    if combined
                    else f"Evidence found but could not synthesize answer for: {comment_text}"
                ),
                refined_comments=[comment_text],
            )

    def _synthesize_answer(
        self,
        comment_text: str,
        hits: list[EvidenceHit],
        function_context: FunctionInfo,
        agent_name: str,
    ) -> tuple[str, list[str]]:
        """Synthesize an answer from evidence hits using LLM.

        Args:
            comment_text: The ambiguous comment.
            hits: Relevant evidence hits.
            function_context: Function context.
            agent_name: Agent to use.

        Returns:
            Tuple of (answer_text, refined_comment_list).

        Raises:
            RuntimeError: If agent invocation fails.
        """
        from spec_manager.refinement.agent_utils import run_agent

        evidence_text = "\n\n".join(
            f"### {hit.lib_id} - {hit.section_heading}\n{hit.excerpt}" for hit in hits
        )

        prompt = (
            f"Resolve the following ambiguity using the provided evidence.\n\n"
            f"## Ambiguous Comment\n{comment_text}\n\n"
            f"## Function Context\n"
            f"Name: {function_context.name}\n"
            f"Parameters: {', '.join(function_context.parameters)}\n\n"
            f"## Evidence\n{evidence_text}\n\n"
            f"## Output\n"
            f"Return JSON with two fields:\n"
            f'- "answer": string with the resolved details\n'
            f'- "refined_comments": array of refined comment strings\n'
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            prompt_path = f.name

        try:
            result = run_agent(agent_name, prompt_path)
            parsed = json.loads(_strip_code_fences(result))
            answer = parsed.get("answer", "")
            refined = parsed.get("refined_comments", [comment_text])
            return answer, refined
        finally:
            Path(prompt_path).unlink(missing_ok=True)


@dataclass
class _SectionEntry:
    """Internal index entry for a section in a spec file."""

    lib_id: str
    section_heading: str
    element_id: str | None
    file_path: str
    line_no: int
    keywords: set[str]
    source: str  # "library" or "spec_snapshot"


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from text.

    Args:
        text: Text potentially wrapped in code fences.

    Returns:
        Text with code fences removed.
    """
    text = text.strip()
    pattern = r"```(?:json|python)?\s*\n?(.*?)(?:\n?```|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text
