"""Auto-detect ChatGPT UI elements from screenshots.

Finds the text input area and speech/stop icon without manual calibration.
Detection strategy:
  1. Find the white circle (speech/stop icon) — brightest circular feature
  2. Infer text input location from the circle position
  3. Detect idle (waveform bars) vs generating (stop square) by scanning
     horizontal lines through the circle for black/white transitions
"""

from __future__ import annotations

import cv2
import numpy as np

from . import actions


def find_icon_circle(
    img: np.ndarray,
    search_region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int] | None:
    """Find the white circle (speech/stop icon) in the image.

    Args:
        img: BGR screenshot image.
        search_region: (x, y, w, h) to restrict search area. None = full image.

    Returns:
        (cx, cy, radius) in image coordinates, or None if not found.
    """
    if search_region:
        sx, sy, sw, sh = search_region
        h, w = img.shape[:2]
        # Clip to image bounds
        sx = max(0, min(sx, w - 1))
        sy = max(0, min(sy, h - 1))
        sw = min(sw, w - sx)
        sh = min(sh, h - sy)
        if sw < 20 or sh < 20:
            return None
        roi = img[sy : sy + sh, sx : sx + sw]
        offset_x, offset_y = sx, sy
    else:
        roi = img
        offset_x, offset_y = 0, 0

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Find circles using HoughCircles
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=30,
        param1=50,
        param2=30,
        minRadius=10,
        maxRadius=30,
    )

    if circles is None:
        return None

    # Filter for bright white circles (the icon has a white background)
    best = None
    best_brightness = 0.0

    for c in circles[0]:
        x, y, r = int(c[0]), int(c[1]), int(c[2])
        # Measure brightness of the circle area
        mask = np.zeros(gray.shape[:2], dtype=np.uint8)
        cv2.circle(mask, (x, y), r, 255, -1)
        mean_val = cv2.mean(gray, mask=mask)[0]

        if mean_val > best_brightness and mean_val > 150:
            best_brightness = mean_val
            best = (x + offset_x, y + offset_y, r)

    return best


def detect_idle_vs_generating(
    img: np.ndarray,
    cx: int,
    cy: int,
    radius: int,
) -> str:
    """Detect whether the icon shows idle (waveform) or generating (stop square).

    Strategy: Scan horizontal lines through the circle center.
    - Waveform icon (idle): Multiple vertical black bars → many dark/light transitions
    - Stop icon (generating): One solid black rectangle → few transitions

    Args:
        img: BGR screenshot image.
        cx, cy: Circle center coordinates.
        radius: Circle radius.

    Returns:
        "idle" or "generating"
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Scan a horizontal band through the center of the circle
    # Use a few scanlines around the center for robustness
    inner_r = int(radius * 0.6)  # Stay well within the circle
    total_transitions = 0
    scanlines = 0

    for dy in range(-inner_r // 2, inner_r // 2 + 1):
        y = cy + dy
        x_start = cx - inner_r
        x_end = cx + inner_r

        if y < 0 or y >= gray.shape[0]:
            continue
        x_start = max(0, x_start)
        x_end = min(gray.shape[1], x_end)

        line = gray[y, x_start:x_end].astype(float)
        if len(line) < 4:
            continue

        # Count transitions between dark (<128) and light (>128)
        is_dark = line < 128
        transitions = np.sum(np.diff(is_dark.astype(int)) != 0)
        total_transitions += transitions
        scanlines += 1

    if scanlines == 0:
        return "unknown"

    avg_transitions = total_transitions / scanlines

    # Waveform icon has 4 vertical bars → ~8 transitions per scanline
    # Stop square has 1 block → ~2 transitions per scanline
    # Threshold at 4 transitions
    if avg_transitions >= 4:
        return "idle"
    else:
        return "generating"


def find_textbox(
    img: np.ndarray,
    icon_cx: int,
    icon_cy: int,
    icon_radius: int,
) -> dict:
    """Infer text input box location from the speech icon position.

    The icon is in the bottom-right of the text input area.
    The text input center is roughly to the left and slightly above the icon.

    Returns:
        dict with 'input_center', 'icon_center', 'icon_radius', 'icon_region'
    """
    # The text input extends to the left of the icon
    # Estimate the input center as being well to the left of the icon
    # and at roughly the same vertical position
    # The input box is typically ~60% of the Firefox window width
    # The icon is at the far right edge of the input

    # Text input center is approximately:
    # - Horizontally: midpoint between sidebar end and icon
    # - Vertically: slightly above the icon (the "Ask anything" line)
    input_x = icon_cx - 200  # rough estimate — the input text area is left of icon
    input_y = icon_cy - 20  # the text area is above the toolbar row

    return {
        "input_center": [input_x, input_y],
        "icon_center": [icon_cx, icon_cy],
        "icon_radius": icon_radius,
        "icon_region": [
            icon_cx - icon_radius - 2,
            icon_cy - icon_radius - 2,
            (icon_radius + 2) * 2,
            (icon_radius + 2) * 2,
        ],
    }


def find_new_chat_button(img: np.ndarray, firefox: dict) -> tuple[int, int] | None:
    """Find the 'New chat' button in the ChatGPT sidebar.

    It's typically in the top-left area of the ChatGPT UI, within the sidebar.
    Look for the pencil/compose icon or 'New chat' text.
    """
    # The new chat button is typically at the top of the sidebar
    # In the ChatGPT UI, it's a small icon in the upper-left
    # For now, estimate based on Firefox window position
    fx, fy = firefox["x"], firefox["y"]
    # The sidebar is roughly 260px wide, new chat button at top
    return (fx + 90, fy + 80)


def find_attach_button(
    img: np.ndarray,
    icon_cx: int,
    icon_cy: int,
) -> tuple[int, int]:
    """Find the attach/paperclip button ('+' button left of Extended thinking).

    It's on the toolbar row, far left side.
    """
    # The '+' button is in the bottom-left of the text input area
    # It's on the same row as the icon, but far to the left
    # Estimate: ~680px to the left of the speech icon
    return (icon_cx - 680, icon_cy)


def find_copy_button(
    img: np.ndarray,
    input_y: int | None = None,
    window_bounds: tuple[int, int, int, int] | None = None,
) -> tuple[int, int] | None:
    """Find the copy button on the last ChatGPT response.

    The response toolbar has 3 small icons (copy, refresh, more) arranged
    horizontally. The copy icon is the leftmost (~15x15px).

    Strategy:
      1. Scan bottom-up for rows containing multiple icon-sized bright clusters
      2. The bottom or top edge of the copy icon is a solid ~10px bright line
      3. Aggregate bright pixels across a window of rows to find icon groups
      4. Return the center of the leftmost group

    Args:
        img: Monitor screenshot.
        input_y: Y-coordinate of the text input area (in monitor-relative coords).
        window_bounds: (x, y, w, h) of the Firefox window in monitor-relative coords.
            Constrains search to the content area (past sidebar).

    Returns:
        (x, y) coordinates of the copy button center, or None.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    if window_bounds:
        wx, wy, ww, wh = window_bounds
        # Content area starts ~280px from left (past sidebar)
        search_left = max(0, wx + 280)
        search_right = min(w, wx + ww - 10)
        max_y = (input_y - 30) if input_y else min(h, wy + wh - 80)
        min_y = max(0, wy + 50)
    else:
        search_left = w // 8
        search_right = w * 3 // 4
        max_y = (input_y - 30) if input_y else int(h * 0.65)
        min_y = h // 8

    # Scan in windows of 18 rows (icon height), stepping by 4
    for window_top in range(max_y - 18, min_y, -4):
        window_bottom = window_top + 18

        # Collect all bright pixel x-positions across the window
        all_bright_x = set()
        for y in range(window_top, window_bottom):
            if y >= h:
                continue
            row = gray[y, search_left:search_right]
            bright = np.where(row > 140)[0] + search_left
            all_bright_x.update(bright.tolist())

        if len(all_bright_x) < 15:
            continue

        # Cluster the x-positions (gap > 8 separates icons)
        sorted_x = sorted(all_bright_x)
        clusters = []
        cluster = [sorted_x[0]]
        for x in sorted_x[1:]:
            if x - cluster[-1] <= 8:
                cluster.append(x)
            else:
                clusters.append(cluster)
                cluster = [x]
        clusters.append(cluster)

        # Filter for icon-sized clusters (8-30px wide)
        icon_clusters = [c for c in clusters if 8 <= (max(c) - min(c)) <= 30]

        # We need exactly 2-3 icon clusters (copy + retry + maybe more)
        if not (2 <= len(icon_clusters) <= 4):
            continue

        # Reject if there are large clusters (text labels, not icons)
        has_large = any((max(c) - min(c)) > 30 for c in clusters)
        if has_large:
            continue

        # Total bright pixels should be modest (icons are sparse)
        if len(all_bright_x) > 120:
            continue

        # The icon clusters should be roughly evenly spaced (20-40px apart)
        centers = [(min(c) + max(c)) // 2 for c in icon_clusters]
        if len(centers) >= 2:
            gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
            if any(g < 15 or g > 60 for g in gaps):
                continue

        # The copy button is the leftmost cluster
        copy_cluster = icon_clusters[0]
        cx = (min(copy_cluster) + max(copy_cluster)) // 2
        cy = (window_top + window_bottom) // 2

        return (int(cx), int(cy))

    return None


def auto_calibrate(monitor: str = "1") -> dict:
    """Fully automatic calibration — detect all UI elements.

    Takes a screenshot and finds:
      - Speech/stop icon (white circle)
      - Text input center
      - New chat button
      - Attach button
      - Copy button location (estimated)

    Args:
        monitor: Which monitor to screenshot ("1", "2", etc. or "primary").

    Returns:
        config dict compatible with the calibrate.save_config format,
        plus monitor offset for coordinate translation.
    """
    # Get Firefox window info
    firefox = actions.find_firefox()
    if firefox is None:
        raise RuntimeError("Firefox not found. Is it running?")

    # Get monitor info to determine offset
    monitors = actions.get_monitors()
    monitor_idx = int(monitor) - 1 if monitor.isdigit() else None
    if monitor_idx is not None and monitor_idx < len(monitors):
        mon = monitors[monitor_idx]
        mon_offset_x = mon["x"]
        mon_offset_y = mon["y"]
    else:
        mon_offset_x = 0
        mon_offset_y = 0

    # Take screenshot of the specific monitor
    img = actions.screenshot(monitor)

    # Search the right half of the monitor for the white circle
    # (Firefox size reporting may be inaccurate due to DPI scaling)
    h, w = img.shape[:2]
    circle = find_icon_circle(img, search_region=(w // 3, h // 3, w * 2 // 3, h * 2 // 3))

    if circle is None:
        # Fallback: search the full image
        circle = find_icon_circle(img)

    if circle is None:
        raise RuntimeError(
            "Could not find the speech icon (white circle). "
            "Make sure ChatGPT is loaded with an idle chat."
        )

    # Firefox position relative to this monitor (for other element estimation)
    ff_rel_x = firefox["x"] - mon_offset_x
    ff_rel_y = firefox["y"] - mon_offset_y

    cx, cy, r = circle

    # Detect current state
    state = detect_idle_vs_generating(img, cx, cy, r)

    # Find text input location
    textbox = find_textbox(img, cx, cy, r)

    # Estimate other elements
    new_chat = find_new_chat_button(
        img,
        {
            "x": ff_rel_x,
            "y": ff_rel_y,
            "w": firefox["w"],
            "h": firefox["h"],
        },
    )
    attach = find_attach_button(img, cx, cy)

    # Convert from monitor-relative to absolute Windows coordinates
    config = {
        "monitor": monitor,
        "monitor_offset": [mon_offset_x, mon_offset_y],
        "firefox": {
            "x": firefox["x"],
            "y": firefox["y"],
            "w": firefox["w"],
            "h": firefox["h"],
        },
        "icon_center": [cx + mon_offset_x, cy + mon_offset_y],
        "icon_radius": r,
        "icon_region": [
            cx - r - 2 + mon_offset_x,
            cy - r - 2 + mon_offset_y,
            (r + 2) * 2,
            (r + 2) * 2,
        ],
        "input_center": [
            textbox["input_center"][0] + mon_offset_x,
            textbox["input_center"][1] + mon_offset_y,
        ],
        "new_chat": [
            new_chat[0] + mon_offset_x,
            new_chat[1] + mon_offset_y,
        ]
        if new_chat
        else None,
        "attach_button": [
            attach[0] + mon_offset_x,
            attach[1] + mon_offset_y,
        ],
        "copy_button": [
            cx + mon_offset_x,
            cy + mon_offset_y + 200,  # rough estimate — below the input area
        ],
        "current_state": state,
    }

    return config


def detect_is_idle(config: dict) -> tuple[bool, float]:
    """Check if ChatGPT is idle using auto-detection.

    Returns:
        (is_idle, confidence) tuple.
    """
    mon = config.get("monitor", "1")
    mon_ox, mon_oy = config.get("monitor_offset", [0, 0])

    img = actions.screenshot(mon)

    # Get the icon center in monitor-relative coords
    abs_cx, abs_cy = config["icon_center"]
    cx = abs_cx - mon_ox
    cy = abs_cy - mon_oy
    r = config["icon_radius"]

    # First, verify the circle is still there (it may have shifted)
    search_margin = 50
    search_region = (
        max(0, cx - r - search_margin),
        max(0, cy - r - search_margin),
        (r + search_margin) * 2,
        (r + search_margin) * 2,
    )

    circle = find_icon_circle(img, search_region=search_region)

    if circle is None:
        # Circle not found in expected area — search wider
        h, w = img.shape[:2]
        wider_region = (
            max(0, w // 3),
            max(0, h // 3),
            w * 2 // 3,
            h * 2 // 3,
        )
        circle = find_icon_circle(img, search_region=wider_region)

    if circle is None:
        # Last resort: search the full image
        circle = find_icon_circle(img)

    if circle is None:
        # Can't find the icon at all — might be in a different UI state
        return False, 0.0

    found_cx, found_cy, found_r = circle

    # Update config with new position if shifted
    config["icon_center"] = [found_cx + mon_ox, found_cy + mon_oy]
    config["icon_radius"] = found_r

    # Detect state
    state = detect_idle_vs_generating(img, found_cx, found_cy, found_r)

    is_idle = state == "idle"
    # Confidence is binary for now — could be refined
    confidence = 1.0 if state in ("idle", "generating") else 0.0

    return is_idle, confidence
