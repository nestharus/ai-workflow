"""Schemas for spec and decisions indexes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .validation_utils import DECISION_ID_RE, ELEMENT_ID_RE, LIB_ID_RE, validate_iso8601

_KIND_BY_PREFIX: dict[str, Literal["detail", "constraint", "analysis", "overview"]] = {
    "DTL": "detail",
    "CON": "constraint",
    "ANL": "analysis",
    "OVW": "overview",
}


class SpecElement(BaseModel):
    element_id: str
    kind: Literal["detail", "constraint", "analysis", "overview"]
    section: str
    text: str
    raw_line: str
    citations: list[str] = Field(default_factory=list)
    mentions_libs: list[str] = Field(default_factory=list)

    @field_validator("element_id")
    @classmethod
    def validate_element_id(cls, value: str) -> str:
        if not ELEMENT_ID_RE.fullmatch(value):
            raise ValueError("element_id must match DTL/CON/ANL/OVW-LIB-####-####")
        return value

    @model_validator(mode="after")
    def validate_kind_matches_element_id(self) -> SpecElement:
        prefix = self.element_id.split("-", 1)[0]
        expected_kind = _KIND_BY_PREFIX.get(prefix)
        if expected_kind is None:
            raise ValueError("element_id must start with DTL, CON, ANL, or OVW")
        if self.kind != expected_kind:
            raise ValueError(
                f"kind '{self.kind}' does not match element_id prefix '{prefix}' ({expected_kind})"
            )
        return self


class SpecIndex(BaseModel):
    lib_id: str
    generated_at: str
    spec_path: str
    elements: list[SpecElement]

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        if not LIB_ID_RE.fullmatch(value):
            raise ValueError("lib_id must match LIB-####")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return validate_iso8601(value)


class Decision(BaseModel):
    decision_id: str
    status: Literal["open", "resolved", "superseded"] = "open"
    question: str
    context: str | None = None
    options: list[str] = Field(default_factory=list)
    default: str | None = None
    citations: list[str] = Field(default_factory=list)

    @field_validator("decision_id")
    @classmethod
    def validate_decision_id(cls, value: str) -> str:
        if not DECISION_ID_RE.fullmatch(value):
            raise ValueError("decision_id must match ANL-LIB-####-####")
        return value


class DecisionsIndex(BaseModel):
    lib_id: str
    generated_at: str
    decisions_path: str
    decisions: list[Decision]

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        if not LIB_ID_RE.fullmatch(value):
            raise ValueError("lib_id must match LIB-####")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return validate_iso8601(value)
