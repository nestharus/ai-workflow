"""Demotion chain: gate/test failure to concrete edit targets.

Replaces the old "skip atom" behavior with "demote atom → patch L1 →
GapQueue → re-loop".

Key types:
- DemotionTicket: concrete edit target produced by gate/test failures
- RoutingItem: content that needs Phase 0 routing
- RoutedPatch: result of routing a single item
- DemotionManager: applies tickets to the target layer
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class DemotionTicket:
    """A concrete demotion produced by gate/test/verify failure.

    Instead of skipping an atom that fails a gate, the system produces
    a DemotionTicket that becomes an actionable edit target at the
    appropriate layer.
    """

    ticket_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str = ""
    slice_id: str = ""

    source: Literal[
        "ALGORITHMIC_GATE",
        "ARCH_GATE",
        "TEST_FAILURE",
        "LINEAGE",
        "REVIEW",
    ] = "ALGORITHMIC_GATE"
    gate: str | None = None

    target_layer: Literal["L1", "L2", "L3"] = "L1"
    severity: Literal["BLOCKER", "MAJOR", "MINOR"] = "BLOCKER"

    failing_pins: list[str] = field(default_factory=list)
    failing_atoms: list[str] = field(default_factory=list)
    failing_files: list[str] = field(default_factory=list)

    diagnosis: str = ""
    evidence_refs: list[str] = field(default_factory=list)

    recommended_spec_patch: str | None = None
    recommended_code_patch: str | None = None
    questions: list[str] = field(default_factory=list)

    routing_required: bool = False
    routing_payload: dict[str, Any] | None = None

    apply_status: Literal["PENDING", "APPLIED", "REJECTED", "BLOCKED"] = "PENDING"
    applied_patch_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DemotionTicket:
        """Deserialize from a dict."""
        return cls(**{
            k: v for k, v in data.items()
            if k in {f.name for f in __import__("dataclasses").fields(cls)}
        })


@dataclass
class RoutingItem:
    """Content that needs Phase 0 routing into L1 code-as-spec."""

    item_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    text: str = ""
    source_path: str | None = None
    desired_slice_hint: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class RoutedPatch:
    """Result of routing a single item through Phase 0."""

    target_slice_id: str = ""
    unified_diff_path: str = ""
    notes_path: str = ""


class DemotionManager:
    """Applies DemotionTickets to the target layer.

    Replaces "skip atom" with "demote → patch → GapQueue → loop".

    Usage::

        manager = DemotionManager(workspace_root=Path("."))
        results = manager.apply(ticket, slice_root=Path("..."))
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def apply(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
    ) -> dict[str, Any]:
        """Apply a demotion ticket to the target layer.

        Steps:
        1. Apply recommended patch (spec or code) if present.
        2. Otherwise, generate a minimal gap stub.
        3. Update registries (mark atoms/pins as demoted).
        4. Feed GapQueue with new evidence.
        5. Handle routing hook if needed.
        6. Record lineage.

        Args:
            ticket: The demotion ticket to apply.
            slice_root: Root of the slice worktree.

        Returns:
            Application result dict.
        """
        result: dict[str, Any] = {
            "ticket_id": ticket.ticket_id,
            "applied": False,
            "patches": [],
            "gap_evidence_added": 0,
        }

        # 1. Apply patch
        if ticket.recommended_spec_patch:
            patch_path = self._write_patch(
                ticket, slice_root, ticket.recommended_spec_patch, "spec"
            )
            result["patches"].append(str(patch_path))
            result["applied"] = True
        elif ticket.recommended_code_patch and ticket.target_layer == "L3":
            patch_path = self._write_patch(
                ticket, slice_root, ticket.recommended_code_patch, "code"
            )
            result["patches"].append(str(patch_path))
            result["applied"] = True
        else:
            # Generate minimal gap stub
            stub_path = self._generate_gap_stub(ticket, slice_root)
            if stub_path:
                result["patches"].append(str(stub_path))
                result["applied"] = True

        # 2. Create gap evidence entries
        gap_evidence = self._create_gap_evidence(ticket)
        result["gap_evidence_added"] = len(gap_evidence)

        # 3. Handle routing hook
        if ticket.routing_required and ticket.routing_payload:
            routing_item = RoutingItem(
                text=ticket.routing_payload.get("text", ""),
                source_path=ticket.routing_payload.get("source_path"),
                desired_slice_hint=ticket.routing_payload.get("desired_slice_hint"),
                tags=ticket.routing_payload.get("tags", []),
            )
            result["routing_item"] = routing_item.item_id

        # 4. Update status
        ticket.apply_status = "APPLIED" if result["applied"] else "BLOCKED"

        # 5. Record lineage
        self._record_lineage(ticket, slice_root, result)

        return result

    def _write_patch(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
        patch_content: str,
        patch_type: str,
    ) -> Path:
        """Write a patch file to the slice worktree."""
        patches_dir = slice_root / ".pdd_demotions"
        patches_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patches_dir / f"{ticket.ticket_id}_{patch_type}.patch"
        patch_path.write_text(patch_content, encoding="utf-8")
        ticket.applied_patch_paths.append(str(patch_path))
        return patch_path

    def _generate_gap_stub(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
    ) -> Path | None:
        """Generate a minimal spec comment stub for the failing item."""
        if not ticket.failing_files:
            return None

        stubs_dir = slice_root / ".pdd_demotions"
        stubs_dir.mkdir(parents=True, exist_ok=True)
        stub_path = stubs_dir / f"{ticket.ticket_id}_stub.txt"

        lines = [
            f"# DEMOTION: {ticket.ticket_id}",
            f"# Source: {ticket.source}",
            f"# Gate: {ticket.gate or 'N/A'}",
            f"# Severity: {ticket.severity}",
            f"# Diagnosis: {ticket.diagnosis}",
            "",
            "# Failing items:",
        ]
        for pin in ticket.failing_pins:
            lines.append(f"#   Pin: {pin}")
        for atom in ticket.failing_atoms:
            lines.append(f"#   Atom: {atom}")
        for f in ticket.failing_files:
            lines.append(f"#   File: {f}")
        if ticket.questions:
            lines.append("")
            lines.append("# Open questions:")
            for q in ticket.questions:
                lines.append(f"#   - {q}")

        stub_path.write_text("\n".join(lines), encoding="utf-8")
        ticket.applied_patch_paths.append(str(stub_path))
        return stub_path

    def _create_gap_evidence(
        self, ticket: DemotionTicket
    ) -> list[dict[str, Any]]:
        """Create GapEvidence entries from a demotion ticket."""
        evidence = []
        for file_path in ticket.failing_files:
            evidence.append({
                "source": f"demotion:{ticket.ticket_id}",
                "file": file_path,
                "description": ticket.diagnosis,
                "severity": ticket.severity,
                "gate": ticket.gate,
            })
        return evidence

    def _record_lineage(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
        result: dict[str, Any],
    ) -> None:
        """Write demotion lineage record."""
        lineage_dir = slice_root / ".pdd_demotions"
        lineage_dir.mkdir(parents=True, exist_ok=True)
        lineage_path = lineage_dir / f"{ticket.ticket_id}_lineage.json"
        lineage_path.write_text(
            json.dumps(
                {
                    "ticket": ticket.to_dict(),
                    "result": result,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
