#!/usr/bin/env python3
"""
Validate annotations in plan.md:
1. Find all IDs (labels) missing annotations
2. Validate existing annotations use correct format (=[id] vs +[id])
3. Validate annotations reference legal/declared IDs

Annotation formats:
- (=[id]) - labeled reference: "this belongs to id" or "this is id"
- (+[id]) - context reference: "this references id"
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict


# ID patterns that should be annotated
ID_PATTERNS = [
    (r'Algorithm\s+\d+', 'Algorithm'),
    (r'P\d+I\d+', 'Invariant'),
    (r'P\d+C\d+', 'PatchClaim'),
    (r'P\d+\.\d+', 'Math'),
    (r'Lean\d+', 'Lean'),
    (r'Lean\s+\d+', 'Lean'),
    (r'(?<![A-Za-z])C\d+(?![0-9])', 'Claim'),  # C1, C2 but not in code context
    (r'(?<![A-Za-z])G\d+(?![0-9])', 'Goal'),
    (r'(?<![A-Za-z])D\d+(?![0-9])', 'DataStructure'),
    (r'Comp\d+', 'Component'),
    (r'(?<![A-Za-z])S\d+(?![0-9])', 'Statement'),
    (r'(?<![A-Za-z])T\d+(?![0-9])', 'Topic'),
    (r'(?<![A-Za-z])P\d+(?![0-9IC\.])', 'Patch'),  # P1, P2 but not P1I1, P1C1, P1.1
    (r'NFG\d+', 'NFG'),
    (r'INV-P\d+', 'InvariantSection'),
]

# Annotation pattern: (=[id]) or (+[id])
ANNOTATION_PATTERN = re.compile(r'\(([=+])\[([^\]]+)\]\)')


@dataclass
class ValidationResult:
    """Results of annotation validation."""
    declarations: list = field(default_factory=list)  # IDs in headers (no annotation needed)
    missing_annotations: list = field(default_factory=list)  # Prose refs missing annotation
    invalid_format: list = field(default_factory=list)
    invalid_references: list = field(default_factory=list)
    valid_labeled: list = field(default_factory=list)  # (=[id]) in headers
    valid_context: list = field(default_factory=list)  # (+[id]) in prose
    declared_ids: set = field(default_factory=set)


def is_in_code_block(lines: list[str], line_idx: int) -> bool:
    """Check if a line is inside a code block."""
    in_code = False
    for i in range(line_idx):
        line = lines[i].strip()
        if line.startswith('```') or line.startswith('~~~'):
            in_code = not in_code
    return in_code


def is_code_variable(text: str, match_start: int, match_end: int, id_str: str) -> bool:
    """
    Check if an ID match looks like a code variable rather than a document reference.

    Heuristics:
    - Single letter + single digit (C0, S0, x1, etc.) in certain contexts
    - Preceded by assignment operators, array brackets, etc.
    - Part of a larger identifier
    """
    # Check context before the match
    if match_start > 0:
        char_before = text[match_start - 1]
        # If preceded by underscore, letter, or digit, it's part of a larger identifier
        if char_before.isalnum() or char_before == '_':
            return True

    # Check context after the match
    if match_end < len(text):
        char_after = text[match_end]
        # If followed by underscore, letter, or digit, it's part of a larger identifier
        if char_after.isalnum() or char_after == '_':
            return True

    # Single letter + single digit patterns that are likely code variables
    if re.match(r'^[A-Z]\d$', id_str):
        # Look for code-like context
        context_before = text[max(0, match_start-10):match_start]
        context_after = text[match_end:match_end+10]

        # Code indicators
        code_indicators = ['=', '[', ']', '(', ')', ',', '.', '_', ':', ';', '+', '-', '*', '/']
        if any(ind in context_before[-3:] for ind in code_indicators):
            return True
        if any(ind in context_after[:3] for ind in code_indicators):
            return True

    return False


def extract_declared_ids(lines: list[str]) -> set[str]:
    """Extract all IDs declared in headers."""
    declared = set()

    for line in lines:
        if not line.strip().startswith('#'):
            continue

        # Remove markdown header prefix
        clean = re.sub(r'^#+\s*', '', line).strip()

        for pattern, _ in ID_PATTERNS:
            for match in re.finditer(pattern, clean):
                declared.add(match.group())

    # Also add patch IDs P1-P10 as they're implicit
    for i in range(1, 11):
        declared.add(f'P{i}')

    return declared


def find_line_annotations(text: str) -> list[tuple[str, str, int, int]]:
    """Find all annotations on a line. Returns [(type, id, start, end), ...]"""
    return [(m.group(1), m.group(2), m.start(), m.end()) for m in ANNOTATION_PATTERN.finditer(text)]


def is_inside_annotation(start: int, end: int, annotations: list[tuple[str, str, int, int]]) -> bool:
    """Check if a position is inside an annotation bracket."""
    for _, _, ann_start, ann_end in annotations:
        if start >= ann_start and end <= ann_end:
            return True
    return False


def find_id_in_text(text: str, line_num: int, in_header: bool) -> list[tuple]:
    """Find all IDs in a line of text."""
    found = []

    # Find all annotations on the line
    line_annotations = find_line_annotations(text)

    for pattern, id_type in ID_PATTERNS:
        for match in re.finditer(pattern, text):
            id_str = match.group()
            start = match.start()
            end = match.end()

            # Skip if this looks like a code variable
            if is_code_variable(text, start, end, id_str):
                continue

            # Skip IDs that appear inside annotation brackets
            if is_inside_annotation(start, end, line_annotations):
                continue

            # Check if immediately followed by annotation (for prose refs)
            after_match = text[end:]
            # Allow optional space before annotation
            immediate_ann = re.match(r'\s*' + ANNOTATION_PATTERN.pattern, after_match)

            if immediate_ann:
                ann_type = immediate_ann.group(1)  # '=' or '+'
                ann_id = immediate_ann.group(2)
                found.append({
                    'line': line_num,
                    'id': id_str,
                    'type': id_type,
                    'in_header': in_header,
                    'has_annotation': True,
                    'annotation_type': 'labeled' if ann_type == '=' else 'context',
                    'annotation_id': ann_id,
                    'context': text[max(0, start-20):end+30].strip()
                })
            elif in_header and line_annotations:
                # Header with ownership annotation at end of line
                # Use the first annotation as ownership marker
                ann_type, ann_id, _, _ = line_annotations[0]
                found.append({
                    'line': line_num,
                    'id': id_str,
                    'type': id_type,
                    'in_header': in_header,
                    'has_annotation': True,
                    'annotation_type': 'labeled' if ann_type == '=' else 'context',
                    'annotation_id': ann_id,
                    'context': text[max(0, start-20):end+30].strip()
                })
            else:
                found.append({
                    'line': line_num,
                    'id': id_str,
                    'type': id_type,
                    'in_header': in_header,
                    'has_annotation': False,
                    'annotation_type': None,
                    'annotation_id': None,
                    'context': text[max(0, start-20):end+30].strip()
                })

    return found


def validate_annotations(filepath: Path) -> ValidationResult:
    """Validate all annotations in a file."""
    result = ValidationResult()

    content = filepath.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Extract declared IDs
    result.declared_ids = extract_declared_ids(lines)

    # Scan all lines
    in_code_block = False

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track code blocks
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_code_block = not in_code_block
            continue

        # Skip lines inside code blocks
        if in_code_block:
            continue

        is_header = stripped.startswith('#')

        # Find all IDs in this line
        found_ids = find_id_in_text(line, line_num, is_header)

        for item in found_ids:
            if item['in_header']:
                # Header IDs are DECLARATIONS - they don't need annotations
                # But they may have context annotations like (=[P1]) for invariants
                result.declarations.append(item)
                if item['has_annotation']:
                    if item['annotation_type'] == 'labeled':
                        result.valid_labeled.append(item)
                    else:
                        # Context ref in header is unusual but valid
                        result.valid_context.append(item)
                    # Validate referenced ID exists
                    if item['annotation_id'] not in result.declared_ids:
                        result.invalid_references.append({
                            **item,
                            'error': f"Referenced ID '{item['annotation_id']}' not declared"
                        })
                # Headers without annotations are fine - they ARE declarations
            else:
                # Prose IDs are REFERENCES - they should have (+[id]) annotations
                if not item['has_annotation']:
                    result.missing_annotations.append(item)
                else:
                    # Validate annotation format
                    if item['annotation_type'] == 'labeled':
                        # Labeled refs (=[id]) in prose are unusual
                        result.invalid_format.append({
                            **item,
                            'error': 'Labeled reference (=[id]) in prose should be (+[id]) context ref'
                        })
                    else:  # context
                        result.valid_context.append(item)

                    # Validate referenced ID exists
                    if item['annotation_id'] not in result.declared_ids:
                        result.invalid_references.append({
                            **item,
                            'error': f"Referenced ID '{item['annotation_id']}' not declared"
                        })

    return result


def main():
    import sys
    base = Path(__file__).parent

    # Accept file path as argument, default to plan.md
    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])
        if not target_path.is_absolute():
            target_path = base / target_path
    else:
        target_path = base / "plan.md"

    print(f"Validating annotations in {target_path}...")
    result = validate_annotations(target_path)

    print("=" * 70)
    print("ANNOTATION VALIDATION RESULTS")
    print("=" * 70)

    print(f"\nDeclared IDs: {len(result.declared_ids)}")

    # Missing annotations
    print(f"\n{'='*70}")
    print(f"MISSING ANNOTATIONS: {len(result.missing_annotations)}")
    print("=" * 70)

    if result.missing_annotations:
        # Group by type
        by_type = defaultdict(list)
        for item in result.missing_annotations:
            by_type[item['type']].append(item)

        for id_type, items in sorted(by_type.items()):
            print(f"\n## {id_type} ({len(items)} items)")
            for item in items[:10]:
                loc = "header" if item['in_header'] else "prose"
                print(f"  L{item['line']} [{loc}]: {item['id']} - \"{item['context'][:50]}...\"")
            if len(items) > 10:
                print(f"  ... and {len(items) - 10} more")

    # Invalid format
    if result.invalid_format:
        print(f"\n{'='*70}")
        print(f"INVALID FORMAT: {len(result.invalid_format)}")
        print("=" * 70)
        for item in result.invalid_format:
            print(f"  L{item['line']}: {item['id']} - {item['error']}")

    # Invalid references
    if result.invalid_references:
        print(f"\n{'='*70}")
        print(f"INVALID REFERENCES: {len(result.invalid_references)}")
        print("=" * 70)
        for item in result.invalid_references:
            print(f"  L{item['line']}: {item['id']} references '{item['annotation_id']}' - {item['error']}")

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"Declarations in headers: {len(result.declarations)}")
    print(f"  - With labeled ref (=[id]): {len(result.valid_labeled)}")
    print(f"  - Without annotation: {len(result.declarations) - len(result.valid_labeled)}")
    print(f"Valid context references (+[id]) in prose: {len(result.valid_context)}")
    print(f"Missing annotations (prose refs): {len(result.missing_annotations)}")
    print(f"Invalid format: {len(result.invalid_format)}")
    print(f"Invalid references: {len(result.invalid_references)}")

    total_issues = len(result.missing_annotations) + len(result.invalid_format) + len(result.invalid_references)
    print(f"\nTotal issues: {total_issues}")

    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    exit(main())
