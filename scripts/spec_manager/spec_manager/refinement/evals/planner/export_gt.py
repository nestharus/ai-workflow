"""Export ground truth template from planner traces.

Reads traces for a run, groups by ``decision_key``, and emits a YAML
template with observed outputs as candidate expected variants.  Each
case is marked ``review_status: TODO`` for expert curation.

Usage::

    exporter = GroundTruthExporter(workspace_root)
    exporter.export(run_id="treasury-eval-1", out_path=Path("gt.yaml"))
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False
    yaml = None  # type: ignore[assignment]


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
    input_fingerprint: dict[str, str] = field(default_factory=dict)
    review_status: str = "TODO"
    load_error: str = ""


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
        phase0_gt_ref: str | None = None,
    ) -> Path:
        """Read traces for *run_id* and write a GT template to *out_path*."""
        from spec_manager.refinement.evals.planner.trace_loader import (
            TraceLoadDiagnostics,
            filter_traces,
            load_index,
            load_trace,
        )

        diagnostics = TraceLoadDiagnostics()
        entries = load_index(self._workspace, diagnostics=diagnostics)
        run_entries = filter_traces(entries, run_id=run_id) if run_id else entries

        # Group by decision_key (first occurrence wins if duplicates)
        seen_keys: set[str] = set()
        cases: list[ExportedCase] = []

        for entry in run_entries:
            if entry.decision_key in seen_keys:
                continue
            seen_keys.add(entry.decision_key)

            parts = entry.decision_key.split(":") if entry.decision_key else []
            capability = parts[1] if len(parts) > 1 else entry.capability
            layer = parts[0] if parts else entry.layer
            slice_id = parts[2] if len(parts) > 2 else entry.slice_id
            iteration = 0
            if len(parts) > 3:
                try:
                    iteration = int(parts[3])
                except (TypeError, ValueError):
                    logger.warning(
                        "Trace %s has invalid decision-key iteration %r; defaulting to 0",
                        entry.trace_id,
                        parts[3],
                    )

            try:
                trace = load_trace(self._workspace, entry.trace_id, diagnostics=diagnostics)
            except Exception as exc:
                logger.warning("Trace %s could not be loaded: %s", entry.trace_id, exc)
                cases.append(
                    ExportedCase(
                        decision_key=entry.decision_key,
                        capability=capability,
                        layer=layer,
                        slice_id=slice_id,
                        iteration=iteration,
                        trace_id=entry.trace_id,
                        observed_status=entry.status,
                        observed_outputs={},
                        input_fingerprint={},
                        review_status="LOAD_FAILED",
                        load_error=str(exc),
                    )
                )
                continue

            outputs = trace.artifacts.get("outputs", {})

            cases.append(
                ExportedCase(
                    decision_key=entry.decision_key,
                    capability=capability,
                    layer=layer,
                    slice_id=slice_id,
                    iteration=iteration,
                    trace_id=entry.trace_id,
                    observed_status=entry.status,
                    observed_outputs=outputs,
                    input_fingerprint=self._build_input_fingerprint(
                        trace=trace,
                        capability=capability,
                        layer=layer,
                        slice_id=slice_id,
                    ),
                )
            )

        # Build the GT template
        gt_doc = self._build_template(spec_id, cases, phase0_gt_ref=phase0_gt_ref)
        if diagnostics.issues:
            gt_doc["load_diagnostics"] = diagnostics.to_dict()

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
        self,
        spec_id: str,
        cases: list[ExportedCase],
        *,
        phase0_gt_ref: str | None = None,
    ) -> dict[str, Any]:
        """Build a GT document dict from exported cases."""
        doc: dict[str, Any] = {
            "meta": {
                "spec_id": spec_id,
                "gt_version": 1,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%d"),
                "phase0_gt_ref": phase0_gt_ref or f"{spec_id}_ground_truth.yaml",
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
                "input_fingerprint": dict(case.input_fingerprint),
                "review_status": case.review_status,
                "observed_trace_id": case.trace_id,
                "observed_status": case.observed_status,
                "expected": self._scaffold_expected(case),
                "process_expectations": [],
                "rubric": {
                    "hard_gates": [],
                    "soft_signals": [],
                },
            }
            if case.load_error:
                entry["load_error"] = case.load_error
            doc["cases"].append(entry)

        return doc

    def _build_input_fingerprint(
        self,
        *,
        trace: Any,
        capability: str,
        layer: str,
        slice_id: str,
    ) -> dict[str, str]:
        """Build capability-scoped input fingerprints for drift detection."""
        request = trace.request if isinstance(trace.request, dict) else {}
        inputs = request.get("inputs", {})
        if not isinstance(inputs, dict):
            inputs = {}

        metadata = request.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        outputs = trace.artifacts.get("outputs", {})
        if not isinstance(outputs, dict):
            outputs = {}

        fingerprint: dict[str, str] = {}
        request_input_hash = request.get("input_hash")
        if isinstance(request_input_hash, str) and request_input_hash:
            fingerprint["identity_inputs_hash"] = f"sha256:{request_input_hash}"

        cap = str(capability or "").upper()
        if cap == "RESOLVE_SIGNAL":
            signal = inputs.get("signal")
            signal_id = ""
            if isinstance(signal, dict):
                signal_id = str(
                    signal.get("signal_id") or signal.get("event_id") or signal.get("id") or ""
                )
            if signal_id:
                fingerprint["signal_id_hash"] = self._hash_payload(
                    {"signal_id": signal_id, "layer": layer}
                )
            else:
                signal_text = ""
                if isinstance(signal, dict):
                    signal_text = str(
                        signal.get("text")
                        or signal.get("question")
                        or signal.get("message")
                        or signal.get("summary")
                        or ""
                    )
                elif signal is not None:
                    signal_text = str(signal)
                if signal_text:
                    fingerprint["signal_text_hash"] = self._hash_payload(
                        {"signal_text": signal_text, "layer": layer}
                    )

        elif cap == "GAP":
            bundle = inputs.get("bundle", {})
            if not isinstance(bundle, dict):
                bundle = {}
            bundle_id = str(bundle.get("bundle_id") or bundle.get("id") or bundle.get("path") or "")
            if bundle_id:
                fingerprint["evidence_bundle_hash"] = self._hash_payload(bundle_id)

            open_gaps = self._extract_open_gaps(inputs, metadata)
            if open_gaps:
                fingerprint["open_gaps_hash"] = self._hash_payload(self._normalize_gaps(open_gaps))

        elif cap == "PLAN":
            gaps = inputs.get("gaps", [])
            if isinstance(gaps, list):
                fingerprint["gaps_hash"] = self._hash_payload(self._normalize_gaps(gaps))

            discovery_signature = (
                metadata.get("discovery_signature")
                or metadata.get("discovery_hash")
                or inputs.get("discovery_signature")
                or trace.artifacts.get("discovery")
                or outputs.get("discovery")
            )
            if discovery_signature:
                fingerprint["discovery_signature_hash"] = self._hash_payload(discovery_signature)
            fingerprint["slice_snapshot_hash"] = self._hash_payload(
                {"slice_id": slice_id, "layer": layer}
            )

        elif cap == "UNDER_SPEC":
            events = inputs.get("events", [])
            if isinstance(events, list):
                fingerprint["events_hash"] = self._hash_payload(self._normalize_events(events))

        elif cap == "INTEGRATION_ANALYSIS":
            fingerprint["slice_snapshot_hash"] = self._hash_payload(
                {"slice_id": slice_id, "layer": layer}
            )
            topology = (
                inputs.get("topology")
                or metadata.get("topology")
                or trace.artifacts.get("discovery")
                or outputs.get("discovery")
            )
            if topology:
                topology_files = self._extract_topology_files(topology)
                if topology_files:
                    fingerprint["topology_files_hash"] = self._hash_payload(topology_files)
            diffs = inputs.get("diffs") or metadata.get("diffs")
            if diffs:
                fingerprint["diffs_hash"] = self._hash_payload(diffs)

        if not fingerprint:
            fingerprint["input_payload_hash"] = self._hash_payload(inputs)
        return fingerprint

    @staticmethod
    def _extract_open_gaps(
        inputs: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        bundle = inputs.get("bundle", {})
        if isinstance(bundle, dict):
            bundle_gaps = bundle.get("gaps", {})
            if isinstance(bundle_gaps, dict):
                open_gaps = bundle_gaps.get("open_gaps", [])
                if isinstance(open_gaps, list):
                    return [g for g in open_gaps if isinstance(g, dict)]
        gaps = inputs.get("gaps", [])
        if isinstance(gaps, list):
            return [g for g in gaps if isinstance(g, dict)]
        meta_gaps = metadata.get("open_gaps", [])
        if isinstance(meta_gaps, list):
            return [g for g in meta_gaps if isinstance(g, dict)]
        return []

    @staticmethod
    def _normalize_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for gap in gaps:
            deps_raw = gap.get("dependencies", [])
            if isinstance(deps_raw, list):
                deps = [str(dep) for dep in deps_raw if dep is not None]
            elif deps_raw:
                deps = [str(deps_raw)]
            else:
                deps = []
            deps.sort()
            normalized.append(
                {
                    "target": str(gap.get("target", "") or gap.get("component_id", "") or ""),
                    "description": str(gap.get("description", "") or gap.get("gap", "") or ""),
                    "dependencies": deps,
                }
            )
        return sorted(
            normalized,
            key=lambda item: (
                item["target"],
                item["description"],
                ",".join(item["dependencies"]),
            ),
        )

    @staticmethod
    def _normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for event in events:
            key_context = event.get("key_context", event.get("context", {}))
            normalized.append(
                {
                    "event_id": str(event.get("event_id", "")),
                    "question": str(
                        event.get("question", "") or event.get("observed_question", "")
                    ),
                    "key_context": key_context
                    if isinstance(key_context, (dict, list, str))
                    else {},
                }
            )
        return sorted(
            normalized,
            key=lambda item: (
                item["event_id"],
                item["question"],
                GroundTruthExporter._canonical_json(item["key_context"]),
            ),
        )

    @staticmethod
    def _extract_topology_files(topology: Any) -> list[str]:
        if isinstance(topology, dict):
            files = topology.get("files")
            if isinstance(files, list):
                return sorted(str(f) for f in files)
            return sorted(str(k) for k in topology)
        if isinstance(topology, list):
            return sorted(str(item) for item in topology)
        return []

    @staticmethod
    def _canonical_json(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _hash_payload(cls, payload: Any) -> str:
        digest = hashlib.sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

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
                events_gt.append(
                    {
                        "event_id": "",
                        "should_block": blocked,
                        "observed_question": q,
                    }
                )
            return {"events": events_gt}

        if cap == "GAP":
            discovery = outputs.get("discovery", {})
            return {
                "must_find": [],
                "must_not_find": [],
                "observed_discovery_keys": sorted(discovery.keys())
                if isinstance(discovery, dict)
                else [],
            }

        if cap == "INTEGRATION_ANALYSIS":
            discovery = outputs.get("discovery", {})
            return {
                "must_include_risks": [],
                "must_not_include_risks": [],
                "observed_topology_keys": sorted(discovery.keys())
                if isinstance(discovery, dict)
                else [],
            }

        return {"_raw_outputs": outputs}

    def _write_yaml_or_json(self, path: Path, doc: dict[str, Any]) -> None:
        """Write canonical YAML output, failing if PyYAML is unavailable."""
        if not _HAS_YAML:
            raise RuntimeError(
                "PyYAML is required to export planner ground truth YAML. "
                "Install it with: pip install pyyaml"
            )
        text = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
        path.write_text(text, encoding="utf-8")
