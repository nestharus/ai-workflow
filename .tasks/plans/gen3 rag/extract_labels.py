#!/usr/bin/env python3
"""
Extract all labeled elements from plan.md to create libs.md.

Labels include:
- Goals: G#
- Invariants: P#I#
- Claims: P#C#
- Data structures: Named structures under "data structures" sections
- Algorithms: Algorithm #
- Math sections: P#.#
- Lean skeletons: P# Lean #
- Proofs: Under "proofs" sections

Output format in libs.md:
- Element label/name
  - (library labels will be added by sub-agents)
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# Legal library labels from the analysis
LEGAL_LIBRARIES = [
    "foundation",      # Foundation & Memory Model
    "graph",           # Graph Representation & Topology
    "field",           # Field Geometry & Optimization
    "storage",         # Storage, Versioning & Epochs
    "ingestion",       # Ingestion & Grammar-Based Parsing
    "embedding",       # Embedding & Coordinate Alignment
    "patterns",        # Patterns, Abstractions & Compression
    "uncertainty",     # Uncertainty, Risk & Governance
    "exploration",     # Exploration, Curiosity & Learning
    "workspace",       # Memory Management & Workspace Model
    "deployment",      # Deployment, Reliability & Continuity
    "verification",    # Formal Verification & Proof Infrastructure
]


@dataclass
class LabeledElement:
    label: str           # The canonical label (e.g., "G1", "P1I1", "Algorithm 3")
    name: str            # Full name/description
    line_num: int        # Line number in plan.md
    category: str        # goal, invariant, claim, structure, algorithm, math, lean, proof
    patch: Optional[str] # Which patch it belongs to (P1, P2, etc.)


def extract_labels(content: str) -> list[LabeledElement]:
    """Extract all labeled elements from plan.md."""
    elements = []
    lines = content.split('\n')

    current_patch = None
    current_section = ""
    in_data_structures = False
    in_proofs = False

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Track current patch from headers
        patch_match = re.match(r'^#+\s+(P\d+)\b', stripped)
        if patch_match:
            current_patch = patch_match.group(1)

        # Track section type
        if re.match(r'^#+\s+.*data\s+structures', stripped, re.IGNORECASE):
            in_data_structures = True
            in_proofs = False
            current_section = "data_structures"
        elif re.match(r'^#+\s+.*proofs?.*obligations?', stripped, re.IGNORECASE):
            in_proofs = True
            in_data_structures = False
            current_section = "proofs"
        elif re.match(r'^#+\s+.*algorithms?', stripped, re.IGNORECASE):
            in_data_structures = False
            in_proofs = False
            current_section = "algorithms"
        elif re.match(r'^#+\s+.*invariants?', stripped, re.IGNORECASE):
            in_data_structures = False
            in_proofs = False
            current_section = "invariants"
        elif re.match(r'^#+\s+.*claims?', stripped, re.IGNORECASE):
            in_data_structures = False
            in_proofs = False
            current_section = "claims"
        elif re.match(r'^#+\s+.*lean', stripped, re.IGNORECASE):
            in_data_structures = False
            in_proofs = False
            current_section = "lean"
        elif re.match(r'^#+\s+.*math', stripped, re.IGNORECASE):
            in_data_structures = False
            in_proofs = False
            current_section = "math"
        elif re.match(r'^#\s', stripped):  # Top-level header resets
            in_data_structures = False
            in_proofs = False

        # Extract Goals: G#
        goal_match = re.match(r'^#+\s+\*{0,2}(G\d+)\*{0,2}\s*[:\-–]?\s*(.+)?$', stripped)
        if goal_match:
            elements.append(LabeledElement(
                label=goal_match.group(1),
                name=goal_match.group(2) or "",
                line_num=line_num,
                category="goal",
                patch=current_patch
            ))
            continue

        # Extract Invariants: P#I#
        inv_match = re.match(r'^#+\s+\*{0,2}(P\d+I\d+)\*{0,2}\s*[:\-–]?\s*(.+)?$', stripped)
        if inv_match:
            elements.append(LabeledElement(
                label=inv_match.group(1),
                name=inv_match.group(2) or "",
                line_num=line_num,
                category="invariant",
                patch=current_patch
            ))
            continue

        # Extract Claims: P#C#
        claim_match = re.match(r'^#+\s+\*{0,2}(P\d+C\d+)\*{0,2}\s*[:\-–]?\s*(.+)?$', stripped)
        if claim_match:
            elements.append(LabeledElement(
                label=claim_match.group(1),
                name=claim_match.group(2) or "",
                line_num=line_num,
                category="claim",
                patch=current_patch
            ))
            continue

        # Extract Algorithms: Algorithm #
        alg_match = re.match(r'^#+\s+\*{0,2}(Algorithm\s+\d+)\*{0,2}[:\s]*(.+)?$', stripped)
        if alg_match:
            elements.append(LabeledElement(
                label=alg_match.group(1),
                name=alg_match.group(2) or "",
                line_num=line_num,
                category="algorithm",
                patch=current_patch
            ))
            continue

        # Extract Math sections: P#.# (excluding P8 which uses different format)
        math_match = re.match(r'^#+\s+\*{0,2}(P\d+\.\d+)\*{0,2}\s*[:\-–]?\s*(.+)?$', stripped)
        if math_match:
            elements.append(LabeledElement(
                label=math_match.group(1),
                name=math_match.group(2) or "",
                line_num=line_num,
                category="math",
                patch=current_patch
            ))
            continue

        # Extract Lean skeletons: P# Lean #
        lean_match = re.match(r'^#+\s+\*{0,2}(P\d+\s+Lean\s+\d+)\*{0,2}[:\s]*(.+)?$', stripped)
        if lean_match:
            elements.append(LabeledElement(
                label=lean_match.group(1),
                name=lean_match.group(2) or "",
                line_num=line_num,
                category="lean",
                patch=current_patch
            ))
            continue

        # Also check for Lean #: format
        lean_match2 = re.match(r'^#+\s+\*{0,2}(Lean\s+\d+)\*{0,2}[:\s]*(.+)?$', stripped)
        if lean_match2:
            elements.append(LabeledElement(
                label=lean_match2.group(1),
                name=lean_match2.group(2) or "",
                line_num=line_num,
                category="lean",
                patch=current_patch
            ))
            continue

        # Extract Data structures (named headers under data structures sections)
        if in_data_structures and re.match(r'^###\s+\*{0,2}([A-Z][A-Za-z]+)\*{0,2}$', stripped):
            struct_match = re.match(r'^###\s+\*{0,2}([A-Z][A-Za-z]+)\*{0,2}$', stripped)
            if struct_match:
                elements.append(LabeledElement(
                    label=struct_match.group(1),
                    name="",
                    line_num=line_num,
                    category="structure",
                    patch=current_patch
                ))
                continue

    return elements


def write_libs_md(elements: list[LabeledElement], output_path: Path):
    """Write libs.md with elements grouped by category."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Library Assignments\n\n")
        f.write("Each element below needs library labels as sublists.\n\n")
        f.write("## Legal Libraries\n\n")
        for lib in LEGAL_LIBRARIES:
            f.write(f"- `{lib}`\n")
        f.write("\n---\n\n")

        # Group by category
        categories = {}
        for elem in elements:
            if elem.category not in categories:
                categories[elem.category] = []
            categories[elem.category].append(elem)

        # Write each category
        category_order = ["goal", "invariant", "claim", "structure", "algorithm", "math", "lean"]

        for cat in category_order:
            if cat not in categories:
                continue

            cat_elements = categories[cat]
            f.write(f"## {cat.title()}s ({len(cat_elements)})\n\n")

            for elem in cat_elements:
                # Format: - Label: Name (line #) [patch]
                name_part = f": {elem.name}" if elem.name else ""
                patch_part = f" [{elem.patch}]" if elem.patch else ""
                f.write(f"- **{elem.label}**{name_part}{patch_part} (L{elem.line_num})\n")
                # Placeholder for library labels
                f.write(f"  - <!-- libraries: -->\n")

            f.write("\n")


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_path = base / "libs.md"

    content = plan_path.read_text(encoding='utf-8')
    elements = extract_labels(content)

    print(f"Extracted {len(elements)} labeled elements:")

    # Count by category
    by_cat = {}
    for e in elements:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1

    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")

    write_libs_md(elements, libs_path)
    print(f"\nWritten to: {libs_path}")


if __name__ == "__main__":
    main()
