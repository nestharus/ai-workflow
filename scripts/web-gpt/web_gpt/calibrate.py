"""Interactive calibration wizard for ChatGPT UI element positions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from . import actions

CALIBRATION_DIR = Path(__file__).parent.parent / ".calibration"
CONFIG_FILE = CALIBRATION_DIR / "config.json"
IDLE_TEMPLATE_FILE = CALIBRATION_DIR / "idle_template.png"


def _prompt_position(label: str) -> tuple[int, int]:
    """Ask user to position mouse, capture coordinates."""
    input(f"  Move mouse to {label}, then press Enter... ")
    x, y = actions.mouse_position()
    print(f"    -> ({x}, {y})")
    return x, y


def _capture_template(cx: int, cy: int, size: int = 60) -> None:
    """Capture a template image centered at (cx, cy)."""
    half = size // 2
    full = actions.screenshot()
    template = full[cy - half : cy + half, cx - half : cx + half]
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(IDLE_TEMPLATE_FILE), template)
    print(f"    Saved template ({size}x{size}px)")


def load_config() -> dict:
    """Load calibration config."""
    if not CONFIG_FILE.exists():
        print("Not calibrated. Run: uv run web-gpt calibrate", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text())


def save_config(data: dict) -> None:
    """Save calibration config."""
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def load_idle_template():
    """Load the idle (speech icon) template image."""
    template = cv2.imread(str(IDLE_TEMPLATE_FILE))
    if template is None:
        print("Idle template missing. Run: uv run web-gpt calibrate", file=sys.stderr)
        sys.exit(1)
    return template


def run_calibration() -> None:
    """Interactive calibration wizard."""
    print("=== web-gpt calibration ===\n")
    print("Open ChatGPT in Firefox with a fresh/idle chat.")
    print("Make sure GPT 5.2 Pro + Extended Thinking are already selected.\n")
    input("Press Enter when ready...")

    config = {}

    # 1. Speech icon (idle detection)
    print("\n[1/5] Speech icon (microphone) — idle state indicator")
    ix, iy = _prompt_position("the CENTER of the speech icon")
    config["icon_center"] = [ix, iy]
    icon_size = 60
    half = icon_size // 2
    config["icon_region"] = [ix - half, iy - half, icon_size, icon_size]
    _capture_template(ix, iy, icon_size)

    # Verify
    rx, ry, rw, rh = config["icon_region"]
    template = cv2.imread(str(IDLE_TEMPLATE_FILE))
    current = actions.screenshot_region(rx, ry, rw, rh)
    score = actions.match_template(current, template)
    print(f"    Match confidence: {score:.3f}")
    if score < 0.8:
        print("    WARNING: Low confidence. Consider repositioning and retrying.")

    # 2. Text input
    print("\n[2/5] Text input box")
    tx, ty = _prompt_position("the CENTER of the text input box")
    config["input_center"] = [tx, ty]

    # 3. New chat button
    print("\n[3/5] New chat button")
    nx, ny = _prompt_position("the 'New chat' button (top-left area)")
    config["new_chat"] = [nx, ny]

    # 4. Attach button (paperclip)
    print("\n[4/5] Attach / upload button (paperclip icon)")
    ax, ay = _prompt_position("the attach/paperclip button")
    config["attach_button"] = [ax, ay]

    # 5. Copy button on responses
    print("\n[5/5] Copy button on a response")
    print("  Send a quick test message first (e.g., 'hi'), then hover over")
    print("  the response to reveal the copy button (clipboard icon).")
    cx, cy = _prompt_position("the copy button on the LAST response")
    config["copy_button"] = [cx, cy]

    save_config(config)
    print(f"\nCalibration saved to {CONFIG_FILE}")
    print("You can re-run calibration anytime with: uv run web-gpt calibrate")
