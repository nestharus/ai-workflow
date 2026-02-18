"""Send a prompt to ChatGPT and wait for the response."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import actions
from .detect import detect_is_idle


def is_idle(config: dict) -> bool:
    """Check if ChatGPT is idle (speech icon visible)."""
    idle, _confidence = detect_is_idle(config)
    return idle


def start_new_chat(config: dict) -> None:
    """Click the New Chat button."""
    pos = config.get("new_chat")
    if not pos:
        print("Warning: new_chat position not calibrated", file=sys.stderr)
        return
    nx, ny = pos
    print("  Starting new chat...")
    actions.mouse_click(nx, ny)
    actions._human_delay(1.5, 0.5)


def upload_file(config: dict, file_path: Path) -> None:
    """Upload a file via the attach button + file picker dialog."""
    pos = config.get("attach_button")
    if not pos:
        print("Warning: attach_button position not calibrated", file=sys.stderr)
        return

    ax, ay = pos
    print(f"  Uploading: {file_path.name}")

    # Click attach button
    actions.mouse_click(ax, ay)
    actions._human_delay(1.0, 0.5)

    # File dialog should open — type the full path
    actions._human_delay(0.5, 0.3)

    # Type the full absolute path
    path_str = str(file_path.resolve())
    actions.clipboard_set(path_str)
    actions._human_delay(0.2, 0.1)

    # Use Ctrl+L to focus the location bar in the file dialog
    actions.key_combo("ctrl+l")
    actions._human_delay(0.3, 0.2)

    # Paste the path
    actions.key_combo("ctrl+v")
    actions._human_delay(0.3, 0.2)

    # Press Enter to select the file
    actions.key_combo("Return")
    actions._human_delay(1.0, 0.5)

    # Wait for the file to appear as an attachment in the chat
    actions._human_delay(2.0, 1.0)
    print("    File attached.")


def send_prompt(
    config: dict,
    prompt_text: str,
    attachment: Path | None = None,
    new_chat: bool = True,
) -> None:
    """Paste prompt into ChatGPT and send it."""
    # Verify idle
    if not is_idle(config):
        print("Warning: ChatGPT does not appear idle.", file=sys.stderr)
        print("It may still be generating or detection is off.", file=sys.stderr)
        if sys.stdin.isatty():
            resp = input("Continue anyway? [y/N] ")
            if resp.lower() != "y":
                sys.exit(1)
        else:
            print("  Non-interactive mode — continuing anyway.", file=sys.stderr)

    # New chat if requested
    if new_chat:
        start_new_chat(config)
        # Wait for new chat to load
        actions._human_delay(1.0, 0.5)

    # Upload attachment first if provided
    if attachment and attachment.exists():
        upload_file(config, attachment)

    # Click the text input
    ix, iy = config["input_center"]
    print("  Clicking text input...")
    actions.mouse_click(ix, iy)
    actions._human_delay(0.3, 0.2)

    # Paste prompt via clipboard
    print(f"  Pasting prompt ({len(prompt_text)} chars)...")
    actions.clipboard_set(prompt_text)
    actions._human_delay(0.3, 0.2)
    actions.key_combo("ctrl+v")
    actions._human_delay(0.5, 0.3)

    # Send with Enter
    print("  Sending...")
    actions.key_combo("Return")
    actions._human_delay(4.0, 2.0)  # Give ChatGPT time to start generating

    # Verify it started generating
    if is_idle(config):
        print("Warning: ChatGPT still appears idle after sending.", file=sys.stderr)
        print("The prompt may not have been sent.", file=sys.stderr)
        if sys.stdin.isatty():
            resp = input("Continue polling? [y/N] ")
            if resp.lower() != "y":
                sys.exit(1)
        else:
            print("  Non-interactive mode — continuing to poll.", file=sys.stderr)
    else:
        print("  Prompt sent — ChatGPT is generating.")


def wait_for_response(config: dict, poll_interval: int = 15) -> None:
    """Poll until ChatGPT finishes generating."""
    start_time = time.time()
    print(f"  Polling every {poll_interval}s for completion...")

    while True:
        time.sleep(poll_interval)
        elapsed = time.time() - start_time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)

        if is_idle(config):
            # Double-check to avoid false positive during brief pauses
            actions._human_delay(3.0, 1.0)
            if is_idle(config):
                print(f"\n  Response complete! ({mins}m {secs}s elapsed)")
                return

        sys.stdout.write(f"  [{mins:02d}:{secs:02d}] Still generating...\r")
        sys.stdout.flush()


def extract_response(config: dict) -> str:
    """Extract the last response text by clicking the copy button.

    Finds the copy toolbar icon below the last ChatGPT response,
    hovers to ensure it's visible, clicks it, then reads the clipboard.
    """
    from .detect import find_copy_button

    mon = config.get("monitor", "1")
    mon_ox, mon_oy = config.get("monitor_offset", [0, 0])

    # Firefox bounds in monitor-relative coords
    ff = config.get("firefox", {})
    ff_rel = (
        ff.get("x", 0) - mon_ox,
        ff.get("y", 0) - mon_oy,
        ff.get("w", 0),
        ff.get("h", 0),
    )

    # Take screenshot
    img = actions.screenshot(mon)
    icon_y = config["icon_center"][1] - mon_oy if config.get("icon_center") else None
    input_y = (icon_y - 30) if icon_y else None

    pos = find_copy_button(img, input_y=input_y, window_bounds=ff_rel)

    if pos is None:
        print("Warning: could not find copy button.", file=sys.stderr)
        return ""

    abs_x = pos[0] + mon_ox
    abs_y = pos[1] + mon_oy

    # Clear clipboard
    actions.clipboard_set("")
    actions._human_delay(0.3, 0.1)

    # Hover over response area first, then move to button
    print(f"  Copy button at ({abs_x}, {abs_y})")
    actions.mouse_move(abs_x, abs_y - 30, jitter=False)
    actions._human_delay(0.5, 0.2)
    actions.mouse_move(abs_x, abs_y, jitter=False)
    actions._human_delay(0.3, 0.1)

    # Click
    actions.mouse_click(abs_x, abs_y, jitter=False)
    actions._human_delay(1.0, 0.5)

    text = actions.clipboard_get()
    return text
