"""Low-level browser interaction primitives via Windows PowerShell.

Uses a PowerShell helper script (winctl.ps1) for all interactions to stay
in the Windows coordinate system, avoiding WSLg X11-to-Windows mapping issues.
"""

from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

WINCTL_SCRIPT_WSL = Path(__file__).parent / "winctl.ps1"
# Convert WSL path to Windows path for PowerShell
WINCTL_SCRIPT = str(WINCTL_SCRIPT_WSL).replace("/mnt/c/", "C:\\").replace("/", "\\")
SCREENSHOT_PATH = r"C:\Users\xteam\AppData\Local\Temp\web_gpt_screen.png"
SCREENSHOT_PATH_WSL = Path("/mnt/c/Users/xteam/AppData/Local/Temp/web_gpt_screen.png")


def _ps(command: str, *args: str, timeout: float = 30) -> str:
    """Run a winctl.ps1 command and return stdout."""
    cmd = [
        "powershell.exe",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(WINCTL_SCRIPT),
        command,
        *[str(a) for a in args],
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell {command} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _jitter(value: int, spread: int = 3) -> int:
    """Add small random offset to a coordinate."""
    return value + random.randint(-spread, spread)


def _human_delay(base: float = 0.3, variance: float = 0.2) -> None:
    """Sleep for a human-like random duration."""
    time.sleep(base + random.uniform(0, variance))


def screenshot(monitor: str = "primary") -> np.ndarray:
    """Take a screenshot via PowerShell, return as BGR numpy array.

    Args:
        monitor: "primary", "all", or monitor number (1-based).
    """
    win_path = str(SCREENSHOT_PATH)
    _ps("screenshot", win_path, monitor)
    img = cv2.imread(str(SCREENSHOT_PATH_WSL))
    if img is None:
        raise RuntimeError(f"Failed to read screenshot from {SCREENSHOT_PATH_WSL}")
    return img


def screenshot_region(x: int, y: int, w: int, h: int) -> np.ndarray:
    """Screenshot and crop a specific region (Windows logical coords)."""
    full = screenshot()
    return full[y : y + h, x : x + w]


def mouse_move(x: int, y: int, jitter: bool = True) -> None:
    """Move mouse to target with optional jitter."""
    tx = _jitter(x) if jitter else x
    ty = _jitter(y) if jitter else y
    _ps("mouse_move", str(tx), str(ty))
    _human_delay(0.05, 0.05)


def mouse_click(x: int, y: int, jitter: bool = True) -> None:
    """Move to target and click with human-like delays."""
    tx = _jitter(x) if jitter else x
    ty = _jitter(y) if jitter else y
    _human_delay(0.08, 0.12)
    _ps("mouse_click", str(tx), str(ty))
    _human_delay(0.2, 0.3)


def mouse_position() -> tuple[int, int]:
    """Get current mouse position (Windows logical coords)."""
    out = _ps("mouse_pos")
    # Output: pos:X,Y
    parts = out.split(":")[-1].split(",")
    return int(parts[0]), int(parts[1])


def clipboard_set(text: str) -> None:
    """Set clipboard contents via PowerShell, then re-focus Firefox."""
    # Write text to a temp file and read it in PS to avoid escaping issues
    tmp = Path("/mnt/c/Users/xteam/AppData/Local/Temp/web_gpt_clip.txt")
    tmp.write_text(text, encoding="utf-8")
    win_tmp = r"C:\Users\xteam\AppData\Local\Temp\web_gpt_clip.txt"
    subprocess.run(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            WINCTL_SCRIPT,
            "clip_set_file",
            win_tmp,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )


def clipboard_get() -> str:
    """Get clipboard contents via PowerShell."""
    # Write clipboard text to a temp file to avoid encoding issues
    win_tmp = r"C:\Users\xteam\AppData\Local\Temp\web_gpt_clip_out.txt"
    wsl_tmp = Path("/mnt/c/Users/xteam/AppData/Local/Temp/web_gpt_clip_out.txt")
    subprocess.run(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"$t = [System.Windows.Forms.Clipboard]::GetText(); "
            f"[System.IO.File]::WriteAllText('{win_tmp}', $t)",
        ],
        capture_output=True,
        timeout=15,
    )
    if wsl_tmp.exists():
        return wsl_tmp.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def key_combo(*keys: str) -> None:
    """Send a key combination via PowerShell SendKeys.

    Translates common key names to SendKeys format:
        ctrl+v -> ^v, ctrl+l -> ^l, Return -> {ENTER}, etc.
    """
    _human_delay(0.1, 0.15)

    combo = "+".join(keys)
    sendkeys = _translate_keys(combo)
    _ps("key", sendkeys)
    _human_delay(0.15, 0.1)


def _translate_keys(combo: str) -> str:
    """Translate xdotool-style key combo to SendKeys format."""
    # Handle common patterns
    combo = combo.lower()

    if combo == "return" or combo == "enter":
        return "{ENTER}"
    if combo == "tab":
        return "{TAB}"
    if combo == "escape":
        return "{ESC}"

    # ctrl+X -> ^X
    if combo.startswith("ctrl+"):
        key = combo[5:]
        return f"^{key}"

    # alt+X -> %X
    if combo.startswith("alt+"):
        key = combo[4:]
        return f"%{key}"

    # shift+X -> +X
    if combo.startswith("shift+"):
        key = combo[6:]
        return f"+{key}"

    return combo


def console_exec(js_code: str, retries: int = 2) -> None:
    """Execute JavaScript in Firefox's Web Console.

    Uses a single PowerShell process to: focus Firefox → dismiss dialogs →
    open console → paste JS → execute → close console. This avoids the
    focus-stealing issue that occurs when using separate PS calls.

    Includes retry logic: if Ctrl+Shift+K toggled the console *closed*
    instead of open (because it was already open), the clipboard will
    still contain the JS text. In that case, a second attempt will open
    the console and succeed.
    """
    tmp = Path("/mnt/c/Users/xteam/AppData/Local/Temp/web_gpt_console.js")
    tmp.write_text(js_code, encoding="utf-8")
    win_tmp = r"C:\Users\xteam\AppData\Local\Temp\web_gpt_console.js"

    for attempt in range(retries):
        _ps("console_exec", win_tmp, timeout=30)
        time.sleep(0.5)
        clip = clipboard_get()
        if clip.strip() != js_code.strip():
            return  # clipboard was overwritten by copy() → success
        if attempt < retries - 1:
            # Console was likely in wrong toggle state — try again
            time.sleep(0.5)


def match_template(image: np.ndarray, template: np.ndarray, threshold: float = 0.8) -> float:
    """Match template against image, return max confidence score."""
    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val)


def find_firefox() -> dict | None:
    """Find Firefox window position and size (Windows logical coords)."""
    out = _ps("find_firefox")
    if "notfound" in out:
        return None
    # Output: firefox:hwnd,x,y,w,h,title
    for line in out.splitlines():
        if line.startswith("firefox:"):
            parts = line[8:].split(",", 5)
            return {
                "hwnd": int(parts[0]),
                "x": int(parts[1]),
                "y": int(parts[2]),
                "w": int(parts[3]),
                "h": int(parts[4]),
                "title": parts[5] if len(parts) > 5 else "",
            }
    return None


def move_firefox(x: int, y: int, w: int, h: int) -> None:
    """Move and resize Firefox window."""
    _ps("move_firefox", str(x), str(y), str(w), str(h))


def get_monitors() -> list[dict]:
    """Get monitor layout info."""
    out = _ps("monitors")
    monitors = []
    for line in out.splitlines():
        if line.startswith("monitor:"):
            parts = line[8:].split(",")
            monitors.append(
                {
                    "name": parts[0],
                    "x": int(parts[1]),
                    "y": int(parts[2]),
                    "w": int(parts[3]),
                    "h": int(parts[4]),
                    "primary": parts[5] == "True",
                }
            )
    return monitors
