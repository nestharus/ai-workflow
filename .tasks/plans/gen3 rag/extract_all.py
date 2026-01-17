#!/usr/bin/env python3
"""
Extract ALL content headers from plan.md to libs.md.
Captures everything that was missed by the narrow pattern-based extraction.
"""

import re
from pathlib import Path


# Skip these section headers (they organize content, not content themselves)
# NOTE: non-goals, non-functionals, performance targets ARE content - don't skip them
SECTION_KEYWORDS = [
    'data structure', 'algorithms', 'algorithm section', 'invariants',
    'claims', 'proofs', 'proof obligation', 'lean skeleton', 'math section',
    'goals section', 'references', 'summary', 'overview',
    'integration points'
]


def is_section_header(text: str) -> bool:
    """Check if this is an organizing section header."""
    lower = text.lower()
    # Match "P# data structures", "P# algorithms", etc.
    if re.match(r'^P\d+\s+(data structures|algorithms|math|invariants|claims|proofs|lean)', lower):
        return True
    for kw in SECTION_KEYWORDS:
        if kw in lower:
            return True
    return False


def get_existing_elements(libs_content: str) -> set[str]:
    """Get elements already in libs.md."""
    elements = set()
    for line in libs_content.split('\n'):
        match = re.match(r'^- \*\*(.+?)\*\*', line)
        if match:
            elements.add(match.group(1))
    return elements


def extract_missing(plan_content: str, existing: set[str]) -> list[dict]:
    """Extract headers from plan.md that are not in existing."""
    missing = []
    lines = plan_content.split('\n')

    for i, line in enumerate(lines):
        match = re.match(r'^(#{2,3})\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            line_num = i + 1

            # Skip if already in libs.md (exact match only for short labels)
            found = text in existing
            if not found:
                for elem in existing:
                    # Only match if the existing element is a substantial prefix (>80% of text)
                    # This prevents "Algorithm 1" from matching "Algorithm 1: Streaming ingestion"
                    if text == elem:
                        found = True
                        break
                    if len(elem) > 20 and (elem in text or text in elem):
                        found = True
                        break

            if found:
                continue

            # Skip section headers
            if is_section_header(text):
                continue

            missing.append({
                'text': text,
                'line_num': line_num,
                'level': level
            })

    return missing


def categorize_element(text: str) -> tuple[str, str]:
    """Determine category and primary library for an element."""
    lower = text.lower()

    # P8 concepts -> patterns
    if 'disentangle' in lower or 'factor' in lower or 'module' in lower:
        return 'concept', 'patterns'
    if 'rebuild' in lower or 'compress' in lower:
        return 'concept', 'patterns'
    if 'idea engine' in lower or 'idea' in lower:
        return 'concept', 'exploration'

    # Core graph primitives
    if text in ['Node', 'Edge', 'Graph']:
        return 'structure', 'graph'
    if 'graph token' in lower or 'grammar rule' in lower:
        return 'structure', 'ingestion'
    if 'parse' in lower:
        return 'structure', 'ingestion'
    if 'coordinate' in lower or 'adapter' in lower:
        return 'structure', 'embedding'

    # Storage concepts
    if any(x in lower for x in ['epoch', 'snapshot', 'index', 'event log', 'ann']):
        return 'structure', 'storage'

    # Field/math concepts
    if any(x in lower for x in ['procrustes', 'alignment', 'orthogonal', 'composite']):
        return 'math', 'field'

    # Spec/overview
    if 'spec' in lower or 'problem' in lower or 'core move' in lower:
        return 'concept', 'foundation'

    # P5/P8 components
    if lower.startswith('p5') or lower.startswith('p8'):
        return 'concept', 'patterns'

    # Default
    return 'concept', 'foundation'


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_path = base / "libs.md"

    plan_content = plan_path.read_text(encoding='utf-8')
    libs_content = libs_path.read_text(encoding='utf-8')

    existing = get_existing_elements(libs_content)
    missing = extract_missing(plan_content, existing)

    print(f"Existing elements: {len(existing)}")
    print(f"Missing elements: {len(missing)}")

    # Group by category
    by_category = {}
    for elem in missing:
        cat, lib = categorize_element(elem['text'])
        elem['category'] = cat
        elem['primary'] = lib
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(elem)

    # Build new section for libs.md
    new_section = "\n## Additional Elements ({count})\n\n".format(count=len(missing))

    for cat in ['concept', 'structure', 'math']:
        if cat not in by_category:
            continue
        elems = by_category[cat]
        new_section += f"### {cat.title()}s ({len(elems)})\n\n"
        for elem in elems:
            new_section += f"- **{elem['text']}** (L{elem['line_num']})\n"
            new_section += f"  - primary: {elem['primary']}\n"
            new_section += f"  - related: \n"
        new_section += "\n"

    # Append to libs.md
    new_libs = libs_content + new_section
    libs_path.write_text(new_libs, encoding='utf-8')

    print(f"\nAdded {len(missing)} elements to libs.md")
    print("\nBy category:")
    for cat, elems in by_category.items():
        print(f"  {cat}: {len(elems)}")

    print("\nBy primary library:")
    by_lib = {}
    for elem in missing:
        lib = elem['primary']
        by_lib[lib] = by_lib.get(lib, 0) + 1
    for lib, count in sorted(by_lib.items(), key=lambda x: -x[1]):
        print(f"  {lib}: {count}")


if __name__ == "__main__":
    main()
