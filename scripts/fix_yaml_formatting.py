#!/usr/bin/env python3
"""Fix YAML formatting issues in documentation files.

Converts inline quoted strings with escape sequences to proper block scalars.
"""

import re
import sys
from pathlib import Path


def fix_yaml_file(file_path: Path) -> bool:
    """Fix formatting issues in a single YAML file.

    Args:
        file_path: Path to the YAML file to fix.

    Returns:
        True if changes were made, False otherwise.
    """
    content = file_path.read_text(encoding="utf-8")
    original = content

    # Pattern 1: Fix code blocks with inline \n escapes
    # Matches: code: "..." or code: '...' spanning multiple lines
    content = fix_code_blocks(content)

    # Pattern 2: Fix description blocks with awkward quoting
    content = fix_multiline_quoted_fields(content, "description")

    # Pattern 3: Fix text blocks with double single-quotes for escaping
    content = fix_escaped_quotes_in_text(content)

    # Pattern 4: Strip trailing whitespace from all lines
    content = strip_trailing_whitespace(content)

    if content != original:
        file_path.write_text(content, encoding="utf-8")
        return True
    return False


def strip_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from all lines."""
    lines = content.split("\n")
    return "\n".join(line.rstrip() for line in lines)


def fix_code_blocks(content: str) -> str:
    """Convert inline code strings with \\n to block scalars."""
    # Match code: followed by a quoted string that contains \n
    # This regex captures the indentation and the quoted content
    pattern = re.compile(
        r'^(\s*)(code:\s*)"((?:[^"\\]|\\.)*)"\s*$',
        re.MULTILINE,
    )

    def replace_double_quoted(m: re.Match[str]) -> str:
        indent = m.group(1)
        code_content = m.group(3)
        # Unescape the content
        code_content = code_content.replace("\\n", "\n")
        code_content = code_content.replace('\\"', '"')
        code_content = code_content.replace("\\\\", "\\")
        return format_as_block_scalar(indent, "code", code_content)

    content = pattern.sub(replace_double_quoted, content)

    # Also handle single-quoted strings
    pattern_single = re.compile(
        r"^(\s*)(code:\s*)'((?:[^'\\]|\\.|'')*)'\s*$",
        re.MULTILINE,
    )

    def replace_single_quoted(m: re.Match[str]) -> str:
        indent = m.group(1)
        code_content = m.group(3)
        # Unescape single quote escaping
        code_content = code_content.replace("''", "'")
        if "\\n" in code_content:
            code_content = code_content.replace("\\n", "\n")
        return format_as_block_scalar(indent, "code", code_content)

    content = pattern_single.sub(replace_single_quoted, content)

    # Handle multi-line quoted strings (YAML folded style with backslash continuation)
    content = fix_multiline_code_blocks(content)

    return content


def fix_multiline_code_blocks(content: str) -> str:
    """Fix code blocks that span multiple lines with backslash continuations."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a code: line with a quoted string
        match = re.match(r'^(\s*)(code:\s*)"(.*)$', line)
        if match:
            indent = match.group(1)
            code_start = match.group(3)

            # Check if it continues (ends with backslash or quote not closed)
            if code_start.rstrip().endswith("\\") or '"' not in code_start[:-1]:
                # Collect all continuation lines
                full_code = code_start
                i += 1
                while i < len(lines):
                    cont_line = lines[i]
                    # Check if this is a continuation line (indented more)
                    if cont_line.startswith(indent + " "):
                        # Remove the leading spaces that are part of YAML folding
                        stripped = cont_line.lstrip()
                        full_code += stripped
                        if not stripped.rstrip().endswith("\\") and '"' in stripped:
                            # Found the closing quote
                            break
                    else:
                        # Not a continuation, put it back
                        i -= 1
                        break
                    i += 1

                # Now parse the full code string
                # Remove trailing quote if present
                if full_code.endswith('"'):
                    full_code = full_code[:-1]

                # Unescape
                full_code = full_code.replace("\\n", "\n")
                full_code = full_code.replace('\\"', '"')
                full_code = full_code.replace("\\\n", "")  # Line continuations
                full_code = full_code.replace("\\", "")  # Remaining backslashes from continuation

                result.append(format_as_block_scalar(indent, "code", full_code.strip()))
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def fix_multiline_quoted_fields(content: str, field_name: str) -> str:
    """Fix fields that use awkward multi-line quoting."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match field: 'content that continues
        match = re.match(rf"^(\s*)({field_name}:\s*)'(.*)$", line)
        if match:
            indent = match.group(1)
            field_content = match.group(3)

            # Check if quote is not closed on this line
            if not field_content.rstrip().endswith("'") or field_content.rstrip() == "'":
                # Collect continuation lines
                i += 1
                while i < len(lines):
                    cont_line = lines[i]
                    if cont_line.startswith(indent + " ") or cont_line.strip() == "":
                        stripped = cont_line.strip()
                        if stripped:
                            field_content += " " + stripped
                        if stripped.endswith("'"):
                            # Found closing quote
                            field_content = field_content[:-1]  # Remove trailing quote
                            break
                    else:
                        i -= 1
                        break
                    i += 1

                # Clean up the content
                field_content = field_content.replace("''", "'")
                field_content = field_content.strip()

                result.append(format_as_block_scalar(indent, field_name, field_content))
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def fix_escaped_quotes_in_text(content: str) -> str:
    """Fix text fields that use '' for escaping apostrophes."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match text: ''Content or text: 'Content with ''escaped''
        match = re.match(r"^(\s*)(text:\s*)''(.*)$", line)
        if match:
            indent = match.group(1)
            text_content = match.group(3)

            # Collect all lines until we find the closing
            i += 1
            while i < len(lines):
                cont_line = lines[i]
                if cont_line.startswith(indent + " ") or (
                    cont_line.strip() == "" and i + 1 < len(lines)
                ):
                    stripped = cont_line.strip()
                    if stripped:
                        text_content += " " + stripped
                    if stripped.endswith("''") and not stripped.endswith("'''"):
                        text_content = text_content[:-2]  # Remove trailing ''
                        break
                else:
                    i -= 1
                    break
                i += 1

            # Unescape
            text_content = text_content.replace("''", "'")
            text_content = text_content.strip()

            result.append(format_as_block_scalar(indent, "text", text_content))
            i += 1
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def format_as_block_scalar(indent: str, field_name: str, content: str) -> str:
    """Format a field value as a YAML block scalar."""
    lines = content.split("\n")
    block_indent = indent + "  "

    if len(lines) == 1 and len(content) < 60 and ":" not in content:
        # Short content without special chars can stay inline
        # But if it has colons or is long, use block scalar
        return f"{indent}{field_name}: {content}"

    result = f"{indent}{field_name}: |"
    for line in lines:
        result += f"\n{block_indent}{line}"

    return result


def main() -> int:
    """Main entry point."""
    project_root = Path(__file__).parent.parent

    if not project_root.exists():
        print(f"Error: project root not found at {project_root}", file=sys.stderr)
        return 1

    # Collect all YAML files from docs/, tests/, scripts/, and root
    yml_files: list[Path] = []
    yml_files.extend(project_root.glob("*.yml"))
    yml_files.extend(project_root.glob("*.yaml"))
    for subdir in ["docs", "tests", "scripts"]:
        subdir_path = project_root / subdir
        if subdir_path.exists():
            yml_files.extend(subdir_path.rglob("*.yml"))
            yml_files.extend(subdir_path.rglob("*.yaml"))

    fixed_count = 0

    for yml_file in yml_files:
        try:
            if fix_yaml_file(yml_file):
                print(f"Fixed: {yml_file.relative_to(project_root)}")
                fixed_count += 1
        except Exception as e:
            print(f"Error processing {yml_file}: {e}", file=sys.stderr)

    print(f"\nFixed {fixed_count} of {len(yml_files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
