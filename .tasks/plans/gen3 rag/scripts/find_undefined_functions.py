#!/usr/bin/env python3
"""
Find undefined function calls in algorithm pseudocode blocks.

Scans plan.md and library files for:
1. Function DEFINITIONS: `function FUNC_NAME(...):`
2. Function CALLS: `FUNC_NAME(...)` in pseudocode blocks

Reports functions that are called but never defined.
"""

import re
from pathlib import Path
from collections import defaultdict


# Common utility functions to ignore (built-in operations)
BUILTIN_FUNCTIONS = {
    # Math/aggregation
    'SUM', 'NORM', 'NORM2', 'MAX', 'MIN', 'ABS', 'SQRT', 'LOG', 'EXP',
    'SHUFFLE', 'SORT', 'TOPK', 'ARGMAX', 'ARGMIN', 'MEAN', 'VAR',
    # Control flow / state
    'UPDATE', 'APPEND', 'RETURN', 'BREAK', 'CONTINUE',
    # Set operations
    'UNION', 'INTERSECT', 'DIFFERENCE',
    # Basic accessors that are likely struct fields
    'GET', 'SET', 'LOOKUP', 'INSERT', 'DELETE', 'CONTAINS',
}


def extract_pseudocode_blocks(content: str) -> list[tuple[int, str]]:
    """Extract all ```pseudo ... ``` blocks with line numbers."""
    blocks = []
    lines = content.split('\n')
    in_block = False
    block_start = 0
    block_lines = []

    for i, line in enumerate(lines):
        if line.strip().startswith('```pseudo'):
            in_block = True
            block_start = i + 1
            block_lines = []
        elif in_block and line.strip().startswith('```'):
            blocks.append((block_start, '\n'.join(block_lines)))
            in_block = False
        elif in_block:
            block_lines.append(line)

    return blocks


def extract_function_definitions(blocks: list[tuple[int, str]]) -> dict[str, int]:
    """Extract function definitions from pseudocode blocks."""
    definitions = {}

    for line_num, block in blocks:
        # Match: function FUNC_NAME(...):
        for match in re.finditer(r'function\s+([A-Z][A-Z0-9_]*)\s*\(', block):
            func_name = match.group(1)
            definitions[func_name] = line_num

    return definitions


def extract_function_calls(blocks: list[tuple[int, str]]) -> dict[str, list[int]]:
    """Extract function calls from pseudocode blocks."""
    calls = defaultdict(list)

    for line_num, block in blocks:
        # Match: FUNC_NAME(...) - uppercase function names with parentheses
        # Exclude: function definitions, keywords, and things after 'for X in'
        for match in re.finditer(r'\b([A-Z][A-Z0-9_]*)\s*\(', block):
            func_name = match.group(1)
            # Skip if this is a definition line
            line_start = block.rfind('\n', 0, match.start()) + 1
            line_end = block.find('\n', match.end())
            if line_end == -1:
                line_end = len(block)
            line = block[line_start:line_end]

            if not line.strip().startswith('function '):
                calls[func_name].append(line_num)

    return calls


def find_algorithm_context(content: str, line_num: int) -> str:
    """Find which algorithm a line belongs to."""
    lines = content.split('\n')
    for i in range(line_num - 1, -1, -1):
        if i < len(lines):
            line = lines[i]
            match = re.match(r'^#{2,3}\s+(Algorithm\s+\d+[^#\n]*)', line)
            if match:
                return match.group(1).strip()
    return "Unknown"


def scan_file(filepath: Path) -> tuple[dict, dict, str]:
    """Scan a file for function definitions and calls."""
    content = filepath.read_text(encoding='utf-8')
    blocks = extract_pseudocode_blocks(content)
    definitions = extract_function_definitions(blocks)
    calls = extract_function_calls(blocks)
    return definitions, calls, content


def main():
    base = Path(__file__).resolve().parents[1]
    plan_file = base / "plan.md"
    libs_dir = base / "libraries"

    print("=" * 70)
    print("UNDEFINED FUNCTION ANALYSIS")
    print("=" * 70)

    # Collect all definitions and calls
    all_definitions = {}
    all_calls = defaultdict(list)
    file_contents = {}

    # Scan plan.md
    if plan_file.exists():
        defs, calls, content = scan_file(plan_file)
        file_contents['plan.md'] = content
        for func, line in defs.items():
            all_definitions[func] = ('plan.md', line)
        for func, lines in calls.items():
            for line in lines:
                all_calls[func].append(('plan.md', line))

    # Scan library files
    for lib_file in sorted(libs_dir.glob("*.md")):
        defs, calls, content = scan_file(lib_file)
        file_contents[lib_file.name] = content
        for func, line in defs.items():
            if func not in all_definitions:
                all_definitions[func] = (lib_file.name, line)
        for func, lines in calls.items():
            for line in lines:
                all_calls[func].append((lib_file.name, line))

    print(f"\nFound {len(all_definitions)} function definitions")
    print(f"Found {len(all_calls)} unique function calls")

    # Find undefined functions
    undefined = {}
    for func, call_locations in all_calls.items():
        if func not in all_definitions and func not in BUILTIN_FUNCTIONS:
            undefined[func] = call_locations

    print(f"\nUndefined functions: {len(undefined)}")

    # Group by likely category based on name patterns
    categories = {
        'PATTERN': [],
        'FIELD': [],
        'EMBED': [],
        'GRAPH': [],
        'PARSE': [],
        'WORKSPACE': [],
        'HYPOTHESIS': [],
        'INDEX': [],
        'STATE': [],
        'OTHER': [],
    }

    for func in sorted(undefined.keys()):
        categorized = False
        for cat in ['PATTERN', 'FIELD', 'EMBED', 'GRAPH', 'PARSE', 'WORKSPACE', 'HYPOTHESIS', 'INDEX', 'STATE']:
            if cat in func:
                categories[cat].append(func)
                categorized = True
                break
        if not categorized:
            categories['OTHER'].append(func)

    print("\n" + "=" * 70)
    print("UNDEFINED FUNCTIONS BY CATEGORY")
    print("=" * 70)

    for category, funcs in categories.items():
        if funcs:
            print(f"\n## {category} ({len(funcs)} functions)")
            for func in sorted(funcs):
                locations = undefined[func]
                # Get first call location for context
                first_file, first_line = locations[0]
                content = file_contents.get(first_file, '')
                algo = find_algorithm_context(content, first_line)
                print(f"  - {func}")
                print(f"      Called {len(locations)}x, first in {first_file}:{first_line} ({algo})")

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nTotal defined functions: {len(all_definitions)}")
    print(f"Total unique calls: {len(all_calls)}")
    print(f"Undefined functions: {len(undefined)}")
    print(f"Built-in functions (ignored): {len(BUILTIN_FUNCTIONS)}")

    # List all undefined with call counts
    print("\n" + "=" * 70)
    print("ALL UNDEFINED FUNCTIONS (sorted by call count)")
    print("=" * 70)

    sorted_undefined = sorted(undefined.items(), key=lambda x: -len(x[1]))
    for func, locations in sorted_undefined:
        print(f"  {func}: {len(locations)} calls")

    return undefined


if __name__ == "__main__":
    main()
