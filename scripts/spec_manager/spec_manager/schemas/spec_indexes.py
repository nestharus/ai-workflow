"""Schemas for spec and decisions indexes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_LIB_ID_RE = re.compile(r"^LIB-\d{4}$")
_SPEC_ELEMENT_ID_RE = re.compile(
    r"^(?:REQ-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|INV-LIB-\d{4}-\d{4})$"
)
_DECISION_ID_RE = re.compile(r"^DEC-LIB-\d{4}-\d{4}$")


def _validate_iso8601(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("value must be ISO-8601") from exc
    return value


class SpecElement(BaseModel):
    element_id: str
    kind: Literal["requirement", "flow", "invariant"]
    section: str
    text: str
    raw_line: str
    citations: list[str] = Field(default_factory=list)
    mentions_libs: list[str] = Field(default_factory=list)

    @field_validator("element_id")
    @classmethod
    def validate_element_id(cls, value: str) -> str:
        if not _SPEC_ELEMENT_ID_RE.fullmatch(value):
            raise ValueError(
                "element_id must match REQ-LIB-####-####, FLOW-LIB-####-##, or INV-LIB-####-####"
            )
        return value


class SpecIndex(BaseModel):
    lib_id: str
    generated_at: str
    spec_path: str
    elements: list[SpecElement]

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        if not _LIB_ID_RE.fullmatch(value):
            raise ValueError("lib_id must match LIB-####")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_iso8601(value)


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
        if not _DECISION_ID_RE.fullmatch(value):
            raise ValueError("decision_id must match DEC-LIB-####-####")
        return value


class DecisionsIndex(BaseModel):
    lib_id: str
    generated_at: str
    decisions_path: str
    decisions: list[Decision]

    @field_validator("lib_id")
    @classmethod
    def validate_lib_id(cls, value: str) -> str:
        if not _LIB_ID_RE.fullmatch(value):
            raise ValueError("lib_id must match LIB-####")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_iso8601(value)
