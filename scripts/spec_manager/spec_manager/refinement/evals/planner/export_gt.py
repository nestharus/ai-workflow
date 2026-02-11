"""Export ground truth template from planner traces.

Reads traces for a run, groups by ``decision_key``, and emits a YAML
template with observed outputs as candidate expected variants.  Each
case is marked ``review_status: TODO`` for expert curation.

Usage::

    exporter = GroundTruthExporter(workspace_root)
    exporter.export(run_id="treasury-eval-1", out_path=Path("gt.yaml"))
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExportedCase:
    """One ground truth case derived from a trace."""

    decision_key: str = ""
    capability: str = ""
    layer: str = ""
    slice_id: str = ""
    iteration: int = 0
    trace_id: str = ""
    observed_status: str = ""
    observed_outputs: dict[str, Any] = field(default_factory=dict)
    review_status: str = "TODO"


class GroundTruthExporter:
    """Exports a ground truth template from planner traces."""

    def __init__(self, workspace_root: Path) -> None:
        self._workspace = workspace_root

    def export(
        self,
        run_id: str,
        out_path: Path,
        *,
        spec_id: str = "chaotic_treasury_expanded",
    ) -> Path:
        """Read traces for *run_id* and write a GT template to *out_path*."""
        from spec_manager.refinement.evals.planner.trace_loader import (
            filter_traces,
            load_index,
            load_trace,
        )

        entries = load_index(self._workspace)
        run_entries = filter_traces(entries, run_id=run_id) if run_id else entries

        # Group by decision_key (first occurrence wins if duplicates)
        seen_keys: set[str] = set()
        cases: list[ExportedCase] = []

        for entry in run_entries:
            if entry.decision_key in seen_keys:
                continue
            seen_keys.add(entry.decision_key)

            try:
                trace = load_trace(self._workspace, entry.trace_id)
            except Exception:
                logger.warning("Skipping trace %s: load failed", entry.trace_id)
                continue

            outputs = trace.artifacts.get("outputs", {})
            parts = entry.decision_key.split(":") if entry.decision_key else []

            cases.append(ExportedCase(
                decision_key=entry.decision_key,
                capability=parts[1] if len(parts) > 1 else entry.capability,
                layer=parts[0] if parts else entry.layer,
                slice_id=parts[2] if len(parts) > 2 else entry.slice_id,
                iteration=int(parts[3]) if len(parts) > 3 else 0,
                trace_id=entry.trace_id,
                observed_status=entry.status,
                observed_outputs=outputs,
            ))

        # Build the GT template
        gt_doc = self._build_template(spec_id, cases)

        # Write output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_yaml_or_json(out_path, gt_doc)

        logger.info(
            "Exported %d GT cases from %d traces → %s",
            len(cases),
            len(run_entries),
            out_path,
        )
        return out_path

    def _build_template(
        self, spec_id: str, cases: list[ExportedCase]
    ) -> dict[str, Any]:
        """Build a GT document dict from exported cases."""
        doc: dict[str, Any] = {
            "meta": {
                "spec_id": spec_id,
                "gt_version": 1,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%d"),
                "notes": "Auto-exported from planner traces. Review each case.",
            },
            "cases": [],
        }

        for case in cases:
            entry: dict[str, Any] = {
                "decision_key": case.decision_key,
                "capability": case.capability,
                "layer": case.layer,
                "slice_id": case.slice_id,
                "iteration": case.iteration,
                "review_status": case.review_status,
                "observed_trace_id": case.trace_id,
                "observed_status": case.observed_status,
                "expected": self._scaffold_expected(case),
            }
            doc["cases"].append(entry)

        return doc

    def _scaffold_expected(self, case: ExportedCase) -> dict[str, Any]:
        """Build a capability-specific expected scaffold from observed outputs."""
        cap = case.capability
        outputs = case.observed_outputs

        if cap == "RESOLVE_SIGNAL":
            response = outputs.get("response")
            return {
                "should_resolve": response is not None,
                "answers_any_of": [str(response)] if response else [],
            }

        if cap == "PLAN":
            intentions = outputs.get("intentions", [])
            must_include = []
            for i, intent in enumerate(intentions):
                fn = intent.get("function_name", intent.get("component_id", f"item_{i}"))
                match: dict[str, Any] = {}
                if intent.get("function_name"):
                    match["function_name_any_of"] = [intent["function_name"]]
                if intent.get("file"):
                    match["file_any_of"] = [intent["file"]]
                if intent.get("component_id"):
                    match["component_id_any_of"] = [intent["component_id"]]
                must_include.append({"id": f"obs:{fn}", "match": match})

            return {
                "outcome": {
                    "intentions": {
                        "must_include": must_include,
                        "must_not_include": [],
                    },
                },
                "invariants": [],
            }

        if cap == "UNDER_SPEC":
            blocked = outputs.get("blocked", False)
            questions = outputs.get("questions", [])
            events_gt = []
            for q in questions:
                events_gt.append({
                    "event_id": "",
                    "should_block": blocked,
                    "observed_question": q,
                })
            return {"events": events_gt}

        if cap == "GAP":
            discovery = outputs.get("discovery", {})
            return {
                "must_find": [],
                "must_not_find": [],
                "observed_discovery_keys": sorted(discovery.keys()) if isinstance(discovery, dict) else [],
            }

        if cap == "INTEGRATION_ANALYSIS":
            discovery = outputs.get("discovery", {})
            return {
                "must_include_risks": [],
                "must_not_include_risks": [],
                "observed_topology_keys": sorted(discovery.keys()) if isinstance(discovery, dict) else [],
            }

        return {"_raw_outputs": outputs}

    def _write_yaml_or_json(self, path: Path, doc: dict[str, Any]) -> None:
        """Write as YAML if pyyaml available, otherwise JSON."""
        try:
            import yaml

            text = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
            path.write_text(text, encoding="utf-8")
        except ImportError:
            path.write_text(
                json.dumps(doc, indent=2, sort_keys=False, default=str) + "\n",
                encoding="utf-8",
            )
