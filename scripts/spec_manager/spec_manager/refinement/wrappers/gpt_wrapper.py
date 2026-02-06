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

import json
import re
from dataclasses import dataclass, field
from typing import Any

from spec_manager.refinement.wrappers.token_manager import TokenBudget, TokenManager


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
                        "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
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
- Use null for optional fields with no value"""


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

    # Validate structure
    def validate_against_schema(
        data: Any,
        schema: dict[str, Any],
        path: str = "",
    ) -> list[str]:
        schema_errors: list[str] = []
        schema_type = schema.get("type")

        if schema_type == "object":
            if not isinstance(data, dict):
                return [f"{path}: expected object, got {type(data).__name__}"]

            # Check required fields
            for req in schema.get("required", []):
                if req not in data:
                    schema_errors.append(f"{path}.{req}: required field missing")

            # Validate properties
            for prop, prop_schema in schema.get("properties", {}).items():
                if prop in data:
                    schema_errors.extend(
                        validate_against_schema(data[prop], prop_schema, f"{path}.{prop}")
                    )

        elif schema_type == "array":
            if not isinstance(data, list):
                return [f"{path}: expected array, got {type(data).__name__}"]

            items_schema = schema.get("items")
            if items_schema:
                for i, item in enumerate(data):
                    schema_errors.extend(
                        validate_against_schema(item, items_schema, f"{path}[{i}]")
                    )

        elif schema_type == "string":
            if not isinstance(data, str):
                schema_errors.append(f"{path}: expected string, got {type(data).__name__}")

            # Check enum constraint
            if "enum" in schema and data not in schema["enum"]:
                schema_errors.append(f"{path}: must be one of {schema['enum']}")

        elif schema_type == "number" or schema_type == "integer":
            if not isinstance(data, (int, float)):
                schema_errors.append(f"{path}: expected number, got {type(data).__name__}")

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
        return GPT_STRICT_OUTPUT_FORMATS.get(
            self.task_type,
            GPT_STRICT_OUTPUT_FORMATS["requirement_audit"],
        )

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
            output_format = self.get_output_format()
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
        output_format = self.get_output_format()
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
{create_format_enforcement_suffix(self.get_output_format())}"""
