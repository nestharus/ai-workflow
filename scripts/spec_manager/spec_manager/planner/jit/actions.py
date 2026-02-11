from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "agent": self.agent,
            "tool": self.tool,
            "inputs": dict(self.inputs),
            "prompt": self.prompt,
        }
