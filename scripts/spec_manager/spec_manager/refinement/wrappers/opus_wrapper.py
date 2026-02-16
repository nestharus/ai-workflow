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
from typing import Any

from spec_manager.refinement.wrappers.token_manager import TokenManager

# Tasks where Opus excels
OPUS_PREFERRED_TASKS = [
    "library_synthesis",
    "architecture_proposal",
    "design_decision",
    "intent_extraction",
    "high_level_planning",
    "context_understanding",
]

SCHEMA_METADATA_KEYWORDS = {
    "title",
    "description",
    "default",
    "examples",
}
SCHEMA_VALIDATION_KEYWORDS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "additionalProperties",
}
SUPPORTED_SCHEMA_KEYWORDS = SCHEMA_METADATA_KEYWORDS | SCHEMA_VALIDATION_KEYWORDS
SUPPORTED_SCHEMA_TYPES = {
    "object",
    "array",
    "string",
    "number",
    "integer",
    "boolean",
    "null",
}


def _serialize_context_value(value: Any) -> str:
    """Serialize context values with a deterministic prompt-facing format."""
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    raise TypeError(f"Unsupported context value type: {type(value).__name__}")


def _find_unsupported_schema_features(schema: Any, path: str = "root") -> list[str]:
    errors: list[str] = []

    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in SUPPORTED_SCHEMA_KEYWORDS:
                errors.append(f"{path}: unsupported schema keyword '{key}'")

            if key == "type":
                schema_types = value if isinstance(value, list) else [value]
                if not isinstance(schema_types, list):
                    errors.append(f"{path}.type: expected string or list of strings")
                else:
                    for schema_type in schema_types:
                        if schema_type not in SUPPORTED_SCHEMA_TYPES:
                            errors.append(f"{path}.type: unsupported schema type '{schema_type}'")

            if key == "properties":
                if not isinstance(value, dict):
                    errors.append(f"{path}.properties: expected object")
                else:
                    for prop_name, prop_schema in value.items():
                        errors.extend(
                            _find_unsupported_schema_features(
                                prop_schema,
                                f"{path}.properties.{prop_name}",
                            )
                        )

            if key == "items":
                errors.extend(_find_unsupported_schema_features(value, f"{path}.items"))

            if key == "additionalProperties" and isinstance(value, dict):
                errors.extend(
                    _find_unsupported_schema_features(value, f"{path}.additionalProperties")
                )

    return errors


def _matches_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return False


def _validate_against_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    schema_support_errors = _find_unsupported_schema_features(schema)
    if schema_support_errors:
        return False, schema_support_errors

    def _validate(value: Any, schema_fragment: dict[str, Any], path: str) -> list[str]:
        fragment_errors: list[str] = []
        schema_type = schema_fragment.get("type")
        schema_types = schema_type if isinstance(schema_type, list) else [schema_type]

        if schema_type is not None and not any(
            _matches_schema_type(value, allowed_type) for allowed_type in schema_types
        ):
            return [f"{path}: expected {schema_types}, got {type(value).__name__}"]

        if "enum" in schema_fragment and value not in schema_fragment["enum"]:
            fragment_errors.append(f"{path}: value must be one of {schema_fragment['enum']}")

        if "object" in schema_types and isinstance(value, dict):
            properties = schema_fragment.get("properties", {})
            required = schema_fragment.get("required", [])

            for required_field in required:
                if required_field not in value:
                    fragment_errors.append(f"{path}.{required_field}: required field missing")

            for prop_name, prop_schema in properties.items():
                if prop_name in value:
                    fragment_errors.extend(
                        _validate(value[prop_name], prop_schema, f"{path}.{prop_name}")
                    )

            additional_properties = schema_fragment.get("additionalProperties", True)
            extra_keys = sorted(set(value) - set(properties))
            if additional_properties is False and extra_keys:
                for key in extra_keys:
                    fragment_errors.append(f"{path}.{key}: additional property not allowed")
            elif isinstance(additional_properties, dict):
                for key in extra_keys:
                    fragment_errors.extend(
                        _validate(value[key], additional_properties, f"{path}.{key}")
                    )

        if "array" in schema_types and isinstance(value, list):
            items_schema = schema_fragment.get("items")
            if isinstance(items_schema, dict):
                for index, item in enumerate(value):
                    fragment_errors.extend(_validate(item, items_schema, f"{path}[{index}]"))

        return fragment_errors

    validation_errors = _validate(data, schema, "root")
    return len(validation_errors) == 0, validation_errors


def _validate_tool_output(
    structured_data: Any,
    tool_request: ToolUseRequest | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate tool output against the current task tool schema."""
    if structured_data is None:
        return None, []

    if not isinstance(structured_data, dict):
        return None, [f"Structured output must be an object, got {type(structured_data).__name__}"]

    if tool_request is None:
        return None, ["Structured output is unverified: no tool schema available for task"]

    schema = {
        "type": "object",
        "properties": tool_request.input_schema,
        "required": tool_request.required_fields,
        "additionalProperties": False,
    }
    is_valid, errors = _validate_against_schema(structured_data, schema)
    if not is_valid:
        return None, errors
    return structured_data, []


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
    confidence: float = 0.0
    needs_refinement: bool = False
    refinement_areas: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


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
            refinement_areas.append(
                f"Function '{func.get('name')}' parameters lack type annotations"
            )

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
            context_lines: list[str] = []
            for key, value in context.items():
                serialized = _serialize_context_value(value)
                context_lines.append(f"- {key}: {serialized}")
            context_text = "\n".join(context_lines)
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
        candidate_structured_data: Any = tool_use_result
        raw_text = raw_output if isinstance(raw_output, str) else ""

        if candidate_structured_data is None and isinstance(raw_output, dict):
            candidate_structured_data = raw_output

        tool_request = self.get_tool_for_task()
        structured_data, validation_errors = _validate_tool_output(
            candidate_structured_data,
            tool_request,
        )

        if not raw_text and candidate_structured_data is not None:
            raw_text = json.dumps(candidate_structured_data, sort_keys=True, ensure_ascii=True)

        # Extract intent from output
        intent = ""
        confidence = 0.0
        if structured_data:
            for intent_field in ("purpose", "overview", "description"):
                candidate_intent = structured_data.get(intent_field, "")
                if isinstance(candidate_intent, str) and candidate_intent.strip():
                    intent = candidate_intent.strip()
                    break
            confidence = 0.95 if intent else 0.7
        elif raw_text:
            # Try to extract intent from first paragraph
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if paragraphs:
                intent = paragraphs[0][:500]
                confidence = 0.4

        # Identify what needs refinement
        refinement_areas: list[str] = []
        if structured_data:
            refinement_areas = identify_refinement_needs(structured_data)

        if validation_errors:
            refinement_areas.append("Structured output failed schema validation")
            confidence = min(confidence, 0.3)

        if not intent:
            refinement_areas.append("Intent extraction is weak or missing")
            confidence = min(confidence, 0.2 if raw_text else 0.0)

        return OpusOutput(
            intent_captured=intent,
            structured_data=structured_data,
            raw_text=raw_text,
            confidence=confidence,
            needs_refinement=len(refinement_areas) > 0,
            refinement_areas=refinement_areas,
            validation_errors=validation_errors,
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
