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
from typing import Any, Callable

from spec_manager.refinement.wrappers.token_manager import TokenBudget, TokenManager, estimate_tokens


# Task size limits for GLM
GLM_TASK_SIZE_LIMITS = {
    "summarization": {"max_input_chars": 8000, "max_output_tokens": 1000},
    "evidence_mapping": {"max_input_chars": 4000, "max_output_tokens": 500},
    "section_extraction": {"max_input_chars": 6000, "max_output_tokens": 800},
    "term_extraction": {"max_input_chars": 4000, "max_output_tokens": 600},
    "default": {"max_input_chars": 5000, "max_output_tokens": 800},
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
    lines = prompt.split("\n")
    simplified_lines: list[str] = []

    skip_patterns = [
        r"^Note:",
        r"^Remember:",
        r"^Important:",
        r"^For example,",
        r"^This means",
        r"^In other words",
    ]

    for line in lines:
        stripped = line.strip()

        # Skip empty lines in sequence
        if not stripped:
            if simplified_lines and simplified_lines[-1] != "":
                simplified_lines.append("")
            continue

        # Skip verbose explanation patterns
        if any(re.match(pattern, stripped, re.IGNORECASE) for pattern in skip_patterns):
            continue

        # Simplify conditional statements
        if "if possible" in stripped.lower():
            stripped = stripped.replace("if possible", "").replace("If possible", "")
            stripped = re.sub(r"\s+", " ", stripped).strip()

        if "when applicable" in stripped.lower():
            stripped = stripped.replace("when applicable", "").replace("When applicable", "")
            stripped = re.sub(r"\s+", " ", stripped).strip()

        # Remove hedging language
        hedging_phrases = [
            "you might want to",
            "consider",
            "it would be good to",
            "you could",
            "perhaps",
            "maybe",
        ]
        for phrase in hedging_phrases:
            if phrase in stripped.lower():
                # Convert to direct instruction
                stripped = re.sub(
                    rf"(?i){re.escape(phrase)}\s*",
                    "",
                    stripped,
                )

        if stripped:
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
    json_match = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])", text, re.DOTALL)
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
    if output_schema is not None:
        is_valid, validation_errors = _validate_against_schema(json_data, output_schema)
        if not is_valid:
            errors.extend(validation_errors)
            return ExtractedOutput(
                is_valid=False,
                partial_value=json_data,
                errors=errors,
            )

    return ExtractedOutput(is_valid=True, value=json_data)


def _validate_against_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Basic JSON schema validation.

    Args:
        data: Data to validate.
        schema: JSON schema to validate against.

    Returns:
        Tuple of (is_valid, list of error messages).
    """
    errors: list[str] = []

    schema_type = schema.get("type")

    if schema_type == "object":
        if not isinstance(data, dict):
            return False, [f"Expected object, got {type(data).__name__}"]

        required = schema.get("required", [])
        for req_field in required:
            if req_field not in data:
                errors.append(f"Missing required field: {req_field}")

        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in data:
                is_valid, prop_errors = _validate_against_schema(data[prop_name], prop_schema)
                if not is_valid:
                    errors.extend([f"{prop_name}: {e}" for e in prop_errors])

    elif schema_type == "array":
        if not isinstance(data, list):
            return False, [f"Expected array, got {type(data).__name__}"]

        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(data):
                is_valid, item_errors = _validate_against_schema(item, items_schema)
                if not is_valid:
                    errors.extend([f"[{i}]: {e}" for e in item_errors])

    elif schema_type == "string":
        if not isinstance(data, str):
            return False, [f"Expected string, got {type(data).__name__}"]

    elif schema_type == "number":
        if not isinstance(data, (int, float)):
            return False, [f"Expected number, got {type(data).__name__}"]

    elif schema_type == "boolean":
        if not isinstance(data, bool):
            return False, [f"Expected boolean, got {type(data).__name__}"]

    return len(errors) == 0, errors


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
        if simplify:
            prompt = simplify_prompt_for_glm(prompt)

        if enforce_limits:
            limits = self.get_task_limits()
            max_chars = limits["max_input_chars"]
            if len(prompt) > max_chars:
                # Truncate with ellipsis
                prompt = prompt[: max_chars - 3] + "..."

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
