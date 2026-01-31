"""Automated repair helpers for spec refinement artifacts."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from scripts.spec_refinement.workspace import WorkspaceManager

from .agent_utils import run_agent

DEFAULT_REPAIR_MODEL = "gpt-5.2-low"

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


def repair_artifact(
    *,
    output: str,
    errors: list[dict[str, Any]],
    allowlists: dict[str, Any],
    artifact_type: ArtifactType,
    model_override: str,
    manager: WorkspaceManager,
) -> str:
    """Attempt to repair a non-compliant artifact using a specialized repair agent."""
    if not errors:
        logger.info("Repair skipped; no validation errors (artifact_type=%s).", artifact_type.value)
        return output
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
    return repaired


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
