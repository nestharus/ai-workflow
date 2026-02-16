from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(Enum):
    CALL_AGENT = "call_agent"
    RUN_TOOL = "run_tool"
    USER_INPUT = "user_input"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class NextAction:
    """Tells the planner executor what to do next.

    Exactly one of *agent* / *tool* / *prompt* is meaningful depending
    on the *action* type:

    * ``CALL_AGENT`` — *agent* names the target, *inputs* carries payload.
    * ``RUN_TOOL``   — *tool* names the tool,  *inputs* carries payload.
    * ``USER_INPUT`` — *prompt* describes what to ask the user.
    * ``COMPLETE``   — terminal, no further work.
    * ``ERROR``      — terminal, *prompt* carries the error message.
    """

    action: ActionType
    agent: str = ""
    tool: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionType):
            raise TypeError("NextAction.action must be an ActionType")
        if not isinstance(self.inputs, dict):
            raise TypeError("NextAction.inputs must be a dict")

        self.agent = str(self.agent or "").strip()
        self.tool = str(self.tool or "").strip()
        self.prompt = str(self.prompt or "").strip()
        self.inputs = deepcopy(self.inputs)

        required_field: str | None = None
        forbidden_fields: set[str] = set()

        if self.action == ActionType.CALL_AGENT:
            required_field = "agent"
            forbidden_fields = {"tool", "prompt"}
        elif self.action == ActionType.RUN_TOOL:
            required_field = "tool"
            forbidden_fields = {"agent", "prompt"}
        elif self.action == ActionType.USER_INPUT or self.action == ActionType.ERROR:
            required_field = "prompt"
            forbidden_fields = {"agent", "tool"}
        elif self.action == ActionType.COMPLETE:
            forbidden_fields = {"agent", "tool", "prompt"}

        values = {
            "agent": self.agent,
            "tool": self.tool,
            "prompt": self.prompt,
        }
        if required_field is not None and not values[required_field]:
            raise ValueError(
                f"NextAction {self.action.value!r} requires non-empty field {required_field!r}"
            )
        invalid_fields = [name for name in forbidden_fields if values[name]]
        if invalid_fields:
            formatted = ", ".join(sorted(invalid_fields))
            raise ValueError(f"NextAction {self.action.value!r} does not allow fields: {formatted}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "agent": self.agent,
            "tool": self.tool,
            "inputs": deepcopy(self.inputs),
            "prompt": self.prompt,
        }
