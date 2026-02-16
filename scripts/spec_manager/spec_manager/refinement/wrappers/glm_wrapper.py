"""GLM model wrapper for spec refinement.

GLM 4.7 characteristics:
- Good for small tasks
- Poor at following complex instructions
- Good at summarization
- Requires simplified prompts

This wrapper optimizes interactions with GLM by:
1. Simplifying complex prompts
2. Enforcing task size limits
3. Using Python for structured output extraction
4. Implementing retry logic with repair prompts
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from spec_manager.refinement.wrappers.token_manager import (
    TokenManager,
)

# Task size limits for GLM
GLM_TASK_SIZE_LIMITS = {
    "summarization": {"max_input_chars": 8000, "max_output_tokens": 1000},
    "evidence_mapping": {"max_input_chars": 4000, "max_output_tokens": 500},
    "section_extraction": {"max_input_chars": 6000, "max_output_tokens": 800},
    "term_extraction": {"max_input_chars": 4000, "max_output_tokens": 600},
    "default": {"max_input_chars": 5000, "max_output_tokens": 800},
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


def simplify_prompt_for_glm(prompt: str) -> str:
    """Simplify a prompt for GLM model.

    GLM struggles with:
    - Complex nested instructions
    - Multiple conditional rules
    - Verbose explanations

    This function:
    1. Removes verbose explanations
    2. Flattens nested instructions
    3. Simplifies conditionals to direct statements

    Args:
        prompt: Original prompt text.

    Returns:
        Simplified prompt suitable for GLM.
    """
    lines = prompt.splitlines()
    simplified_lines: list[str] = []

    for line in lines:
        stripped = re.sub(r"\s+", " ", line.strip())

        # Collapse runs of blank lines while preserving line ordering/content.
        if not stripped:
            if simplified_lines and simplified_lines[-1] != "":
                simplified_lines.append("")
            continue

        simplified_lines.append(stripped)

    # Remove trailing empty lines
    while simplified_lines and simplified_lines[-1] == "":
        simplified_lines.pop()

    return "\n".join(simplified_lines)


def extract_json_from_text(text: str) -> dict[str, Any] | list[Any] | None:
    """Extract JSON from potentially messy GLM output.

    GLM often embeds JSON in markdown code blocks or
    includes extra text before/after the JSON.

    Args:
        text: Raw output text from GLM.

    Returns:
        Extracted JSON object, or None if extraction fails.
    """
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON-like structure
    # Look for { ... } or [ ... ]
    json_match = re.search(
        r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", text, re.DOTALL
    )
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


@dataclass
class ExtractedOutput:
    """Result of structured output extraction.

    Attributes:
        is_valid: Whether extraction was successful.
        value: Extracted value if successful.
        partial_value: Partially extracted value if incomplete.
        errors: List of extraction errors.
    """

    is_valid: bool
    is_verified: bool = False
    value: Any = None
    partial_value: Any = None
    errors: list[str] = field(default_factory=list)


def extract_structured_output(
    raw_output: str,
    output_schema: dict[str, Any] | None = None,
) -> ExtractedOutput:
    """Extract structured output from GLM response.

    Uses Python-based extraction rather than relying on GLM
    to follow output format instructions.

    Args:
        raw_output: Raw text output from GLM.
        output_schema: Expected JSON schema for validation.

    Returns:
        ExtractedOutput with validation status and values.
    """
    errors: list[str] = []

    # Try JSON extraction
    json_data = extract_json_from_text(raw_output)
    if json_data is None:
        errors.append("Could not extract JSON from output")
        return ExtractedOutput(
            is_valid=False,
            partial_value=raw_output,
            errors=errors,
        )

    # Validate against schema if provided
    if output_schema is None:
        errors.append("Output extracted but unverified: output_schema is required for validation")
        return ExtractedOutput(
            is_valid=False,
            is_verified=False,
            value=json_data,
            errors=errors,
        )

    is_valid, validation_errors = _validate_against_schema(json_data, output_schema)
    if not is_valid:
        errors.extend(validation_errors)
        return ExtractedOutput(
            is_valid=False,
            is_verified=False,
            partial_value=json_data,
            errors=errors,
        )

    return ExtractedOutput(is_valid=True, is_verified=True, value=json_data)


def _find_unsupported_schema_features(schema: Any, path: str = "root") -> list[str]:
    """Find unsupported JSON-schema features.

    This validator intentionally supports a strict subset. Unknown validation
    keywords are rejected so callers do not assume checks that were never run.
    """
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


def _matches_schema_type(data: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(data, dict)
    if schema_type == "array":
        return isinstance(data, list)
    if schema_type == "string":
        return isinstance(data, str)
    if schema_type == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if schema_type == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if schema_type == "boolean":
        return isinstance(data, bool)
    if schema_type == "null":
        return data is None
    return False


def _validate_against_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Basic JSON schema validation.

    Args:
        data: Data to validate.
        schema: JSON schema to validate against.

    Returns:
        Tuple of (is_valid, list of error messages).
    """
    errors = _find_unsupported_schema_features(schema)
    if errors:
        return False, errors

    def _validate(value: Any, schema_fragment: dict[str, Any], path: str) -> list[str]:
        fragment_errors: list[str] = []
        schema_type = schema_fragment.get("type")

        if schema_type is not None:
            schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
            if not any(_matches_schema_type(value, allowed_type) for allowed_type in schema_types):
                fragment_errors.append(
                    f"{path}: expected {schema_types}, got {type(value).__name__}"
                )
                return fragment_errors

        if "enum" in schema_fragment and value not in schema_fragment["enum"]:
            fragment_errors.append(f"{path}: value must be one of {schema_fragment['enum']}")

        schema_types = schema_type if isinstance(schema_type, list) else [schema_type]
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


@dataclass
class GLMWrapper:
    """Wrapper for GLM model interactions.

    Attributes:
        token_manager: Token manager for budget tracking.
        max_retries: Maximum retry attempts for failed extractions.
        task_type: Current task type for size limits.
    """

    token_manager: TokenManager = field(default_factory=lambda: TokenManager(model_name="glm-4.7"))
    max_retries: int = 2
    task_type: str = "default"

    def get_task_limits(self) -> dict[str, int]:
        """Get size limits for current task type.

        Returns:
            Dictionary with max_input_chars and max_output_tokens.
        """
        return GLM_TASK_SIZE_LIMITS.get(self.task_type, GLM_TASK_SIZE_LIMITS["default"])

    def prepare_prompt(
        self,
        prompt: str,
        simplify: bool = True,
        enforce_limits: bool = True,
    ) -> str:
        """Prepare a prompt for GLM.

        Args:
            prompt: Original prompt.
            simplify: Whether to simplify the prompt.
            enforce_limits: Whether to enforce character limits.

        Returns:
            Prepared prompt.
        """
        source_prompt = prompt
        if simplify:
            simplified_prompt = simplify_prompt_for_glm(source_prompt)
            if simplified_prompt != source_prompt:
                prompt = (
                    "AUTHORITATIVE SOURCE PROMPT:\n"
                    f"{source_prompt}\n\n"
                    "SIMPLIFIED WORKING VIEW (do not drop source requirements):\n"
                    f"{simplified_prompt}"
                )
            else:
                prompt = source_prompt

        if enforce_limits:
            limits = self.get_task_limits()
            max_chars = limits["max_input_chars"]
            if len(prompt) > max_chars:
                raise ValueError(
                    "Prepared GLM prompt exceeds task limit "
                    f"({len(prompt)} chars > {max_chars} chars for task_type='{self.task_type}')"
                )

        return prompt

    def process_output(
        self,
        raw_output: str,
        output_schema: dict[str, Any] | None = None,
    ) -> ExtractedOutput:
        """Process raw GLM output into structured data.

        Args:
            raw_output: Raw text from GLM.
            output_schema: Expected output schema.

        Returns:
            ExtractedOutput with validation status.
        """
        return extract_structured_output(raw_output, output_schema)

    def create_repair_prompt(
        self,
        original_prompt: str,
        raw_output: str,
        errors: list[str],
    ) -> str:
        """Create a repair prompt for retry attempts.

        Args:
            original_prompt: Original prompt that failed.
            raw_output: Raw output that had errors.
            errors: List of error messages.

        Returns:
            Repair prompt for retry.
        """
        error_list = "\n".join(f"- {e}" for e in errors[:3])  # Limit errors shown

        repair_prompt = f"""Fix the following output.

Errors found:
{error_list}

Original output:
{raw_output[:500]}

Provide corrected output as valid JSON only."""

        return simplify_prompt_for_glm(repair_prompt)
