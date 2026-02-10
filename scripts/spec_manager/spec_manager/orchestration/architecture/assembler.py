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
        return cls(
            projection_id=d.get("projection_id", ""),
            projection_type=d.get("type", d.get("projection_type", "PASS_THROUGH")),
            from_pin=d.get("from_pin", ""),
            to_arch_fqn=d.get("to_arch_fqn", ""),
            file=d.get("file", ""),
            span=d.get("span"),
            evidence_paths=d.get("evidence_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "type": self.projection_type,
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
        input_context = self._build_agent_context(
            slice_id=slice_id,
            slice_root=slice_root,
            pins_snapshot_path=pins_snapshot_path,
            graph_snapshot_path=graph_snapshot_path,
            analysis_path=analysis_path,
            constraints_path=constraints_path,
        )

        # Call the architecture agent
        agent_output = self._call_architecture_agent(input_context)

        if agent_output is None:
            logger.warning("Architecture agent returned no output for slice '%s'", slice_id)
            return result

        # Parse agent output
        result.patches_applied = agent_output.get("architecture_patch", [])
        result.projection_proposals = agent_output.get("projection_proposals", [])
        result.pin_proposals = agent_output.get("pin_proposals", [])
        result.edge_proposals = agent_output.get("edge_proposals", [])
        result.under_spec_events = agent_output.get("under_spec_events", [])
        result.notes = agent_output.get("notes_md", "")

        # Extract test paths
        tests = agent_output.get("tests", [])
        result.tests_added = [t.get("path", "") for t in tests if t.get("path")]

        # Write artifacts
        self._write_artifacts(iteration_dir, result, tests)

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
    ) -> str:
        """Build the prompt context for the architecture agent."""
        parts = [f"## SLICE: {slice_id}\n"]

        # Include pin registry excerpt
        if pins_snapshot_path and pins_snapshot_path.exists():
            try:
                pins_data = json.loads(pins_snapshot_path.read_text(encoding="utf-8"))
                parts.append("## PIN REGISTRY\n```json\n")
                parts.append(json.dumps(pins_data, indent=2)[:5000])
                parts.append("\n```\n")
            except Exception:
                pass

        # Include graph snapshot excerpt
        if graph_snapshot_path and graph_snapshot_path.exists():
            try:
                graph_data = json.loads(graph_snapshot_path.read_text(encoding="utf-8"))
                parts.append("## ADJACENCY GRAPH\n```json\n")
                parts.append(json.dumps(graph_data, indent=2)[:5000])
                parts.append("\n```\n")
            except Exception:
                pass

        # Include analysis
        if analysis_path and analysis_path.exists():
            try:
                analysis = analysis_path.read_text(encoding="utf-8")
                parts.append(f"## LIBRARY ANALYSIS\n{analysis[:3000]}\n")
            except Exception:
                pass

        # Include constraints
        if constraints_path and constraints_path.exists():
            try:
                constraints = constraints_path.read_text(encoding="utf-8")
                parts.append(f"## CONSTRAINTS\n{constraints[:2000]}\n")
            except Exception:
                pass

        # List existing architecture files
        arch_files = []
        for p in sorted(slice_root.rglob("*")):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                arch_files.append(str(p.relative_to(slice_root)))

        if arch_files:
            parts.append("## EXISTING FILES\n")
            for f in arch_files[:50]:
                parts.append(f"- {f}\n")

        parts.append(
            "\n## TASK\n"
            "Build architecture code that composes the promoted atom pins.\n"
            "Generate services/handlers/middleware. Every wrapper must include "
            "a stable `# pdd:pin=PIN-ARCH-...` marker for traceability.\n"
            "Return JSON with: architecture_patch, projection_proposals, "
            "pin_proposals, edge_proposals, tests, under_spec_events, notes_md.\n"
        )

        return "\n".join(parts)

    def _call_architecture_agent(
        self, context: str
    ) -> dict[str, Any] | None:
        """Call the pdd-architecture-implementor agent."""
        try:
            from spec_manager.core.agent_utils import run_agent
            from spec_manager.refinement.formats import (
                _extract_json_payload,
                _strip_code_fences,
            )

            output = run_agent(
                agent_name="pdd-architecture-implementor",
                prompt=context,
                workspace=self._workspace,
            )
            cleaned = _strip_code_fences(output)
            return json.loads(_extract_json_payload(cleaned))
        except Exception as exc:
            logger.warning("Architecture agent failed: %s", exc)
            return None

    @staticmethod
    def _write_artifacts(
        iteration_dir: Path,
        result: ArchitectureAssemblyResult,
        tests: list[dict[str, Any]],
    ) -> None:
        """Write architecture artifacts to the iteration directory."""
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
