"""Model profile configuration for multi-model PDD runs.

Supports both single-model and mixed-model routing via role-based
model selection.

Usage::

    profile = ModelProfile(
        name="opus",
        producer_model_id="claude-opus-4",
        role_models={"planner": "claude-opus-4", "judge": "gpt-4.1"},
    )
    model = profile.get_model_for_role("planner")  # "claude-opus-4"
    model = profile.get_model_for_role("refinement")  # fallback: "claude-opus-4"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ModelProfile:
    """Model configuration for a pipeline run.

    Attributes:
        name: Profile name (e.g., "opus", "gpt5.3").
        producer_model_id: Default model ID for all roles.
        role_models: Optional per-role overrides. Keys: "planner",
            "refinement", "review", "judge".
    """

    name: str = ""
    producer_model_id: str = ""
    role_models: dict[str, str] = field(default_factory=dict)

    def get_model_for_role(self, role: str) -> str:
        """Get the model ID for a specific role.

        Falls back to producer_model_id if no role-specific override.
        """
        return self.role_models.get(role, self.producer_model_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelProfile:
        return cls(
            name=data.get("name", ""),
            producer_model_id=data.get("producer_model_id", ""),
            role_models=data.get("role_models", {}),
        )
