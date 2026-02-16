"""GPT model wrapper for spec refinement.

GPT characteristics:
- Good at synthesis and following precise formats
- May miss broader intent/context
- Best for audits, reviews, and spec refinement
- Excellent at strict output format enforcement

This wrapper optimizes interactions with GPT by:
1. Enforcing strict output formats
2. Providing intent context from Opus
3. Using for detail refinement tasks
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from spec_manager.refinement.wrappers.token_manager import TokenManager

# Strict output format templates for GPT
GPT_STRICT_OUTPUT_FORMATS = {
    "requirement_audit": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "text": {"type": "string"},
                        "category": {"type": "string"},
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                        },
                        "verification_method": {"type": "string"},
                    },
                    "required": ["requirement_id", "text", "category"],
                },
            },
            "coverage_gaps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "issue": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
        },
        "required": ["requirements"],
    },
    "spec_synthesis": {
        "type": "object",
        "properties": {
            "specification": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "version": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section_id": {"type": "string"},
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "requirements": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["section_id", "title", "content"],
                        },
                    },
                },
                "required": ["title", "sections"],
            },
            "traceability": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "required": ["specification"],
    },
    "detail_refinement": {
        "type": "object",
        "properties": {
            "refined_functions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "parameters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "constraints": {"type": "string"},
                                },
                                "required": ["name", "type"],
                            },
                        },
                        "return_type": {"type": "string"},
                        "errors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "condition": {"type": "string"},
                                    "error_type": {"type": "string"},
                                    "message": {"type": "string"},
                                },
                            },
                        },
                        "edge_cases": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["name", "parameters", "return_type"],
                },
            },
            "refined_interfaces": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "interface_name": {"type": "string"},
                        "methods": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "contracts": {
                            "type": "object",
                            "properties": {
                                "preconditions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "postconditions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "invariants": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["interface_name", "methods"],
                },
            },
        },
    },
}

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


def _allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    schema_copy = copy.deepcopy(schema)
    schema_type = schema_copy.get("type")
    if schema_type is None:
        return schema_copy

    if isinstance(schema_type, str):
        if schema_type != "null":
            schema_copy["type"] = [schema_type, "null"]
    elif isinstance(schema_type, list) and "null" not in schema_type:
        schema_copy["type"] = [*schema_type, "null"]

    if "enum" in schema_copy and None not in schema_copy["enum"]:
        schema_copy["enum"] = [*schema_copy["enum"], None]

    return schema_copy


def _build_runtime_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema_copy = copy.deepcopy(schema)
    schema_type = schema_copy.get("type")

    if schema_type == "object":
        required = set(schema_copy.get("required", []))
        properties = schema_copy.get("properties", {})
        if isinstance(properties, dict):
            rewritten_properties: dict[str, Any] = {}
            for prop_name, prop_schema in properties.items():
                rewritten_property_schema = _build_runtime_schema(prop_schema)
                if prop_name not in required:
                    rewritten_property_schema = _allow_null(rewritten_property_schema)
                rewritten_properties[prop_name] = rewritten_property_schema
            schema_copy["properties"] = rewritten_properties

        additional_properties = schema_copy.get("additionalProperties")
        if isinstance(additional_properties, dict):
            schema_copy["additionalProperties"] = _build_runtime_schema(additional_properties)

    if schema_type == "array":
        items_schema = schema_copy.get("items")
        if isinstance(items_schema, dict):
            schema_copy["items"] = _build_runtime_schema(items_schema)

    return schema_copy


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


def create_format_enforcement_suffix(output_format: dict[str, Any]) -> str:
    """Create a suffix that enforces output format.

    Args:
        output_format: JSON schema for expected output.

    Returns:
        Format enforcement text to append to prompt.
    """
    schema_str = json.dumps(output_format, indent=2)

    return f"""
OUTPUT FORMAT (STRICT - follow exactly):
```json
{schema_str}
```

IMPORTANT:
- Output ONLY valid JSON matching the schema above
- Do NOT include any text before or after the JSON
- Do NOT wrap in markdown code blocks
- ALL required fields must be present
- Optional fields may be omitted or set to null when the schema permits it"""


def validate_gpt_output(
    output: str,
    expected_format: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    """Validate GPT output against expected format.

    Args:
        output: Raw output from GPT.
        expected_format: Expected JSON schema.

    Returns:
        Tuple of (is_valid, parsed_data, errors).
    """
    errors: list[str] = []

    # Clean output - remove any markdown or extra text
    cleaned = output.strip()

    # Remove markdown code blocks if present
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

    # Try to parse JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return False, None, errors

    schema_support_errors = _find_unsupported_schema_features(expected_format)
    if schema_support_errors:
        return False, None, schema_support_errors

    # Validate structure
    def validate_against_schema(
        data: Any,
        schema: dict[str, Any],
        path: str = "",
    ) -> list[str]:
        schema_errors: list[str] = []
        schema_type = schema.get("type")

        if schema_type is not None:
            schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
            if not any(_matches_schema_type(data, allowed_type) for allowed_type in schema_types):
                return [f"{path}: expected {schema_types}, got {type(data).__name__}"]
        else:
            schema_types = []

        if "enum" in schema and data not in schema["enum"]:
            schema_errors.append(f"{path}: must be one of {schema['enum']}")

        if "object" in schema_types and isinstance(data, dict):
            properties = schema.get("properties", {})
            # Check required fields
            for req in schema.get("required", []):
                if req not in data:
                    schema_errors.append(f"{path}.{req}: required field missing")

            # Validate properties
            for prop, prop_schema in properties.items():
                if prop in data:
                    schema_errors.extend(
                        validate_against_schema(data[prop], prop_schema, f"{path}.{prop}")
                    )

            additional_properties = schema.get("additionalProperties", True)
            extra_keys = sorted(set(data) - set(properties))
            if additional_properties is False and extra_keys:
                for key in extra_keys:
                    schema_errors.append(f"{path}.{key}: additional property not allowed")
            elif isinstance(additional_properties, dict):
                for key in extra_keys:
                    schema_errors.extend(
                        validate_against_schema(
                            data[key],
                            additional_properties,
                            f"{path}.{key}",
                        )
                    )

        if "array" in schema_types and isinstance(data, list):
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                for i, item in enumerate(data):
                    schema_errors.extend(
                        validate_against_schema(item, items_schema, f"{path}[{i}]")
                    )

        return schema_errors

    validation_errors = validate_against_schema(data, expected_format, "root")
    errors.extend(validation_errors)

    return len(errors) == 0, data, errors


@dataclass
class IntentContext:
    """Context from Opus to provide to GPT.

    Attributes:
        high_level_intent: The overall goal/intent.
        key_decisions: Important decisions already made.
        constraints: Constraints that must be respected.
        focus_areas: Areas GPT should focus on refining.
    """

    high_level_intent: str
    key_decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    focus_areas: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Convert to prompt section text.

        Returns:
            Formatted context section for prompt.
        """
        sections: list[str] = [f"INTENT: {self.high_level_intent}"]

        if self.key_decisions:
            decisions_text = "\n".join(f"  - {d}" for d in self.key_decisions)
            sections.append(f"KEY DECISIONS:\n{decisions_text}")

        if self.constraints:
            constraints_text = "\n".join(f"  - {c}" for c in self.constraints)
            sections.append(f"CONSTRAINTS:\n{constraints_text}")

        if self.focus_areas:
            focus_text = "\n".join(f"  - {f}" for f in self.focus_areas)
            sections.append(f"FOCUS AREAS:\n{focus_text}")

        return "\n\n".join(sections)


@dataclass
class GPTWrapper:
    """Wrapper for GPT model interactions.

    Attributes:
        token_manager: Token manager for budget tracking.
        task_type: Current task type.
        strict_format: Whether to enforce strict output format.
    """

    token_manager: TokenManager = field(default_factory=lambda: TokenManager(model_name="gpt"))
    task_type: str = "requirement_audit"
    strict_format: bool = True

    def get_output_format(self) -> dict[str, Any]:
        """Get output format for current task type.

        Returns:
            JSON schema for expected output.
        """
        if self.task_type not in GPT_STRICT_OUTPUT_FORMATS:
            raise ValueError(f"Unknown GPT task_type '{self.task_type}'")
        return GPT_STRICT_OUTPUT_FORMATS[self.task_type]

    def get_runtime_output_format(self) -> dict[str, Any]:
        """Get runtime schema used for both prompting and validation."""
        return _build_runtime_schema(self.get_output_format())

    def prepare_prompt(
        self,
        prompt: str,
        intent_context: IntentContext | None = None,
    ) -> str:
        """Prepare prompt for GPT with format enforcement.

        Args:
            prompt: Original prompt.
            intent_context: Context from Opus if available.

        Returns:
            Prepared prompt with format enforcement.
        """
        parts: list[str] = []

        # Add intent context if provided
        if intent_context:
            parts.append(intent_context.to_prompt_section())
            parts.append("---")

        parts.append(prompt)

        # Add format enforcement
        if self.strict_format:
            output_format = self.get_runtime_output_format()
            parts.append(create_format_enforcement_suffix(output_format))

        return "\n\n".join(parts)

    def process_output(
        self,
        raw_output: str,
    ) -> tuple[bool, dict[str, Any] | None, list[str]]:
        """Process and validate GPT output.

        Args:
            raw_output: Raw output from GPT.

        Returns:
            Tuple of (is_valid, parsed_data, errors).
        """
        output_format = self.get_runtime_output_format()
        return validate_gpt_output(raw_output, output_format)

    def create_correction_prompt(
        self,
        original_prompt: str,
        raw_output: str,
        errors: list[str],
    ) -> str:
        """Create a correction prompt for invalid output.

        Args:
            original_prompt: Original prompt.
            raw_output: Invalid output that was produced.
            errors: List of validation errors.

        Returns:
            Correction prompt.
        """
        errors_text = "\n".join(f"- {e}" for e in errors[:5])

        return f"""Your previous output had validation errors:

{errors_text}

Original output (truncated):
{raw_output[:500]}

Please provide corrected output following the exact format specified.
{create_format_enforcement_suffix(self.get_runtime_output_format())}"""
