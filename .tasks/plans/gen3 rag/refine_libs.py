#!/usr/bin/env python3
"""
Refine libs.md with primary + related structure.

For multi-library elements (4+), use refined_assignments.md.
For others, use first library as primary, rest as related.
"""

import re
from pathlib import Path


def parse_refined_assignments(content: str) -> dict:
    """Parse refined_assignments.md into {element: {primary, related}}"""
    refined = {}
    current_element = None

    for line in content.split('\n'):
        # Match element headers like "## Algorithm 2 (combined P1 + P10)" or "## EdgeBelief"
        elem_match = re.match(r'^## (.+?)(?:\s*\(|$)', line)
        if elem_match:
            current_element = elem_match.group(1).strip()
            refined[current_element] = {"primary": None, "related": []}
            continue

        if current_element:
            # Match primary
            prim_match = re.match(r'^- \*\*primary\*\*:\s*(.+)$', line)
            if prim_match:
                refined[current_element]["primary"] = prim_match.group(1).strip()

            # Match related
            rel_match = re.match(r'^- \*\*related\*\*:\s*(.+)$', line)
            if rel_match:
                related = [r.strip() for r in rel_match.group(1).split(',')]
                refined[current_element]["related"] = related

    return refined


def refine_libs(libs_content: str, refined: dict) -> str:
    """Update libs.md with primary/related structure."""
    lines = libs_content.split('\n')
    new_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match element lines
        elem_match = re.match(r'^- \*\*(.+?)\*\*(.*)$', line)
        if elem_match:
            element = elem_match.group(1)
            rest = elem_match.group(2)
            new_lines.append(line)

            # Get next line (current labels)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                label_match = re.match(r'^  - (.+)$', next_line)

                if label_match and not label_match.group(1).startswith('<!--'):
                    current_labels = [l.strip() for l in label_match.group(1).split(',')]

                    # Check if this element has refined assignment
                    if element in refined and refined[element]["primary"]:
                        primary = refined[element]["primary"]
                        related = refined[element]["related"]
                        new_lines.append(f"  - primary: {primary}")
                        if related:
                            new_lines.append(f"  - related: {', '.join(related)}")
                    elif len(current_labels) >= 4:
                        # Multi-lib but not in refined - check for partial matches
                        # Try matching without version suffix
                        found = False
                        for ref_elem in refined:
                            if element.startswith(ref_elem) or ref_elem.startswith(element):
                                primary = refined[ref_elem]["primary"]
                                related = refined[ref_elem]["related"]
                                new_lines.append(f"  - primary: {primary}")
                                if related:
                                    new_lines.append(f"  - related: {', '.join(related)}")
                                found = True
                                break
                        if not found:
                            # Keep first as primary, rest as related
                            new_lines.append(f"  - primary: {current_labels[0]}")
                            if len(current_labels) > 1:
                                new_lines.append(f"  - related: {', '.join(current_labels[1:])}")
                    else:
                        # Few libraries - first is primary, rest are related
                        new_lines.append(f"  - primary: {current_labels[0]}")
                        if len(current_labels) > 1:
                            new_lines.append(f"  - related: {', '.join(current_labels[1:])}")

                    i += 2  # Skip element and old label line
                    continue

            i += 1
            continue

        new_lines.append(line)
        i += 1

    return '\n'.join(new_lines)


def main():
    base = Path(__file__).parent
    libs_path = base / "libs.md"
    refined_path = base / "refined_assignments.md"

    libs_content = libs_path.read_text(encoding='utf-8')
    refined_content = refined_path.read_text(encoding='utf-8')

    refined = parse_refined_assignments(refined_content)
    print(f"Parsed {len(refined)} refined assignments")

    new_content = refine_libs(libs_content, refined)

    # Backup original
    backup_path = base / "libs_backup.md"
    backup_path.write_text(libs_content, encoding='utf-8')
    print(f"Backed up to {backup_path}")

    # Write refined version
    libs_path.write_text(new_content, encoding='utf-8')
    print(f"Refined libs.md written")

    # Count primary distributions
    primaries = {}
    for line in new_content.split('\n'):
        if line.strip().startswith('- primary:'):
            lib = line.split(':')[1].strip()
            primaries[lib] = primaries.get(lib, 0) + 1

    print("\nPrimary library distribution:")
    for lib, count in sorted(primaries.items(), key=lambda x: -x[1]):
        print(f"  {lib}: {count}")


if __name__ == "__main__":
    main()
