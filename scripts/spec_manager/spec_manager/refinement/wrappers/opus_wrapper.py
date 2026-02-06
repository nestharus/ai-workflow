"""Opus model wrapper for spec refinement.

Opus characteristics:
- Good understanding of intent and context
- Can handle complex architectural decisions
- May be sloppy with implementation details
- Best for high-level synthesis tasks

This wrapper optimizes interactions with Opus by:
1. Leveraging tool_use for structured output
2. Using for library synthesis and architecture proposals
3. Passing output to GPT for detail refinement when needed
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from spec_manager.refinement.wrappers.token_manager import TokenBudget, TokenManager


# Tasks where Opus excels
OPUS_PREFERRED_TASKS = [
    "library_synthesis",
    "architecture_proposal",
    "design_decision",
    "intent_extraction",
    "high_level_planning",
    "context_understanding",
]


@dataclass
class ToolUseRequest:
    """Request for tool_use structured output.

    Attributes:
        tool_name: Name of the tool to invoke.
        tool_description: Description of what the tool does.
        input_schema: JSON schema for tool input.
        required_fields: List of required field names.
    """

    tool_name: str
    tool_description: str
    input_schema: dict[str, Any]
    required_fields: list[str] = field(default_factory=list)

    def to_tool_definition(self) -> dict[str, Any]:
        """Convert to Claude tool definition format.

        Returns:
            Tool definition dictionary.
        """
        return {
            "name": self.tool_name,
            "description": self.tool_description,
            "input_schema": {
                "type": "object",
                "properties": self.input_schema,
                "required": self.required_fields,
            },
        }


@dataclass
class OpusOutput:
    """Processed output from Opus.

    Attributes:
        intent_captured: The high-level intent/goal extracted.
        structured_data: Structured data from tool_use.
        raw_text: Raw text output if any.
        confidence: Confidence score (0-1) in the output.
        needs_refinement: Whether output needs detail refinement.
        refinement_areas: Areas that need refinement.
    """

    intent_captured: str
    structured_data: dict[str, Any] | None = None
    raw_text: str = ""
    confidence: float = 1.0
    needs_refinement: bool = False
    refinement_areas: list[str] = field(default_factory=list)


def create_library_synthesis_tool() -> ToolUseRequest:
    """Create tool definition for library synthesis.

    Returns:
        ToolUseRequest for library synthesis.
    """
    return ToolUseRequest(
        tool_name="synthesize_library",
        tool_description="Synthesize a library specification from extracted information",
        input_schema={
            "library_name": {
                "type": "string",
                "description": "Name of the library",
            },
            "purpose": {
                "type": "string",
                "description": "High-level purpose of the library",
            },
            "key_functions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "parameters": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "description": "Key functions the library provides",
            },
            "dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "External dependencies",
            },
            "design_rationale": {
                "type": "string",
                "description": "Rationale for design decisions",
            },
        },
        required_fields=["library_name", "purpose", "key_functions"],
    )


def create_architecture_proposal_tool() -> ToolUseRequest:
    """Create tool definition for architecture proposals.

    Returns:
        ToolUseRequest for architecture proposals.
    """
    return ToolUseRequest(
        tool_name="propose_architecture",
        tool_description="Propose an architecture design based on requirements",
        input_schema={
            "architecture_name": {
                "type": "string",
                "description": "Name for the architecture",
            },
            "overview": {
                "type": "string",
                "description": "High-level overview of the architecture",
            },
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "responsibility": {"type": "string"},
                        "interfaces": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "description": "Major components and their responsibilities",
            },
            "data_flow": {
                "type": "string",
                "description": "Description of data flow between components",
            },
            "key_decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "rationale": {"type": "string"},
                        "alternatives_considered": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "description": "Key architectural decisions with rationale",
            },
        },
        required_fields=["architecture_name", "overview", "components"],
    )


def identify_refinement_needs(output: dict[str, Any]) -> list[str]:
    """Identify areas in Opus output that need detail refinement.

    Opus tends to be sloppy with:
    - Precise type definitions
    - Edge case handling
    - Detailed parameter specifications
    - Exact error conditions

    Args:
        output: Structured output from Opus.

    Returns:
        List of areas needing refinement.
    """
    refinement_areas: list[str] = []

    # Check for vague function parameters
    for func in output.get("key_functions", []):
        params = func.get("parameters", [])
        if not params:
            refinement_areas.append(f"Function '{func.get('name')}' missing parameter details")
        elif all(isinstance(p, str) and ":" not in p for p in params):
            refinement_areas.append(f"Function '{func.get('name')}' parameters lack type annotations")

    # Check for missing error handling
    if "error_handling" not in output and "key_functions" in output:
        refinement_areas.append("Missing error handling specifications")

    # Check for vague descriptions
    for key in ["purpose", "overview", "description"]:
        value = output.get(key, "")
        if value and len(value) < 50:
            refinement_areas.append(f"'{key}' description may be too brief")

    # Check components for missing interfaces
    for comp in output.get("components", []):
        if not comp.get("interfaces"):
            refinement_areas.append(f"Component '{comp.get('name')}' missing interface definitions")

    return refinement_areas


@dataclass
class OpusWrapper:
    """Wrapper for Opus model interactions.

    Attributes:
        token_manager: Token manager for budget tracking.
        use_tool_use: Whether to use tool_use for structured output.
        task_type: Current task type.
    """

    token_manager: TokenManager = field(default_factory=lambda: TokenManager(model_name="opus"))
    use_tool_use: bool = True
    task_type: str = "library_synthesis"

    def is_preferred_task(self, task_type: str) -> bool:
        """Check if Opus is preferred for a task type.

        Args:
            task_type: Type of task.

        Returns:
            True if Opus is preferred for this task.
        """
        return task_type in OPUS_PREFERRED_TASKS

    def get_tool_for_task(self) -> ToolUseRequest | None:
        """Get tool definition for current task type.

        Returns:
            ToolUseRequest if applicable, None otherwise.
        """
        if not self.use_tool_use:
            return None

        if self.task_type == "library_synthesis":
            return create_library_synthesis_tool()
        elif self.task_type in ("architecture_proposal", "design_decision"):
            return create_architecture_proposal_tool()

        return None

    def prepare_prompt(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Prepare prompt and tools for Opus.

        Args:
            prompt: Original prompt.
            context: Additional context to include.

        Returns:
            Tuple of (prepared_prompt, tools_list).
        """
        # Opus benefits from explicit context framing
        if context:
            context_text = "\n".join(f"- {k}: {v}" for k, v in context.items())
            prompt = f"Context:\n{context_text}\n\nTask:\n{prompt}"

        tools: list[dict[str, Any]] = []
        tool_request = self.get_tool_for_task()
        if tool_request:
            tools.append(tool_request.to_tool_definition())

        return prompt, tools

    def process_output(
        self,
        raw_output: str | dict[str, Any],
        tool_use_result: dict[str, Any] | None = None,
    ) -> OpusOutput:
        """Process Opus output and identify refinement needs.

        Args:
            raw_output: Raw output from Opus.
            tool_use_result: Result from tool_use if applicable.

        Returns:
            OpusOutput with processed data.
        """
        structured_data = tool_use_result
        raw_text = raw_output if isinstance(raw_output, str) else ""

        if structured_data is None and isinstance(raw_output, dict):
            structured_data = raw_output

        # Extract intent from output
        intent = ""
        if structured_data:
            intent = (
                structured_data.get("purpose")
                or structured_data.get("overview")
                or structured_data.get("description", "")
            )
        elif raw_text:
            # Try to extract intent from first paragraph
            paragraphs = raw_text.split("\n\n")
            if paragraphs:
                intent = paragraphs[0][:500]

        # Identify what needs refinement
        refinement_areas: list[str] = []
        if structured_data:
            refinement_areas = identify_refinement_needs(structured_data)

        return OpusOutput(
            intent_captured=intent,
            structured_data=structured_data,
            raw_text=raw_text,
            needs_refinement=len(refinement_areas) > 0,
            refinement_areas=refinement_areas,
        )

    def create_refinement_prompt(
        self,
        opus_output: OpusOutput,
    ) -> str:
        """Create a prompt for GPT to refine Opus output.

        Args:
            opus_output: Output from Opus that needs refinement.

        Returns:
            Prompt for GPT refinement.
        """
        areas_text = "\n".join(f"- {area}" for area in opus_output.refinement_areas)

        prompt = f"""Refine the following specification with precise details.

Intent: {opus_output.intent_captured}

Current specification:
```json
{json.dumps(opus_output.structured_data, indent=2)}
```

Areas needing refinement:
{areas_text}

Provide the refined specification with:
1. Precise type annotations for all parameters
2. Explicit error conditions and handling
3. Detailed interface contracts
4. Edge case specifications

Output as JSON only."""

        return prompt
