"""Architecture assembler: builds L2 services/handlers from promoted atoms.

After atoms are promoted at L1 (pins exist), the architectural agent
builds services, event handlers, and middleware that compose those atoms.

The assembler:
1. Reads pin registry + adjacency graph snapshots.
2. Identifies missing projections / architecture entrypoints.
3. Calls the ``pdd-architecture-implementor`` agent per slice.
4. Applies architecture patches to L2 dirty worktree.
5. Merges projection proposals into the pin registry.
6. Writes evidence artifacts into the EvidenceBundle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PINS_CHARS = 5000
_MAX_GRAPH_CHARS = 5000
_MAX_ANALYSIS_CHARS = 3000
_MAX_CONSTRAINTS_CHARS = 2000
_MAX_EXISTING_FILES = 50


@dataclass
class ProjectionProposal:
    """LLM-proposed projection mapping atom pin to architecture function."""

    projection_id: str = ""
    projection_type: str = "PASS_THROUGH"  # PASS_THROUGH, EVENT_BRIDGE, STORE_FACADE, COMPOSITION
    from_pin: str = ""
    to_arch_fqn: str = ""
    file: str = ""
    span: dict[str, Any] | None = None
    evidence_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectionProposal:
        if "projection_type" not in d:
            raise ValueError("ProjectionProposal missing required field: projection_type")
        if "type" in d:
            raise ValueError("ProjectionProposal uses deprecated field: type")
        return cls(
            projection_id=d.get("projection_id", ""),
            projection_type=str(d["projection_type"]).strip() or "PASS_THROUGH",
            from_pin=d.get("from_pin", ""),
            to_arch_fqn=d.get("to_arch_fqn", ""),
            file=d.get("file", ""),
            span=d.get("span"),
            evidence_paths=d.get("evidence_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "projection_type": self.projection_type,
            "from_pin": self.from_pin,
            "to_arch_fqn": self.to_arch_fqn,
            "file": self.file,
            "span": self.span,
            "evidence_paths": self.evidence_paths,
        }


@dataclass
class ArchitectureAssemblyResult:
    """Result of running the architecture assembler on a slice."""

    patches_applied: list[dict[str, Any]] = field(default_factory=list)
    projection_proposals: list[dict[str, Any]] = field(default_factory=list)
    pin_proposals: list[dict[str, Any]] = field(default_factory=list)
    edge_proposals: list[dict[str, Any]] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""


@dataclass
class ArchitectureAgentCallResult:
    """Result of a single architecture-agent invocation."""

    payload: dict[str, Any] | None = None
    raw_output: str = ""
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)


class ArchitectureAssembler:
    """Builds L2 architecture from promoted L1 atoms.

    Args:
        workspace_root: Repository root.
        run_id: Current run identifier.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_id: str = "",
    ) -> None:
        self._workspace = workspace_root
        self._run_id = run_id

    def assemble_for_slice(
        self,
        *,
        slice_id: str,
        slice_root: Path,
        iteration_dir: Path,
        pins_snapshot_path: Path | None = None,
        graph_snapshot_path: Path | None = None,
        analysis_path: Path | None = None,
        constraints_path: Path | None = None,
    ) -> ArchitectureAssemblyResult:
        """Run architecture assembly for a single slice.

        Args:
            slice_id: Library/slice identifier.
            slice_root: Root of the slice worktree.
            iteration_dir: Directory for output artifacts.
            pins_snapshot_path: Path to PinRegistry snapshot.
            graph_snapshot_path: Path to AdjacencyGraph snapshot.
            analysis_path: Path to library analysis.md.
            constraints_path: Path to library constraints.md.

        Returns:
            ArchitectureAssemblyResult with all artifacts.
        """
        result = ArchitectureAssemblyResult()
        iteration_dir.mkdir(parents=True, exist_ok=True)

        # Build input context for the architecture agent
        input_context, context_events = self._build_agent_context(
            slice_id=slice_id,
            slice_root=slice_root,
            pins_snapshot_path=pins_snapshot_path,
            graph_snapshot_path=graph_snapshot_path,
            analysis_path=analysis_path,
            constraints_path=constraints_path,
        )
        result.under_spec_events.extend(context_events)

        # Call the architecture agent
        call_result = self._call_architecture_agent(input_context)
        result.under_spec_events.extend(call_result.under_spec_events)

        if call_result.payload is None:
            logger.warning("Architecture agent returned no output for slice '%s'", slice_id)
            self._write_artifacts(
                iteration_dir=iteration_dir,
                result=result,
                tests=[],
                prompt_context=input_context,
                raw_agent_output=call_result.raw_output,
            )
            return result

        payload_errors = self._validate_architecture_payload(call_result.payload)
        if payload_errors:
            result.under_spec_events.append(
                {
                    "kind": "ARCHITECTURE_OUTPUT_SCHEMA_VIOLATION",
                    "question": (
                        "Architecture agent output schema is invalid; "
                        "required keys/types are missing or malformed."
                    ),
                    "context": "\n".join(payload_errors),
                    "source": "ARCHITECTURE_ASSEMBLER",
                    "classification": "systematic",
                    "recovery": "demote",
                }
            )
            self._write_artifacts(
                iteration_dir=iteration_dir,
                result=result,
                tests=[],
                prompt_context=input_context,
                raw_agent_output=call_result.raw_output,
            )
            return result

        # Parse agent output
        result.patches_applied = list(call_result.payload["architecture_patch"])
        try:
            result.projection_proposals = [
                ProjectionProposal.from_dict(proposal).to_dict()
                for proposal in call_result.payload["projection_proposals"]
            ]
        except (TypeError, ValueError) as exc:
            result.under_spec_events.append(
                {
                    "kind": "ARCHITECTURE_OUTPUT_SCHEMA_VIOLATION",
                    "question": "Architecture projection proposal schema is invalid.",
                    "context": str(exc),
                    "source": "ARCHITECTURE_ASSEMBLER",
                    "classification": "systematic",
                    "recovery": "demote",
                }
            )
            self._write_artifacts(
                iteration_dir=iteration_dir,
                result=result,
                tests=[],
                prompt_context=input_context,
                raw_agent_output=call_result.raw_output,
            )
            return result
        result.pin_proposals = list(call_result.payload["pin_proposals"])
        result.edge_proposals = list(call_result.payload["edge_proposals"])
        result.under_spec_events.extend(list(call_result.payload["under_spec_events"]))
        result.notes = call_result.payload["notes_md"]

        # Extract test paths
        tests = list(call_result.payload["tests"])
        result.tests_added = [t.get("path", "") for t in tests if t.get("path")]

        # Write artifacts
        self._write_artifacts(
            iteration_dir=iteration_dir,
            result=result,
            tests=tests,
            prompt_context=input_context,
            raw_agent_output=call_result.raw_output,
        )

        return result

    def _build_agent_context(
        self,
        *,
        slice_id: str,
        slice_root: Path,
        pins_snapshot_path: Path | None,
        graph_snapshot_path: Path | None,
        analysis_path: Path | None,
        constraints_path: Path | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Build the prompt context for the architecture agent."""
        parts = [f"## SLICE: {slice_id}\n"]
        under_spec_events: list[dict[str, Any]] = []

        # Include pin registry excerpt
        if pins_snapshot_path and pins_snapshot_path.exists():
            try:
                pins_data = json.loads(pins_snapshot_path.read_text(encoding="utf-8"))
                parts.append("## PIN REGISTRY\n```json\n")
                pins_dump = json.dumps(pins_data, indent=2)
                parts.append(self._format_truncated_text(pins_dump, _MAX_PINS_CHARS))
                parts.append("\n```\n")
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                under_spec_events.append(
                    self._build_context_read_failure_event(
                        artifact="PIN_REGISTRY",
                        artifact_path=pins_snapshot_path,
                        exc=exc,
                    )
                )
                parts.append(
                    "## PIN REGISTRY\n"
                    f"[UNREADABLE: {pins_snapshot_path} ({type(exc).__name__}: {exc})]\n"
                )

        # Include graph snapshot excerpt
        if graph_snapshot_path and graph_snapshot_path.exists():
            try:
                graph_data = json.loads(graph_snapshot_path.read_text(encoding="utf-8"))
                parts.append("## ADJACENCY GRAPH\n```json\n")
                graph_dump = json.dumps(graph_data, indent=2)
                parts.append(self._format_truncated_text(graph_dump, _MAX_GRAPH_CHARS))
                parts.append("\n```\n")
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                under_spec_events.append(
                    self._build_context_read_failure_event(
                        artifact="ADJACENCY_GRAPH",
                        artifact_path=graph_snapshot_path,
                        exc=exc,
                    )
                )
                parts.append(
                    "## ADJACENCY GRAPH\n"
                    f"[UNREADABLE: {graph_snapshot_path} ({type(exc).__name__}: {exc})]\n"
                )

        # Include analysis
        if analysis_path and analysis_path.exists():
            try:
                analysis = analysis_path.read_text(encoding="utf-8")
                parts.append(
                    "## LIBRARY ANALYSIS\n"
                    f"{self._format_truncated_text(analysis, _MAX_ANALYSIS_CHARS)}\n"
                )
            except (OSError, UnicodeDecodeError) as exc:
                under_spec_events.append(
                    self._build_context_read_failure_event(
                        artifact="LIBRARY_ANALYSIS",
                        artifact_path=analysis_path,
                        exc=exc,
                    )
                )
                parts.append(
                    "## LIBRARY ANALYSIS\n"
                    f"[UNREADABLE: {analysis_path} ({type(exc).__name__}: {exc})]\n"
                )

        # Include constraints
        if constraints_path and constraints_path.exists():
            try:
                constraints = constraints_path.read_text(encoding="utf-8")
                parts.append(
                    "## CONSTRAINTS\n"
                    f"{self._format_truncated_text(constraints, _MAX_CONSTRAINTS_CHARS)}\n"
                )
            except (OSError, UnicodeDecodeError) as exc:
                under_spec_events.append(
                    self._build_context_read_failure_event(
                        artifact="CONSTRAINTS",
                        artifact_path=constraints_path,
                        exc=exc,
                    )
                )
                parts.append(
                    "## CONSTRAINTS\n"
                    f"[UNREADABLE: {constraints_path} ({type(exc).__name__}: {exc})]\n"
                )

        # List existing architecture files
        arch_files = []
        for p in sorted(slice_root.rglob("*")):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                arch_files.append(str(p.relative_to(slice_root)))

        if arch_files:
            parts.append("## EXISTING FILES\n")
            for f in arch_files[:_MAX_EXISTING_FILES]:
                parts.append(f"- {f}\n")
            if len(arch_files) > _MAX_EXISTING_FILES:
                omitted = len(arch_files) - _MAX_EXISTING_FILES
                parts.append(f"- [TRUNCATED: {omitted} files omitted of {len(arch_files)} total]\n")

        parts.append(
            "\n## TASK\n"
            "Build architecture code that composes the promoted atom pins.\n"
            "Generate services/handlers/middleware. Every wrapper must include "
            "a stable `# pdd:pin=PIN-ARCH-...` marker for traceability.\n"
            "Return JSON with: architecture_patch, projection_proposals, "
            "pin_proposals, edge_proposals, tests, under_spec_events, notes_md.\n"
            "Each projection proposal must use `projection_type` (never `type`).\n"
        )

        return "\n".join(parts), under_spec_events

    def _call_architecture_agent(self, context: str) -> ArchitectureAgentCallResult:
        """Call the pdd-architecture-implementor agent."""
        result = ArchitectureAgentCallResult()

        try:
            from spec_manager.core.agent_utils import run_agent

            result.raw_output = run_agent(
                agent_name="pdd-architecture-implementor",
                prompt=context,
                workspace=self._workspace,
            )
        except Exception as exc:
            logger.warning("Architecture agent failed: %s", exc)
            classification, recovery = self._classify_failure(exc)
            result.under_spec_events.append(
                {
                    "kind": "ARCHITECTURE_AGENT_FAILURE",
                    "question": f"Architecture agent invocation failed: {type(exc).__name__}",
                    "context": str(exc),
                    "source": "ARCHITECTURE_ASSEMBLER",
                    "classification": classification,
                    "recovery": recovery,
                }
            )
            return result

        try:
            from spec_manager.refinement.formats import extract_json_from_llm_output

            payload = extract_json_from_llm_output(
                result.raw_output,
                allow_array=False,
                allow_object=True,
                location="orchestration.architecture.assembler",
            )
            if not isinstance(payload, dict):
                raise TypeError("Architecture agent response must be a JSON object")
            result.payload = payload
            return result
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Architecture agent produced invalid response: %s", exc)
            classification, recovery = self._classify_failure(exc)
            result.under_spec_events.append(
                {
                    "kind": "ARCHITECTURE_AGENT_FAILURE",
                    "question": f"Architecture agent response parsing failed: {type(exc).__name__}",
                    "context": str(exc),
                    "source": "ARCHITECTURE_ASSEMBLER",
                    "classification": classification,
                    "recovery": recovery,
                }
            )
            return result

    @staticmethod
    def _build_context_read_failure_event(
        *,
        artifact: str,
        artifact_path: Path,
        exc: Exception,
    ) -> dict[str, Any]:
        return {
            "kind": "ARCHITECTURE_CONTEXT_READ_FAILURE",
            "question": f"Could not read {artifact} input for architecture assembly.",
            "context": f"{artifact_path}: {type(exc).__name__}: {exc}",
            "source": "ARCHITECTURE_ASSEMBLER",
            "classification": "systematic",
            "recovery": "demote",
        }

    @staticmethod
    def _format_truncated_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        omitted = len(text) - limit
        return f"{text[:limit]}\n[TRUNCATED: {omitted} chars omitted of {len(text)} total]"

    @staticmethod
    def _classify_failure(exc: Exception) -> tuple[str, str]:
        transient_errors = (TimeoutError, ConnectionError)
        systematic_errors = (ValueError, TypeError, json.JSONDecodeError, KeyError)
        if isinstance(exc, transient_errors):
            return "transient", "retry"
        if isinstance(exc, systematic_errors):
            return "systematic", "demote"
        return "systematic", "demote"

    @staticmethod
    def _validate_architecture_payload(payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        required_types: dict[str, type] = {
            "architecture_patch": list,
            "projection_proposals": list,
            "pin_proposals": list,
            "edge_proposals": list,
            "tests": list,
            "under_spec_events": list,
            "notes_md": str,
        }
        for key, expected_type in required_types.items():
            if key not in payload:
                errors.append(f"Missing required key: {key}")
                continue
            if not isinstance(payload[key], expected_type):
                errors.append(
                    f"Invalid type for {key}: expected {expected_type.__name__}, "
                    f"got {type(payload[key]).__name__}"
                )

        proposals = payload.get("projection_proposals")
        if isinstance(proposals, list):
            for idx, proposal in enumerate(proposals):
                if not isinstance(proposal, dict):
                    errors.append(f"projection_proposals[{idx}] must be an object")
                    continue
                if "projection_type" not in proposal:
                    errors.append(f"projection_proposals[{idx}] missing projection_type")
                if "type" in proposal:
                    errors.append(f"projection_proposals[{idx}] uses forbidden field type")

        tests = payload.get("tests")
        if isinstance(tests, list):
            for idx, test_artifact in enumerate(tests):
                if not isinstance(test_artifact, dict):
                    errors.append(f"tests[{idx}] must be an object")
        return errors

    @staticmethod
    def _write_artifacts(
        iteration_dir: Path,
        result: ArchitectureAssemblyResult,
        tests: list[dict[str, Any]],
        prompt_context: str,
        raw_agent_output: str,
    ) -> None:
        """Write architecture artifacts to the iteration directory."""
        if prompt_context:
            prompt_path = iteration_dir / "architecture_agent_prompt.md"
            prompt_path.write_text(prompt_context, encoding="utf-8")

        if raw_agent_output:
            response_path = iteration_dir / "architecture_agent_raw_output.md"
            response_path.write_text(raw_agent_output, encoding="utf-8")

        if result.projection_proposals:
            path = iteration_dir / "projection_proposals.json"
            path.write_text(
                json.dumps(result.projection_proposals, indent=2),
                encoding="utf-8",
            )

        if result.pin_proposals:
            path = iteration_dir / "arch_pin_proposals.json"
            path.write_text(
                json.dumps(result.pin_proposals, indent=2),
                encoding="utf-8",
            )

        if result.edge_proposals:
            path = iteration_dir / "arch_edge_proposals.json"
            path.write_text(
                json.dumps(result.edge_proposals, indent=2),
                encoding="utf-8",
            )

        if tests:
            path = iteration_dir / "arch_tests_added.json"
            path.write_text(json.dumps(tests, indent=2), encoding="utf-8")

        if result.under_spec_events:
            path = iteration_dir / "arch_under_spec_events.json"
            path.write_text(
                json.dumps(result.under_spec_events, indent=2),
                encoding="utf-8",
            )

        if result.notes:
            path = iteration_dir / "arch_notes.md"
            path.write_text(result.notes, encoding="utf-8")
