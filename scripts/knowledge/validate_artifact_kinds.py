"""Validate the Artifact Kind Registry for schema compliance and consistency.

This module validates the Artifact Kind Registry (`.knowledge/artifacts/kinds.yml`)
to ensure schema compliance, deterministic structure patterns, and prevent
duplicate/overlapping artifact kinds.

Per docs/plans/fact_redesign.md lines 434-479, validation checks include:
1. Schema checks (blocking): required fields, uniqueness, alias targets, render plan refs
2. Sample execution checks (blocking when samples present): extract and validate samples
3. Determinism checks (blocking): verify structure patterns are deterministic
4. Duplicate detection (warning): warn about similar/overlapping artifact kinds

Usage:
    uv run knowledge.validate-artifact-kinds [--knowledge-path PATH] [--strict] [--json-report PATH]

Args:
    --knowledge-path: Base knowledge directory (default: .knowledge)
    --strict: Upgrade warnings to blocking errors
    --json-report: Output JSON validation report to specified path

Exit Codes:
    0: Success (or warnings only)
    1: Blocking errors
"""

import argparse
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.compare_yaml_docs import extract_field_facts, extract_ids_and_objects

# Module-level logger
_logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """A blocking validation error.

    Attributes:
        kind_id: The artifact kind ID (or None for registry-level errors).
        field: The field name where the error occurred.
        message: Description of the error.
    """

    kind_id: str | None
    field: str
    message: str


@dataclass
class ValidationWarning:
    """A non-blocking validation warning.

    Attributes:
        kind_id: The artifact kind ID (or None for registry-level warnings).
        field: The field name where the warning occurred.
        message: Description of the warning.
    """

    kind_id: str | None
    field: str
    message: str


@dataclass
class ValidationResult:
    """Result of validating the artifact kind registry.

    Attributes:
        passed: True if no blocking errors occurred.
        errors: List of blocking validation errors.
        warnings: List of non-blocking validation warnings.
    """

    passed: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)

    def add_error(
        self,
        kind_id: str | None,
        field_name: str,
        message: str,
    ) -> None:
        """Add a blocking error.

        Args:
            kind_id: The artifact kind ID (or None for registry-level errors).
            field_name: The field name where the error occurred.
            message: Description of the error.
        """
        self.errors.append(ValidationError(kind_id, field_name, message))
        self.passed = False

    def add_warning(
        self,
        kind_id: str | None,
        field_name: str,
        message: str,
    ) -> None:
        """Add a non-blocking warning.

        Args:
            kind_id: The artifact kind ID (or None for registry-level warnings).
            field_name: The field name where the warning occurred.
            message: Description of the warning.
        """
        self.warnings.append(ValidationWarning(kind_id, field_name, message))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output.

        Returns:
            Dictionary representation with passed, errors, and warnings.
        """
        return {
            "passed": self.passed,
            "errors": [
                {"kind_id": e.kind_id, "field": e.field, "message": e.message}
                for e in self.errors
            ],
            "warnings": [
                {"kind_id": w.kind_id, "field": w.field, "message": w.message}
                for w in self.warnings
            ],
        }


# Required fields per the registry schema (docs/plans/fact_redesign.md lines 350-361)
REQUIRED_FIELDS = frozenset(
    {
        "kind_id",
        "content_form",
        "structure_pattern",
        "extraction_contract",
        "rendering_contract",
    }
)


def load_registry(knowledge_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load the artifact kind registry from YAML.

    Args:
        knowledge_path: Base knowledge directory path.

    Returns:
        Tuple of (list of kind entries, error message if loading failed).
    """
    registry_path = knowledge_path / "artifacts" / "kinds.yml"
    if not registry_path.exists():
        return [], f"Registry file not found: {registry_path}"

    try:
        content = registry_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return [], f"Failed to parse registry YAML: {exc}"
    except OSError as exc:
        return [], f"Failed to read registry file: {exc}"

    if not isinstance(data, dict):
        return [], "Registry must be a YAML mapping with 'kinds' key"

    kinds = data.get("kinds", [])
    if not isinstance(kinds, list):
        return [], "'kinds' must be a list of artifact kind entries"

    return kinds, None


def validate_schema(kinds: list[dict[str, Any]], result: ValidationResult) -> None:
    """Validate schema requirements for all registry entries.

    Checks:
    - Required fields present with canonical names
    - kind_id uniqueness
    - Alias targets exist
    - Render plan references (warns if render_plans directory doesn't exist)

    Args:
        kinds: List of artifact kind entries.
        result: ValidationResult to accumulate errors and warnings.
    """
    seen_kind_ids: set[str] = set()
    all_kind_ids: set[str] = {k.get("kind_id", "") for k in kinds if isinstance(k, dict)}

    for idx, kind in enumerate(kinds):
        if not isinstance(kind, dict):
            result.add_error(None, f"kinds[{idx}]", "Entry must be a mapping/dict")
            continue

        kind_id = kind.get("kind_id")
        if not kind_id:
            result.add_error(None, f"kinds[{idx}].kind_id", "Missing required field 'kind_id'")
            kind_id_str = f"<unknown-{idx}>"
        else:
            kind_id_str = str(kind_id)

        # Check required fields
        for req_field in REQUIRED_FIELDS:
            if req_field not in kind:
                result.add_error(kind_id_str, req_field, f"Missing required field '{req_field}'")

        # Check kind_id uniqueness
        if kind_id:
            if kind_id in seen_kind_ids:
                result.add_error(kind_id_str, "kind_id", f"Duplicate kind_id: '{kind_id}'")
            seen_kind_ids.add(kind_id)

        # Check alias targets exist
        aliases = kind.get("aliases", [])
        if isinstance(aliases, list):
            for alias in aliases:
                if alias not in all_kind_ids:
                    result.add_error(
                        kind_id_str,
                        "aliases",
                        f"Alias target '{alias}' does not exist in registry",
                    )

        # Check render_plan_id references
        rendering = kind.get("rendering_contract", {})
        if isinstance(rendering, dict):
            render_plan_id = rendering.get("render_plan_id")
            if render_plan_id:
                # For V1, render_plans directory may not exist yet - warn but don't block
                result.add_warning(
                    kind_id_str,
                    "rendering_contract.render_plan_id",
                    f"Render plan '{render_plan_id}' reference not validated "
                    "(render_plans directory not yet implemented)",
                )


def validate_structure_pattern_determinism(
    kinds: list[dict[str, Any]],
    result: ValidationResult,
) -> None:
    """Validate that structure patterns are deterministic (no semantic inference).

    Checks:
    - root_path uses valid path syntax
    - sibling_constraints use valid key/value matching
    - content_sniff uses valid regex or prefix/suffix patterns

    Args:
        kinds: List of artifact kind entries.
        result: ValidationResult to accumulate errors and warnings.
    """
    for kind in kinds:
        if not isinstance(kind, dict):
            continue

        kind_id = kind.get("kind_id", "<unknown>")
        pattern = kind.get("structure_pattern", {})

        if not isinstance(pattern, dict):
            result.add_error(kind_id, "structure_pattern", "Must be a mapping/dict")
            continue

        # Validate root_path syntax (should be path-like: sections[*].items[*].text)
        root_path = pattern.get("root_path")
        if root_path:
            # Basic validation: should contain valid path characters
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\[\]\*\.]*$", root_path):
                result.add_error(
                    kind_id,
                    "structure_pattern.root_path",
                    f"Invalid root_path syntax: '{root_path}'",
                )

        # Validate sibling_constraints
        sibling_constraints = pattern.get("sibling_constraints", [])
        if isinstance(sibling_constraints, list):
            for idx, constraint in enumerate(sibling_constraints):
                if not isinstance(constraint, dict):
                    result.add_error(
                        kind_id,
                        f"structure_pattern.sibling_constraints[{idx}]",
                        "Constraint must be a mapping/dict",
                    )
                    continue

                if "key" not in constraint:
                    result.add_error(
                        kind_id,
                        f"structure_pattern.sibling_constraints[{idx}]",
                        "Missing required 'key' field",
                    )

                # Must have at least one matching operator
                has_operator = any(
                    op in constraint for op in ["equals", "matches", "starts_with", "ends_with"]
                )
                if not has_operator and "key" in constraint:
                    result.add_error(
                        kind_id,
                        f"structure_pattern.sibling_constraints[{idx}]",
                        "Must specify a matching operator (equals, matches, starts_with, ends_with)",
                    )

        # Validate content_sniff patterns
        content_sniff = pattern.get("content_sniff", {})
        if isinstance(content_sniff, dict):
            # Validate regex patterns
            regex_pattern = content_sniff.get("matches")
            if regex_pattern:
                try:
                    re.compile(regex_pattern)
                except re.error as exc:
                    result.add_error(
                        kind_id,
                        "structure_pattern.content_sniff.matches",
                        f"Invalid regex pattern: {exc}",
                    )

            # Validate starts_with_any is a list of strings
            starts_with_any = content_sniff.get("starts_with_any", [])
            if not isinstance(starts_with_any, list):
                result.add_error(
                    kind_id,
                    "structure_pattern.content_sniff.starts_with_any",
                    "Must be a list of strings",
                )
            elif starts_with_any:
                for idx, prefix in enumerate(starts_with_any):
                    if not isinstance(prefix, str):
                        result.add_error(
                            kind_id,
                            f"structure_pattern.content_sniff.starts_with_any[{idx}]",
                            f"Must be a string, got {type(prefix).__name__}",
                        )


def _resolve_element_and_field(
    data: Any,  # noqa: ANN401
    source_file: str,
    element_id: str,
    field_path: str | None,
) -> tuple[dict[str, Any] | None, list[Any] | None, str | None]:
    """Resolve an element and optional field path from parsed YAML data.

    Uses extract_ids_and_objects to build an id->object map and locate the element.

    Args:
        data: Parsed YAML data.
        source_file: Relative path to the source file.
        element_id: The element ID to locate.
        field_path: Optional field path within the element.

    Returns:
        Tuple of (element_data, field_facts for element, error message if failed).
    """
    try:
        id_to_object, _ = extract_ids_and_objects(data, source_file=source_file)
    except Exception as exc:
        return None, None, f"Failed to extract IDs from YAML: {exc}"

    if element_id not in id_to_object:
        return None, None, f"Element ID '{element_id}' not found in file"

    element_data = id_to_object[element_id]

    try:
        facts_by_element = extract_field_facts(data, source_file)
    except Exception as exc:
        return None, None, f"Failed to extract field facts: {exc}"

    element_facts = facts_by_element.get(element_id, [])

    return element_data, element_facts, None


def _validate_sample_extraction(
    kind: dict[str, Any],
    element_facts: list[Any],
    field_path: str | None,
    kind_id: str,
    example_idx: int,
    result: ValidationResult,
) -> None:
    """Validate that sample extraction matches expected structure.

    Verifies that required fields from structure_pattern and extraction_contract
    exist in the extracted facts.

    Args:
        kind: The artifact kind entry.
        element_facts: List of FieldFact instances for the element.
        field_path: Optional field path specified in the example.
        kind_id: The kind ID for error reporting.
        example_idx: Index of the example for error reporting.
        result: ValidationResult to accumulate errors and warnings.
    """
    pattern = kind.get("structure_pattern", {})
    extraction = kind.get("extraction_contract", {})

    # Get required_fields from structure_pattern if specified
    required_fields = pattern.get("required_fields", [])
    if required_fields and isinstance(required_fields, list):
        fact_field_paths = {f.field_path for f in element_facts}
        fact_keys = {f.key for f in element_facts}

        for req_field in required_fields:
            # Check if the field exists either as a full path or as a key
            field_found = req_field in fact_keys or any(
                fp.endswith(f".{req_field}") or fp == req_field for fp in fact_field_paths
            )
            if not field_found:
                result.add_error(
                    kind_id,
                    f"examples[{example_idx}]",
                    f"Required field '{req_field}' not found in sample element facts",
                )

    # Validate contributor paths from extraction_contract if specified
    contributors = extraction.get("contributors", [])
    if contributors and isinstance(contributors, list):
        for contributor in contributors:
            if not isinstance(contributor, dict):
                continue

            contrib_path = contributor.get("field_path")
            if not contrib_path:
                continue

            # Check if contributor path exists in facts (partial match allowed)
            path_found = any(
                f.field_path == contrib_path
                or f.field_path.startswith(f"{contrib_path}.")
                or f.field_path.startswith(f"{contrib_path}[")
                for f in element_facts
            )
            if not path_found:
                # This is a warning since contributor paths may be optional
                result.add_warning(
                    kind_id,
                    f"examples[{example_idx}]",
                    f"Contributor path '{contrib_path}' not found in sample element",
                )


def validate_samples(
    kinds: list[dict[str, Any]],
    result: ValidationResult,
    strict: bool = False,
) -> None:
    """Validate sample artifact roots declared in examples field.

    Performs full sample-execution validation by:
    1. Checking sample source files exist
    2. Loading and parsing the YAML files
    3. Locating the specified element_id using extract_ids_and_objects
    4. Extracting FieldFacts using extract_field_facts
    5. Verifying required fields from structure_pattern exist in facts
    6. Verifying contributor paths from extraction_contract exist

    Args:
        kinds: List of artifact kind entries.
        result: ValidationResult to accumulate errors and warnings.
        strict: If True, treat sample resolution failures as errors.
    """
    for kind in kinds:
        if not isinstance(kind, dict):
            continue

        kind_id = kind.get("kind_id", "<unknown>")
        examples = kind.get("examples", [])

        if not examples:
            result.add_warning(
                kind_id,
                "examples",
                "No sample artifacts declared for validation",
            )
            continue

        if not isinstance(examples, list):
            result.add_error(kind_id, "examples", "Must be a list of sample references")
            continue

        for idx, example in enumerate(examples):
            if not isinstance(example, dict):
                result.add_error(
                    kind_id,
                    f"examples[{idx}]",
                    "Sample must be a mapping/dict",
                )
                continue

            source_file = example.get("source_file")
            if not source_file:
                result.add_error(
                    kind_id,
                    f"examples[{idx}].source_file",
                    "Missing required 'source_file' field",
                )
                continue

            # Check if source file exists
            source_path = REPO_ROOT / source_file
            if not source_path.exists():
                if strict:
                    result.add_error(
                        kind_id,
                        f"examples[{idx}].source_file",
                        f"Sample source file not found: {source_file}",
                    )
                else:
                    result.add_warning(
                        kind_id,
                        f"examples[{idx}].source_file",
                        f"Sample source file not found: {source_file}",
                    )
                continue

            element_id = example.get("element_id")
            if not element_id:
                result.add_warning(
                    kind_id,
                    f"examples[{idx}].element_id",
                    "No element_id specified for sample",
                )
                continue

            field_path = example.get("field_path")

            # Load and parse the YAML file
            try:
                content = source_path.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
            except (yaml.YAMLError, OSError) as exc:
                if strict:
                    result.add_error(
                        kind_id,
                        f"examples[{idx}]",
                        f"Failed to parse sample file: {exc}",
                    )
                else:
                    result.add_warning(
                        kind_id,
                        f"examples[{idx}]",
                        f"Failed to parse sample file: {exc}",
                    )
                continue

            # Resolve element and extract facts
            element_data, element_facts, resolve_error = _resolve_element_and_field(
                data, source_file, element_id, field_path
            )

            if resolve_error:
                if strict:
                    result.add_error(
                        kind_id,
                        f"examples[{idx}]",
                        resolve_error,
                    )
                else:
                    result.add_warning(
                        kind_id,
                        f"examples[{idx}]",
                        resolve_error,
                    )
                continue

            # Validate extraction matches expected structure
            if element_facts:
                _validate_sample_extraction(
                    kind, element_facts, field_path, kind_id, idx, result
                )


def compute_pattern_signature(kind: dict[str, Any]) -> str:
    """Compute a normalized signature for a structure pattern.

    Used for duplicate/similarity detection.

    Args:
        kind: Artifact kind entry dict.

    Returns:
        Normalized string signature of the structure pattern.
    """
    pattern = kind.get("structure_pattern", {})
    if not isinstance(pattern, dict):
        return ""

    parts = []

    root_path = pattern.get("root_path", "")
    if root_path:
        # Normalize wildcards
        normalized = re.sub(r"\[\d+\]", "[*]", root_path)
        parts.append(f"root={normalized}")

    sibling_constraints = pattern.get("sibling_constraints", [])
    if isinstance(sibling_constraints, list):
        for constraint in sibling_constraints:
            if isinstance(constraint, dict):
                key = constraint.get("key", "")
                for op in ["equals", "matches", "starts_with", "ends_with"]:
                    if op in constraint:
                        parts.append(f"sibling.{key}.{op}={constraint[op]}")

    content_sniff = pattern.get("content_sniff", {})
    if isinstance(content_sniff, dict):
        for key in ["starts_with_any", "matches"]:
            if key in content_sniff:
                val = content_sniff[key]
                if isinstance(val, list):
                    val = ",".join(sorted(str(v) for v in val))
                parts.append(f"sniff.{key}={val}")

    return "|".join(sorted(parts))


def _compute_jaccard_similarity(sig1: str, sig2: str) -> float:
    """Compute Jaccard similarity between two pattern signatures.

    Tokenizes signatures on '|' delimiter and computes intersection/union ratio.

    Args:
        sig1: First signature string.
        sig2: Second signature string.

    Returns:
        Jaccard similarity coefficient (0.0 to 1.0).
    """
    if not sig1 or not sig2:
        return 0.0

    tokens1 = set(sig1.split("|"))
    tokens2 = set(sig2.split("|"))

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    if not union:
        return 0.0

    return len(intersection) / len(union)


def validate_duplicates(
    kinds: list[dict[str, Any]],
    result: ValidationResult,
    similarity_threshold: float = 0.8,
) -> None:
    """Detect duplicate or near-duplicate artifact kinds.

    Compares structure patterns to identify kinds that may be duplicates
    or candidates for merging. Uses exact match for identical patterns
    (blocking error) and Jaccard similarity for near-duplicates (warning).

    Args:
        kinds: List of artifact kind entries.
        result: ValidationResult to accumulate errors and warnings.
        similarity_threshold: Jaccard similarity threshold for warning (0.0-1.0).
    """
    # Collect signatures with their kind IDs
    kind_signatures: list[tuple[str, str]] = []

    for kind in kinds:
        if not isinstance(kind, dict):
            continue

        kind_id = kind.get("kind_id", "<unknown>")
        sig = compute_pattern_signature(kind)

        if sig:
            kind_signatures.append((kind_id, sig))

    # Check for identical signatures (always block)
    signatures_to_kinds: dict[str, list[str]] = {}
    for kind_id, sig in kind_signatures:
        if sig not in signatures_to_kinds:
            signatures_to_kinds[sig] = []
        signatures_to_kinds[sig].append(kind_id)

    for sig, kind_ids in signatures_to_kinds.items():
        if len(kind_ids) > 1:
            result.add_error(
                kind_ids[0],
                "structure_pattern",
                f"Identical structure pattern with: {', '.join(kind_ids[1:])}",
            )

    # Check for near-duplicates using Jaccard similarity
    checked_pairs: set[tuple[str, str]] = set()
    for i, (kind_id1, sig1) in enumerate(kind_signatures):
        for j, (kind_id2, sig2) in enumerate(kind_signatures):
            if i >= j:
                continue

            # Skip if already identified as identical
            if sig1 == sig2:
                continue

            # Create ordered pair to avoid duplicate warnings
            pair = (min(kind_id1, kind_id2), max(kind_id1, kind_id2))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            similarity = _compute_jaccard_similarity(sig1, sig2)
            if similarity >= similarity_threshold:
                result.add_warning(
                    kind_id1,
                    "structure_pattern",
                    f"Near-duplicate pattern with '{kind_id2}' "
                    f"(Jaccard similarity: {similarity:.2f})",
                )


def validate_registry(
    knowledge_path: Path,
    strict: bool = False,
) -> ValidationResult:
    """Validate the artifact kind registry.

    Runs all validation checks and returns accumulated results.

    Args:
        knowledge_path: Base knowledge directory path.
        strict: If True, upgrade warnings to blocking errors.

    Returns:
        ValidationResult with all errors and warnings.
    """
    result = ValidationResult()

    kinds, load_error = load_registry(knowledge_path)
    if load_error:
        result.add_error(None, "registry", load_error)
        return result

    if not kinds:
        result.add_warning(None, "registry", "Registry is empty")
        if strict:
            result.passed = False
        return result

    # Run validation checks
    validate_schema(kinds, result)
    validate_structure_pattern_determinism(kinds, result)
    validate_samples(kinds, result, strict=strict)
    validate_duplicates(kinds, result)

    # In strict mode, warnings become errors
    if strict and result.warnings:
        for warning in result.warnings:
            result.add_error(warning.kind_id, warning.field, f"[strict] {warning.message}")
        result.warnings = []

    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Validate the Artifact Kind Registry for schema compliance and consistency.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=REPO_ROOT / ".knowledge",
        help="Base knowledge directory (default: .knowledge)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Upgrade warnings to blocking errors",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Output JSON validation report to specified path",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for artifact kind validation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Exit code: 0 on success, 1 on blocking errors.
    """
    args = parse_args(argv)

    result = validate_registry(args.knowledge_path, args.strict)

    # Output JSON report if requested
    if args.json_report:
        try:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(
                json.dumps(result.to_dict(), indent=2),
                encoding="utf-8",
            )
            print(f"JSON report written to: {args.json_report}")
        except OSError as exc:
            print(f"Error writing JSON report: {exc}", file=sys.stderr)

    # Print results
    if result.errors:
        print(f"\n{len(result.errors)} error(s):", file=sys.stderr)
        for error in result.errors:
            kind_prefix = f"[{error.kind_id}] " if error.kind_id else ""
            print(f"  ERROR: {kind_prefix}{error.field}: {error.message}", file=sys.stderr)

    if result.warnings:
        print(f"\n{len(result.warnings)} warning(s):")
        for warning in result.warnings:
            kind_prefix = f"[{warning.kind_id}] " if warning.kind_id else ""
            print(f"  WARNING: {kind_prefix}{warning.field}: {warning.message}")

    if result.passed:
        print("\nValidation passed.")
        return 0

    print("\nValidation failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
