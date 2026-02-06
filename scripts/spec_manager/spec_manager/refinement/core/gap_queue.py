"""Gap queue with stagnation detection and coverage metrics."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from spec_manager.refinement.core.gap import Gap


@dataclass
class GapQueue:
    """Queue of gaps with stagnation detection and coverage metrics."""

    gaps: list[Gap] = field(default_factory=list)
    stagnation_count: int = 0
    stagnation_threshold: int = 3
    last_content_hash: str = ""
    is_stagnant: bool = False

    @staticmethod
    def _compute_content_hash(gaps: list[Gap]) -> str:
        """Compute deterministic hash for gaps based on open source pointers.

        Uses source pointers (e.g. ``[spec_snapshot/rules.md::SEC-F0002-0004]``)
        instead of gap IDs.  Gap IDs are derived from LLM-generated descriptions
        which vary across iterations, making ID-based hashing useless for
        stagnation detection.  Source pointers remain stable, so repeated gaps
        about the same sources will produce the same hash, correctly triggering
        stagnation.
        """
        if not gaps:
            return ""
        open_sources: set[str] = set()
        for gap in gaps:
            if gap.status == "open":
                for src in gap.source:
                    open_sources.add(src)
        if not open_sources:
            return ""
        canonical = "|".join(sorted(open_sources))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def update(self, current_gaps: list[Gap]) -> None:
        """Update queue with current gaps and check for stagnation."""
        current_hash = self._compute_content_hash(current_gaps)

        if current_hash == self.last_content_hash and self.last_content_hash:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0

        self.gaps = current_gaps
        self.last_content_hash = current_hash
        self.is_stagnant = self.stagnation_count >= self.stagnation_threshold

    def mark_progress(self) -> None:
        """Reset stagnation counters after progress is made."""
        self.stagnation_count = 0
        self.is_stagnant = False

    def get_open_gaps(self) -> list[Gap]:
        """Return gaps that are still open."""
        return [gap for gap in self.gaps if gap.status == "open"]

    def get_closed_gaps(self) -> list[Gap]:
        """Return gaps that are integrated."""
        return [gap for gap in self.gaps if gap.status == "integrated"]

    def get_coverage_metrics(self) -> dict[str, Any]:
        """Compute coverage metrics for current gaps."""
        total_gaps = len(self.gaps)
        open_gaps = len([gap for gap in self.gaps if gap.status == "open"])
        closed_gaps = len([gap for gap in self.gaps if gap.status == "integrated"])
        convergence_ratio = closed_gaps / total_gaps if total_gaps > 0 else 1.0
        return {
            "total_gaps": total_gaps,
            "open_gaps": open_gaps,
            "closed_gaps": closed_gaps,
            "convergence_ratio": convergence_ratio,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "gaps": [gap.to_dict() for gap in self.gaps],
            "stagnation_count": self.stagnation_count,
            "stagnation_threshold": self.stagnation_threshold,
            "last_content_hash": self.last_content_hash,
            "is_stagnant": self.is_stagnant,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapQueue:
        """Deserialize from dictionary."""
        return cls(
            gaps=[Gap.from_dict(gap) for gap in data.get("gaps", [])],
            stagnation_count=data.get("stagnation_count", 0),
            stagnation_threshold=data.get("stagnation_threshold", 3),
            last_content_hash=data.get("last_content_hash", ""),
            is_stagnant=data.get("is_stagnant", False),
        )
