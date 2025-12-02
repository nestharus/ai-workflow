#!/usr/bin/env python3
r"""Fix YAML formatting issues in documentation files.

Converts inline quoted strings with escape sequences to proper block scalars.
Handles fields: code, description, example, text, scope.
"""

import re
import sys
from pathlib import Path

# Fields that should be converted to block scalars when they contain
# multi-line content or escape sequences
BLOCK_SCALAR_FIELDS = ("code", "description", "example", "text", "scope", "query")


def fix_yaml_file(file_path: Path) -> bool:
    """Fix formatting issues in a single YAML file.

    Args:
        file_path: Path to the YAML file to fix.

    Returns:
        True if changes were made, False otherwise.
    """
    content = file_path.read_text(encoding="utf-8")
    original = content

    # Pattern 1: Fix double-quoted fields with \n escapes (all target fields)
    for field in BLOCK_SCALAR_FIELDS:
        content = fix_double_quoted_field(content, field)

    # Pattern 2: Fix single-quoted fields with continuation or trailing WS
    for field in BLOCK_SCALAR_FIELDS:
        content = fix_single_quoted_field(content, field)

    # Pattern 3: Fix text blocks with double single-quotes for escaping
    content = fix_escaped_quotes_in_text(content)

    # Pattern 4: Wrap long lines in existing block scalars
    content = wrap_long_block_scalar_lines(content)

    # Pattern 5: Strip trailing whitespace from all lines
    content = strip_trailing_whitespace(content)

    if content != original:
        file_path.write_text(content, encoding="utf-8")
        return True
    return False


def strip_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from all lines."""
    lines = content.split("\n")
    return "\n".join(line.rstrip() for line in lines)


def wrap_long_block_scalar_lines(content: str) -> str:
    """Wrap lines in existing block scalars that exceed max length."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a block scalar start (field: | or field: >)
        match = re.match(r"^(\s*)(\w+):\s*[|>](-?)(\d*)$", line)
        if match:
            indent = match.group(1)
            # Groups 2-4 capture field_name, chomp indicator, explicit indent
            # but we only need indent for calculating content indent

            result.append(line)
            i += 1

            # Calculate the block content indent
            block_indent = indent + "  "
            available_width = MAX_LINE_LENGTH - len(block_indent)

            # Collect and wrap block scalar content lines
            while i < len(lines):
                content_line = lines[i]

                # Check if still in block scalar (more indented than field)
                if content_line.startswith(block_indent) or content_line.strip() == "":
                    # Extract the content (remove block indent)
                    if content_line.strip() == "":
                        result.append("")
                    else:
                        stripped_content = content_line[len(block_indent) :]

                        # Wrap if too long
                        if len(content_line) > MAX_LINE_LENGTH:
                            wrapped = wrap_text(stripped_content, available_width)
                            for wrapped_line in wrapped:
                                result.append(f"{block_indent}{wrapped_line}")
                        else:
                            result.append(content_line)
                    i += 1
                else:
                    # End of block scalar
                    break
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def fix_double_quoted_field(content: str, field_name: str) -> str:
    r"""Convert double-quoted fields with \n escapes to block scalars."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match field: "content..." (double-quoted)
        pattern = rf'^(\s*)({re.escape(field_name)}:\s*)"(.*)$'
        match = re.match(pattern, line)
        if match:
            indent = match.group(1)
            field_start = match.group(3)

            # Check if quote closes on same line
            if field_start.endswith('"') and not field_start.endswith('\\"'):
                # Single-line double-quoted string
                field_content = field_start[:-1]
                # Check if it has escapes worth converting
                if "\\n" in field_content or "\\\\" in field_content:
                    field_content = unescape_double_quoted(field_content)
                    result.append(format_as_block_scalar(indent, field_name, field_content))
                    i += 1
                    continue
            else:
                # Multi-line double-quoted string
                full_content = field_start
                i += 1
                while i < len(lines):
                    cont_line = lines[i]
                    # Check if this is a continuation (indented more or continuation of quote)
                    if cont_line.startswith(indent + " ") or cont_line.strip().startswith('"'):
                        stripped = cont_line.lstrip()
                        # Handle YAML line continuation: if full_content ends with \,
                        # it's a continuation marker that should be removed
                        if full_content.endswith("\\"):
                            full_content = full_content[:-1]
                        full_content += stripped
                        # Check for closing quote (not escaped)
                        if stripped.rstrip().endswith('"') and not stripped.rstrip().endswith(
                            '\\"'
                        ):
                            break
                    else:
                        i -= 1
                        break
                    i += 1

                # Remove trailing quote
                if full_content.endswith('"'):
                    full_content = full_content[:-1]

                full_content = unescape_double_quoted(full_content)
                result.append(format_as_block_scalar(indent, field_name, full_content.strip()))
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def unescape_double_quoted(content: str) -> str:
    """Unescape a double-quoted YAML string.

    YAML double-quoted strings support:
    - \\n for newlines
    - \\" for literal quotes
    - \\\\ for literal backslash
    - \\ followed by space = escaped space (just becomes a space)
    - \\ followed by actual newline for line continuation (folding)
    """
    # First, handle YAML line continuations: backslash followed by
    # actual newline and optional leading whitespace on next line.
    # This joins the lines without adding a space.
    # The pattern matches: \ then optional whitespace, then actual newline, then indent
    content = re.sub(r"\\[ \t]*\r?\n[ \t]*", "", content)

    # Handle standard escape sequences
    content = content.replace("\\n", "\n")
    content = content.replace('\\"', '"')
    content = content.replace("\\t", "\t")
    # Handle escaped space (\ followed by space) - just becomes space
    content = content.replace("\\ ", " ")
    # Handle escaped backslash last
    content = content.replace("\\\\", "\\")
    return content


def fix_single_quoted_field(content: str, field_name: str) -> str:
    """Convert single-quoted fields spanning multiple lines to block scalars."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Match field: 'content... (single-quoted, possibly multi-line)
        pattern = rf"^(\s*)({re.escape(field_name)}:\s*)'(.*)$"
        match = re.match(pattern, line)
        if match:
            indent = match.group(1)
            field_start = match.group(3)

            # Check if quote closes on same line (not escaped '')
            ends_with_quote = field_start.rstrip().endswith(
                "'"
            ) and not field_start.rstrip().endswith("''")
            if ends_with_quote and "'" in field_start[:-1]:
                # Might be single line, but check for trailing whitespace issues
                field_content = field_start.rstrip()[:-1]
                # Only convert if it has trailing whitespace before the quote or embedded escapes
                if field_start != field_start.rstrip() or "''" in field_content:
                    field_content = field_content.replace("''", "'")
                    result.append(format_as_block_scalar(indent, field_name, field_content.strip()))
                    i += 1
                    continue
            elif not ends_with_quote:
                # Multi-line single-quoted string
                full_content = field_start
                i += 1
                while i < len(lines):
                    cont_line = lines[i]
                    # Check for continuation - more indented or blank
                    if cont_line.startswith(indent + " ") or cont_line.strip() == "":
                        stripped = cont_line.strip()
                        if stripped:
                            full_content += " " + stripped
                        # Check for closing quote
                        if stripped.endswith("'") and not stripped.endswith("''"):
                            full_content = full_content.rstrip()[:-1]  # Remove trailing '
                            break
                    else:
                        i -= 1
                        break
                    i += 1

                # Unescape single quotes
                full_content = full_content.replace("''", "'")
                result.append(format_as_block_scalar(indent, field_name, full_content.strip()))
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


MAX_LINE_LENGTH = 120


def wrap_text(text: str, max_width: int) -> list[str]:
    """Wrap text to fit within max_width, preserving existing line breaks."""
    if max_width <= 10:
        max_width = 80  # Safety fallback

    result_lines = []
    for paragraph in text.split("\n"):
        if len(paragraph) <= max_width:
            result_lines.append(paragraph)
            continue

        # Need to wrap this paragraph
        words = paragraph.split(" ")
        current_line = ""
        for word in words:
            if not current_line:
                current_line = word
            elif len(current_line) + 1 + len(word) <= max_width:
                current_line += " " + word
            else:
                result_lines.append(current_line)
                current_line = word

        if current_line:
            result_lines.append(current_line)

    return result_lines


def format_as_block_scalar(indent: str, field_name: str, content: str) -> str:
    """Format a field value as a YAML block scalar with line wrapping."""
    block_indent = indent + "  "
    # Available width for content = max_length - block_indent_length
    available_width = MAX_LINE_LENGTH - len(block_indent)

    # Wrap the content lines
    wrapped_lines = wrap_text(content, available_width)

    # Check if it can stay inline (single short line, no special chars)
    if (
        len(wrapped_lines) == 1
        and len(wrapped_lines[0]) < 60
        and ":" not in wrapped_lines[0]
        and len(indent) + len(field_name) + 2 + len(wrapped_lines[0]) <= MAX_LINE_LENGTH
    ):
        return f"{indent}{field_name}: {wrapped_lines[0]}"

    result = f"{indent}{field_name}: |"
    for line in wrapped_lines:
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
