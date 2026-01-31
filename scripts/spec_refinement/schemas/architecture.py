"""Schemas for architecture proposal and selection outputs."""

from __future__ import annotations

from pydantic import BaseModel


class ArchitectureComponent(BaseModel):
    name: str
    responsibilities: list[str]


class ArchitectureTradeoffs(BaseModel):
    advantages: list[str]
    disadvantages: list[str]


class ArchitectureCandidate(BaseModel):
    arch_id: str
    pattern: str
    description: str
    components: list[ArchitectureComponent]
    communication: str
    deployment: str
    citations: list[str]
    tradeoffs: ArchitectureTradeoffs


class ArchitectureProposal(BaseModel):
    candidates: list[ArchitectureCandidate]


class ArchitectureSelection(BaseModel):
    selected_arch_id: str
    rationale: str
    rejected_architectures: list[dict[str, str]]
    implementation_risks: list[str]
    evolution_notes: str
