"""Pattern library for language-agnostic code review.

Provides a core rule catalog of principles, optional strategy packs
for language/framework-specific detection cues, and an evolution
mechanism that collects StrategyCandidate instances from repeated
human approvals.

Core reviewers always run with core principles.  Strategy packs are
optional overlays scoped by language, framework, or repository.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class Pattern:
    """A single review pattern/rule.

    Attributes:
        pattern_id: Unique identifier.
        principle: Core language-agnostic statement of what must be true.
        signals: Optional language/framework-specific detection cues.
        fix_guidance: Minimal remediation suggestions.
        dimension: Which review dimension this pattern serves
            (ARCH_BOUNDARY, TOPOLOGY, PIN_COVERAGE, CLARITY, etc.).
        enabled: Whether this pattern is active.
    """

    pattern_id: str = ""
    principle: str = ""
    signals: list[dict[str, str]] = field(default_factory=list)
    fix_guidance: str = ""
    dimension: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pattern:
        """Reconstruct from a dict, ignoring unknown keys."""
        import dataclasses as _dc

        known = {f.name for f in _dc.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class StrategyPack:
    """Optional overlay of language/framework-specific signals.

    Attributes:
        pack_id: Unique identifier (e.g., "python", "fastapi").
        language: Target language (empty = language-agnostic).
        framework: Target framework (empty = framework-agnostic).
        scope: Scope qualifier (e.g., repository name).
        patterns: Patterns in this pack.
    """

    pack_id: str = ""
    language: str = ""
    framework: str = ""
    scope: str = ""
    patterns: list[Pattern] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "pack_id": self.pack_id,
            "language": self.language,
            "framework": self.framework,
            "scope": self.scope,
            "patterns": [p.to_dict() for p in self.patterns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyPack:
        """Reconstruct from a dict."""
        import dataclasses as _dc

        raw_patterns = data.get("patterns", []) if isinstance(data.get("patterns"), list) else []
        patterns = [Pattern.from_dict(p) for p in raw_patterns]
        known = {f.name for f in _dc.fields(cls)} - {"patterns"}
        return cls(patterns=patterns, **{k: v for k, v in data.items() if k in known})


@dataclass
class StrategyCandidate:
    """Candidate for evolution into a strategy pattern.

    Created when a human approves a fix or a recurring finding is detected.

    Attributes:
        signal_patterns: Code patterns observed in the codebase.
        approved_remediation: The fix that was approved.
        exceptions: Known false positives.
        occurrences: How many times this was seen.
        source_dimension: Which review dimension generated this.
    """

    signal_patterns: list[str] = field(default_factory=list)
    approved_remediation: str = ""
    exceptions: list[str] = field(default_factory=list)
    occurrences: int = 1
    source_dimension: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return asdict(self)


# ------------------------------------------------------------------
# Default core patterns
# ------------------------------------------------------------------


def _default_core_patterns() -> list[Pattern]:
    """Return built-in core patterns covering all review dimensions."""
    return [
        # ---- ARCH_BOUNDARY (4 patterns) ----
        Pattern(
            pattern_id="AB-001",
            principle="Each component must have a single, clearly defined responsibility.",
            dimension="ARCH_BOUNDARY",
            fix_guidance="Split the component so each piece owns exactly one concern.",
        ),
        Pattern(
            pattern_id="AB-002",
            principle=(
                "Dependencies must flow in one direction: higher layers depend on "
                "lower layers, never the reverse."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance="Invert the dependency or introduce an abstraction at the boundary.",
        ),
        Pattern(
            pattern_id="AB-003",
            principle=(
                "Cross-cutting concerns must not leak implementation details across "
                "component boundaries."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance=(
                "Route cross-cutting behavior through a dedicated mechanism rather than "
                "direct coupling."
            ),
        ),
        Pattern(
            pattern_id="AB-004",
            principle=(
                "Public interfaces of a component must be the only way other "
                "components interact with it."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance=(
                "Remove internal-detail references and route through the declared public interface."
            ),
        ),
        # ---- TOPOLOGY (4 patterns) ----
        Pattern(
            pattern_id="TP-001",
            principle="Every declared component must be reachable from at least one entrypoint.",
            dimension="TOPOLOGY",
            fix_guidance="Wire the orphan component into an existing handler chain or remove it.",
        ),
        Pattern(
            pattern_id="TP-002",
            principle=(
                "Handler chains must be complete: every event that is emitted must have a consumer."
            ),
            dimension="TOPOLOGY",
            fix_guidance="Add a handler for the unconsumed event or remove the emission.",
        ),
        Pattern(
            pattern_id="TP-003",
            principle="All declared entrypoints must be reachable and functional.",
            dimension="TOPOLOGY",
            fix_guidance="Connect the entrypoint to the component graph or remove the declaration.",
        ),
        Pattern(
            pattern_id="TP-004",
            principle=(
                "Data flow paths must form complete pipelines from source to sink "
                "with no dead ends."
            ),
            dimension="TOPOLOGY",
            fix_guidance="Extend the pipeline to a terminal consumer or prune the dead-end branch.",
        ),
        # ---- PIN_COVERAGE (3 patterns) ----
        Pattern(
            pattern_id="PC-001",
            principle="Every promoted pin must be consumed by at least one downstream component.",
            dimension="PIN_COVERAGE",
            fix_guidance="Add a consumer for the orphan pin or revoke the promotion.",
        ),
        Pattern(
            pattern_id="PC-002",
            principle="No edge in the component graph may reference a pin that does not exist.",
            dimension="PIN_COVERAGE",
            fix_guidance="Create the missing pin or correct the edge reference.",
        ),
        Pattern(
            pattern_id="PC-003",
            principle=(
                "Every edge declared in the architecture must be realized in the implementation."
            ),
            dimension="PIN_COVERAGE",
            fix_guidance="Implement the declared edge or remove it from the architecture manifest.",
        ),
        # ---- ARCH_DRIFT (3 patterns) ----
        Pattern(
            pattern_id="AD-001",
            principle="The implementation must conform to the declared architecture manifest.",
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Update the implementation to match the manifest, or amend the "
                "manifest through the promotion process."
            ),
        ),
        Pattern(
            pattern_id="AD-002",
            principle=(
                "No component may exist in the implementation without a corresponding declaration."
            ),
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Declare the component in the manifest or remove it from the implementation."
            ),
        ),
        Pattern(
            pattern_id="AD-003",
            principle=(
                "Configuration and environment values must be externalized, not "
                "embedded in component logic."
            ),
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Move the embedded value to a configuration source and reference it indirectly."
            ),
        ),
        # ---- GOVERNANCE (3 patterns) ----
        Pattern(
            pattern_id="GV-001",
            principle="Every promotion decision must have a recorded receipt with rationale.",
            dimension="GOVERNANCE",
            fix_guidance="Generate a decision receipt before allowing the promotion to proceed.",
        ),
        Pattern(
            pattern_id="GV-002",
            principle=(
                "No artifact may be modified without an authorized promotion or demotion ticket."
            ),
            dimension="GOVERNANCE",
            fix_guidance="Route the change through the promotion loop or create a demotion ticket.",
        ),
        Pattern(
            pattern_id="GV-003",
            principle=(
                "Evidence bundles must contain all required references before a gate can pass."
            ),
            dimension="GOVERNANCE",
            fix_guidance="Populate the missing evidence references in the bundle.",
        ),
        # ---- CLARITY (2 patterns) ----
        Pattern(
            pattern_id="CL-001",
            principle=(
                "Code structure and naming must convey intent without requiring "
                "external documentation."
            ),
            dimension="CLARITY",
            fix_guidance="Rename symbols to express their purpose and restructure for readability.",
        ),
        Pattern(
            pattern_id="CL-002",
            principle=(
                "Function and type names must accurately describe what they do, not how they do it."
            ),
            dimension="CLARITY",
            fix_guidance=(
                "Rename to reflect the behavioral contract rather than the "
                "implementation mechanism."
            ),
        ),
        # ---- CONSISTENCY (2 patterns) ----
        Pattern(
            pattern_id="CN-001",
            principle=(
                "Public APIs within the same component must follow uniform conventions "
                "for signatures, return types, and error handling."
            ),
            dimension="CONSISTENCY",
            fix_guidance=(
                "Align the inconsistent API to match the established convention in the component."
            ),
        ),
        Pattern(
            pattern_id="CN-002",
            principle=(
                "Naming, formatting, and structural conventions must be uniform "
                "within a codebase scope."
            ),
            dimension="CONSISTENCY",
            fix_guidance="Apply the dominant convention consistently across the scope.",
        ),
        # ---- MAINTAINABILITY (2 patterns) ----
        Pattern(
            pattern_id="MT-001",
            principle=(
                "No single function or method should exceed a complexity threshold "
                "that impairs understanding."
            ),
            dimension="MAINTAINABILITY",
            fix_guidance="Extract sub-routines or simplify control flow to reduce complexity.",
        ),
        Pattern(
            pattern_id="MT-002",
            principle="Duplicated logic must be consolidated into a single authoritative location.",
            dimension="MAINTAINABILITY",
            fix_guidance="Extract the duplicated logic into a shared function or module.",
        ),
        # ---- CORRECTNESS (2 patterns) ----
        Pattern(
            pattern_id="CR-001",
            principle=(
                "All boundary conditions and edge cases identified in the spec must "
                "have corresponding handling."
            ),
            dimension="CORRECTNESS",
            fix_guidance="Add explicit handling for the missing edge case.",
        ),
        Pattern(
            pattern_id="CR-002",
            principle=(
                "Every error path must terminate in a defined recovery or propagation action."
            ),
            dimension="CORRECTNESS",
            fix_guidance="Add error handling that either recovers or propagates with context.",
        ),
        # ---- DRIFT (2 patterns) ----
        Pattern(
            pattern_id="DR-001",
            principle=(
                "Implementation must not introduce capabilities beyond what the "
                "current plan specifies."
            ),
            dimension="DRIFT",
            fix_guidance=(
                "Remove the unplanned capability or create a plan amendment through "
                "the promotion loop."
            ),
        ),
        Pattern(
            pattern_id="DR-002",
            principle="Each iteration's changes must be traceable to a gap or plan item.",
            dimension="DRIFT",
            fix_guidance="Link the change to an existing plan item or file a new gap.",
        ),
        # ---- DIFF_IMPACT (2 patterns) ----
        Pattern(
            pattern_id="DI-001",
            principle=(
                "A refactor-only change must preserve observable behavior at all declared "
                "interfaces and side-effect boundaries."
            ),
            dimension="DIFF_IMPACT",
            fix_guidance=(
                "Rework the patch to preserve behavior, or reclassify and route it as a "
                "behavior_change."
            ),
        ),
        Pattern(
            pattern_id="DI-002",
            principle=(
                "Any detected behavior change must be explicitly classified and demoted to "
                "the authoritative layer before promotion can continue."
            ),
            dimension="DIFF_IMPACT",
            fix_guidance=(
                "Emit a behavior_change finding with evidence and route the change through "
                "the appropriate lower-layer workflow."
            ),
        ),
    ]


# ------------------------------------------------------------------
# PatternLibrary
# ------------------------------------------------------------------


class PatternLibrary:
    """Manages core patterns and strategy packs.

    The library is loaded from a JSON file and provides patterns
    to reviewers.  Core patterns are language-agnostic principles.
    Strategy packs add optional detection cues.
    """

    def __init__(self, library_path: Path | None = None) -> None:
        self._core_patterns: list[Pattern] = []
        self._strategy_packs: list[StrategyPack] = []
        self._candidates: list[StrategyCandidate] = []
        self._library_path = library_path
        if library_path and library_path.exists():
            self._load(library_path)
        else:
            self._load_defaults()

    # -- persistence -------------------------------------------------

    def _load_defaults(self) -> None:
        """Load built-in core patterns."""
        self._core_patterns = _default_core_patterns()

    def _load(self, path: Path) -> None:
        """Load patterns from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        self._core_patterns = [Pattern.from_dict(p) for p in data.get("core_patterns", [])]
        self._strategy_packs = [StrategyPack.from_dict(sp) for sp in data.get("strategy_packs", [])]
        self._candidates = [StrategyCandidate(**c) for c in data.get("candidates", [])]

    def save(self, path: Path | None = None) -> Path:
        """Persist the library to disk."""
        target = path or self._library_path or Path("pattern_library.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "core_patterns": [p.to_dict() for p in self._core_patterns],
            "strategy_packs": [sp.to_dict() for sp in self._strategy_packs],
            "candidates": [c.to_dict() for c in self._candidates],
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return target

    # -- query -------------------------------------------------------

    def get_patterns_for_dimension(
        self,
        dimension: str,
        *,
        language: str = "",
        framework: str = "",
    ) -> list[Pattern]:
        """Get all active patterns for a review dimension.

        Includes core patterns plus any matching strategy pack overlays
        filtered by language and framework.
        """
        patterns = [p for p in self._core_patterns if p.dimension == dimension and p.enabled]
        for sp in self._strategy_packs:
            if language and sp.language and sp.language != language:
                continue
            if framework and sp.framework and sp.framework != framework:
                continue
            patterns.extend(p for p in sp.patterns if p.dimension == dimension and p.enabled)
        return patterns

    def get_review_prompt_section(self, dimension: str, **kwargs: Any) -> str:
        """Generate a prompt section with patterns for a given dimension.

        Returns a markdown-formatted block suitable for inclusion in
        an LLM review prompt.  Returns empty string if no patterns match.
        """
        patterns = self.get_patterns_for_dimension(dimension, **kwargs)
        if not patterns:
            return ""
        lines: list[str] = ["## Review Patterns", ""]
        for p in patterns:
            lines.append(f"### {p.pattern_id}: {p.principle}")
            if p.signals:
                lines.append("Signals:")
                for sig in p.signals:
                    lang = sig.get("language", "any")
                    cue = sig.get("cue", "")
                    lines.append(f"  - [{lang}] {cue}")
            if p.fix_guidance:
                lines.append(f"Fix: {p.fix_guidance}")
            lines.append("")
        return "\n".join(lines)

    # -- evolution ---------------------------------------------------

    def record_candidate(self, candidate: StrategyCandidate) -> None:
        """Record a strategy candidate from a repeated finding or human approval.

        If a candidate with overlapping signal patterns and the same
        source dimension already exists, the occurrence count is merged
        and signal patterns are unioned.
        """
        for existing in self._candidates:
            if existing.source_dimension == candidate.source_dimension and set(
                existing.signal_patterns
            ) & set(candidate.signal_patterns):
                existing.occurrences += candidate.occurrences
                existing.signal_patterns = list(
                    set(existing.signal_patterns) | set(candidate.signal_patterns)
                )
                return
        self._candidates.append(candidate)

    # -- properties --------------------------------------------------

    @property
    def candidates(self) -> list[StrategyCandidate]:
        """All recorded strategy candidates."""
        return list(self._candidates)

    @property
    def core_patterns(self) -> list[Pattern]:
        """All core patterns (read-only copy)."""
        return list(self._core_patterns)

    @property
    def strategy_packs(self) -> list[StrategyPack]:
        """All strategy packs (read-only copy)."""
        return list(self._strategy_packs)
