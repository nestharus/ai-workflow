"""Format repair strategy.

Normalizes LLM outputs with format violations (code fences, preambles,
invalid JSON) before downstream parsing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.json_extraction import (
    _extract_json_payload,
    _record_json_extraction_evidence,
)
from spec_manager.refinement.repair import (
    ArtifactType,
    get_repair_model,
    repair_artifact,
)
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


@dataclass(frozen=True)
class _RepairWorkspaceAdapter:
    """Adapter to provide a workspace_path for repair agents."""

    workspace_path: Path


class FormatRepairStrategy(Strategy):
    """Normalize outputs with JSON format violations."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        """Initialize the strategy.

        Args:
            definition: Strategy definition from YAML.
            tools: Dictionary of available tools.
        """
        self.definition = definition
        self.tools = tools or {}
        self._json_extractor = self.tools.get("json_extractor") or _extract_json_payload
        self._repair_agent = self.tools.get("repair_agent") or repair_artifact

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "format_repair"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Normalize LLM outputs with format violations"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Invalid JSON, code fences, preambles causing downstream parsing failures"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if any unit needs format repair."""
        if context.phase != StrategyPhase.CLEANING:
            return False
        return any(self._needs_repair(unit.content) for unit in context.units)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute format repair on units needing cleanup."""
        actions: list[str] = []
        issues: list[str] = []
        all_evidence: list[dict[str, Any]] = []
        repair_count = 0
        extraction_count = 0

        for unit in context.units:
            original = unit.content
            if not self._needs_repair(original):
                continue

            unit_evidence: list[dict[str, Any]] = []

            extracted = str(self._json_extractor(original))
            had_code_fence = self._has_code_fence(original)
            had_preamble = self._has_preamble(original, extracted)
            extraction_succeeded = False
            if extracted != original:
                try:
                    json.loads(extracted)
                    extraction_succeeded = True
                except Exception:
                    extraction_succeeded = False

            if extraction_succeeded:
                _record_json_extraction_evidence(
                    original,
                    extracted,
                    unit_evidence,
                    location=f"format_repair:{unit.id}",
                )
                self._preserve_original_content(unit, original, "json_extraction")
                unit.content = extracted
                unit.content_hash = hashlib.sha256(extracted.encode()).hexdigest()
                unit.add_modification("format_repair")
                unit.metadata["format_repair"] = {
                    "method": "json_extraction",
                    "had_code_fence": had_code_fence,
                    "had_preamble": had_preamble,
                }
                extraction_count += 1
                issues.append(f"Format repair: extracted JSON payload for {unit.id}")
                if had_code_fence:
                    issues.append(f"Format repair: removed code fences from {unit.id}")
                if had_preamble:
                    issues.append(f"Format repair: stripped preamble from {unit.id}")
                actions.append(f"Extracted JSON payload for {unit.id}")
                all_evidence.extend(unit_evidence)
                continue

            errors = self._build_errors(original, extracted)
            if had_code_fence:
                issues.append(f"Format repair: removed code fences from {unit.id}")
            if had_preamble:
                issues.append(f"Format repair: stripped preamble from {unit.id}")
            try:
                artifact_type = self._infer_artifact_type(original)
                repaired_output, evidence_records = self._repair_agent(
                    output=original,
                    errors=errors,
                    allowlists={},
                    artifact_type=artifact_type,
                    model_override=get_repair_model(),
                    manager=self._build_repair_manager(context),
                )
                self._preserve_original_content(unit, original, "repair_agent")
                unit.content = repaired_output
                unit.content_hash = hashlib.sha256(repaired_output.encode()).hexdigest()
                unit.add_modification("format_repair")
                unit.metadata["format_repair"] = {
                    "method": "repair_agent",
                    "had_code_fence": had_code_fence,
                    "had_preamble": had_preamble,
                }
                repair_count += 1
                issues.append(f"Format repair: normalized JSON for {unit.id}")
                if evidence_records:
                    actions.append(
                        f"Repair agent invoked for {unit.id} ({len(evidence_records)} record(s))"
                    )
                    all_evidence.extend(evidence_records)
            except Exception as exc:
                issues.append(f"Format repair: failed to repair {unit.id}: {exc}")

        return StrategyResult(
            units=context.units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "repair_count": repair_count,
                "extraction_count": extraction_count,
            },
            evidence_records=all_evidence,
        )

    def _needs_repair(self, content: str) -> bool:
        """Heuristic check for format violations."""
        stripped = content.lstrip()
        if stripped.startswith("```"):
            return True
        if "[agent-exec]" in content:
            return True
        if self._has_preamble(content, None):
            return True
        if stripped.startswith("{") or stripped.startswith("["):
            extracted = str(self._json_extractor(content))
            return extracted.strip() != content.strip()
        return False

    def _has_code_fence(self, content: str) -> bool:
        """Check for fenced code blocks."""
        return content.lstrip().startswith("```")

    def _has_preamble(self, content: str, extracted: str | None) -> bool:
        """Detect leading commentary before JSON payload."""
        stripped = content.lstrip()
        if stripped.startswith("```"):
            return False
        if stripped.startswith("{") or stripped.startswith("["):
            return False
        first_obj = stripped.find("{")
        first_list = stripped.find("[")
        has_json = first_obj != -1 or first_list != -1
        if not has_json:
            return False
        if extracted is None:
            return True
        return extracted.strip() != content.strip()

    def _build_errors(self, original: str, extracted: str) -> list[dict[str, Any]]:
        """Build validation errors for repair agent."""
        message = "Invalid JSON output"
        if extracted and extracted != original:
            message = "Invalid JSON after extraction"
        return [
            {
                "type": "invalid_json",
                "message": message,
            }
        ]

    def _infer_artifact_type(self, content: str) -> ArtifactType:
        """Infer artifact type from content keys."""
        lowered = content.lower()
        if "candidate_labels" in lowered and "uncertain_labels" in lowered:
            return ArtifactType.LIBRARY_LABELS
        if "patches" in lowered and "file_id" in lowered and "lib_id" in lowered:
            return ArtifactType.SPEC_PATCHES
        if "selected_arch_id" in lowered and "rejected_architectures" in lowered:
            return ArtifactType.ARCHITECTURE_SELECTION
        if "components" in lowered and "tradeoffs" in lowered:
            return ArtifactType.ARCHITECTURE_MAPPING
        if "evidence" in lowered and "file_id" in lowered:
            return ArtifactType.EVIDENCE_JSON
        if "responsibilities" in lowered and "boundaries" in lowered:
            return ArtifactType.CHARTER
        return ArtifactType.SPEC

    def _build_repair_manager(self, context: ProcessingContext) -> _RepairWorkspaceAdapter:
        """Build a workspace adapter for repair agent runs."""
        workspace_path = context.config.get("workspace_path")
        if isinstance(workspace_path, Path):
            resolved = workspace_path
        elif isinstance(workspace_path, str) and workspace_path:
            resolved = Path(workspace_path)
        else:
            resolved = Path(".")
        return _RepairWorkspaceAdapter(workspace_path=resolved)

    @staticmethod
    def _preserve_original_content(unit: object, content: str, mode: str) -> None:
        """Persist pre-repair content so repairs are auditable/replayable."""
        if not hasattr(unit, "metadata"):
            return
        history = unit.metadata.setdefault("content_history", [])
        history.append(
            {
                "strategy": "format_repair",
                "mode": mode,
                "content": content,
            }
        )
