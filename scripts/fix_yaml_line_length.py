#!/usr/bin/env python3
"""Fix yamllint "line too long" warnings in YAML documentation files.

This script wraps long lines within YAML block scalars (text: |, rule: |, etc.)
while preserving exact indentation and structure.
"""

import re
import sys
from pathlib import Path


def wrap_text_preserving_indent(text: str, base_indent: str, max_length: int = 120) -> str:
    """Wrap text while preserving base indentation.

    Args:
        text: The text to wrap (without leading indent)
        base_indent: The indentation to apply to all lines
        max_length: Maximum line length

    Returns:
        Wrapped text with proper indentation
    """
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word

        # Calculate the full line length with indentation
        full_length = len(base_indent) + len(test_line)

        if full_length > max_length and current_line:
            # Save current line and start new one
            lines.append(base_indent + current_line)
            current_line = word
        else:
            current_line = test_line

    if current_line:
        lines.append(base_indent + current_line)

    return "\n".join(lines)


def fix_yaml_file(file_path: Path, dry_run: bool = False) -> tuple[bool, int]:
    """Fix line length issues in a YAML file.

    Args:
        file_path: Path to the YAML file
        dry_run: If True, don't write changes

    Returns:
        Tuple of (success, num_fixes)
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        num_fixes = 0
        i = 0

        while i < len(lines):
            line = lines[i]
            line_stripped = line.rstrip("\n\r")

            # Check if this line starts a block scalar for text fields
            match = re.match(
                r"^(\s*)(text|rule|content|description|definition|note|example|analysis|code):\s*\|",
                line_stripped,
            )

            if match:
                # Found a block scalar start
                new_lines.append(line)
                i += 1

                # Collect all lines in this block
                block_lines = []
                block_indent = None

                while i < len(lines):
                    block_line = lines[i]
                    block_line_stripped = block_line.rstrip("\n\r")

                    # Empty line - keep it
                    if not block_line_stripped.strip():
                        block_lines.append(block_line)
                        i += 1
                        continue

                    # Determine block content indentation from first non-empty line
                    if block_indent is None:
                        stripped = block_line_stripped.lstrip()
                        block_indent = block_line_stripped[
                            : len(block_line_stripped) - len(stripped)
                        ]

                    # Check if we're still in the block
                    if (
                        block_line_stripped.startswith(block_indent)
                        or not block_line_stripped.strip()
                    ):
                        # This line belongs to the block
                        if len(block_line_stripped) > 120:
                            # Need to wrap this line
                            content = block_line_stripped[len(block_indent) :]
                            wrapped = wrap_text_preserving_indent(
                                content, block_indent, max_length=120
                            )
                            block_lines.append(wrapped + "\n")
                            num_fixes += 1
                        else:
                            block_lines.append(block_line)
                        i += 1
                    else:
                        # We've exited the block
                        break

                # Add all the block lines
                new_lines.extend(block_lines)
            else:
                # Not a block scalar start
                # Check if it's a simple long line we can wrap
                if len(line_stripped) > 120:
                    # Check if it's a key: value line
                    kv_match = re.match(r"^(\s*)(\w+):\s+(.+)$", line_stripped)
                    if kv_match:
                        indent, key, value = kv_match.groups()
                        # Wrap the value part, converting to block scalar format
                        new_lines.append(f"{indent}{key}: |\n")
                        wrapped = wrap_text_preserving_indent(value, indent + "  ", max_length=120)
                        new_lines.append(wrapped + "\n")
                        num_fixes += 1
                    else:
                        # Can't wrap this line safely
                        new_lines.append(line)
                else:
                    new_lines.append(line)
                i += 1

        if num_fixes > 0:
            if not dry_run:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                print(f"  Fixed {file_path} ({num_fixes} long lines wrapped)")
            else:
                print(f"  Would fix {file_path} ({num_fixes} long lines)")
            return True, 1
        else:
            print(f"  No changes needed for {file_path}")
            return True, 0

    except Exception as e:
        print(f"  Error processing {file_path}: {e}")
        import traceback

        traceback.print_exc()
        return False, 0


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix yamllint line-too-long warnings in YAML files"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="YAML files to process (if not specified, processes all docs/**/*.yml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without modifying files"
    )

    args = parser.parse_args()

    # Determine which files to process
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        # Find all YAML files in docs/
        docs_dir = Path(__file__).parent.parent / "docs"
        if not docs_dir.exists():
            # Try current directory
            docs_dir = Path("docs")

        if not docs_dir.exists():
            print("Error: docs/ directory not found")
            sys.exit(1)

        files = sorted(docs_dir.rglob("*.yml"))

    if not files:
        print("No YAML files found to process")
        sys.exit(1)

    print(f"Processing {len(files)} YAML files...")
    if args.dry_run:
        print("DRY RUN MODE - no files will be modified")
    print()

    total_success = 0
    total_changed = 0
    total_errors = 0

    for file_path in files:
        success, num_changes = fix_yaml_file(file_path, dry_run=args.dry_run)
        if success:
            total_success += 1
            total_changed += num_changes
        else:
            total_errors += 1

    print()
    print("Summary:")
    print(f"  Files processed: {total_success}")
    print(f"  Files changed: {total_changed}")
    print(f"  Errors: {total_errors}")

    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
