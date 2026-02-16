"""Scoring framework for PDD pipeline runs.

Computes hard gates and soft signals mechanically from stored artifacts
(EvidenceBundles, CI receipts, demotion ledger, approval artifacts).

Hard gates block the pipeline:
- ``gates.final_pass`` — all required promotion gates PASS at final iteration
- ``ci.final_pass`` — dirty→clean CI PASS at required tier
- ``governance.no_fail`` — governance status != FAIL
- ``alignment.no_high`` — no HIGH-severity POWER drift/reward hacking
- ``l3.no_behavior_change`` — L3 diff-impact classifier = refactor_only

Soft signals provide diagnostics:
- ``l1.gap_closure`` — 1 - (final_open_gaps / initial_open_gaps); PASS=1.0, WARN>=0.99, FAIL<0.99
- ``l1.gate_first_attempt_rate`` — first-attempt pass / slices;
  PASS>=0.6, WARN>=0.4
- ``l2.pin_consumption_rate`` — consumed_pins / promoted_pins_in_scope; PASS=1.0, WARN>=0.95
- ``l2.component_coverage`` — implemented_components / manifest_components; PASS=1.0, WARN>=0.98
- ``l2.gate_first_attempt_rate`` — first-attempt pass / slices; PASS>=0.5, WARN>=0.3
- ``l3.reviewer_first_pass_rate`` — first-review pass / files;
  PASS>=0.4, WARN>=0.2
- ``l3.refactor_churn`` — changed_LOC / total_LOC in touched files; PASS<=0.15, WARN<=0.30
- ``pipeline.total_demotions`` — total tickets emitted; PASS<=(slices*0.5), WARN<=(slices*1.0)
- ``pipeline.iteration_efficiency`` — total_iterations / total_slices; PASS<=3, WARN<=6
- ``pipeline.ci_first_pass_rate`` — first-attempt dirty->clean pass;
  PASS>=0.8, WARN>=0.6
- ``pipeline.stagnation_rate`` — stagnated_slices / total_slices; PASS=0, WARN<=0.05
- ``pipeline.governance_compliance`` — governance FAIL/WARN findings + missing receipts
- ``pipeline.blocking_under_spec_rate`` — under-spec BLOCKED events / total slices

Usage::

    reporter = RunReporter(
        workspace_root=Path("."),
        run_id="abc",
    )
    scorecard = reporter.compute()
    reporter.write(scorecard)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScorecardMetric:
    """A single scorecard metric."""

    name: str = ""
    raw: float = 0.0
    score: float = 0.0  # 0.0-1.0 normalized
    status: str = "PASS"  # PASS | WARN | FAIL
    hard_gate: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Scorecard:
    """Complete scorecard for a run."""

    run_id: str = ""
    hard_gates: list[ScorecardMetric] = field(default_factory=list)
    soft_signals: list[ScorecardMetric] = field(default_factory=list)
    overall_pass: bool = True
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "overall_pass": self.overall_pass,
            "summary": self.summary,
            "hard_gates": [m.to_dict() for m in self.hard_gates],
            "soft_signals": [m.to_dict() for m in self.soft_signals],
        }


@dataclass
class SliceArtifact:
    """Normalized latest evidence snapshot for one slice."""

    slice_id: str
    layer: str
    status: str
    iterations: int
    remaining_gaps: int
    initial_gaps: int
    demotion_count: int
    gate_passed: bool
    first_attempt_pass: bool
    promoted_pins: int
    consumed_pins: int
    changed_loc: int
    total_loc: int
    behavior_change_findings: int
    governance_fail_findings: int
    governance_warn_findings: int
    governance_receipts_missing: int
    under_spec_blocker_events: int
    stagnation_detected: bool
    max_iterations_hit: bool
    l3_first_review_total_files: int
    l3_first_review_passed_files: int
    bundle_path: str


@dataclass
class ArtifactSnapshot:
    """Artifact snapshot loaded from run-scoped evidence."""

    l1_slices: list[SliceArtifact] = field(default_factory=list)
    l2_slices: list[SliceArtifact] = field(default_factory=list)
    l3_slices: list[SliceArtifact] = field(default_factory=list)
    ci_receipts: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    demotion_count: int = 0
    alignment: dict[str, Any] = field(default_factory=dict)
    manifest_components: int = 0
    implemented_components: int = 0


@dataclass
class BundleProjection:
    """Stable projection of bundle fields consumed by scoring."""

    status: str
    iteration: int
    gate_pass_states: list[bool]
    has_gate_records: bool
    open_gaps: list[dict[str, Any]]
    demotions_emitted: list[dict[str, Any]]
    pin_proposals: list[dict[str, Any]]
    changed_files: list[str]
    manifest_files: list[dict[str, Any]]
    source_entries: list[dict[str, Any]]
    patch_path: str
    verification_path: str
    promotion_path: str
    under_spec_blockers: list[dict[str, Any]]
    stagnation_is_stagnant: bool


class RunReporter:
    """Aggregates evidence and computes scorecard."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._run_dir = workspace_root / ".pdd_runs" / run_id
        self._reports_dir = workspace_root / "reports" / "pdd" / run_id

    def compute(self, *, quality_scorecard: dict[str, Any] | None = None) -> Scorecard:
        """Compute scorecard from persisted run-scoped artifacts."""
        artifacts = self._collect_artifacts()
        hard_gates = self._compute_hard_gates(artifacts)
        soft_signals = self._compute_soft_signals(artifacts)
        quality_payload = quality_scorecard or self._load_quality_scorecard()
        if quality_payload:
            soft_signals.extend(self._promote_quality_signals(quality_payload))
        overall_pass = all(g.status != "FAIL" for g in hard_gates)

        failing_gates = [g.name for g in hard_gates if g.status == "FAIL"]
        warnings = [s.name for s in soft_signals if s.status == "WARN"]
        summary_parts = []
        if overall_pass:
            summary_parts.append("All hard gates PASS.")
        else:
            summary_parts.append(f"FAIL: {', '.join(failing_gates)}")
        if warnings:
            summary_parts.append(f"Warnings: {', '.join(warnings)}")

        return Scorecard(
            run_id=self.run_id,
            hard_gates=hard_gates,
            soft_signals=soft_signals,
            overall_pass=overall_pass,
            summary=" ".join(summary_parts),
        )

    def _collect_artifacts(self) -> ArtifactSnapshot:
        """Load evidence bundles, CI receipts, approvals, and demotion ledger."""
        histories = self._load_slice_histories()
        latest_slices: list[SliceArtifact] = []
        for slice_id, bundles in histories.items():
            latest_slices.append(self._slice_artifact_from_history(slice_id, bundles))

        l1_slices = [s for s in latest_slices if s.layer == "l1"]
        l2_slices = [s for s in latest_slices if s.layer == "l2"]
        l3_slices = [s for s in latest_slices if s.layer == "l3"]

        manifest_components = self._load_manifest_components_count()
        implemented_components = sum(1 for s in l2_slices if s.status == "COMPLETE")

        return ArtifactSnapshot(
            l1_slices=l1_slices,
            l2_slices=l2_slices,
            l3_slices=l3_slices,
            ci_receipts=self._load_ci_receipts(),
            approvals=self._load_approval_artifacts(),
            demotion_count=self._load_demotion_count(),
            alignment=self._load_alignment_report(),
            manifest_components=manifest_components,
            implemented_components=implemented_components,
        )

    def _load_slice_histories(self) -> dict[str, list[tuple[int, dict[str, Any], Path]]]:
        """Return all bundle.json snapshots grouped by slice and sorted by iteration."""
        run_slices_dir = self._run_dir / "slices"
        if not run_slices_dir.exists():
            return {}

        histories: dict[str, list[tuple[int, dict[str, Any], Path]]] = {}
        for bundle_path in sorted(run_slices_dir.glob("*/iter_*/bundle.json")):
            try:
                payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Skipping unreadable bundle: %s", bundle_path, exc_info=True)
                continue
            slice_id = bundle_path.parent.parent.name
            iteration = self._iter_from_dir(bundle_path.parent.name)
            histories.setdefault(slice_id, []).append((iteration, payload, bundle_path))

        for entries in histories.values():
            entries.sort(key=lambda item: item[0])
        return histories

    @staticmethod
    def _iter_from_dir(iter_dir_name: str) -> int:
        if iter_dir_name.startswith("iter_"):
            try:
                return int(iter_dir_name.split("_", 1)[1])
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _slice_layer(slice_id: str) -> str:
        if slice_id.startswith("arch-"):
            return "l2"
        if slice_id.startswith("cq-"):
            return "l3"
        return "l1"

    @staticmethod
    def _project_bundle(bundle: dict[str, Any]) -> BundleProjection:
        gates_section = bundle.get("gates")
        gates_rows = (gates_section or {}).get("gates") if isinstance(gates_section, dict) else []
        gate_pass_states = [
            bool(row.get("passed", False)) for row in gates_rows if isinstance(row, dict)
        ]

        gaps_section = bundle.get("gaps")
        open_gaps = (gaps_section or {}).get("open_gaps") if isinstance(gaps_section, dict) else []
        stagnation = (
            (gaps_section or {}).get("stagnation") if isinstance(gaps_section, dict) else {}
        )

        demotions_section = bundle.get("demotions")
        demotions_emitted = (
            (demotions_section or {}).get("emitted") if isinstance(demotions_section, dict) else []
        )

        implementation_section = bundle.get("implementation")
        pin_proposals = (
            (implementation_section or {}).get("pin_proposals")
            if isinstance(implementation_section, dict)
            else []
        )
        patch_path = str(
            (implementation_section or {}).get("patch_path", "")
            if isinstance(implementation_section, dict)
            else ""
        ).strip()

        diff_section = bundle.get("diff")
        changed_files_raw = (
            (diff_section or {}).get("changed_files") if isinstance(diff_section, dict) else []
        )
        changed_files = [
            str(path).strip()
            for path in changed_files_raw
            if isinstance(path, str) and str(path).strip()
        ]

        manifest_section = bundle.get("manifest")
        manifest_files = (
            (manifest_section or {}).get("files") if isinstance(manifest_section, dict) else []
        )

        source_index = bundle.get("source_index")
        source_entries = (
            (source_index or {}).get("entries") if isinstance(source_index, dict) else []
        )

        verification_section = bundle.get("verification")
        verification_path = str(
            (verification_section or {}).get("path", "")
            if isinstance(verification_section, dict)
            else ""
        ).strip()

        promotion_section = bundle.get("promotion")
        promotion_path = str(
            (promotion_section or {}).get("path", "") if isinstance(promotion_section, dict) else ""
        ).strip()

        under_spec_section = bundle.get("under_spec")
        under_spec_blockers = (
            (under_spec_section or {}).get("blockers")
            if isinstance(under_spec_section, dict)
            else []
        )

        iteration_raw = bundle.get("iteration", 0)
        try:
            iteration = int(iteration_raw)
        except (TypeError, ValueError):
            iteration = 0

        return BundleProjection(
            status=str(bundle.get("status", "")).strip().upper(),
            iteration=max(iteration, 0),
            gate_pass_states=gate_pass_states,
            has_gate_records=bool(gate_pass_states),
            open_gaps=[gap for gap in open_gaps if isinstance(gap, dict)]
            if isinstance(open_gaps, list)
            else [],
            demotions_emitted=[item for item in demotions_emitted if isinstance(item, dict)]
            if isinstance(demotions_emitted, list)
            else [],
            pin_proposals=[item for item in pin_proposals if isinstance(item, dict)]
            if isinstance(pin_proposals, list)
            else [],
            changed_files=changed_files,
            manifest_files=[item for item in manifest_files if isinstance(item, dict)]
            if isinstance(manifest_files, list)
            else [],
            source_entries=[item for item in source_entries if isinstance(item, dict)]
            if isinstance(source_entries, list)
            else [],
            patch_path=patch_path,
            verification_path=verification_path,
            promotion_path=promotion_path,
            under_spec_blockers=[item for item in under_spec_blockers if isinstance(item, dict)]
            if isinstance(under_spec_blockers, list)
            else [],
            stagnation_is_stagnant=bool(stagnation.get("is_stagnant", False))
            if isinstance(stagnation, dict)
            else False,
        )

    @staticmethod
    def _bundle_passed_gates(bundle: BundleProjection) -> bool:
        if not bundle.has_gate_records:
            return False
        return all(bundle.gate_pass_states)

    def _slice_artifact_from_history(
        self,
        slice_id: str,
        bundles: list[tuple[int, dict[str, Any], Path]],
    ) -> SliceArtifact:
        """Build normalized per-slice metrics from bundle history."""
        first_iter, first_bundle, first_path = bundles[0]
        latest_iter, latest_bundle, latest_path = bundles[-1]
        first_projection = self._project_bundle(first_bundle)
        latest_projection = self._project_bundle(latest_bundle)

        layer = self._slice_layer(slice_id)
        latest_gaps = latest_projection.open_gaps
        first_gaps = first_projection.open_gaps
        demotions = latest_projection.demotions_emitted
        pin_proposals = latest_projection.pin_proposals
        status = latest_projection.status
        iterations = max(1, latest_projection.iteration or latest_iter or 1)
        behavior_change_findings = sum(
            1
            for gap in latest_gaps
            if isinstance(gap, dict) and gap.get("required_change_type") == "behavior_change"
        )
        first_attempt_pass = (
            first_iter == 1
            and first_projection.status == "COMPLETE"
            and self._bundle_passed_gates(first_projection)
        )
        changed_loc, total_loc = self._compute_loc_metrics(
            layer=layer,
            bundle=latest_projection,
            bundle_path=latest_path,
        )
        governance_fail, governance_warn, governance_missing = self._governance_findings(
            latest_projection,
            latest_path,
        )
        under_spec_blockers = self._under_spec_blocker_events(latest_projection)
        stagnation_detected, max_iterations_hit = self._stagnation_flags(
            layer=layer,
            bundle=latest_projection,
            iterations=iterations,
            remaining_gaps=len(latest_gaps),
        )
        l3_review_total = 0
        l3_review_passed = 0
        if layer == "l3":
            l3_review_total, l3_review_passed = self._l3_first_review_file_counts(
                first_projection,
                first_path,
            )

        return SliceArtifact(
            slice_id=slice_id,
            layer=layer,
            status=status,
            iterations=iterations,
            remaining_gaps=len(latest_gaps),
            initial_gaps=len(first_gaps),
            demotion_count=len(demotions),
            gate_passed=self._bundle_passed_gates(latest_projection),
            first_attempt_pass=first_attempt_pass,
            promoted_pins=len(pin_proposals),
            consumed_pins=len(pin_proposals) if status == "COMPLETE" else 0,
            changed_loc=changed_loc,
            total_loc=total_loc,
            behavior_change_findings=behavior_change_findings,
            governance_fail_findings=governance_fail,
            governance_warn_findings=governance_warn,
            governance_receipts_missing=governance_missing,
            under_spec_blocker_events=under_spec_blockers,
            stagnation_detected=stagnation_detected,
            max_iterations_hit=max_iterations_hit,
            l3_first_review_total_files=l3_review_total,
            l3_first_review_passed_files=l3_review_passed,
            bundle_path=str(latest_path),
        )

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _ci_receipt_passed(receipt: dict[str, Any]) -> bool:
        failed = receipt.get("failed")
        if isinstance(failed, bool):
            return not failed
        failure_evidence = receipt.get("failure_evidence")
        if isinstance(failure_evidence, dict):
            if not bool(failure_evidence.get("batch_success", True)):
                return False
            if not bool(failure_evidence.get("gates_passed", True)):
                return False
            if not bool(failure_evidence.get("tests_passed", True)):
                return False
            propagation_failures = failure_evidence.get("propagation_failures", [])
            if isinstance(propagation_failures, list) and any(propagation_failures):
                return False
        return True

    def _compute_loc_metrics(
        self,
        *,
        layer: str,
        bundle: BundleProjection,
        bundle_path: Path,
    ) -> tuple[int, int]:
        # L3 has file-level structural metrics + patch artifacts; prefer those.
        if layer == "l3":
            changed_loc = self._patch_changed_loc(bundle=bundle, bundle_path=bundle_path)
            total_loc = 0
            touched_total_loc = 0
            touched_files: set[str] = set()
            for path in bundle.changed_files:
                touched_files.add(path)

            for entry in bundle.source_entries:
                rel_path = str(entry.get("path", "")).strip()
                if not rel_path or rel_path.startswith("__"):
                    continue
                analysis = entry.get("analysis", {})
                if not isinstance(analysis, dict):
                    continue
                metrics = analysis.get("metrics", {})
                if not isinstance(metrics, dict):
                    continue
                line_count = max(self._as_int(metrics.get("lines"), 0), 0)
                if line_count <= 0:
                    continue
                total_loc += line_count

                diff_summary = analysis.get("diff_summary", {})
                changed_from_previous = False
                present_in_manifest_diff = False
                if isinstance(diff_summary, dict):
                    changed_from_previous = bool(
                        diff_summary.get("changed_from_previous_iteration", False)
                    )
                    present_in_manifest_diff = bool(
                        diff_summary.get("present_in_manifest_diff", False)
                    )
                if changed_from_previous or present_in_manifest_diff or rel_path in touched_files:
                    touched_total_loc += line_count

            if total_loc <= 0:
                total_loc = max(1, len(bundle.manifest_files))
            if touched_total_loc > 0:
                total_loc = touched_total_loc
            if changed_loc <= 0 and touched_total_loc > 0:
                changed_loc = touched_total_loc
            return max(changed_loc, 0), max(total_loc, 1)

        return (
            len(bundle.changed_files),
            max(1, len(bundle.manifest_files)),
        )

    def _patch_changed_loc(self, *, bundle: BundleProjection, bundle_path: Path) -> int:
        patch_ref = bundle.patch_path
        if not patch_ref:
            return 0
        patch_path = bundle_path.parent / patch_ref
        if not patch_path.exists():
            return 0
        try:
            lines = patch_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return 0
        changed = 0
        for line in lines:
            if line.startswith("+++ ") or line.startswith("--- "):
                continue
            if line.startswith("+") or line.startswith("-"):
                changed += 1
        return changed

    def _governance_findings(
        self, bundle: BundleProjection, bundle_path: Path
    ) -> tuple[int, int, int]:
        fail_messages: set[str] = set()
        warn_messages: set[str] = set()
        iteration_dir = bundle_path.parent

        verification_ref = bundle.verification_path
        if verification_ref:
            verification_payload = self._read_json_dict(iteration_dir / verification_ref)
            rows = verification_payload.get("findings", [])
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                category = str(row.get("category", "")).strip().lower()
                dimension = str(row.get("dimension", "")).strip().upper()
                if category != "governance" and dimension != "GOVERNANCE":
                    continue
                severity = str(row.get("severity", "MINOR")).strip().upper()
                message = str(row.get("evidence") or row.get("description") or "governance finding")
                if severity in {"BLOCKER", "MAJOR"}:
                    fail_messages.add(f"verification:{message}")
                else:
                    warn_messages.add(f"verification:{message}")

        quality_path = iteration_dir / "quality.receipts.json"
        missing_receipts = 0
        quality_payload = self._read_json_dict(quality_path)
        receipt_rows = quality_payload.get("receipts", []) if quality_payload else []
        governance_receipts_seen = False
        for receipt in receipt_rows if isinstance(receipt_rows, list) else []:
            if not isinstance(receipt, dict):
                continue
            dimension = str(receipt.get("dimension", "")).strip().upper()
            if dimension != "GOVERNANCE":
                continue
            governance_receipts_seen = True
            status = str(receipt.get("status", "")).strip().upper()
            reviewer = str(receipt.get("reviewer_id", "governance-reviewer")).strip()
            if status == "FAIL":
                fail_messages.add(f"quality:{reviewer}")
        if not quality_path.exists() or not governance_receipts_seen:
            missing_receipts = 1

        promotion_ref = bundle.promotion_path
        if promotion_ref:
            promotion_payload = self._read_json_dict(iteration_dir / promotion_ref)
            dirty_clean = (
                promotion_payload.get("dirty_clean_governance", {})
                if isinstance(promotion_payload, dict)
                else {}
            )
            if isinstance(dirty_clean, dict):
                failures = dirty_clean.get("failures", [])
                warnings = dirty_clean.get("warnings", [])
                for failure in failures if isinstance(failures, list) else []:
                    failure_text = str(failure).strip()
                    if failure_text:
                        fail_messages.add(f"promotion:{failure_text}")
                for warning in warnings if isinstance(warnings, list) else []:
                    warning_text = str(warning).strip()
                    if warning_text:
                        warn_messages.add(f"promotion:{warning_text}")

        return len(fail_messages), len(warn_messages), missing_receipts

    def _under_spec_blocker_events(self, bundle: BundleProjection) -> int:
        blocker_count = len(bundle.under_spec_blockers)
        status = bundle.status
        if blocker_count == 0 and status == "BLOCKED":
            blocker_count = 1
        return blocker_count

    @staticmethod
    def _layer_max_iterations(layer: str) -> int:
        limits = {"l1": 20, "l2": 30, "l3": 15}
        return limits.get(layer, 20)

    def _stagnation_flags(
        self,
        *,
        layer: str,
        bundle: BundleProjection,
        iterations: int,
        remaining_gaps: int,
    ) -> tuple[bool, bool]:
        stagnant = bundle.stagnation_is_stagnant
        status = bundle.status
        max_hit = (
            status == "FAILED"
            and remaining_gaps > 0
            and iterations >= self._layer_max_iterations(layer)
            and not stagnant
        )
        return stagnant or max_hit, max_hit

    def _l3_first_review_file_counts(
        self,
        first_bundle: BundleProjection,
        first_path: Path,
    ) -> tuple[int, int]:
        candidate_files: set[str] = set()
        for entry in first_bundle.source_entries:
            rel_path = str(entry.get("path", "")).strip()
            if rel_path and not rel_path.startswith("__"):
                candidate_files.add(rel_path)
        if not candidate_files:
            for item in first_bundle.manifest_files:
                rel_path = str(item.get("path", "")).strip()
                if rel_path:
                    candidate_files.add(rel_path)

        by_file: dict[str, list[str]] = defaultdict(list)
        for file_path in sorted(candidate_files):
            by_file[file_path] = []

        quality_payload = self._read_json_dict(first_path.parent / "quality.receipts.json")
        receipts = quality_payload.get("receipts", [])
        for receipt in receipts if isinstance(receipts, list) else []:
            if not isinstance(receipt, dict):
                continue
            rel_path = str(receipt.get("file") or receipt.get("target_file") or "").strip()
            if not rel_path:
                continue
            if candidate_files and rel_path not in candidate_files:
                continue
            status = str(receipt.get("status", "")).strip().upper()
            by_file[rel_path].append("PASS" if status == "PASS" else "FAIL")

        total_files = len(by_file)
        passed_files = sum(
            1
            for statuses in by_file.values()
            if statuses and all(status == "PASS" for status in statuses)
        )
        return total_files, passed_files

    def _load_ci_receipts(self) -> list[dict[str, Any]]:
        """Load all run-scoped CI batch receipts."""
        receipts: list[dict[str, Any]] = []
        ci_dir = self._run_dir / "ci"
        if not ci_dir.exists():
            return receipts

        for order, receipt_path in enumerate(sorted(ci_dir.glob("*/batches/*.json"))):
            try:
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Skipping unreadable CI receipt: %s", receipt_path, exc_info=True)
                continue
            if isinstance(payload, dict):
                payload["_path"] = str(receipt_path)
                payload["_order"] = order
                receipts.append(payload)
        return receipts

    def _load_approval_artifacts(self) -> list[dict[str, Any]]:
        """Load all approval decision artifacts for this run."""
        approvals: list[dict[str, Any]] = []
        approvals_root = self._run_dir / "approvals"
        if not approvals_root.exists():
            return approvals

        for decision_path in sorted(approvals_root.glob("**/decision.json")):
            try:
                payload = json.loads(decision_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "Skipping unreadable approval decision: %s",
                    decision_path,
                    exc_info=True,
                )
                continue
            if isinstance(payload, dict):
                payload["_path"] = str(decision_path)
                approvals.append(payload)
        return approvals

    def _load_demotion_count(self) -> int:
        """Count demotion tickets from authoritative ledger."""
        ledger_path = self._run_dir / "demotions" / "ledger.jsonl"
        if not ledger_path.exists():
            return 0
        count = 0
        try:
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                json.loads(line)
                count += 1
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse demotion ledger at %s", ledger_path, exc_info=True)
        return count

    def _load_alignment_report(self) -> dict[str, Any]:
        """Load POWER alignment report from run-scoped reports directory."""
        path = self._reports_dir / "alignment_report.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse alignment report at %s", path, exc_info=True)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_manifest_components_count(self) -> int:
        """Load component count from run-scoped component manifest."""
        path = self._reports_dir / "component_manifest.json"
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse component manifest at %s", path, exc_info=True)
            return 0
        components = payload.get("components", []) if isinstance(payload, dict) else []
        return len(components) if isinstance(components, list) else 0

    def _load_quality_scorecard(self) -> dict[str, Any] | None:
        """Load run-scoped quality scorecard when available."""
        path = self._reports_dir / "quality_scorecard.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read quality scorecard at %s", path, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _promote_quality_signals(self, quality: dict[str, Any]) -> list[ScorecardMetric]:
        """Promote stable quality scorecard metrics into run-level diagnostics."""
        promoted: list[ScorecardMetric] = []

        arch_score = self._as_float(quality.get("arch_quality_score"))
        if arch_score is not None:
            dimensions = quality.get("architecture_judge_dimensions")
            dim_count = len(dimensions) if isinstance(dimensions, list) else 0
            promoted.append(
                ScorecardMetric(
                    name="architecture.llm_quality",
                    raw=arch_score,
                    score=arch_score,
                    status=_quality_status(arch_score),
                    detail=f"judge_dimensions={dim_count}",
                )
            )

        code_score = self._as_float(quality.get("code_quality_score"))
        if code_score is not None:
            risk_count = (
                len(quality.get("code_risks", []))
                if isinstance(quality.get("code_risks"), list)
                else 0
            )
            promoted.append(
                ScorecardMetric(
                    name="code.llm_quality",
                    raw=code_score,
                    score=code_score,
                    status=_quality_status(code_score),
                    detail=f"systemic_risks={risk_count}",
                )
            )

        sampled_files = quality.get("code_sampled_files")
        if isinstance(sampled_files, list):
            sampled_count = len([item for item in sampled_files if isinstance(item, dict)])
            if sampled_count >= 3:
                sampled_status = "PASS"
            elif sampled_count > 0:
                sampled_status = "WARN"
            else:
                sampled_status = "FAIL"
            promoted.append(
                ScorecardMetric(
                    name="code.sampled_file_coverage",
                    raw=float(sampled_count),
                    score=min(sampled_count / 8.0, 1.0),
                    status=sampled_status,
                    detail=f"sampled_files={sampled_count}",
                )
            )

        return promoted

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def write(self, scorecard: Scorecard) -> tuple[Path, Path]:
        """Write scores.json and final_report.md."""
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Machine-readable
        scores_path = self._reports_dir / "scores.json"
        scores_path.write_text(json.dumps(scorecard.to_dict(), indent=2), encoding="utf-8")

        # Human-readable
        md_path = self._reports_dir / "final_report.md"
        md_path.write_text(self._render_markdown(scorecard), encoding="utf-8")

        return scores_path, md_path

    def _compute_hard_gates(self, artifacts: ArtifactSnapshot) -> list[ScorecardMetric]:
        """Compute hard gate metrics from persisted artifacts."""
        gates: list[ScorecardMetric] = []
        all_slices = artifacts.l1_slices + artifacts.l2_slices + artifacts.l3_slices

        # 1. gates.final_pass: all required promotion gates pass
        all_slices_passed = all(s.status == "COMPLETE" and s.gate_passed for s in all_slices)
        gates.append(
            ScorecardMetric(
                name="gates.final_pass",
                raw=1.0 if all_slices_passed else 0.0,
                score=1.0 if all_slices_passed else 0.0,
                status="PASS" if all_slices_passed else "FAIL",
                hard_gate=True,
                evidence_refs=[s.bundle_path for s in all_slices[:20]],
            )
        )

        # 2. ci.final_pass: latest dirty->clean CI receipt per slice/layer must PASS
        expected_keys = {(s.layer, s.slice_id) for s in all_slices}
        latest_ci: dict[tuple[str, str], bool] = {}
        for receipt in artifacts.ci_receipts:
            layer = str(receipt.get("layer", "")).strip().lower()
            slice_id = str(receipt.get("slice_id", "")).strip()
            key = (layer, slice_id)
            if key not in expected_keys:
                continue
            latest_ci[key] = self._ci_receipt_passed(receipt)
        missing_ci_keys = sorted(expected_keys - set(latest_ci.keys()))
        ci_passed = (
            all(latest_ci.get(key, False) for key in expected_keys) if expected_keys else True
        )
        if not artifacts.ci_receipts and expected_keys:
            ci_passed = False
        gates.append(
            ScorecardMetric(
                name="ci.final_pass",
                raw=1.0 if ci_passed else 0.0,
                score=1.0 if ci_passed else 0.0,
                status="PASS" if ci_passed else "FAIL",
                hard_gate=True,
                evidence_refs=[
                    str(r.get("_path", "")) for r in artifacts.ci_receipts[:20] if r.get("_path")
                ],
                detail=(
                    "latest_passed="
                    f"{sum(1 for ok in latest_ci.values() if ok)}/{len(expected_keys)}"
                    f"; missing_receipts={len(missing_ci_keys)}"
                ),
            )
        )

        # 3. governance.no_fail: no governance FAIL findings
        governance_fail_count = sum(s.governance_fail_findings for s in all_slices)
        governance_warn_count = sum(s.governance_warn_findings for s in all_slices)
        governance_missing_receipts = sum(s.governance_receipts_missing for s in all_slices)
        governance_ok = governance_fail_count == 0
        gates.append(
            ScorecardMetric(
                name="governance.no_fail",
                raw=1.0 if governance_ok else 0.0,
                score=1.0 if governance_ok else 0.0,
                status="PASS" if governance_ok else "FAIL",
                hard_gate=True,
                evidence_refs=[s.bundle_path for s in all_slices[:20]],
                detail=(
                    f"fail={governance_fail_count}; warn={governance_warn_count}; "
                    f"missing_receipts={governance_missing_receipts}"
                ),
            )
        )

        # 4. alignment.no_high: no HIGH-severity POWER findings
        drift_findings = int(artifacts.alignment.get("drift_findings", 0) or 0)
        reward_findings = int(artifacts.alignment.get("reward_hacking_findings", 0) or 0)
        alignment_ok = (drift_findings + reward_findings) == 0
        gates.append(
            ScorecardMetric(
                name="alignment.no_high",
                raw=1.0 if alignment_ok else 0.0,
                score=1.0 if alignment_ok else 0.0,
                status="PASS" if alignment_ok else "FAIL",
                hard_gate=True,
                evidence_refs=[str(self._reports_dir / "alignment_report.json")],
            )
        )

        # 5. l3.no_behavior_change: L3 didn't introduce behavior changes
        l3_ok = all(
            s.status == "COMPLETE" and s.behavior_change_findings == 0 for s in artifacts.l3_slices
        )
        gates.append(
            ScorecardMetric(
                name="l3.no_behavior_change",
                raw=1.0 if l3_ok else 0.0,
                score=1.0 if l3_ok else 0.0,
                status="PASS" if l3_ok else "FAIL",
                hard_gate=True,
                evidence_refs=[s.bundle_path for s in artifacts.l3_slices[:20]],
            )
        )

        return gates

    def _compute_soft_signals(self, artifacts: ArtifactSnapshot) -> list[ScorecardMetric]:
        """Compute run diagnostics from persisted artifacts."""
        signals: list[ScorecardMetric] = []

        # ------------------------------------------------------------------
        # Gather per-layer slice lists
        # ------------------------------------------------------------------
        l1_slices = artifacts.l1_slices
        l2_slices = artifacts.l2_slices
        l3_slices = artifacts.l3_slices
        all_slices = l1_slices + l2_slices + l3_slices

        total_slices = len(all_slices)
        safe_total = max(total_slices, 1)

        # Aggregate stats across all layers
        total_iterations = sum(s.iterations for s in all_slices)
        slice_demotions = sum(s.demotion_count for s in all_slices)
        total_demotions = max(slice_demotions, artifacts.demotion_count)
        stagnated_count = sum(1 for s in all_slices if s.stagnation_detected)
        governance_fail_count = sum(s.governance_fail_findings for s in all_slices)
        governance_warn_count = sum(s.governance_warn_findings for s in all_slices)
        governance_missing_receipts = sum(s.governance_receipts_missing for s in all_slices)
        under_spec_blocked_events = sum(s.under_spec_blocker_events for s in all_slices)

        # ------------------------------------------------------------------
        # 1. l1.gap_closure — 1 - (final_open_gaps / initial_open_gaps)
        #    PASS = 1.0, WARN >= 0.99, FAIL < 0.99
        # ------------------------------------------------------------------
        initial_gaps = 0
        final_gaps = 0
        for s in l1_slices:
            s_initial = s.initial_gaps
            s_final = s.remaining_gaps
            if s.status == "COMPLETE":
                s_final = 0
            initial_gaps += s_initial
            final_gaps += s_final

        gap_closure_raw = 1.0 - (final_gaps / initial_gaps) if initial_gaps > 0 else 1.0

        if gap_closure_raw >= 1.0:
            gap_status = "PASS"
        elif gap_closure_raw >= 0.99:
            gap_status = "WARN"
        else:
            gap_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l1.gap_closure",
                raw=gap_closure_raw,
                score=gap_closure_raw,
                status=gap_status,
            )
        )

        # ------------------------------------------------------------------
        # 2. l1.gate_first_attempt_rate — slices passing all gates on first
        #    promote attempt / total L1 slices.
        #    PASS >= 0.6, WARN >= 0.4, FAIL < 0.4
        # ------------------------------------------------------------------
        l1_total = max(len(l1_slices), 1)
        l1_first_attempt = sum(1 for s in l1_slices if s.first_attempt_pass)
        l1_first_rate = l1_first_attempt / l1_total

        if l1_first_rate >= 0.6:
            l1_first_status = "PASS"
        elif l1_first_rate >= 0.4:
            l1_first_status = "WARN"
        else:
            l1_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l1.gate_first_attempt_rate",
                raw=l1_first_rate,
                score=l1_first_rate,
                status=l1_first_status,
            )
        )

        # ------------------------------------------------------------------
        # 3. l2.pin_consumption_rate — consumed_pins / promoted_pins_in_scope
        #    PASS = 1.0, WARN >= 0.95, FAIL < 0.95
        #    Extract from L2 slice gate data if available, else default 1.0.
        # ------------------------------------------------------------------
        total_promoted_pins = 0
        total_consumed_pins = 0
        for s in l2_slices:
            promoted = s.promoted_pins
            consumed = s.consumed_pins
            total_promoted_pins += promoted
            total_consumed_pins += consumed

        pin_detail = ""
        if total_promoted_pins > 0:
            pin_rate = total_consumed_pins / total_promoted_pins
            if pin_rate >= 1.0:
                pin_status = "PASS"
            elif pin_rate >= 0.95:
                pin_status = "WARN"
            else:
                pin_status = "FAIL"
            pin_detail = f"consumed={total_consumed_pins}; promoted={total_promoted_pins}"
        else:
            pin_rate = 0.0
            pin_status = "WARN"
            pin_detail = "missing_pin_evidence=promoted_pins"

        signals.append(
            ScorecardMetric(
                name="l2.pin_consumption_rate",
                raw=pin_rate,
                score=min(pin_rate, 1.0),
                status=pin_status,
                detail=pin_detail,
            )
        )

        # ------------------------------------------------------------------
        # 4. l2.component_coverage — implemented_components / manifest_components
        #    PASS = 1.0, WARN >= 0.98, FAIL < 0.98
        #    Extract from L2 results if manifest data exists, else default 1.0.
        # ------------------------------------------------------------------
        manifest_components = artifacts.manifest_components
        implemented_components = artifacts.implemented_components

        if manifest_components > 0:
            comp_coverage = implemented_components / manifest_components
            comp_detail = f"implemented={implemented_components}; manifest={manifest_components}"
            if comp_coverage >= 1.0:
                comp_status = "PASS"
            elif comp_coverage >= 0.98:
                comp_status = "WARN"
            else:
                comp_status = "FAIL"
        else:
            comp_coverage = 0.0
            comp_status = "WARN"
            comp_detail = "missing_component_manifest=true"

        signals.append(
            ScorecardMetric(
                name="l2.component_coverage",
                raw=comp_coverage,
                score=min(comp_coverage, 1.0),
                status=comp_status,
                detail=comp_detail,
            )
        )

        # ------------------------------------------------------------------
        # 5. l2.gate_first_attempt_rate — first-attempt pass / L2 slices
        #    PASS >= 0.5, WARN >= 0.3, FAIL < 0.3
        # ------------------------------------------------------------------
        l2_total = max(len(l2_slices), 1)
        l2_first_attempt = sum(1 for s in l2_slices if s.first_attempt_pass)
        l2_first_rate = l2_first_attempt / l2_total

        if l2_first_rate >= 0.5:
            l2_first_status = "PASS"
        elif l2_first_rate >= 0.3:
            l2_first_status = "WARN"
        else:
            l2_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l2.gate_first_attempt_rate",
                raw=l2_first_rate,
                score=l2_first_rate,
                status=l2_first_status,
            )
        )

        # ------------------------------------------------------------------
        # 6. l3.reviewer_first_pass_rate — files passing all reviewers on
        #    first review / total L3 files.
        #    PASS >= 0.4, WARN >= 0.2, FAIL < 0.2
        # ------------------------------------------------------------------
        l3_file_total = sum(s.l3_first_review_total_files for s in l3_slices)
        l3_first_pass = sum(s.l3_first_review_passed_files for s in l3_slices)
        l3_first_rate = l3_first_pass / l3_file_total if l3_file_total > 0 else 0.0

        if l3_first_rate >= 0.4:
            l3_first_status = "PASS"
        elif l3_first_rate >= 0.2:
            l3_first_status = "WARN"
        else:
            l3_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l3.reviewer_first_pass_rate",
                raw=l3_first_rate,
                score=l3_first_rate,
                status=l3_first_status,
                detail=f"files={l3_first_pass}/{l3_file_total}",
            )
        )

        # ------------------------------------------------------------------
        # 7. l3.refactor_churn — changed_LOC / total_LOC in touched files
        #    PASS <= 0.15, WARN <= 0.30, FAIL > 0.30
        #    Look in L3 slice results for change metrics if available.
        # ------------------------------------------------------------------
        total_changed_loc = 0
        total_loc = 0
        for s in l3_slices:
            total_changed_loc += s.changed_loc
            total_loc += s.total_loc

        churn_raw = total_changed_loc / total_loc if total_loc > 0 else 0.0

        if churn_raw <= 0.15:
            churn_status = "PASS"
        elif churn_raw <= 0.30:
            churn_status = "WARN"
        else:
            churn_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l3.refactor_churn",
                raw=churn_raw,
                score=max(0.0, 1.0 - churn_raw),
                status=churn_status,
            )
        )

        # ------------------------------------------------------------------
        # 8. pipeline.total_demotions — total tickets emitted
        #    PASS <= (slices * 0.5), WARN <= (slices * 1.0), FAIL > slices * 1.0
        # ------------------------------------------------------------------
        demotion_pass_threshold = safe_total * 0.5
        demotion_warn_threshold = safe_total * 1.0

        if total_demotions <= demotion_pass_threshold:
            demo_status = "PASS"
        elif total_demotions <= demotion_warn_threshold:
            demo_status = "WARN"
        else:
            demo_status = "FAIL"

        # Score: 1.0 when 0 demotions, 0.0 when demotions >= 2 * slices
        demo_score = max(0.0, 1.0 - total_demotions / max(safe_total * 2.0, 1.0))
        signals.append(
            ScorecardMetric(
                name="pipeline.total_demotions",
                raw=float(total_demotions),
                score=demo_score,
                status=demo_status,
            )
        )

        # ------------------------------------------------------------------
        # 9. pipeline.iteration_efficiency — total_iterations / total_slices
        #    PASS <= 3, WARN <= 6, FAIL > 6
        # ------------------------------------------------------------------
        iter_ratio = total_iterations / safe_total

        if iter_ratio <= 3.0:
            iter_status = "PASS"
        elif iter_ratio <= 6.0:
            iter_status = "WARN"
        else:
            iter_status = "FAIL"

        # Score: 1.0 at ratio 1, 0.0 at ratio >= 10
        iter_score = max(0.0, 1.0 - (iter_ratio - 1.0) / 9.0) if iter_ratio >= 1.0 else 1.0
        signals.append(
            ScorecardMetric(
                name="pipeline.iteration_efficiency",
                raw=iter_ratio,
                score=iter_score,
                status=iter_status,
            )
        )

        # ------------------------------------------------------------------
        # 10. pipeline.ci_first_pass_rate — successful dirty->clean on first
        #     attempt / total promotions.
        #     PASS >= 0.8, WARN >= 0.6, FAIL < 0.6
        # ------------------------------------------------------------------
        ci_total = 0
        ci_first_pass = 0
        ci_detail = ""
        if artifacts.ci_receipts:
            known_slice_ids = {s.slice_id for s in all_slices}
            ordered_receipts = sorted(
                artifacts.ci_receipts,
                key=lambda receipt: self._as_int(receipt.get("_order"), 0),
            )
            first_seen: dict[tuple[str, str], bool] = {}
            latest_seen: dict[tuple[str, str], bool] = {}
            for receipt in ordered_receipts:
                layer = str(receipt.get("layer", "")).strip().lower()
                slice_id = str(receipt.get("slice_id", "")).strip()
                if not layer or slice_id not in known_slice_ids:
                    continue
                key = (layer, slice_id)
                passed = self._ci_receipt_passed(receipt)
                if key not in first_seen:
                    first_seen[key] = passed
                latest_seen[key] = passed

            ci_total = len(first_seen)
            ci_first_pass = sum(1 for ok in first_seen.values() if ok)
            ci_rate = ci_first_pass / ci_total if ci_total > 0 else 0.0

            layer_parts: list[str] = []
            for layer_name in ("l1", "l2", "l3"):
                keys = [key for key in first_seen if key[0] == layer_name]
                layer_total = len(keys)
                if layer_total == 0:
                    layer_parts.append(f"{layer_name}:first=n/a,eventual=n/a,n=0")
                    continue
                first_rate = sum(1 for key in keys if first_seen.get(key, False)) / layer_total
                eventual_rate = sum(1 for key in keys if latest_seen.get(key, False)) / layer_total
                layer_parts.append(
                    f"{layer_name}:first={first_rate:.2f},eventual={eventual_rate:.2f},n={layer_total}"
                )
            ci_detail = "; ".join(layer_parts)
        else:
            ci_rate = 0.0
            ci_status = "WARN"
            ci_detail = "ci_receipts_missing=true"

        if artifacts.ci_receipts:
            if ci_rate >= 0.8:
                ci_status = "PASS"
            elif ci_rate >= 0.6:
                ci_status = "WARN"
            else:
                ci_status = "FAIL"
        else:
            ci_status = "WARN"

        signals.append(
            ScorecardMetric(
                name="pipeline.ci_first_pass_rate",
                raw=ci_rate,
                score=ci_rate,
                status=ci_status,
                detail=ci_detail,
            )
        )

        # ------------------------------------------------------------------
        # 11. pipeline.stagnation_rate — stagnated_slices / total_slices
        #     PASS = 0, WARN <= 0.05, FAIL > 0.05
        # ------------------------------------------------------------------
        stag_rate = stagnated_count / safe_total

        if stag_rate == 0.0:
            stag_status = "PASS"
        elif stag_rate <= 0.05:
            stag_status = "WARN"
        else:
            stag_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="pipeline.stagnation_rate",
                raw=stag_rate,
                score=1.0 - stag_rate,
                status=stag_status,
                detail=f"stagnated_slices={stagnated_count}; total_slices={total_slices}",
            )
        )

        # ------------------------------------------------------------------
        # 12. pipeline.governance_compliance — governance FAIL/WARN findings
        #     plus missing governance receipts.
        # ------------------------------------------------------------------
        governance_incidents = (
            governance_fail_count + governance_warn_count + governance_missing_receipts
        )
        if governance_fail_count > 0:
            governance_status = "FAIL"
        elif governance_warn_count > 0 or governance_missing_receipts > 0:
            governance_status = "WARN"
        else:
            governance_status = "PASS"
        governance_score = 1.0 / (1.0 + float(governance_incidents))
        signals.append(
            ScorecardMetric(
                name="pipeline.governance_compliance",
                raw=float(governance_incidents),
                score=governance_score,
                status=governance_status,
                detail=(
                    f"fail={governance_fail_count}; warn={governance_warn_count}; "
                    f"missing_receipts={governance_missing_receipts}"
                ),
            )
        )

        # ------------------------------------------------------------------
        # 13. pipeline.blocking_under_spec_rate — under-spec BLOCKED events
        #     per slice.
        # ------------------------------------------------------------------
        under_spec_rate = under_spec_blocked_events / safe_total
        if under_spec_rate == 0.0:
            under_spec_status = "PASS"
        elif under_spec_rate <= 0.10:
            under_spec_status = "WARN"
        else:
            under_spec_status = "FAIL"
        signals.append(
            ScorecardMetric(
                name="pipeline.blocking_under_spec_rate",
                raw=under_spec_rate,
                score=max(0.0, 1.0 - under_spec_rate),
                status=under_spec_status,
                detail=f"blocked_events={under_spec_blocked_events}; total_slices={total_slices}",
            )
        )

        return signals

    @staticmethod
    def _render_markdown(scorecard: Scorecard) -> str:
        """Back-compat wrapper delegating rendering to ScorecardRenderer."""
        return ScorecardRenderer.render_markdown(scorecard)


class ScorecardRenderer:
    """Render scorecards into human-readable formats."""

    @staticmethod
    def render_markdown(scorecard: Scorecard) -> str:
        """Render scorecard as markdown."""
        lines = [
            f"# Scorecard — Run {scorecard.run_id}",
            "",
            f"**Overall**: {'PASS' if scorecard.overall_pass else 'FAIL'}",
            f"**Summary**: {scorecard.summary}",
            "",
            "## Hard Gates",
            "",
            "| Gate | Status | Score |",
            "|------|--------|-------|",
        ]
        for g in scorecard.hard_gates:
            lines.append(f"| {g.name} | {g.status} | {g.score:.2f} |")

        lines.extend(
            [
                "",
                "## Soft Signals",
                "",
                "| Signal | Status | Score | Raw |",
                "|--------|--------|-------|-----|",
            ]
        )
        for s in scorecard.soft_signals:
            lines.append(f"| {s.name} | {s.status} | {s.score:.2f} | {s.raw:.1f} |")

        lines.append("")
        return "\n".join(lines)


def _quality_status(score: float) -> str:
    if score >= 0.80:
        return "PASS"
    if score >= 0.65:
        return "WARN"
    return "FAIL"
