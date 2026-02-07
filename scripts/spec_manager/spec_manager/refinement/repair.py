"""Automated repair helpers for spec refinement artifacts."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.workspace import WorkspaceManager

_FALLBACK_REPAIR_MODEL = "gpt-5.2-low"
_REPAIR_MODEL_SELECTION_PATH = (
    Path(__file__).resolve().parent / "evaluation/results/REPAIR_MODEL_SELECTION.md"
)
_REPAIR_MODEL_RECOMMENDATION_PATTERN = re.compile(
    r"recommend\s+\*\*(?P<model>[^*]+)\*\*",
    re.IGNORECASE,
)
_REPAIR_MODEL_DEFAULT_PATTERN = re.compile(
    r"Current default:\s*\*\*(?P<model>[^*]+)\*\*",
    re.IGNORECASE,
)


def _load_selected_repair_model() -> str:
    try:
        content = _REPAIR_MODEL_SELECTION_PATH.read_text(encoding="utf-8")
    except OSError:
        return _FALLBACK_REPAIR_MODEL
    for pattern in (_REPAIR_MODEL_RECOMMENDATION_PATTERN, _REPAIR_MODEL_DEFAULT_PATTERN):
        match = pattern.search(content)
        if match:
            return match.group("model").strip()
    return _FALLBACK_REPAIR_MODEL


DEFAULT_REPAIR_MODEL = _load_selected_repair_model()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairAgentSelection:
    """Agent and model configuration for artifact repair operations."""

    agent_name: str
    model_name: str


class ArtifactType(str, Enum):
    """Valid artifact types for compliance validation and repair."""

    SUMMARY = "summary"
    CHARTER = "charter"
    LIBRARY_LABELS = "library_labels"
    SPEC = "spec"
    SPEC_PATCHES = "spec_patches"
    EVIDENCE_JSON = "evidence_json"
    ARCHITECTURE_SELECTION = "architecture_selection"
    ARCHITECTURE_MAPPING = "architecture_mapping"
    INTERFACE_CONTRACT = "interface_contract"
    PATCH_OUTPUT = "patch_output"
    PATCH_AUDIT = "patch_audit"


def repair_artifact(
    *,
    output: str,
    errors: list[dict[str, Any]],
    allowlists: dict[str, Any],
    artifact_type: ArtifactType,
    model_override: str,
    manager: WorkspaceManager,
) -> tuple[str, list[dict[str, Any]]]:
    """Attempt to repair a non-compliant artifact using a specialized repair agent."""
    evidence_records: list[dict[str, Any]] = []
    if not errors:
        logger.info("Repair skipped; no validation errors (artifact_type=%s).", artifact_type.value)
        return output, evidence_records
    prompt = _build_repair_prompt(
        output=output,
        errors=errors,
        allowlists=allowlists,
        artifact_type=artifact_type,
    )
    selection = _select_repair_agent(artifact_type, model_override=model_override)
    logger.info(
        "Repair attempt (artifact_type=%s, agent=%s, model=%s, errors=%d).",
        artifact_type.value,
        selection.agent_name,
        selection.model_name,
        len(errors),
    )
    start = time.perf_counter()
    try:
        repaired = run_agent(
            agent_name=selection.agent_name,
            prompt=prompt,
            workspace=manager.workspace_path,
            extra_env={"REPAIR_MODEL": selection.model_name},
        )
        if not isinstance(repaired, str):
            raise TypeError(f"Expected str from repair agent, got {type(repaired).__name__}")
    except Exception:
        logger.exception(
            "Repair failed (artifact_type=%s, agent=%s, model=%s).",
            artifact_type.value,
            selection.agent_name,
            selection.model_name,
        )
        raise
    latency_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Repair completed (artifact_type=%s, agent=%s, model=%s, latency_ms=%.2f).",
        artifact_type.value,
        selection.agent_name,
        selection.model_name,
        latency_ms,
    )
    evidence_records.append(
        {
            "category": "format",
            "type": "repair_agent_invoked",
            "details": {
                "artifact_type": artifact_type.value,
                "error_count": len(errors),
                "model_used": selection.model_name,
                "latency_ms": latency_ms,
            },
        }
    )
    return repaired, evidence_records


def get_repair_model() -> str:
    """Get the repair model from environment or use default."""
    override = (os.getenv("REPAIR_MODEL") or "").strip()
    return override or DEFAULT_REPAIR_MODEL


def _build_repair_prompt(
    *,
    output: str,
    errors: list[dict[str, Any]],
    allowlists: dict[str, Any],
    artifact_type: ArtifactType,
) -> str:
    error_list = _format_error_list(errors)
    allowlist_text = _format_allowlists(allowlists)
    lines = [
        "You are a compliance repair agent.",
        "Fix ONLY compliance issues. Do NOT add new content,",
        "change semantics, or invent information.",
        "",
        f"Artifact Type: {artifact_type.value}",
        "",
        "INVALID OUTPUT (verbatim):",
        "<BEGIN_OUTPUT>",
        output,
        "<END_OUTPUT>",
        "",
        "VALIDATION ERRORS:",
        error_list,
        "",
        "ALLOWLISTS:",
        allowlist_text,
        "",
        "Return ONLY the corrected output. No preamble, no code fences, no explanations.",
    ]
    return "\n".join(lines)


def _select_repair_agent(
    artifact_type: ArtifactType,
    *,
    model_override: str | None = None,
) -> RepairAgentSelection:
    mapping = {
        ArtifactType.SUMMARY: "repair-summary",
        ArtifactType.CHARTER: "repair-charter",
        ArtifactType.LIBRARY_LABELS: "repair-library-labels",
        ArtifactType.SPEC: "repair-spec",
        ArtifactType.SPEC_PATCHES: "repair-spec-patches",
        ArtifactType.EVIDENCE_JSON: "repair-evidence-json",
        ArtifactType.ARCHITECTURE_SELECTION: "repair-architecture-selection",
        ArtifactType.ARCHITECTURE_MAPPING: "repair-architecture-mapping",
        ArtifactType.INTERFACE_CONTRACT: "chatgpt-interface-contract-repairer",
        ArtifactType.PATCH_OUTPUT: "chatgpt-patch-repairer",
        ArtifactType.PATCH_AUDIT: "chatgpt-patch-audit-judge",
    }
    if artifact_type not in mapping:
        raise ValueError(f"Unsupported artifact type: {artifact_type}")
    model_name = model_override or get_repair_model()
    if not model_name:
        raise ValueError("Repair model override is empty.")
    return RepairAgentSelection(agent_name=mapping[artifact_type], model_name=model_name)


def _format_error_list(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "None"
    lines = []
    for index, error in enumerate(errors, start=1):
        error_type = error.get("type", "unknown")
        message = error.get("message", "").strip()
        context = _format_error_context(error)
        lines.append(f"{index}. [{error_type}] {message} (context: {context})")
    return "\n".join(lines)


def _format_error_context(error: dict[str, Any]) -> str:
    parts = []
    for key in sorted(error.keys()):
        if key in {"type", "message"}:
            continue
        value = error.get(key)
        if value is None:
            continue
        parts.append(f"{key}={_format_context_value(value)}")
    return "; ".join(parts) if parts else "none"


def _format_context_value(value: dict[str, object] | list[object]) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


def _format_allowlists(allowlists: dict[str, Any]) -> str:
    if not allowlists:
        return "None"
    lines = []
    for key in sorted(allowlists.keys()):
        value = allowlists[key]
        formatted = _format_allowlist_value(value)
        if "\n" in formatted:
            lines.append(f"{key}:")
            lines.extend([f"  {line}" for line in formatted.splitlines()])
        else:
            lines.append(f"{key}: {formatted}")
    return "\n".join(lines)


def _format_allowlist_value(
    value: dict[str, object] | list[object] | tuple[object, ...] | set[object],
) -> str:
    if isinstance(value, dict):
        if not value:
            return "None"
        lines = []
        for subkey in sorted(value.keys()):
            items = value[subkey]
            if isinstance(items, (dict, list, tuple, set)):
                items_text = _format_allowlist_value(items)
            else:
                items_text = str(items)
            lines.append(f"- {subkey}: {items_text}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value]
        return ", ".join(items) if items else "None"
    return str(value)
