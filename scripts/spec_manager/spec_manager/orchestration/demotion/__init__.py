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

import difflib
import json
import logging
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.core.gap import GapEvidence, GapSynthesizer

logger = logging.getLogger(__name__)


@dataclass
class DemotionTicket:
    """A concrete demotion produced by gate/test/verify failure.

    Instead of skipping an atom that fails a gate, the system produces
    a DemotionTicket that becomes an actionable edit target at the
    appropriate layer.
    """

    ticket_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    run_id: str = ""
    slice_id: str = ""

    source: Literal[
        "ALGORITHMIC_GATE",
        "ARCH_GATE",
        "TEST_FAILURE",
        "LINEAGE",
        "REVIEW",
    ] = "ALGORITHMIC_GATE"
    category: str = ""  # style | maintainability | architecture | logic | drift | governance
    gate: str | None = None

    target_layer: Literal["L1", "L2", "L3"] = "L1"
    severity: Literal["BLOCKER", "MAJOR", "MINOR"] = "BLOCKER"

    # Multi-layer traceability
    origin_layer: Literal["L1", "L2", "L3"] = "L1"
    hop_trace: list[Literal["L1", "L2", "L3"]] = field(default_factory=list)

    failing_pins: list[str] = field(default_factory=list)
    failing_atoms: list[str] = field(default_factory=list)
    failing_files: list[str] = field(default_factory=list)
    component_id: str | None = None
    symbol_span_anchors: list[dict[str, Any]] = field(default_factory=list)

    diagnosis: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    investigator_report_ref: str = ""

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
        return cls(
            **{
                k: v
                for k, v in data.items()
                if k in {f.name for f in __import__("dataclasses").fields(cls)}
            }
        )


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

    def __init__(
        self,
        workspace_root: Path,
        run_id: str = "",
        *,
        gap_queue: Any | None = None,
        branch_manager: Any | None = None,
        routing_callback: Callable[[list[RoutingItem], Path], list[RoutedPatch]] | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._gap_queue = gap_queue
        self._branch_manager = branch_manager
        self._routing_callback = routing_callback

    def apply(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
        *,
        gap_queue: Any | None = None,
        branch_manager: Any | None = None,
        routing_callback: Callable[[list[RoutingItem], Path], list[RoutedPatch]] | None = None,
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
            "registry_updates": [],
            "routing_patches": [],
            "errors": [],
        }
        if not ticket.hop_trace:
            ticket.hop_trace = [ticket.origin_layer, ticket.target_layer]

        # 1. Apply patch directly in the slice worktree
        if ticket.recommended_spec_patch:
            applied, patch_path, patch_error = self._apply_recommended_patch(
                ticket, slice_root, ticket.recommended_spec_patch, "spec"
            )
            if patch_path:
                result["patches"].append(str(patch_path))
            if patch_error:
                result["errors"].append(patch_error)
            result["applied"] = bool(applied)
        elif ticket.recommended_code_patch and ticket.target_layer == "L3":
            applied, patch_path, patch_error = self._apply_recommended_patch(
                ticket, slice_root, ticket.recommended_code_patch, "code"
            )
            if patch_path:
                result["patches"].append(str(patch_path))
            if patch_error:
                result["errors"].append(patch_error)
            result["applied"] = bool(applied)
        else:
            # Generate minimal in-file L1 annotation so GAP_EXPLORATION can see it.
            annotation_path = self._generate_gap_stub(ticket, slice_root)
            if annotation_path:
                result["patches"].append(str(annotation_path))
                result["applied"] = True

        # 2. Update branch/pin metadata registries
        registry_updates = self._update_registries(ticket, branch_manager=branch_manager)
        if registry_updates:
            result["registry_updates"] = registry_updates

        # 3. Convert demotion into GapQueue evidence
        gap_evidence = self._create_gap_evidence(ticket, result.get("patches", []))
        result["gap_evidence_added"] = len(gap_evidence)
        self._feed_gap_queue(gap_evidence, gap_queue=gap_queue)

        # 4. Handle routing hook with partial Phase 0 routing
        if ticket.routing_required and ticket.routing_payload:
            routed, routing_item_id = self._route_ticket(
                ticket,
                slice_root=slice_root,
                routing_callback=routing_callback,
            )
            result["routing_item"] = routing_item_id
            if routed:
                result["routing_patches"] = routed
                result["patches"].extend(routed)
                result["applied"] = True

        # 5. Update status
        ticket.apply_status = "APPLIED" if result["applied"] else "BLOCKED"

        # 6. Record lineage
        self._record_lineage(ticket, slice_root, result)

        # 7. Append to demotion ledger (JSONL)
        self._append_to_ledger(ticket, result)

        return result

    def _patch_dir(self, slice_root: Path) -> Path:
        patches_dir = slice_root / ".pdd_demotions"
        patches_dir.mkdir(parents=True, exist_ok=True)
        return patches_dir

    def _write_patch(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
        patch_content: str,
        patch_type: str,
    ) -> Path:
        """Write a patch file to the slice worktree."""
        patches_dir = self._patch_dir(slice_root)
        patch_path = patches_dir / f"{ticket.ticket_id}_{patch_type}.patch"
        patch_path.write_text(patch_content, encoding="utf-8")
        return patch_path

    def _apply_recommended_patch(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
        patch_content: str,
        patch_type: str,
    ) -> tuple[bool, Path | None, str]:
        """Persist and apply a unified diff to the actual slice worktree."""
        patch_path = self._write_patch(ticket, slice_root, patch_content, patch_type)

        # Prefer git apply when slice_root is inside a git worktree.
        check_cmd = ["git", "apply", "--check", str(patch_path)]
        apply_cmd = ["git", "apply", str(patch_path)]
        check = subprocess.run(
            check_cmd,
            cwd=slice_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode == 0:
            apply = subprocess.run(
                apply_cmd,
                cwd=slice_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if apply.returncode == 0:
                ticket.applied_patch_paths.append(str(patch_path))
                return True, patch_path, ""
            return False, patch_path, apply.stderr.strip() or "git apply failed"

        # Fallback to `patch` for environments where git apply is unavailable.
        try:
            fallback_check = subprocess.run(
                ["patch", "--dry-run", "-p0", "-i", str(patch_path)],
                cwd=slice_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            err = check.stderr.strip() or "git apply failed and patch command is unavailable"
            return False, patch_path, err
        if fallback_check.returncode != 0:
            err = check.stderr.strip() or fallback_check.stderr.strip() or "patch --dry-run failed"
            return False, patch_path, err

        fallback_apply = subprocess.run(
            ["patch", "-p0", "-i", str(patch_path)],
            cwd=slice_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if fallback_apply.returncode != 0:
            err = fallback_apply.stderr.strip() or "patch apply failed"
            return False, patch_path, err

        ticket.applied_patch_paths.append(str(patch_path))
        return True, patch_path, ""

    @staticmethod
    def _comment_prefix(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp"}:
            return "//"
        if suffix in {".sql", ".lua"}:
            return "--"
        return "#"

    def _generate_gap_stub(
        self,
        ticket: DemotionTicket,
        slice_root: Path,
    ) -> Path | None:
        """Insert a minimal in-file SPEC REQUIRED annotation in L1 code-as-spec."""
        target_file = ""
        if ticket.symbol_span_anchors:
            for anchor in ticket.symbol_span_anchors:
                if isinstance(anchor, dict) and str(anchor.get("file", "")).strip():
                    target_file = str(anchor["file"]).strip()
                    break
        if not target_file and ticket.failing_files:
            target_file = str(ticket.failing_files[0]).strip()
        if not target_file:
            return None

        file_path = Path(target_file)
        resolved = file_path if file_path.is_absolute() else (slice_root / file_path)
        if not resolved.exists() or not resolved.is_file():
            return None

        original = resolved.read_text(encoding="utf-8")
        lines = original.splitlines()
        prefix = self._comment_prefix(resolved)
        insertion = [
            f"{prefix} SPEC REQUIRED [{ticket.ticket_id}]",
            (
                f"{prefix} source={ticket.source} gate={ticket.gate or 'N/A'} "
                f"severity={ticket.severity}"
            ),
        ]
        if ticket.failing_pins:
            insertion.append(f"{prefix} failing_pins={', '.join(ticket.failing_pins)}")
        if ticket.failing_atoms:
            insertion.append(f"{prefix} failing_atoms={', '.join(ticket.failing_atoms)}")
        if ticket.diagnosis:
            insertion.append(f"{prefix} diagnosis={ticket.diagnosis[:300]}")
        for question in ticket.questions:
            insertion.append(f"{prefix} question={question}")
        insertion.append("")

        insert_line = len(lines)
        for anchor in ticket.symbol_span_anchors:
            if not isinstance(anchor, dict):
                continue
            anchor_file = str(anchor.get("file", "")).strip()
            if anchor_file and Path(anchor_file) != file_path and anchor_file != str(file_path):
                continue
            start_line_raw = anchor.get("start_line")
            if isinstance(start_line_raw, int) and start_line_raw > 0:
                insert_line = min(max(start_line_raw - 1, 0), len(lines))
                break

        new_lines = [*lines[:insert_line], *insertion, *lines[insert_line:]]
        updated = "\n".join(new_lines)
        if original.endswith("\n"):
            updated += "\n"
        resolved.write_text(updated, encoding="utf-8")

        patch_text = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path),
            )
        )
        patch_path = self._write_patch(ticket, slice_root, patch_text, "spec_required")
        ticket.applied_patch_paths.append(str(patch_path))
        return patch_path

    def _create_gap_evidence(
        self,
        ticket: DemotionTicket,
        applied_patch_paths: list[str],
    ) -> list[GapEvidence]:
        """Create canonical GapEvidence entries from a demotion ticket."""
        evidence: list[GapEvidence] = []
        targets: list[str] = []
        targets.extend([path for path in ticket.failing_files if path])
        targets.extend([path for path in applied_patch_paths if path])
        if not targets:
            targets = ["demotion:unknown_target"]
        seen: set[str] = set()
        for file_path in targets:
            if file_path in seen:
                continue
            seen.add(file_path)
            details: dict[str, Any] = {
                "source": [f"demotion:{ticket.ticket_id}"],
                "derived_artifact_target": file_path,
                "ticket_id": ticket.ticket_id,
                "source_kind": ticket.source,
                "gate": ticket.gate or "",
                "severity": ticket.severity,
                "failing_pins": list(ticket.failing_pins),
                "failing_atoms": list(ticket.failing_atoms),
                "component_id": ticket.component_id,
                "symbol_span_anchors": list(ticket.symbol_span_anchors),
                "evidence_refs": list(ticket.evidence_refs),
            }
            evidence.append(
                GapEvidence(
                    invariant_family="demotion_ticket",
                    description=ticket.diagnosis or "Demotion ticket generated new gap evidence",
                    details=details,
                    location=file_path,
                    detector="demotion.manager",
                )
            )
        return evidence

    def _feed_gap_queue(self, evidence: list[GapEvidence], *, gap_queue: Any | None = None) -> None:
        queue = gap_queue if gap_queue is not None else self._gap_queue
        if queue is None or not evidence:
            return
        from spec_manager.compliance.detection.orchestrator import (
            ExecutableGapReport,
            integrate_with_gap_queue,
        )

        report = ExecutableGapReport(all_evidence=evidence)
        integrate_with_gap_queue(report, queue, GapSynthesizer())

    @staticmethod
    def _normalize_atom_id(atom_id: str) -> str:
        value = str(atom_id).strip()
        if value.startswith("PIN-ATOM-"):
            return value.removeprefix("PIN-ATOM-")
        return value

    def _update_registries(
        self, ticket: DemotionTicket, *, branch_manager: Any | None = None
    ) -> list[str]:
        """Best-effort demotion metadata updates in branch/pin registries."""
        manager = branch_manager if branch_manager is not None else self._branch_manager
        if manager is None:
            return []

        updates: list[str] = []
        demote_atom = getattr(manager, "demote_atom", None)
        if callable(demote_atom):
            for atom_id in ticket.failing_atoms:
                normalized = self._normalize_atom_id(atom_id)
                if not normalized:
                    continue
                try:
                    demote_atom(normalized, to_layer=ticket.target_layer)
                    updates.append(
                        f"branch_manager.demote_atom({normalized}->{ticket.target_layer})"
                    )
                except Exception as exc:
                    logger.warning("Failed demote_atom(%s): %s", normalized, exc)
        else:
            get_atom = getattr(manager, "get_atom", None)
            register_atom = getattr(manager, "register_atom", None)
            if callable(get_atom) and callable(register_atom):
                for atom_id in ticket.failing_atoms:
                    normalized = self._normalize_atom_id(atom_id)
                    if not normalized:
                        continue
                    atom = get_atom(normalized)
                    if atom is None:
                        continue
                    marker = f"demoted:{ticket.ticket_id}:{ticket.target_layer}"
                    modified = list(getattr(atom, "modified_by", []) or [])
                    if marker not in modified:
                        modified.append(marker)
                        atom.modified_by = modified
                        try:
                            register_atom(atom)
                            updates.append(f"atom_registry.mark_demoted({normalized})")
                        except Exception as exc:
                            logger.warning(
                                "Failed to persist atom demotion marker for %s: %s", normalized, exc
                            )

        pin_registry = getattr(manager, "pin_registry", None)
        pin_update_methods = (
            "mark_dirty",
            "mark_pin_dirty",
            "mark_for_reverification",
            "mark_needs_reverification",
        )
        for method_name in pin_update_methods:
            method = getattr(pin_registry, method_name, None)
            if not callable(method):
                continue
            for pin_id in ticket.failing_pins:
                if not pin_id:
                    continue
                try:
                    method(pin_id)
                    updates.append(f"pin_registry.{method_name}({pin_id})")
                except Exception as exc:
                    logger.warning(
                        "Failed pin registry update %s(%s): %s", method_name, pin_id, exc
                    )
            break

        save = getattr(manager, "save", None)
        if callable(save) and updates:
            try:
                save()
            except Exception as exc:
                logger.warning("Failed to persist registry updates after demotion: %s", exc)
        return updates

    def _route_ticket(
        self,
        ticket: DemotionTicket,
        *,
        slice_root: Path,
        routing_callback: Callable[[list[RoutingItem], Path], list[RoutedPatch]] | None = None,
    ) -> tuple[list[str], str]:
        payload = ticket.routing_payload or {}
        item = RoutingItem(
            text=str(payload.get("text") or ticket.diagnosis).strip(),
            source_path=payload.get("source_path"),
            desired_slice_hint=payload.get("desired_slice_hint"),
            tags=[str(tag) for tag in payload.get("tags", []) if str(tag).strip()],
        )
        router = (
            routing_callback
            or self._routing_callback
            or __import__(
                "spec_manager.orchestration.intake_queue", fromlist=["route_items"]
            ).route_items
        )
        routed = router([item], self.workspace_root)
        applied_paths: list[str] = []
        for routed_patch in routed:
            path = str(routed_patch.unified_diff_path).strip()
            if not path:
                continue
            applied_paths.append(path)
            ticket.applied_patch_paths.append(path)
            # If routing produced a unified diff, apply it to the slice immediately.
            patch_file = Path(path)
            if patch_file.exists() and patch_file.is_file():
                temp_patch: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        delete=False,
                        dir=slice_root,
                        prefix="routed_",
                        suffix=".patch",
                    ) as handle:
                        content = patch_file.read_text(encoding="utf-8")
                        if content.lstrip().startswith("--- "):
                            handle.write(content)
                            temp_patch = Path(handle.name)
                        else:
                            temp_patch = None
                    if temp_patch is not None:
                        check = subprocess.run(
                            ["git", "apply", "--check", str(temp_patch)],
                            cwd=slice_root,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if check.returncode == 0:
                            apply = subprocess.run(
                                ["git", "apply", str(temp_patch)],
                                cwd=slice_root,
                                capture_output=True,
                                text=True,
                                check=False,
                            )
                            if apply.returncode == 0:
                                ticket.applied_patch_paths.append(str(temp_patch))
                            else:
                                logger.warning(
                                    "Failed applying routed patch %s: %s", temp_patch, apply.stderr
                                )
                except Exception as exc:
                    logger.warning(
                        "Failed processing routed patch artifact %s: %s", patch_file, exc
                    )
                finally:
                    if isinstance(temp_patch, Path) and temp_patch.exists():
                        temp_patch.unlink(missing_ok=True)
        return applied_paths, item.item_id

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

    def _append_to_ledger(
        self,
        ticket: DemotionTicket,
        result: dict[str, Any],
    ) -> None:
        """Append a JSONL entry and ticket artifact under the run demotions directory."""
        run_id = self.run_id or ticket.run_id
        if not run_id:
            return
        ledger_dir = self.workspace_root / ".pdd_runs" / run_id / "demotions"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        tickets_dir = ledger_dir / "tickets"
        tickets_dir.mkdir(parents=True, exist_ok=True)

        ticket_record = {
            "ticket": ticket.to_dict(),
            "result": {
                "applied": result.get("applied", False),
                "patches": result.get("patches", []),
                "gap_evidence_added": result.get("gap_evidence_added", 0),
                "registry_updates": result.get("registry_updates", []),
                "routing_patches": result.get("routing_patches", []),
                "errors": result.get("errors", []),
            },
        }
        ticket_path = tickets_dir / f"{ticket.ticket_id}.json"
        ticket_path.write_text(
            json.dumps(ticket_record, indent=2),
            encoding="utf-8",
        )

        ledger_path = ledger_dir / "ledger.jsonl"
        hop_trace = ticket.hop_trace or [ticket.origin_layer, ticket.target_layer]
        entry = {
            "ticket_id": ticket.ticket_id,
            "run_id": run_id,
            "slice_id": ticket.slice_id,
            "created_at": ticket.created_at,
            "source": ticket.source,
            "category": ticket.category,
            "gate": ticket.gate,
            "origin_layer": ticket.origin_layer,
            "target_layer": ticket.target_layer,
            "hop_trace": hop_trace,
            "severity": ticket.severity,
            "diagnosis": ticket.diagnosis[:500],
            "evidence_refs": ticket.evidence_refs,
            "investigator_report_ref": ticket.investigator_report_ref,
            "failing_files": ticket.failing_files,
            "failing_pins": ticket.failing_pins,
            "failing_atoms": ticket.failing_atoms,
            "component_id": ticket.component_id,
            "symbol_span_anchors": ticket.symbol_span_anchors,
            "apply_status": ticket.apply_status,
            "resolution_status": ticket.apply_status,
            "applied": result.get("applied", False),
            "applied_patch_paths": result.get("patches", []),
            "ticket_artifact_path": str(ticket_path),
        }
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
