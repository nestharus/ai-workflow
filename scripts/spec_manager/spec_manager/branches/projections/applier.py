"""Projection proposal applier: merges LLM projection proposals into PinRegistry.

When the architecture agent produces projection proposals (PASS_THROUGH,
EVENT_BRIDGE, STORE_FACADE, COMPOSITION), this module merges them into
the PinRegistry so downstream gates can verify traceability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Result of applying projection proposals."""

    applied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def apply_projection_proposals(
    *,
    pin_registry: Any,
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

    for proposal in projection_proposals:
        from_pin = proposal.get("from_pin", "")
        to_arch_fqn = proposal.get("to_arch_fqn", "")

        if not from_pin or not to_arch_fqn:
            result.skipped += 1
            continue

        try:
            # Record the projection as an edge in the registry
            if hasattr(pin_registry, "import_edges"):
                from spec_manager.schemas.pin_functions import ImportEdge

                edge = ImportEdge(
                    source=from_pin,
                    target=to_arch_fqn,
                    edge_type="projection",
                )
                pin_registry.import_edges.append(edge)
                result.applied += 1
            else:
                result.skipped += 1
                result.errors.append(
                    f"Registry does not support import_edges"
                    f" for projection {from_pin} -> {to_arch_fqn}"
                )
        except Exception as exc:
            result.errors.append(f"Failed to apply projection {from_pin} -> {to_arch_fqn}: {exc}")

    logger.info(
        "Applied %d projection proposals (%d skipped, %d errors)",
        result.applied,
        result.skipped,
        len(result.errors),
    )
    return result
