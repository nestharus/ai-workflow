"""Schemas and helpers for interface edge lists and indexes.

This module defines the structured artifacts used to describe cross-library
interfaces. Edge lists capture the relationship between consuming and providing
libraries, while interface indexes map edges to the generated contract files.

Example:
    edge = EdgeSchema(
        edge_id="EDGE-LIB-0001-LIB-0002",
        consumer_lib="LIB-0001",
        provider_lib="LIB-0002",
        kind="api",
        consumer_elements=["DTL-LIB-0001-0001"],
        provider_elements=["DTL-LIB-0002-0001"],
        summary="Consumer uses provider API.",
        evidence=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
    )
    edge_list = EdgeListSchema(
        run_id="run_001",
        generated_at="2024-01-01T00:00:00",
        edges=[edge],
    )
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from spec_manager.core.evidence_pointers import parse_evidence_pointer

if TYPE_CHECKING:
    from .interface_contract import InterfaceContractSchema

EDGE_ID_RE = re.compile(r"^EDGE-LIB-\d{4}-LIB-\d{4}$")
LIB_ID_RE = re.compile(r"^LIB-\d{4}$")
ELEMENT_ID_RE = re.compile(
    r"^(?:DTL-LIB-\d{4}-\d{4}|CON-LIB-\d{4}-\d{4}|ANL-LIB-\d{4}-\d{4}|OVW-LIB-\d{4}-\d{4})$"
)
TASK_ID_RE = re.compile(r"^TASK-\d{4}$")


def _validate_iso8601(value: str) -> str:
    """Validate an ISO-8601 timestamp with date-time precision.

    Args:
        value: Timestamp string such as "2024-01-01T00:00:00".

    Returns:
        The original timestamp string when valid.

    Raises:
        ValueError: When the timestamp is not ISO-8601 or lacks time.

    Example:
        _validate_iso8601("2024-01-01T00:00:00")
    """
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("value must be ISO-8601") from exc
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("value must be ISO-8601") from None
    return value


class EdgeSchema(BaseModel):
    """Describe a dependency edge between a consumer and provider library.

    Attributes:
        edge_id: Unique identifier, e.g. "EDGE-LIB-0001-LIB-0002".
        consumer_lib: Library that consumes the interface ("LIB-####").
        provider_lib: Library that provides the interface ("LIB-####").
        kind: Interface category such as "api" or "events".
        consumer_elements: Consumer element IDs referencing the dependency.
        provider_elements: Provider element IDs that satisfy the dependency.
        summary: Human-readable summary of the interaction.
        evidence: Evidence pointers supporting the edge.

    Example:
        EdgeSchema.model_validate(
            {
                "edge_id": "EDGE-LIB-0001-LIB-0002",
                "consumer_lib": "LIB-0001",
                "provider_lib": "LIB-0002",
                "kind": "api",
                "consumer_elements": ["DTL-LIB-0001-0001"],
                "provider_elements": ["DTL-LIB-0002-0001"],
                "summary": "Consumer uses provider API.",
                "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            }
        )
    """

    edge_id: str
    consumer_lib: str
    provider_lib: str
    kind: Literal["api", "data", "events", "storage", "config", "other"]
    consumer_elements: list[str]
    provider_elements: list[str]
    summary: str
    evidence: list[str]

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, value: str) -> str:
        """Ensure edge_id matches EDGE-LIB-####-LIB-#### format.

        Args:
            value: Edge identifier string.

        Returns:
            The validated edge identifier.

        Example:
            EdgeSchema.model_validate(
                {
                    "edge_id": "EDGE-LIB-0001-LIB-0002",
                    "consumer_lib": "LIB-0001",
                    "provider_lib": "LIB-0002",
                    "kind": "api",
                    "consumer_elements": ["DTL-LIB-0001-0001"],
                    "provider_elements": ["DTL-LIB-0002-0001"],
                    "summary": "Summary",
                    "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
                }
            )
        """
        if not EDGE_ID_RE.fullmatch(value):
            raise ValueError("edge_id must match EDGE-LIB-####-LIB-####")
        return value

    @field_validator("consumer_lib", "provider_lib")
    @classmethod
    def validate_lib_ids(cls, value: str) -> str:
        """Ensure library IDs match the LIB-#### format.

        Args:
            value: Library identifier string.

        Returns:
            The validated library identifier.

        Example:
            EdgeSchema.model_validate(
                {
                    "edge_id": "EDGE-LIB-0001-LIB-0002",
                    "consumer_lib": "LIB-0001",
                    "provider_lib": "LIB-0002",
                    "kind": "api",
                    "consumer_elements": ["DTL-LIB-0001-0001"],
                    "provider_elements": ["DTL-LIB-0002-0001"],
                    "summary": "Summary",
                    "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
                }
            )
        """
        if not LIB_ID_RE.fullmatch(value):
            raise ValueError("library IDs must match LIB-####")
        return value

    @field_validator("consumer_elements", "provider_elements")
    @classmethod
    def validate_elements(cls, value: list[str]) -> list[str]:
        """Ensure element IDs reference known requirement/flow/invariant/decision IDs.

        Args:
            value: List of element IDs.

        Returns:
            The validated list of element IDs.

        Example:
            EdgeSchema.model_validate(
                {
                    "edge_id": "EDGE-LIB-0001-LIB-0002",
                    "consumer_lib": "LIB-0001",
                    "provider_lib": "LIB-0002",
                    "kind": "api",
                    "consumer_elements": ["DTL-LIB-0001-0001"],
                    "provider_elements": ["DTL-LIB-0002-0001"],
                    "summary": "Summary",
                    "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
                }
            )
        """
        for element_id in value:
            if not ELEMENT_ID_RE.fullmatch(element_id):
                raise ValueError(
                    "element IDs must match DTL-LIB-####-####, CON-LIB-####-####, "
                    "ANL-LIB-####-####, or OVW-LIB-####-####"
                )
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[str]) -> list[str]:
        """Validate evidence pointers, including multi-hop library references.

        Args:
            value: List of evidence pointer strings.

        Returns:
            The validated list of evidence pointers.

        Example:
            EdgeSchema.model_validate(
                {
                    "edge_id": "EDGE-LIB-0001-LIB-0002",
                    "consumer_lib": "LIB-0001",
                    "provider_lib": "LIB-0002",
                    "kind": "api",
                    "consumer_elements": ["DTL-LIB-0001-0001"],
                    "provider_elements": ["DTL-LIB-0002-0001"],
                    "summary": "Summary",
                    "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
                }
            )
        """
        for pointer in value:
            if "," in pointer:
                raise ValueError("evidence pointers must not contain compound references")
            if parse_evidence_pointer(pointer, allow_multi_hop=True) is None:
                raise ValueError("evidence pointers must be valid evidence pointers")
        return value

    @model_validator(mode="after")
    def validate_edge_id_matches_libs(self) -> EdgeSchema:
        """Verify the consumer and provider segments in edge_id match the library fields.

        Returns:
            The validated EdgeSchema instance.

        Raises:
            ValueError: When the edge_id segments do not match consumer_lib or provider_lib.

        Example:
            EdgeSchema.model_validate(
                {
                    "edge_id": "EDGE-LIB-0001-LIB-0002",
                    "consumer_lib": "LIB-0001",
                    "provider_lib": "LIB-0002",
                    "kind": "api",
                    "consumer_elements": ["DTL-LIB-0001-0001"],
                    "provider_elements": ["DTL-LIB-0002-0001"],
                    "summary": "Summary",
                    "evidence": ["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
                }
            )
        """
        parts = self.edge_id.split("-")
        consumer_from_edge = f"{parts[1]}-{parts[2]}"
        provider_from_edge = f"{parts[3]}-{parts[4]}"
        if consumer_from_edge != self.consumer_lib:
            raise ValueError(
                f"edge_id consumer segment '{consumer_from_edge}' "
                f"does not match consumer_lib '{self.consumer_lib}'"
            )
        if provider_from_edge != self.provider_lib:
            raise ValueError(
                f"edge_id provider segment '{provider_from_edge}' "
                f"does not match provider_lib '{self.provider_lib}'"
            )
        return self


class EdgeListSchema(BaseModel):
    """Capture a run's interface edges.

    Attributes:
        run_id: Workflow run identifier.
        generated_at: ISO-8601 timestamp with time component.
        edges: List of interface edges.

    Example:
        EdgeListSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            edges=[],
        )
    """

    run_id: str
    generated_at: str
    edges: list[EdgeSchema]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        """Validate the generated_at timestamp as ISO-8601.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            The validated timestamp string.

        Example:
            EdgeListSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                edges=[],
            )
        """
        return _validate_iso8601(value)

    @field_validator("edges")
    @classmethod
    def validate_edge_ids_unique(cls, value: list[EdgeSchema]) -> list[EdgeSchema]:
        """Ensure each edge_id appears only once in the list.

        Args:
            value: List of EdgeSchema instances.

        Returns:
            The validated list of edges.

        Example:
            EdgeListSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                edges=[],
            )
        """
        seen: set[str] = set()
        duplicates: list[str] = []
        for edge in value:
            if edge.edge_id in seen:
                duplicates.append(edge.edge_id)
            seen.add(edge.edge_id)
        if duplicates:
            raise ValueError("edge_id values must be unique")
        return value


class InterfaceIndexSchema(BaseModel):
    """Index interface edges to generated contract artifacts.

    Attributes:
        run_id: Workflow run identifier.
        generated_at: ISO-8601 timestamp with time component.
        edges_by_consumer: Map of consumer lib to edge IDs.
        edges_by_provider: Map of provider lib to edge IDs.
        contract_files: Map of edge IDs to contract file paths.

    Example:
        InterfaceIndexSchema(
            run_id="run_001",
            generated_at="2024-01-01T00:00:00",
            edges_by_consumer={"LIB-0001": ["EDGE-LIB-0001-LIB-0002"]},
            edges_by_provider={"LIB-0002": ["EDGE-LIB-0001-LIB-0002"]},
            contract_files={
                "EDGE-LIB-0001-LIB-0002": {
                    "markdown": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.md",
                    "json": "libraries/LIB-0001/interfaces/EDGE-LIB-0001-LIB-0002.json",
                }
            },
        )
    """

    run_id: str
    generated_at: str
    edges_by_consumer: dict[str, list[str]]
    edges_by_provider: dict[str, list[str]]
    contract_files: dict[str, dict[str, str]]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        """Validate the generated_at timestamp as ISO-8601.

        Args:
            value: ISO-8601 timestamp string.

        Returns:
            The validated timestamp string.

        Example:
            InterfaceIndexSchema(
                run_id="run_001",
                generated_at="2024-01-01T00:00:00",
                edges_by_consumer={},
                edges_by_provider={},
                contract_files={},
            )
        """
        return _validate_iso8601(value)


def allocate_edge_id(consumer_lib: str, provider_lib: str) -> str:
    """Allocate a deterministic edge ID from library identifiers.

    Args:
        consumer_lib: Consumer library ID ("LIB-####").
        provider_lib: Provider library ID ("LIB-####").

    Returns:
        The edge ID in the form "EDGE-LIB-####-LIB-####".

    Raises:
        ValueError: When either library ID is invalid.

    Example:
        allocate_edge_id("LIB-0001", "LIB-0002")
    """
    if not LIB_ID_RE.fullmatch(consumer_lib) or not LIB_ID_RE.fullmatch(provider_lib):
        raise ValueError("consumer_lib and provider_lib must match LIB-####")
    return f"EDGE-{consumer_lib}-{provider_lib}"


def validate_edge_references(
    edge: EdgeSchema,
    allocated_library_ids: set[str],
    element_lookup: dict[str, set[str]],
) -> tuple[bool, list[str]]:
    """Validate an edge's references against known libraries and element IDs.

    Args:
        edge: EdgeSchema instance to validate.
        allocated_library_ids: Set of known library IDs.
        element_lookup: Mapping of library IDs to element ID sets.

    Returns:
        Tuple of (is_valid, error_messages).

    Example:
        is_valid, errors = validate_edge_references(
            edge,
            {"LIB-0001", "LIB-0002"},
            {"LIB-0001": {"DTL-LIB-0001-0001"}, "LIB-0002": {"DTL-LIB-0002-0001"}},
        )
    """
    errors: list[str] = []

    if edge.consumer_lib not in allocated_library_ids:
        errors.append(f"Unknown consumer library id '{edge.consumer_lib}'.")
    if edge.provider_lib not in allocated_library_ids:
        errors.append(f"Unknown provider library id '{edge.provider_lib}'.")

    consumer_elements = element_lookup.get(edge.consumer_lib, set())
    provider_elements = element_lookup.get(edge.provider_lib, set())

    missing_consumer = [
        element_id for element_id in edge.consumer_elements if element_id not in consumer_elements
    ]
    if missing_consumer:
        errors.append(
            "Missing consumer elements for {lib_id}: {elements}.".format(
                lib_id=edge.consumer_lib,
                elements=", ".join(sorted(missing_consumer)),
            )
        )

    missing_provider = [
        element_id for element_id in edge.provider_elements if element_id not in provider_elements
    ]
    if missing_provider:
        errors.append(
            "Missing provider elements for {lib_id}: {elements}.".format(
                lib_id=edge.provider_lib,
                elements=", ".join(sorted(missing_provider)),
            )
        )

    return not errors, errors


def write_edge_list_json(edge_list: EdgeListSchema, output_path: Path) -> None:
    """Write an edge list JSON file to disk.

    Args:
        edge_list: EdgeListSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_edge_list_json(edge_list, Path("reports/edge_list.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = edge_list.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_edge_list_json(input_path: Path) -> EdgeListSchema:
    """Read and validate an edge list JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated EdgeListSchema instance.

    Example:
        edge_list = read_edge_list_json(Path("reports/edge_list.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return EdgeListSchema.model_validate(json.loads(content))


def build_interface_index(
    edges: list[EdgeSchema],
    run_id: str,
    contract_base_path: Path,
    contracts_ready: set[str] | None = None,
) -> InterfaceIndexSchema:
    """Build an interface index for a set of edges.

    Only edges whose ``edge_id`` appears in *contracts_ready* receive
    ``contract_files`` entries.  When *contracts_ready* is ``None`` every
    edge is assumed to have a written contract (backwards-compatible
    default).

    Args:
        edges: List of EdgeSchema instances.
        run_id: Workflow run identifier.
        contract_base_path: Base path used for contract artifact locations.
        contracts_ready: Edge IDs with successfully written contract
            artifacts.  Edges not in this set are still tracked in the
            consumer/provider lookups but omitted from ``contract_files``
            so the index never references missing files.

    Returns:
        InterfaceIndexSchema containing mappings of edges to contract files.

    Example:
        index = build_interface_index(edges, "run_001", Path("."),
                                      contracts_ready={"EDGE-LIB-0001-LIB-0002"})
    """
    edges_by_consumer: dict[str, list[str]] = {}
    edges_by_provider: dict[str, list[str]] = {}
    contract_files: dict[str, dict[str, str]] = {}

    for edge in edges:
        edges_by_consumer.setdefault(edge.consumer_lib, []).append(edge.edge_id)
        edges_by_provider.setdefault(edge.provider_lib, []).append(edge.edge_id)

        if contracts_ready is not None and edge.edge_id not in contracts_ready:
            continue

        contract_rel = Path("libraries") / edge.consumer_lib / "interfaces" / edge.edge_id
        contract_files[edge.edge_id] = {
            "markdown": str((contract_base_path / contract_rel).with_suffix(".md")),
            "json": str((contract_base_path / contract_rel).with_suffix(".json")),
        }

    return InterfaceIndexSchema(
        run_id=run_id,
        generated_at=datetime.now().isoformat(),
        edges_by_consumer=edges_by_consumer,
        edges_by_provider=edges_by_provider,
        contract_files=contract_files,
    )


def write_interface_index_json(index: InterfaceIndexSchema, output_path: Path) -> None:
    """Write the interface index JSON file to disk.

    Args:
        index: InterfaceIndexSchema to serialize.
        output_path: Destination file path.

    Example:
        write_interface_index_json(index, Path("reports/interface_index.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = index.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_interface_index_json(input_path: Path) -> InterfaceIndexSchema:
    """Read and validate an interface index JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated InterfaceIndexSchema instance.

    Example:
        index = read_interface_index_json(Path("reports/interface_index.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return InterfaceIndexSchema.model_validate(json.loads(content))


def validate_edge_list_completeness(
    edge_list: EdgeListSchema,
    allocated_library_ids: set[str],
    spec_indexes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate edge references against library IDs and spec indexes.

    Args:
        edge_list: Edge list to validate.
        allocated_library_ids: Known library identifiers.
        spec_indexes: Mapping of library IDs to spec index objects.

    Returns:
        List of error dictionaries with edge_id, error_type, message, and context.

    Example:
        errors = validate_edge_list_completeness(edge_list, {"LIB-0001"}, spec_indexes)
    """
    element_lookup: dict[str, set[str]] = {}
    for lib_id, spec_index in spec_indexes.items():
        element_ids: set[str] = set()
        elements = getattr(spec_index, "elements", None)
        if elements is None and isinstance(spec_index, dict):
            elements = spec_index.get("elements")
        if isinstance(elements, list):
            for element in elements:
                element_id = getattr(element, "element_id", None)
                if element_id is None and isinstance(element, dict):
                    element_id = element.get("element_id")
                if isinstance(element_id, str):
                    element_ids.add(element_id)
        decisions = getattr(spec_index, "decisions", None)
        if decisions is None and isinstance(spec_index, dict):
            decisions = spec_index.get("decisions")
        if isinstance(decisions, list):
            for decision in decisions:
                decision_id = getattr(decision, "decision_id", None)
                if decision_id is None and isinstance(decision, dict):
                    decision_id = decision.get("decision_id")
                if isinstance(decision_id, str):
                    element_ids.add(decision_id)
        element_lookup[lib_id] = element_ids

    errors: list[dict[str, Any]] = []
    for edge in edge_list.edges:
        is_valid, messages = validate_edge_references(edge, allocated_library_ids, element_lookup)
        if is_valid:
            continue
        for message in messages:
            errors.append(
                {
                    "edge_id": edge.edge_id,
                    "error_type": "edge_reference_error",
                    "message": message,
                    "context": {
                        "consumer_lib": edge.consumer_lib,
                        "provider_lib": edge.provider_lib,
                        "consumer_elements": edge.consumer_elements,
                        "provider_elements": edge.provider_elements,
                    },
                }
            )

    return errors


def validate_contract_completeness(
    contract: InterfaceContractSchema,
    allocated_library_ids: set[str],
    spec_indexes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate a contract against library IDs, spec indexes, and required sections.

    Args:
        contract: InterfaceContractSchema to validate.
        allocated_library_ids: Known library identifiers.
        spec_indexes: Mapping of library IDs to spec index objects.

    Returns:
        List of error dictionaries with edge_id, error_type, message, and context.

    Example:
        errors = validate_contract_completeness(contract, {"LIB-0001"}, spec_indexes)
    """
    element_lookup: dict[str, set[str]] = {}
    for lib_id, spec_index in spec_indexes.items():
        element_ids: set[str] = set()
        elements = getattr(spec_index, "elements", None)
        if elements is None and isinstance(spec_index, dict):
            elements = spec_index.get("elements")
        if isinstance(elements, list):
            for element in elements:
                element_id = getattr(element, "element_id", None)
                if element_id is None and isinstance(element, dict):
                    element_id = element.get("element_id")
                if isinstance(element_id, str):
                    element_ids.add(element_id)
        decisions = getattr(spec_index, "decisions", None)
        if decisions is None and isinstance(spec_index, dict):
            decisions = spec_index.get("decisions")
        if isinstance(decisions, list):
            for decision in decisions:
                decision_id = getattr(decision, "decision_id", None)
                if decision_id is None and isinstance(decision, dict):
                    decision_id = decision.get("decision_id")
                if isinstance(decision_id, str):
                    element_ids.add(decision_id)
        element_lookup[lib_id] = element_ids

    errors: list[dict[str, Any]] = []

    from .interface_contract import validate_contract_references

    is_valid, messages = validate_contract_references(
        contract, allocated_library_ids, element_lookup
    )
    if not is_valid:
        for message in messages:
            errors.append(
                {
                    "edge_id": contract.edge_id,
                    "error_type": "contract_reference_error",
                    "message": message,
                    "context": {
                        "consumer_lib": contract.consumer_lib,
                        "provider_lib": contract.provider_lib,
                    },
                }
            )

    if not contract.provided:
        errors.append(
            {
                "edge_id": contract.edge_id,
                "error_type": "missing_provided_interfaces",
                "message": "At least one provided interface is required.",
                "context": {},
            }
        )

    if not contract.consumed_by:
        errors.append(
            {
                "edge_id": contract.edge_id,
                "error_type": "missing_consumed_interfaces",
                "message": "At least one consumer entry is required.",
                "context": {},
            }
        )

    for interface in contract.provided:
        for citation in interface.citations:
            if parse_evidence_pointer(citation, allow_multi_hop=True) is None:
                errors.append(
                    {
                        "edge_id": contract.edge_id,
                        "error_type": "invalid_citation",
                        "message": f"Invalid citation pointer '{citation}'.",
                        "context": {"interface": interface.name},
                    }
                )

    for entry in contract.consumed_by:
        for citation in entry.citations:
            if parse_evidence_pointer(citation, allow_multi_hop=True) is None:
                errors.append(
                    {
                        "edge_id": contract.edge_id,
                        "error_type": "invalid_citation",
                        "message": f"Invalid citation pointer '{citation}'.",
                        "context": {"consumer_requirement": entry.consumer_requirement},
                    }
                )

    return errors
