#!/usr/bin/env python3
r"""
Find all ID references in plan.md that may need annotation markers.

This script identifies references to IDs in prose text (excluding headers and code blocks)
and reports whether they already have annotation markers.

Annotation formats:
- (@[=id]) - labeled reference (belongs to)
- (@[+id]) - context reference (references)

ID patterns searched:
- Algorithm \d+
- P\d+I\d+, P\d+C\d+, P\d+\.\d+, P\d+ (alone)
- G\d+, D\d+, Comp\d+, T\d+, C\d+, S\d+

Usage:
    python3 find_references.py                    # Print to console
    python3 find_references.py output.txt         # Save to file
    ./find_references.py                          # If executable

Example output:
    L123: "see the P4 pattern library" -> P4 (no annotation)
    L456: "Algorithm 10 (@[=Algorithm 10])" -> Algorithm 10 (labeled reference)
    L789: "using P5 (@[+P5])" -> P5 (context reference)
"""

import re
from pathlib import Path
from typing import List, Tuple, NamedTuple


class Reference(NamedTuple):
    """A found ID reference."""
    line_num: int
    line_text: str
    id_text: str
    annotation_type: str  # 'labeled', 'context', or 'none'
    context: str


def is_header_line(line: str) -> bool:
    """Check if line is a markdown header."""
    return line.strip().startswith('#')


def is_in_code_block(line_num: int, code_block_ranges: List[Tuple[int, int]]) -> bool:
    """Check if line is inside a code block."""
    for start, end in code_block_ranges:
        if start <= line_num <= end:
            return True
    return False


def find_code_blocks(lines: List[str]) -> List[Tuple[int, int]]:
    """Find all code block ranges (line numbers, 1-indexed)."""
    code_blocks = []
    in_block = False
    block_start = None

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Check for code fence (```, ~~~, or indented code)
        if stripped.startswith('```') or stripped.startswith('~~~'):
            if not in_block:
                in_block = True
                block_start = i
            else:
                in_block = False
                if block_start is not None:
                    code_blocks.append((block_start, i))
                block_start = None

    # Handle unclosed code block
    if in_block and block_start is not None:
        code_blocks.append((block_start, len(lines)))

    return code_blocks


def get_context(line: str, match_start: int, match_end: int, context_chars: int = 30) -> str:
    """Extract context around the matched ID."""
    # Get surrounding text
    start = max(0, match_start - context_chars)
    end = min(len(line), match_end + context_chars)

    context = line[start:end].strip()

    # Clean up context for display
    if start > 0:
        context = '...' + context
    if end < len(line):
        context = context + '...'

    return context


def get_annotation_type(line: str, match_end: int) -> str:
    """
    Check if the ID has an annotation marker and return its type.

    Returns:
        'labeled' - for (@[=id]) format (belongs to)
        'context' - for (@[+id]) format (references)
        'none' - no annotation marker found
    """
    # Look ahead from the match end for annotation pattern
    remaining = line[match_end:].lstrip()

    # Pattern: (@[=something]) - labeled reference
    labeled_pattern = r'^\(@\[=([^\]]+)\]\)'
    if re.match(labeled_pattern, remaining):
        return 'labeled'

    # Pattern: (@[+something]) - context reference
    context_pattern = r'^\(@\[\+([^\]]+)\]\)'
    if re.match(context_pattern, remaining):
        return 'context'

    return 'none'


def find_all_references(file_path: Path) -> List[Reference]:
    """Find all ID references in the file."""

    # ID patterns to search for
    # Order matters - more specific patterns first
    id_patterns = [
        r'\bAlgorithm\s+\d+',
        r'\bP\d+I\d+',
        r'\bP\d+C\d+',
        r'\bP\d+\.\d+',
        r'\bP\d+',
        r'\bG\d+',
        r'\bD\d+',
        r'\bComp\d+',
        r'\bT\d+',
        r'\bC\d+',
        r'\bS\d+',
    ]

    # Compile combined pattern
    combined_pattern = '|'.join(f'({pattern})' for pattern in id_patterns)
    regex = re.compile(combined_pattern)

    references = []

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find all code blocks first
    code_blocks = find_code_blocks(lines)

    for line_num, line in enumerate(lines, start=1):
        # Skip headers
        if is_header_line(line):
            continue

        # Skip code blocks
        if is_in_code_block(line_num, code_blocks):
            continue

        # Find all matches in this line
        for match in regex.finditer(line):
            id_text = match.group(0)
            match_start = match.start()
            match_end = match.end()

            # Check for annotation type
            annot_type = get_annotation_type(line, match_end)

            # Get context
            context = get_context(line, match_start, match_end, context_chars=40)

            references.append(Reference(
                line_num=line_num,
                line_text=line.rstrip(),
                id_text=id_text,
                annotation_type=annot_type,
                context=context
            ))

    return references


def format_reference(ref: Reference) -> str:
    """Format a reference for display."""
    if ref.annotation_type == 'labeled':
        status = "labeled reference (@[=id])"
    elif ref.annotation_type == 'context':
        status = "context reference (@[+id])"
    else:
        status = "no annotation"
    return f'L{ref.line_num}: "{ref.context}" -> {ref.id_text} ({status})'


def print_summary(references: List[Reference]):
    """Print summary statistics."""
    total = len(references)
    labeled = sum(1 for ref in references if ref.annotation_type == 'labeled')
    context = sum(1 for ref in references if ref.annotation_type == 'context')
    without_annotation = sum(1 for ref in references if ref.annotation_type == 'none')

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total references found: {total}")
    print(f"Labeled references (@[=id]): {labeled}")
    print(f"Context references (@[+id]): {context}")
    print(f"Without annotation: {without_annotation}")

    if without_annotation > 0:
        print(f"\nNeeds attention: {without_annotation} references missing annotations")


def main():
    """Main entry point."""
    import sys

    plan_file = Path(__file__).resolve().parents[2] / 'plan.md'

    if not plan_file.exists():
        print(f"Error: {plan_file} not found")
        return 1

    # Check if output file argument provided
    output_file = None
    if len(sys.argv) > 1:
        output_file = Path(sys.argv[1])

    print(f"Scanning {plan_file}...")
    print("=" * 80)

    references = find_all_references(plan_file)

    # Group by annotation type
    without_annotation = [ref for ref in references if ref.annotation_type == 'none']
    labeled_refs = [ref for ref in references if ref.annotation_type == 'labeled']
    context_refs = [ref for ref in references if ref.annotation_type == 'context']

    # Prepare output
    output_lines = []

    # Print references without annotation first (these need attention)
    if without_annotation:
        header = "\nREFERENCES NEEDING ANNOTATION:"
        separator = "-" * 80
        print(header)
        print(separator)
        output_lines.append(header)
        output_lines.append(separator)

        for ref in without_annotation:
            line = format_reference(ref)
            print(line)
            output_lines.append(line)

    # Print labeled references
    if labeled_refs:
        header = "\n\nLABELED REFERENCES (@[=id]):"
        separator = "-" * 80
        print(header)
        print(separator)
        output_lines.append(header)
        output_lines.append(separator)

        for ref in labeled_refs:
            line = format_reference(ref)
            print(line)
            output_lines.append(line)

    # Print context references
    if context_refs:
        header = "\n\nCONTEXT REFERENCES (@[+id]):"
        separator = "-" * 80
        print(header)
        print(separator)
        output_lines.append(header)
        output_lines.append(separator)

        for ref in context_refs:
            line = format_reference(ref)
            print(line)
            output_lines.append(line)

    # Print summary
    print_summary(references)

    # Save to file if requested
    if output_file:
        labeled = sum(1 for ref in references if ref.annotation_type == 'labeled')
        context = sum(1 for ref in references if ref.annotation_type == 'context')
        without = sum(1 for ref in references if ref.annotation_type == 'none')

        output_lines.append("\n" + "=" * 80)
        output_lines.append("SUMMARY")
        output_lines.append("=" * 80)
        output_lines.append(f"Total references found: {len(references)}")
        output_lines.append(f"Labeled references (@[=id]): {labeled}")
        output_lines.append(f"Context references (@[+id]): {context}")
        output_lines.append(f"Without annotation: {without}")
        if without > 0:
            output_lines.append(f"\nNeeds attention: {without} references missing annotations")

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        print(f"\nResults saved to: {output_file}")

    return 0


if __name__ == '__main__':
    exit(main())
