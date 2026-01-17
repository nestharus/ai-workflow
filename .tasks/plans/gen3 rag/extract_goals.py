#!/usr/bin/env python3
"""
Extract goals from plan.md that were missed by the original extraction.

Goal formats in plan.md:
- G6. **Evidence permanence**
- **G12 Structural abstraction**
- G36. **Manifold as a first-class substrate**
- 1. **Reliable directions** (numbered, implicit G1-G5)
"""

import re
from pathlib import Path


def extract_goals(content: str) -> list[dict]:
    """Extract all goals from plan.md."""
    goals = []
    lines = content.split('\n')

    in_goals_section = False
    numbered_goal_counter = 0

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Track when we enter/exit goals section
        if stripped == '# Goals':
            in_goals_section = True
            continue
        elif stripped.startswith('# ') and in_goals_section:
            in_goals_section = False

        # Match G# formats: G6. **name**, **G12 name**, G36. **name**
        # Format 1: G##. **Name**
        match = re.match(r'^G(\d+)\.\s+\*\*(.+?)\*\*', stripped)
        if match:
            goals.append({
                'label': f'G{match.group(1)}',
                'name': match.group(2),
                'line_num': line_num,
            })
            continue

        # Format 2: **G## Name**
        match = re.match(r'^\*\*G(\d+)\s+(.+?)\*\*', stripped)
        if match:
            goals.append({
                'label': f'G{match.group(1)}',
                'name': match.group(2),
                'line_num': line_num,
            })
            continue

        # Format 3: Numbered list in goals section (implicit G1-G5)
        if in_goals_section:
            match = re.match(r'^(\d+)\.\s+\*\*(.+?)\*\*', stripped)
            if match:
                num = int(match.group(1))
                goals.append({
                    'label': f'G{num}',
                    'name': match.group(2),
                    'line_num': line_num,
                })
                continue

    return goals


def main():
    base = Path(__file__).parent
    plan_path = base / "plan.md"
    libs_path = base / "libs.md"

    content = plan_path.read_text(encoding='utf-8')
    goals = extract_goals(content)

    print(f"Found {len(goals)} goals:")
    for g in goals:
        print(f"  {g['label']}: {g['name']} (L{g['line_num']})")

    # Read existing libs.md and insert goals section after the header
    libs_content = libs_path.read_text(encoding='utf-8')

    # Build goals section
    goals_section = "\n## Goals ({count})\n\n".format(count=len(goals))
    for g in goals:
        goals_section += f"- **{g['label']}**: {g['name']} (L{g['line_num']})\n"
        goals_section += f"  - primary: foundation\n"  # Default - can be refined
        goals_section += f"  - related: \n"

    # Insert after the --- separator (after Legal Libraries section)
    parts = libs_content.split('\n---\n', 1)
    if len(parts) == 2:
        new_content = parts[0] + '\n---\n' + goals_section + parts[1]
        libs_path.write_text(new_content, encoding='utf-8')
        print(f"\nGoals section added to libs.md")
    else:
        print("Could not find insertion point in libs.md")


if __name__ == "__main__":
    main()
