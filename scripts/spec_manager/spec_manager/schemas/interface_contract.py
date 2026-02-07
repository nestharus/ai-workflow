"""Schemas and helpers for interface contract artifacts.

Example:
    contract = InterfaceContractSchema(
        edge_id="EDGE-LIB-0001-LIB-0002",
        consumer_lib="LIB-0001",
        provider_lib="LIB-0002",
        provided=[
            ProvidedInterface(
                name="ListItems",
                type="http",
                requirements=["DTL-LIB-0002-0001"],
                details="Lists items from the catalog.",
                acceptance=["Returns 200 with items"],
                citations=["[LIB-0002::spec.md::DTL-LIB-0002-0001]"],
            )
        ],
        consumed_by=[
            ConsumedInterface(
                consumer_requirement="DTL-LIB-0001-0001",
                expectations=["Latency under 100ms"],
                citations=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            )
        ],
    )
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from spec_manager.core.evidence_pointers import parse_evidence_pointer

from .edge_list import EDGE_ID_RE, ELEMENT_ID_RE, LIB_ID_RE

DECISION_ID_RE = re.compile(r"^ANL-LIB-\d{4}-\d{4}$")


def _extract_lib_id_from_decision(decision_id: str) -> str | None:
    """Extract the LIB-#### portion from a decision ID.

    Args:
        decision_id: Decision identifier such as "ANL-LIB-0001-0001".

    Returns:
        The library ID ("LIB-####") or None if parsing fails.

    Example:
        _extract_lib_id_from_decision("ANL-LIB-0001-0001")
    """
    parts = decision_id.split("-")
    if len(parts) < 4:
        return None
    return f"{parts[1]}-{parts[2]}"


class ProvidedInterface(BaseModel):
    """Describe an interface supplied by a provider library.

    Attributes:
        name: Interface name.
        type: Interface type such as "http" or "event".
        requirements: Provider requirement IDs satisfied by the interface.
        details: Free-form description of the interface.
        acceptance: Acceptance criteria statements.
        citations: Evidence pointers supporting the interface.

    Example:
        ProvidedInterface(
            name="ListItems",
            type="http",
            requirements=["DTL-LIB-0002-0001"],
            details="Lists items from the catalog.",
            acceptance=["Returns 200 with items"],
            citations=["[LIB-0002::spec.md::DTL-LIB-0002-0001]"],
        )
    """

    name: str
    type: Literal["function", "http", "event", "file", "db", "config", "other"]
    requirements: list[str]
    details: str
    acceptance: list[str]
    citations: list[str]

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, value: list[str]) -> list[str]:
        """Ensure requirements reference known element IDs.

        Args:
            value: List of requirement IDs.

        Returns:
            The validated list of requirement IDs.

        Example:
            ProvidedInterface(
                name="ListItems",
                type="http",
                requirements=["DTL-LIB-0002-0001"],
                details="Details",
                acceptance=[],
                citations=["[LIB-0002::spec.md::DTL-LIB-0002-0001]"],
            )
        """
        for requirement_id in value:
            if not ELEMENT_ID_RE.fullmatch(requirement_id):
                raise ValueError(
                    "requirement IDs must match DTL-LIB-####-####, CON-LIB-####-####, "
                    "ANL-LIB-####-####, or OVW-LIB-####-####"
                )
        return value

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        """Validate evidence pointers, including multi-hop library references.

        Args:
            value: List of evidence pointer strings.

        Returns:
            The validated list of evidence pointers.

        Example:
            ProvidedInterface(
                name="ListItems",
                type="http",
                requirements=["DTL-LIB-0002-0001"],
                details="Details",
                acceptance=[],
                citations=["[LIB-0002::spec.md::DTL-LIB-0002-0001]"],
            )
        """
        for pointer in value:
            if parse_evidence_pointer(pointer, allow_multi_hop=True) is None:
                raise ValueError("citations must be valid evidence pointers")
        return value


class ConsumedInterface(BaseModel):
    """Describe how a consumer requirement depends on a provider interface.

    Attributes:
        consumer_requirement: Consumer requirement ID that relies on the interface.
        expectations: Expectations or assumptions held by the consumer.
        citations: Evidence pointers supporting the dependency.

    Example:
        ConsumedInterface(
            consumer_requirement="DTL-LIB-0001-0001",
            expectations=["Latency under 100ms"],
            citations=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
        )
    """

    consumer_requirement: str
    expectations: list[str]
    citations: list[str]

    @field_validator("consumer_requirement")
    @classmethod
    def validate_consumer_requirement(cls, value: str) -> str:
        """Ensure the consumer requirement matches known element ID patterns.

        Args:
            value: Consumer requirement ID.

        Returns:
            The validated consumer requirement ID.

        Example:
            ConsumedInterface(
                consumer_requirement="DTL-LIB-0001-0001",
                expectations=[],
                citations=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            )
        """
        if not ELEMENT_ID_RE.fullmatch(value):
            raise ValueError(
                "consumer requirement IDs must match DTL-LIB-####-####, CON-LIB-####-####, "
                "ANL-LIB-####-####, or OVW-LIB-####-####"
            )
        return value

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        """Validate evidence pointers, including multi-hop library references.

        Args:
            value: List of evidence pointer strings.

        Returns:
            The validated list of evidence pointers.

        Example:
            ConsumedInterface(
                consumer_requirement="DTL-LIB-0001-0001",
                expectations=[],
                citations=["[LIB-0001::spec.md::DTL-LIB-0001-0001]"],
            )
        """
        for pointer in value:
            if parse_evidence_pointer(pointer, allow_multi_hop=True) is None:
                raise ValueError("citations must be valid evidence pointers")
        return value


class DataContract(BaseModel):
    """Capture data schema constraints for an interface contract.

    Example:
        DataContract(schemas=["schemas/item.json"], compatibility="Backwards compatible")
    """

    schemas: list[str] = Field(default_factory=list)
    compatibility: str = ""


class OperationalContract(BaseModel):
    """Capture operational expectations for an interface contract.

    Example:
        OperationalContract(
            performance="p95 < 200ms",
            failure_modes="Graceful degradation when provider unavailable",
            security="OAuth2 with mTLS",
        )
    """

    performance: str = ""
    failure_modes: str = ""
    security: str = ""


class InterfaceContractSchema(BaseModel):
    """Structured representation of an interface contract between libraries.

    Attributes:
        edge_id: Edge ID linking the consumer and provider.
        consumer_lib: Consumer library ID ("LIB-####").
        provider_lib: Provider library ID ("LIB-####").
        contract_version: Semantic contract version (default "v1").
        provided: Interfaces supplied by the provider.
        consumed_by: Consumer expectations tied to provider interfaces.
        data_contract: Data schema expectations.
        operational: Operational expectations.
        open_questions: Decision IDs that remain unresolved.

    Example:
        InterfaceContractSchema(
            edge_id="EDGE-LIB-0001-LIB-0002",
            consumer_lib="LIB-0001",
            provider_lib="LIB-0002",
            provided=[],
            consumed_by=[],
            open_questions=["ANL-LIB-0001-0001"],
        )
    """

    edge_id: str
    consumer_lib: str
    provider_lib: str
    contract_version: str = "v1"
    provided: list[ProvidedInterface]
    consumed_by: list[ConsumedInterface]
    data_contract: DataContract = Field(default_factory=DataContract)
    operational: OperationalContract = Field(default_factory=OperationalContract)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, value: str) -> str:
        """Ensure edge_id matches EDGE-LIB-####-LIB-#### format.

        Args:
            value: Edge identifier string.

        Returns:
            The validated edge identifier.

        Example:
            InterfaceContractSchema(
                edge_id="EDGE-LIB-0001-LIB-0002",
                consumer_lib="LIB-0001",
                provider_lib="LIB-0002",
                provided=[],
                consumed_by=[],
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
            InterfaceContractSchema(
                edge_id="EDGE-LIB-0001-LIB-0002",
                consumer_lib="LIB-0001",
                provider_lib="LIB-0002",
                provided=[],
                consumed_by=[],
            )
        """
        if not LIB_ID_RE.fullmatch(value):
            raise ValueError("library IDs must match LIB-####")
        return value

    @field_validator("open_questions")
    @classmethod
    def validate_open_questions(cls, value: list[str]) -> list[str]:
        """Ensure open questions reference decision IDs (ANL-LIB-####-####).

        Args:
            value: List of decision IDs.

        Returns:
            The validated list of decision IDs.

        Example:
            InterfaceContractSchema(
                edge_id="EDGE-LIB-0001-LIB-0002",
                consumer_lib="LIB-0001",
                provider_lib="LIB-0002",
                provided=[],
                consumed_by=[],
                open_questions=["ANL-LIB-0001-0001"],
            )
        """
        for decision_id in value:
            if not DECISION_ID_RE.fullmatch(decision_id):
                raise ValueError("open_questions must contain ANL-LIB-####-#### IDs")
        return value

    @model_validator(mode="after")
    def validate_edge_id_matches_libs(self) -> InterfaceContractSchema:
        """Verify the consumer and provider segments in edge_id match the library fields.

        Returns:
            The validated InterfaceContractSchema instance.

        Raises:
            ValueError: When the edge_id segments do not match consumer_lib or provider_lib.

        Example:
            InterfaceContractSchema(
                edge_id="EDGE-LIB-0001-LIB-0002",
                consumer_lib="LIB-0001",
                provider_lib="LIB-0002",
                provided=[],
                consumed_by=[],
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


def validate_contract_references(
    contract: InterfaceContractSchema,
    allocated_library_ids: set[str],
    element_lookup: dict[str, set[str]],
) -> tuple[bool, list[str]]:
    """Validate contract references against library and element inventories.

    Args:
        contract: InterfaceContractSchema instance to validate.
        allocated_library_ids: Set of known library IDs.
        element_lookup: Mapping of library IDs to element ID sets.

    Returns:
        Tuple of (is_valid, error_messages).

    Example:
        is_valid, errors = validate_contract_references(
            contract,
            {"LIB-0001", "LIB-0002"},
            {"LIB-0001": {"DTL-LIB-0001-0001"}, "LIB-0002": {"DTL-LIB-0002-0001"}},
        )
    """
    errors: list[str] = []

    if contract.consumer_lib not in allocated_library_ids:
        errors.append(f"Unknown consumer library id '{contract.consumer_lib}'.")
    if contract.provider_lib not in allocated_library_ids:
        errors.append(f"Unknown provider library id '{contract.provider_lib}'.")

    provider_elements = element_lookup.get(contract.provider_lib, set())
    required_ids = [
        requirement_id
        for interface in contract.provided
        for requirement_id in interface.requirements
    ]
    missing_provider = [req for req in required_ids if req not in provider_elements]
    if missing_provider:
        errors.append(
            "Missing provider requirements for {lib_id}: {elements}.".format(
                lib_id=contract.provider_lib,
                elements=", ".join(sorted(missing_provider)),
            )
        )

    consumer_elements = element_lookup.get(contract.consumer_lib, set())
    consumer_ids = [entry.consumer_requirement for entry in contract.consumed_by]
    missing_consumer = [req for req in consumer_ids if req not in consumer_elements]
    if missing_consumer:
        errors.append(
            "Missing consumer requirements for {lib_id}: {elements}.".format(
                lib_id=contract.consumer_lib,
                elements=", ".join(sorted(missing_consumer)),
            )
        )

    for decision_id in contract.open_questions:
        lib_id = _extract_lib_id_from_decision(decision_id)
        if lib_id is None:
            errors.append(f"Unable to parse decision id '{decision_id}'.")
            continue
        decision_elements = element_lookup.get(lib_id, set())
        if decision_id not in decision_elements:
            errors.append(f"Unknown decision id '{decision_id}'.")

    return not errors, errors


def write_interface_contract_json(contract: InterfaceContractSchema, output_path: Path) -> None:
    """Write a contract JSON file to disk.

    Args:
        contract: InterfaceContractSchema instance to serialize.
        output_path: Destination file path.

    Example:
        write_interface_contract_json(contract, Path("interfaces/contract.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = contract.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_interface_contract_json(input_path: Path) -> InterfaceContractSchema:
    """Read and validate a contract JSON file.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated InterfaceContractSchema instance.

    Example:
        contract = read_interface_contract_json(Path("interfaces/contract.json"))
    """
    content = input_path.read_text(encoding="utf-8")
    return InterfaceContractSchema.model_validate(json.loads(content))


def write_interface_contract_markdown(
    contract: InterfaceContractSchema,
    output_path: Path,
) -> None:
    """Write a human-readable contract report in markdown.

    Args:
        contract: InterfaceContractSchema instance to serialize.
        output_path: Destination markdown file path.

    Example:
        write_interface_contract_markdown(contract, Path("interfaces/contract.md"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _join(items: list[str]) -> str:
        """Join list values or return a dash when empty.

        Args:
            items: List of strings to join.

        Returns:
            Joined string or "-" when empty.

        Example:
            _join(["a", "b"])
        """
        return ", ".join(items) if items else "-"

    def _escape_table(value: str) -> str:
        """Escape pipe characters for markdown table cells.

        Args:
            value: Raw table cell value.

        Returns:
            Escaped table cell value.

        Example:
            _escape_table("a|b")
        """
        return value.replace("|", "\\|")

    lines: list[str] = [
        "# Interface Contract",
        "",
        "## Purpose",
        "",
        f"- Edge ID: {contract.edge_id}",
        f"- Consumer: {contract.consumer_lib}",
        f"- Provider: {contract.provider_lib}",
        f"- Contract Version: {contract.contract_version}",
        "",
        "## Provided Interfaces",
        "",
        "| Name | Type | Requirements | Details | Acceptance |",
        "| --- | --- | --- | --- | --- |",
    ]

    for interface in contract.provided:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(interface.name),
                    interface.type,
                    _escape_table(_join(interface.requirements)),
                    _escape_table(interface.details or "-"),
                    _escape_table(_join(interface.acceptance)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Consumed By",
            "",
            "| Consumer Requirement | Expectations |",
            "| --- | --- |",
        ]
    )

    for entry in contract.consumed_by:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table(entry.consumer_requirement),
                    _escape_table(_join(entry.expectations)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Data Contract",
            "",
            f"- Schemas: {_join(contract.data_contract.schemas)}",
            f"- Compatibility: {contract.data_contract.compatibility or '-'}",
            "",
            "## Operational Concerns",
            "",
            f"- Performance: {contract.operational.performance or '-'}",
            f"- Failure Modes: {contract.operational.failure_modes or '-'}",
            f"- Security: {contract.operational.security or '-'}",
            "",
            "## Open Questions",
            "",
        ]
    )

    if contract.open_questions:
        lines.extend([f"- {decision_id}" for decision_id in contract.open_questions])
    else:
        lines.append("- None")

    citations: list[str] = []
    seen: set[str] = set()
    for interface in contract.provided:
        for citation in interface.citations:
            if citation in seen:
                continue
            seen.add(citation)
            citations.append(citation)
    for entry in contract.consumed_by:
        for citation in entry.citations:
            if citation in seen:
                continue
            seen.add(citation)
            citations.append(citation)

    lines.extend(["", "## Evidence", ""])
    if citations:
        lines.extend([f"- {citation}" for citation in citations])
    else:
        lines.append("- None")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
