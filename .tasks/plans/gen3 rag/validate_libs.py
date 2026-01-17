#!/usr/bin/env python3
"""
Validate libs.md:
1. Every root element has at least 1 library label
2. All library labels are legal
"""

import re
from pathlib import Path

LEGAL_LIBRARIES = {
    "foundation",
    "graph",
    "field",
    "storage",
    "ingestion",
    "embedding",
    "patterns",
    "uncertainty",
    "exploration",
    "workspace",
    "deployment",
    "verification",
}


def validate_libs(content: str) -> tuple[list[str], dict]:
    """Validate libs.md content. Returns (errors, stats)."""
    errors = []
    stats = {
        "total_elements": 0,
        "elements_with_labels": 0,
        "library_counts": {lib: 0 for lib in LEGAL_LIBRARIES},
        "illegal_labels": set(),
    }

    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match root elements: - **Label**...
        elem_match = re.match(r'^- \*\*(.+?)\*\*', line)
        if elem_match:
            current_element = elem_match.group(1)
            elem_line = i + 1
            stats["total_elements"] += 1

            # Look at next line for labels
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                label_match = re.match(r'^  - (.+)$', next_line)

                if label_match:
                    labels_str = label_match.group(1).strip()

                    # Skip HTML comments (unlabeled placeholders)
                    if labels_str.startswith('<!--'):
                        errors.append(f"Line {elem_line}: Element '{current_element}' has no library labels")
                    else:
                        # Parse comma-separated labels
                        labels = [l.strip() for l in labels_str.split(',')]

                        if labels and labels[0]:
                            stats["elements_with_labels"] += 1

                            for label in labels:
                                if label in LEGAL_LIBRARIES:
                                    stats["library_counts"][label] += 1
                                else:
                                    stats["illegal_labels"].add(label)
                                    errors.append(f"Line {i+2}: Illegal library '{label}' for element '{current_element}'")
                        else:
                            errors.append(f"Line {elem_line}: Element '{current_element}' has no library labels")
                else:
                    errors.append(f"Line {elem_line}: Element '{current_element}' has no library labels")
            else:
                errors.append(f"Line {elem_line}: Element '{current_element}' has no library labels")

        i += 1

    return errors, stats


def main():
    libs_path = Path(__file__).parent / "libs.md"
    content = libs_path.read_text(encoding='utf-8')

    errors, stats = validate_libs(content)

    print("=" * 60)
    print("LIBS.MD VALIDATION REPORT")
    print("=" * 60)

    print(f"\nTotal elements: {stats['total_elements']}")
    print(f"Elements with labels: {stats['elements_with_labels']}")

    print("\nLibrary distribution:")
    for lib, count in sorted(stats['library_counts'].items(), key=lambda x: -x[1]):
        bar = '#' * (count // 2)
        print(f"  {lib:15} {count:3} {bar}")

    if stats['illegal_labels']:
        print(f"\nIllegal labels found: {stats['illegal_labels']}")

    if errors:
        print(f"\n{'=' * 60}")
        print(f"ERRORS ({len(errors)})")
        print("=" * 60)
        for err in errors[:20]:  # Show first 20
            print(f"  {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        return 1
    else:
        print(f"\n{'=' * 60}")
        print("VALIDATION PASSED")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    exit(main())
