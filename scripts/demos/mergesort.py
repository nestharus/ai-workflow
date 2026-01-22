import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np

# --- Configuration ---
N = 32
INTERVAL = 20
Y_SPACING = 300.0
TRAVEL_FRAMES = 40
BUILD_FRAMES = 15
PAUSE_DURATION = 0.5
PAUSE_FRAMES = int(PAUSE_DURATION * 1000 / INTERVAL)

# Visuals - Large Scale
WAVE_WIDTH = 25.0
LINE_WIDTH = 6.0
UNIT_H = 14.0
CURSOR_SIZE = 6

# --- Helper Functions ---


def get_alignment_signal(arr):
    if len(arr) <= 1:
        return np.array([0.0])
    signal = []
    for k in range(len(arr) - 1):
        val = 1.0 if arr[k] <= arr[k + 1] else -1.0
        signal.append(val)
    signal.append(signal[-1])
    return np.array(signal)


def interpolate_arrays(arr_start, arr_end, t):
    return arr_start * (1 - t) + arr_end * t


def build_layout(n):
    # Validate that n is a positive power of 2
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if (n & (n - 1)) != 0:
        raise ValueError(f"n must be a power of 2, got {n}")

    max_depth = int(np.log2(n))
    levels = []
    total_width = 1400.0  # Wide layout

    for depth in range(max_depth + 1):
        num_nodes = 2**depth
        nodes = []
        slot_width = total_width / num_nodes

        for i in range(num_nodes):
            cx = (i * slot_width) + (slot_width / 2) - (total_width / 2)
            cy = -(depth * Y_SPACING)
            pidx = i // 2 if depth > 0 else None
            nodes.append({"cx": cx, "cy": cy, "parent_idx": pidx})
        levels.append(nodes)
    return levels


# --- Animation Generator ---


def scanner_sorter_gen(source_data):
    unsorted_tree = []
    curr = [source_data.copy()]
    unsorted_tree.append(curr)
    while len(curr[0]) > 1:
        next_lvl = []
        for chunk in curr:
            mid = len(chunk) // 2
            next_lvl.append(chunk[:mid])
            next_lvl.append(chunk[mid:])
        unsorted_tree.append(next_lvl)
        curr = next_lvl

    max_depth = len(unsorted_tree) - 1
    tree_data = [[[] for _ in range(len(unsorted_tree[d]))] for d in range(max_depth + 1)]
    tree_data[0] = [list(source_data)]

    # --- PHASE 1: DIVIDE ---
    for d in range(max_depth):
        parents = tree_data[d]
        children_snapshot = unsorted_tree[d + 1]

        sig_data = []
        child_idx = 0
        for chunk in parents:
            if not chunk:
                sig_data.append((None, None, None, None))
                child_idx += 2
                continue
            mid = len(chunk) // 2
            p_sig = get_alignment_signal(chunk)
            s_l, s_r = p_sig[:mid], p_sig[mid:]
            l_data, r_data = children_snapshot[child_idx], children_snapshot[child_idx + 1]
            e_l, e_r = get_alignment_signal(l_data), get_alignment_signal(r_data)
            sig_data.append((s_l, s_r, e_l, e_r))
            child_idx += 2

        for t in range(1, TRAVEL_FRAMES + 1):
            progress = t / TRAVEL_FRAMES
            yield "divide", d, progress, tree_data, children_snapshot, sig_data

        tree_data[d] = [[] for _ in range(len(parents))]
        tree_data[d + 1] = [list(c) for c in children_snapshot]

        for _ in range(PAUSE_FRAMES):
            yield "lock_pause", d + 1, 0, tree_data, None, None

    # --- PHASE 2: ROTATE ---
    for t in range(1, 30):
        progress = t / 30.0
        yield "rotate", max_depth, progress, tree_data, None, None

    # --- PHASE 3: MERGE ---
    for d in range(max_depth, 0, -1):
        parent_depth = d - 1
        num_pairs = len(tree_data[d]) // 2

        puzzles = [{"L_hist": [], "R_hist": []} for _ in range(num_pairs)]
        cursors = [[0.0, 0.0] for _ in range(num_pairs)]

        while True:
            remaining = False
            moves = []

            step_active = False
            for p_idx in range(num_pairs):
                l_idx, r_idx = p_idx * 2, p_idx * 2 + 1
                L, R = tree_data[d][l_idx], tree_data[d][r_idx]

                cL = int(cursors[p_idx][0])
                cR = int(cursors[p_idx][1])

                if cL >= len(L) and cR >= len(R):
                    moves.append(None)
                    continue

                step_active = True
                remaining = True

                winner_side = None
                if cL < len(L) and cR < len(R):
                    if L[cL] <= R[cR]:
                        winner_side = 0
                    else:
                        winner_side = 1
                elif cL < len(L):
                    winner_side = 0
                elif cR < len(R):
                    winner_side = 1

                moves.append(winner_side)

            if not step_active:
                break

            # Interpolate Move
            for f in range(BUILD_FRAMES + 1):
                interp = f / float(BUILD_FRAMES)
                frame_cursors = [list(c) for c in cursors]
                move_states = []

                for p_idx, side in enumerate(moves):
                    if side is None:
                        move_states.append(None)
                        continue
                    if side == 0:
                        frame_cursors[p_idx][0] += interp
                        move_states.append(0)
                    else:
                        frame_cursors[p_idx][1] += interp
                        move_states.append(1)

                yield "build", d, interp, tree_data, puzzles, (frame_cursors, move_states)

            # Commit Move
            for p_idx, side in enumerate(moves):
                if side is None:
                    continue
                if side == 0:
                    cursors[p_idx][0] += 1.0
                    puzzles[p_idx]["L_hist"].append(1.0)
                    puzzles[p_idx]["R_hist"].append(-1.0)
                else:
                    cursors[p_idx][1] += 1.0
                    puzzles[p_idx]["R_hist"].append(1.0)
                    puzzles[p_idx]["L_hist"].append(-1.0)

        # SNAP & PAN
        for t in range(1, TRAVEL_FRAMES + 1):
            progress = t / TRAVEL_FRAMES
            yield "snap_pan", d, progress, tree_data, puzzles, cursors

        for _ in range(PAUSE_FRAMES):
            yield "snap_pan", d, 1.0, tree_data, puzzles, cursors

        # Commit Data
        for p_idx, p in enumerate(puzzles):
            l_idx, r_idx = p_idx * 2, p_idx * 2 + 1
            L, R = tree_data[d][l_idx], tree_data[d][r_idx]
            # Reconstruct merged_vals by replaying the puzzle's merge history
            l_pos, r_pos = 0, 0
            merged_vals = []
            for side in p["L_hist"]:  # 1.0 means take from L, -1.0 means take from R
                if side > 0:
                    merged_vals.append(L[l_pos])
                    l_pos += 1
                else:
                    merged_vals.append(R[r_pos])
                    r_pos += 1
            tree_data[parent_depth][p_idx] = merged_vals

    yield "done", 0, 0, tree_data, None, None


# --- Plotting Functions ---


def plot_horz_interpolated(ax, cx, cy, data, camera_y, start_sig, end_sig, progress):
    if not data:
        return
    if len(data) == 1:
        w = UNIT_H
        ax.plot(
            [cx - w / 2, cx + w / 2],
            [cy - camera_y, cy - camera_y],
            color="red",
            linewidth=LINE_WIDTH,
        )
        return
    if start_sig is None:
        start_sig = get_alignment_signal(data)
    if end_sig is None:
        end_sig = get_alignment_signal(data)

    current_sig = interpolate_arrays(start_sig, end_sig, progress)
    total_w = len(data) * UNIT_H
    x_rel = np.linspace(-total_w / 2, total_w / 2, len(data))
    y_rel = current_sig * (WAVE_WIDTH / 2.0)
    ax.plot(cx + x_rel, (cy - camera_y) + y_rel, color="red", linewidth=LINE_WIDTH)


def plot_horz_signal(ax, cx, cy, data, camera_y):
    plot_horz_interpolated(ax, cx, cy, data, camera_y, None, None, 0)


def plot_rotated_signal(ax, cx, cy, data, angle, camera_y):
    if not data:
        return
    if len(data) == 1:
        w = UNIT_H
        x_rel = np.array([-w / 2, w / 2])
        y_rel = np.array([0, 0])
    else:
        sig = get_alignment_signal(data)
        total_len = len(data) * UNIT_H
        x_rel = np.linspace(-total_len / 2, total_len / 2, len(data))
        y_rel = sig * (WAVE_WIDTH / 2.0)

    theta = np.radians(angle)
    c, s = np.cos(theta), np.sin(theta)
    rx = x_rel * c - y_rel * s
    ry = x_rel * s + y_rel * c
    ax.plot(cx + rx, (cy - camera_y) + ry, color="red", linewidth=LINE_WIDTH)


def draw_segment(ax, cx, y_top, y_bot):
    """Draw a single vertical line segment."""
    ax.plot([cx, cx], [y_bot, y_top], color="red", linewidth=LINE_WIDTH, solid_capstyle="butt")


def draw_cursor(ax, cx, y):
    """Draw cursor marker at position."""
    ax.plot(cx, y, marker="o", color="white", markersize=CURSOR_SIZE, zorder=10)


def plot_scanner_active(
    ax, cx, cy, source_data, history_data, cursor_val, is_moving, anim_progress, camera_y
):
    """Renders a scanner with items passing through a gate.

    Model:
    - The gate is anchored at the node center
    - History (consumed items/gaps) grows ABOVE the gate
    - Source (remaining items) is BELOW the gate
    - During animation: active item slides up, inactive side's source slides down

    Args:
        source_data: Original array of items for this side
        history_data: List of 1.0 (drew item) or -1.0 (gap) for each comparison
        cursor_val: Float, number of items consumed from this side (may have fraction during animation)
        is_moving: True if this side is currently animating
        anim_progress: 0-1 progress of current comparison (shared between both sides)
    """
    if not source_data:
        return

    n_items = len(source_data)
    n_comparisons = len(history_data)

    # Gate is anchored at node center, moves down as comparisons happen
    node_y = cy - camera_y
    gate_y = node_y - (n_comparisons + anim_progress) * UNIT_H

    # Calculate items remaining using BASE cursor (not animated value)
    # During animation, cursor_val = base + anim_progress
    # We need base to know how many items are truly consumed vs being animated
    if is_moving:
        base_cursor = round(cursor_val - anim_progress)  # Items already consumed
        items_remaining = n_items - base_cursor
    else:
        items_remaining = n_items - int(cursor_val)

    # --- 1. Draw History (above gate) ---
    # Each history entry occupies one slot starting from node_y going down
    for i, val in enumerate(history_data):
        slot_top = node_y - i * UNIT_H
        slot_bot = slot_top - UNIT_H
        if val == 1.0:
            draw_segment(ax, cx, slot_top, slot_bot)

    if is_moving and items_remaining > 0:
        # Active side: draw "passed" portion above cursor to match gap on inactive side
        # The passed portion grows from 0 to UNIT_H as cursor moves through the item
        slot_top = node_y - n_comparisons * UNIT_H  # Top of current slot
        passed_height = anim_progress * UNIT_H  # How much cursor has passed

        # Draw passed portion (above cursor) - this matches the gap size
        if passed_height > 0:
            draw_segment(ax, cx, slot_top, slot_top - passed_height)

        # Draw remaining source starting at cursor
        # Total remaining = items_remaining items, but we've drawn passed_height already
        # So draw from cursor down for: (items_remaining * UNIT_H - passed_height)
        remaining_height = items_remaining * UNIT_H - passed_height
        if remaining_height > 0:
            draw_segment(ax, cx, gate_y, gate_y - remaining_height)
    else:
        # Inactive side: source starts at cursor (gate_y)
        # As cursor moves down, gap gradually appears above cursor
        # Source stays connected to cursor, gap grows between history and source
        if items_remaining > 0:
            src_top = gate_y
            src_bot = src_top - items_remaining * UNIT_H
            draw_segment(ax, cx, src_top, src_bot)

    # --- 3. Draw Cursor at gate ---
    if items_remaining > 0:
        draw_cursor(ax, cx, gate_y)


# --- Main Logic ---

data = np.random.randint(0, 100, N)
layout = build_layout(N)
max_d = len(layout) - 1

# Window Size Large
fig, ax = plt.subplots(figsize=(16, 12))
ax.set_facecolor("black")
fig.patch.set_facecolor("black")
ax.set_axis_off()

VIEW_H = 900
# Zoomed Out Camera Limits
ax.set_xlim(-800, 800)
ax.set_ylim(-VIEW_H / 2, VIEW_H / 2)

sorter_gen = scanner_sorter_gen(data)


def update(frame_data):
    ax.clear()
    ax.set_axis_off()
    ax.set_xlim(-800, 800)
    ax.set_ylim(-VIEW_H / 2, VIEW_H / 2)

    phase = frame_data[0]
    d_active = frame_data[1]
    progress = frame_data[2]

    camera_y = 0

    if phase == "divide":
        y_curr = layout[d_active][0]["cy"]
        y_next = layout[d_active + 1][0]["cy"]
        camera_y = y_curr + (y_next - y_curr) * progress
    elif phase == "lock_pause":
        camera_y = layout[d_active][0]["cy"]
    elif phase == "rotate":
        camera_y = layout[max_d][0]["cy"]
    elif phase == "build":
        camera_y = layout[d_active][0]["cy"]
    elif phase == "snap_pan":
        y_child = layout[d_active][0]["cy"]
        y_parent = layout[d_active - 1][0]["cy"]
        camera_y = y_child + (y_parent - y_child) * progress
    elif phase == "done":
        camera_y = layout[0][0]["cy"]

    # Background - bright white tree structure
    for d in range(1, max_d + 1):
        for node in layout[d]:
            p_node = layout[d - 1][node["parent_idx"]]
            py = p_node["cy"] - camera_y
            cy = node["cy"] - camera_y
            if abs(py) < 800 or abs(cy) < 800:
                ax.plot(
                    [p_node["cx"], node["cx"]], [py, cy], color="white", linewidth=1.5, zorder=0
                )

    # Data
    if phase == "divide":
        tree_data = frame_data[3]
        sig_data = frame_data[5]
        for d in range(d_active):
            for i, chunk in enumerate(tree_data[d]):
                node = layout[d][i]
                plot_horz_signal(ax, node["cx"], node["cy"], chunk, camera_y)
        parents = tree_data[d_active]
        child_counter = 0
        for p_idx, chunk in enumerate(parents):
            if not chunk:
                continue
            p_node = layout[d_active][p_idx]
            mid = len(chunk) // 2

            parent_w = len(chunk) * UNIT_H
            l_w = len(chunk[:mid]) * UNIT_H
            r_w = len(chunk[mid:]) * UNIT_H

            l_start_cx = p_node["cx"] - (parent_w / 2) + (l_w / 2)
            r_start_cx = p_node["cx"] + (parent_w / 2) - (r_w / 2)
            l_target = layout[d_active + 1][child_counter]
            r_target = layout[d_active + 1][child_counter + 1]

            lx = l_start_cx + (l_target["cx"] - l_start_cx) * progress
            ly = p_node["cy"] + (l_target["cy"] - p_node["cy"]) * progress
            rx = r_start_cx + (r_target["cx"] - r_start_cx) * progress
            ry = p_node["cy"] + (r_target["cy"] - p_node["cy"]) * progress

            sl, sr, el, er = sig_data[p_idx]
            plot_horz_interpolated(ax, lx, ly, chunk[:mid], camera_y, sl, el, progress)
            plot_horz_interpolated(ax, rx, ry, chunk[mid:], camera_y, sr, er, progress)
            child_counter += 2

    elif phase == "lock_pause":
        tree_data = frame_data[3]
        for d in range(len(tree_data)):
            for i, chunk in enumerate(tree_data[d]):
                node = layout[d][i]
                plot_horz_signal(ax, node["cx"], node["cy"], chunk, camera_y)

    elif phase == "rotate":
        _, d, progress, tree_data, _, _ = frame_data
        angle = -90 * progress
        for i, chunk in enumerate(tree_data[d]):
            node = layout[d][i]
            plot_rotated_signal(ax, node["cx"], node["cy"], chunk, angle, camera_y)

    elif phase == "build":
        _, d, anim_progress, tree_data, puzzles, state_tuple = frame_data
        cursors, moves = state_tuple

        for p_idx, p in enumerate(puzzles):
            l_idx, r_idx = p_idx * 2, p_idx * 2 + 1
            l_node = layout[d][l_idx]
            r_node = layout[d][r_idx]

            c_l, c_r = cursors[p_idx]
            move_side = moves[p_idx] if moves else None

            plot_scanner_active(
                ax,
                l_node["cx"],
                l_node["cy"],
                tree_data[d][l_idx],
                p["L_hist"],
                c_l,
                move_side == 0,
                anim_progress,
                camera_y,
            )
            plot_scanner_active(
                ax,
                r_node["cx"],
                r_node["cy"],
                tree_data[d][r_idx],
                p["R_hist"],
                c_r,
                move_side == 1,
                anim_progress,
                camera_y,
            )

    elif phase == "snap_pan":
        _, d, progress, tree_data, puzzles, cursors = frame_data

        for p_idx, p in enumerate(puzzles):
            l_idx, r_idx = p_idx * 2, p_idx * 2 + 1
            l_node = layout[d][l_idx]
            r_node = layout[d][r_idx]
            p_node = layout[d - 1][p_idx]

            cur_lx = l_node["cx"] + (p_node["cx"] - l_node["cx"]) * progress
            cur_ly = l_node["cy"] + (p_node["cy"] - l_node["cy"]) * progress
            cur_rx = r_node["cx"] + (p_node["cx"] - r_node["cx"]) * progress
            cur_ry = r_node["cy"] + (p_node["cy"] - r_node["cy"]) * progress

            c_l, c_r = (
                cursors[p_idx] if cursors else [len(tree_data[d][l_idx]), len(tree_data[d][r_idx])]
            )

            plot_scanner_active(
                ax, cur_lx, cur_ly, tree_data[d][l_idx], p["L_hist"], c_l, False, 0.0, camera_y
            )
            plot_scanner_active(
                ax, cur_rx, cur_ry, tree_data[d][r_idx], p["R_hist"], c_r, False, 0.0, camera_y
            )

    elif phase == "done":
        tree_data = frame_data[3]
        final = tree_data[0][0]
        root = layout[0][0]
        final_hist = [1.0] * len(final)
        plot_scanner_active(
            ax, root["cx"], root["cy"], final, final_hist, len(final), False, 0.0, camera_y
        )
        ax.set_title("SORTED", color="#00ff00", fontsize=20, y=0.85)


ani = animation.FuncAnimation(
    fig, update, frames=sorter_gen, blit=False, interval=INTERVAL, repeat=False
)
ani.save("sort_merge.gif", writer="pillow", fps=30)
# plt.show()
