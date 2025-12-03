#!/usr/bin/env python3
"""Read clipboard content and save to a timestamped file under docs/plans/timestamp/."""

import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except FileNotFoundError:
        return False


def decode_output(data: bytes) -> str:
    """Decode bytes trying multiple encodings."""
    for encoding in ["utf-8", "utf-16", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def get_clipboard_macos() -> str:
    """Get clipboard content on macOS using pbpaste."""
    result = subprocess.run(["pbpaste"], capture_output=True, check=True)
    return decode_output(result.stdout)


def get_clipboard_windows() -> str:
    """Get clipboard content on native Windows using PowerShell."""
    result = subprocess.run(
        ["powershell", "-command", "Get-Clipboard"],
        capture_output=True,
        check=True,
    )
    return decode_output(result.stdout)


def get_clipboard_wsl() -> str:
    """Get clipboard content in WSL using PowerShell.exe."""
    result = subprocess.run(
        ["powershell.exe", "-command", "Get-Clipboard"],
        capture_output=True,
        check=True,
    )
    return decode_output(result.stdout)


def get_clipboard_linux() -> str:
    """Get clipboard content on Linux using xclip or xsel."""
    # Try xclip first
    if shutil.which("xclip"):
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            check=True,
        )
        return decode_output(result.stdout)

    # Fall back to xsel
    if shutil.which("xsel"):
        result = subprocess.run(
            ["xsel", "--clipboard", "--output"],
            capture_output=True,
            check=True,
        )
        return decode_output(result.stdout)

    raise FileNotFoundError("Neither xclip nor xsel found. Install one of them.")


def get_clipboard_content() -> str:
    """Get clipboard content based on the current platform."""
    system = platform.system()

    try:
        if system == "Darwin":
            return get_clipboard_macos()
        elif system == "Windows":
            return get_clipboard_windows()
        elif system == "Linux":
            if is_wsl():
                return get_clipboard_wsl()
            return get_clipboard_linux()
        else:
            print(f"Unsupported platform: {system}", file=sys.stderr)
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error reading clipboard: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Clipboard tool not found: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Read clipboard and write to timestamped file."""
    # Get the project root (assuming script is in scripts/)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # Create timestamp directory if it doesn't exist
    timestamp_dir = project_root / "docs" / "plans" / "timestamp"
    timestamp_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = timestamp_dir / f"{timestamp}.md"

    # Get clipboard content
    content = get_clipboard_content()

    if not content.strip():
        print("Clipboard is empty", file=sys.stderr)
        sys.exit(1)

    # Write to file
    output_file.write_text(content)

    # Output the created file path
    print(output_file)


if __name__ == "__main__":
    main()
