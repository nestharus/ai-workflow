"""Schemas for pin-function data structures.

Pin-functions are actual extracted functions that serve as bridges between
algorithmic and architectural layers. Both layers import the same atom functions.

Schema Version: 1.0
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ProjectionType(str, Enum):
    """How an architectural location uses a pin-function.

    Fine-grained classification supporting both lineage tracking and
    branch organization. Coarse groupings:
    - Direct: PASS_THROUGH
    - Wrapping: EVENT_BRIDGE, MIDDLEWARE_WRAP, RETRY_DECORATE
    - Combining: SMEAR, AGGREGATION
    - Subsetting: SLICE (aka PROJECTION)
    - Novel: INTRODUCTION
    """

    PASS_THROUGH = "pass_through"  # Architecture imports and calls atom directly
    EVENT_BRIDGE = "event_bridge"  # Atom wrapped in event handler
    MIDDLEWARE_WRAP = "middleware_wrap"  # Atom wrapped in middleware layer
    RETRY_DECORATE = "retry_decorate"  # Atom wrapped with retry/resilience
    SLICE = "slice"  # Architecture uses subset of atom output
    SMEAR = "smear"  # Architecture combines multiple atoms into one location
    AGGREGATION = "aggregation"  # Architecture combines multiple atoms
    INTRODUCTION = "introduction"  # Architectural algorithm with no algorithmic origin


COARSE_GROUP: dict[ProjectionType, str] = {
    ProjectionType.PASS_THROUGH: "direct",
    ProjectionType.EVENT_BRIDGE: "wrap",
    ProjectionType.MIDDLEWARE_WRAP: "wrap",
    ProjectionType.RETRY_DECORATE: "wrap",
    ProjectionType.SLICE: "subset",
    ProjectionType.SMEAR: "combine",
    ProjectionType.AGGREGATION: "combine",
    ProjectionType.INTRODUCTION: "introduction",
}


def coarse_group(pt: ProjectionType) -> str:
    """Return the coarse group name for a fine-grained projection type."""
    return COARSE_GROUP[pt]


class PinFunctionSchema(BaseModel):
    """Schema for validating pin-function mapping data (pin -> atom -> arch).

    Used to validate pin-function definitions at input boundaries.
    """

    pin_id: str
    atom_id: str
    architectural_location: str
    projection_type: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    wrapper_hash: str | None = None

    @field_validator("pin_id")
    @classmethod
    def validate_pin_id(cls, v: str) -> str:
        import re

        if not re.match(r"^PIN-\d{4}$", v):
            raise ValueError("pin_id must match PIN-#### format")
        return v

    @field_validator("projection_type")
    @classmethod
    def validate_projection_type(cls, v: str) -> str:
        allowed = {"pass_through", "projection", "aggregation", "introduction"}
        if v not in allowed:
            raise ValueError(f"projection_type must be one of {sorted(allowed)}")
        return v


class PinFunction(BaseModel):
    """A registered atom function that both layers can import.

    Represents a decomposed algorithm step extracted as a shared function.
    """

    pin_func_id: str  # e.g., "PFUNC-0001"
    function_name: str  # Python qualified name, e.g., "validate_payment"
    module_path: str  # Module where defined, e.g., "atoms.payment"
    file_path: str  # Relative file path, e.g., "atoms/payment.py"
    line_start: int  # First line of function def
    line_end: int  # Last line of function body
    signature: str  # Function signature string
    docstring: str  # First line of docstring (summary)
    content_hash: str  # SHA-256 of function body (for change detection)
    is_shape: bool = False  # True if pure function (no side effects, no state)
    store_touches: list[str] = Field(default_factory=list)
    evidence_atom_ids: list[str] = Field(default_factory=list)


class MicroAddress(BaseModel):
    """Precise address within or referencing a pin-function.

    Supports three addressing modes:
    - Function-level: pin_func_id only (whole function)
    - Line-range: pin_func_id + line_start/line_end (lines within function)
    - Call-site: composition_func + callee pin_func_id (call site in composition)
    """

    pin_func_id: str
    line_start: int | None = None
    line_end: int | None = None
    composition_func: str | None = None


class ImportEdge(BaseModel):
    """A directed edge from a pin-function to an architectural location that imports it.

    Represents one usage of a pin-function in the architectural layer.
    This is a pin-function-to-architecture mapping edge (PFUNC -> arch location).

    Not to be confused with:
    - ``projection.lineage.builder.RawImportRecord``: a raw import
      relationship (which file imports which name from which module).
    - ``projection.lineage.edges.ProjectionLineageEdge``: a lineage
      transformation edge tracking how atoms map to architecture over time.
    """

    edge_id: str  # e.g., "IMEDGE-0001"
    pin_func_id: str  # Source: the pin-function being imported
    arch_location: str  # Target: "file:class.method" or "file:function"
    arch_file_path: str  # Relative path to architectural file
    arch_line: int  # Line number of the import/call site
    projection_type: ProjectionType  # How the architecture uses this pin-function
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_direct_import: bool = True  # True if literal import, False if inferred usage


class PinFunctionRegistry(BaseModel):
    """Complete registry of all pin-functions and their import graph.

    Serializable artifact that represents the full state of the pin system.
    """

    schema_version: str = "1.0"
    pin_functions: list[PinFunction] = Field(default_factory=list)
    import_edges: list[ImportEdge] = Field(default_factory=list)
    created_at: str  # ISO-8601


__all__ = [
    "COARSE_GROUP",
    "ImportEdge",
    "MicroAddress",
    "PinFunction",
    "PinFunctionRegistry",
    "PinFunctionSchema",
    "ProjectionType",
    "coarse_group",
]
