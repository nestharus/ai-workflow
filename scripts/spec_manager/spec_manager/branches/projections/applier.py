"""Projection proposal applier: merges LLM projection proposals into PinRegistry.

When the architecture agent produces projection proposals (PASS_THROUGH,
EVENT_BRIDGE, STORE_FACADE, COMPOSITION), this module merges them into
the PinRegistry so downstream gates can verify traceability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..types import ProjectionType

logger = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Result of applying projection proposals."""

    applied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_details: list[dict[str, Any]] = field(default_factory=list)


class ProjectionEdgeRegistry(Protocol):
    """Explicit contract for projection-edge consumers."""

    def register_projection_edge(
        self,
        *,
        source_pin: str,
        target_location: str,
        projection_type: ProjectionType,
        confidence: float = 1.0,
    ) -> None: ...


def _coerce_projection_type(raw: Any) -> ProjectionType:
    """Coerce proposal projection labels into ProjectionType."""
    if isinstance(raw, ProjectionType):
        return raw
    if not isinstance(raw, str):
        return ProjectionType.SLICE
    value = raw.strip().lower()
    aliases: dict[str, ProjectionType] = {
        "projection": ProjectionType.SLICE,
        "call": ProjectionType.PASS_THROUGH,
        "store_touch": ProjectionType.AGGREGATION,
        "event_emit": ProjectionType.EVENT_BRIDGE,
        "event_handle": ProjectionType.EVENT_BRIDGE,
        "event": ProjectionType.EVENT_BRIDGE,
        "reference": ProjectionType.SLICE,
        "import": ProjectionType.SLICE,
    }
    if value in aliases:
        return aliases[value]
    try:
        return ProjectionType(value)
    except ValueError:
        return ProjectionType.SLICE


def apply_projection_proposals(
    *,
    pin_registry: ProjectionEdgeRegistry,
    projection_proposals: list[dict[str, Any]],
) -> ApplyResult:
    """Merge projection proposals into the PinRegistry.

    Each projection establishes a traceability link from an atom pin
    to an architectural function.  The registry records these as
    import edges with a ``projection`` signal type.

    Args:
        pin_registry: PinFunctionRegistry instance.
        projection_proposals: List of projection proposal dicts.

    Returns:
        ApplyResult with counts.
    """
    result = ApplyResult()

    for idx, proposal in enumerate(projection_proposals):
        from_pin = proposal.get("from_pin", "")
        to_arch_fqn = proposal.get("to_arch_fqn", "")

        if not from_pin or not to_arch_fqn:
            result.skipped += 1
            result.skipped_details.append(
                {
                    "index": idx,
                    "reason": "missing_required_fields",
                    "missing": [
                        name
                        for name, value in (("from_pin", from_pin), ("to_arch_fqn", to_arch_fqn))
                        if not value
                    ],
                    "proposal": dict(proposal),
                }
            )
            continue

        try:
            projection_type = _coerce_projection_type(
                proposal.get("projection_type") or proposal.get("signal_type")
            )
            confidence_raw = proposal.get("confidence", proposal.get("weight", 1.0))
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except (TypeError, ValueError):
                confidence = 1.0

            pin_registry.register_projection_edge(
                source_pin=str(from_pin),
                target_location=str(to_arch_fqn),
                projection_type=projection_type,
                confidence=confidence,
            )
            result.applied += 1
        except Exception as exc:
            result.errors.append(f"Failed to apply projection {from_pin} -> {to_arch_fqn}: {exc}")

    logger.info(
        "Applied %d projection proposals (%d skipped, %d errors)",
        result.applied,
        result.skipped,
        len(result.errors),
    )
    return result
