"""Gap queue with stagnation detection and coverage metrics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from spec_manager.core.gap import Gap


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

    @staticmethod
    def _gap_identity(gap: Gap) -> str:
        """Build a stable identity key for gap reconciliation."""
        normalized_sources = sorted({str(src).strip() for src in gap.source if str(src).strip()})
        if normalized_sources:
            source_key = "|".join(normalized_sources)
        elif str(gap.derived_artifact_target).strip():
            source_key = f"target:{str(gap.derived_artifact_target).strip()}"
        else:
            source_key = f"id:{gap.id}"
        return f"{gap.gap_type.value}:{source_key}"

    @staticmethod
    def _severity_rank(gap: Gap) -> int:
        value = str(gap.severity.value).lower()
        if value == "error":
            return 3
        if value == "warning":
            return 2
        return 1

    @classmethod
    def _merge_gap_records(cls, baseline: Gap, incoming: Gap) -> Gap:
        """Merge latest observation into existing gap while preserving stable identity metadata."""
        merged = replace(
            incoming,
            id=baseline.id,
            created_at=baseline.created_at or incoming.created_at,
            source=sorted(set(baseline.source) | set(incoming.source)),
            evidence=list(incoming.evidence),
        )

        # Preserve strongest severity seen so far.
        if cls._severity_rank(baseline) > cls._severity_rank(merged):
            merged.severity = baseline.severity

        # Union evidence while keeping deterministic content-based uniqueness.
        evidence_seen = {json.dumps(item.to_dict(), sort_keys=True) for item in merged.evidence}
        for item in baseline.evidence:
            key = json.dumps(item.to_dict(), sort_keys=True)
            if key not in evidence_seen:
                merged.evidence.append(item)
                evidence_seen.add(key)

        if not merged.resolution_pointer and baseline.resolution_pointer:
            merged.resolution_pointer = baseline.resolution_pointer
        if not merged.resolution_notes and baseline.resolution_notes:
            merged.resolution_notes = baseline.resolution_notes

        if merged.status == "open":
            merged.resolved_at = None
        else:
            merged.resolved_at = (
                merged.resolved_at or baseline.resolved_at or datetime.now().isoformat()
            )
        return merged

    @staticmethod
    def _retire_gap(gap: Gap) -> Gap:
        """Retire an open gap that no longer appears in the latest observed set."""
        retired = replace(gap)
        if retired.status == "open":
            retired.status = "integrated"
            retired.resolved_at = retired.resolved_at or datetime.now().isoformat()
            if not retired.resolution_notes:
                retired.resolution_notes = (
                    "Automatically retired by queue reconciliation; "
                    "not observed in latest gap snapshot."
                )
        return retired

    def _reconcile(self, current_gaps: list[Gap]) -> list[Gap]:
        """Reconcile latest observed gaps with existing queue state."""
        existing_by_identity: dict[str, Gap] = {}
        for gap in self.gaps:
            identity = self._gap_identity(gap)
            gap_copy = replace(gap, source=list(gap.source), evidence=list(gap.evidence))
            if identity in existing_by_identity:
                existing_by_identity[identity] = self._merge_gap_records(
                    existing_by_identity[identity], gap_copy
                )
            else:
                existing_by_identity[identity] = gap_copy

        incoming_by_identity: dict[str, Gap] = {}
        for gap in current_gaps:
            identity = self._gap_identity(gap)
            gap_copy = replace(gap, source=list(gap.source), evidence=list(gap.evidence))
            if identity in incoming_by_identity:
                incoming_by_identity[identity] = self._merge_gap_records(
                    incoming_by_identity[identity], gap_copy
                )
            else:
                incoming_by_identity[identity] = gap_copy

        reconciled: list[Gap] = []
        seen: set[str] = set()
        for identity, incoming in incoming_by_identity.items():
            existing = existing_by_identity.get(identity)
            if existing is not None:
                reconciled.append(self._merge_gap_records(existing, incoming))
                seen.add(identity)
                continue
            reconciled.append(incoming)

        for identity, existing in existing_by_identity.items():
            if identity in seen:
                continue
            reconciled.append(self._retire_gap(existing))

        return reconciled

    def update(self, current_gaps: list[Gap]) -> None:
        """Reconcile latest gaps into queue state and update stagnation markers."""
        reconciled = self._reconcile(current_gaps)
        current_hash = self._compute_content_hash(reconciled)

        if current_hash == self.last_content_hash and self.last_content_hash:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0

        self.gaps = reconciled
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
