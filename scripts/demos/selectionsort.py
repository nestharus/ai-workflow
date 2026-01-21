import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Polygon

# --- Configuration ---
N = 60  # Number of data points
INTERVAL = 20  # Frame delay in ms
STEPS_PER_FRAME = 3  # Speed multiplier
Y_LIMIT = 4

# --- Helper Functions ---


def bidirectional_selection_sort_generator(arr, steps_per_frame=1):
    n = len(arr)
    left = 0
    right = n - 1

    while left < right:
        min_idx = left
        max_idx = left  # Initialize both to left to start safe

        # Yield start of pass
        yield arr.copy(), left, right, min_idx, max_idx, left, "start"

        # Scan the unsorted range [left, right]
        for j in range(left, right + 1):
            if arr[j] < arr[min_idx]:
                min_idx = j
            if arr[j] > arr[max_idx]:
                max_idx = j

            # Yield scanning progress
            if (j - left) % steps_per_frame == 0:
                yield arr.copy(), left, right, min_idx, max_idx, j, "scan"

        # Final yield before swaps (scan complete)
        yield arr.copy(), left, right, min_idx, max_idx, right, "found"

        # Swap Min to Left
        arr[left], arr[min_idx] = arr[min_idx], arr[left]

        # Critical: If max was at 'left', it just got swapped to 'min_idx'
        if max_idx == left:
            max_idx = min_idx

        # Swap Max to Right
        arr[right], arr[max_idx] = arr[max_idx], arr[right]

        yield arr.copy(), left, right, min_idx, max_idx, right, "swap"

        left += 1
        right -= 1

    yield arr.copy(), -1, -1, -1, -1, -1, "done"


def get_alignment_signal(arr):
    signal = []
    for k in range(len(arr) - 1):
        diff = arr[k + 1] - arr[k]
        val = 1.0 if diff >= 0 else -1.0
        signal.append(val)
    signal.append(1.0)
    return np.array(signal)


# --- Setup Data & Plotting ---

data = np.random.rand(N)
x_domain = np.arange(N)

fig, ax = plt.subplots(figsize=(12, 6))
ax.set_facecolor("#f0f0f0")
ax.set_ylim(-Y_LIMIT, Y_LIMIT)
ax.set_xlim(-5, N + 5)
ax.set_title("Double Selection Sort: Bidirectional Scan")
ax.set_yticks([])
ax.set_xticks([])

# --- Graphics Elements ---

# 1. The Alignment Line
(line_signal,) = ax.plot([], [], color="#222222", linewidth=1.5, alpha=0.8, zorder=5)

# 2. Boundary Markers (Left and Right insertion points)
left_arrow = Polygon([[-0.5, 2], [0.5, 2], [0, 1.0]], closed=True, color="#00AA00", zorder=10)
right_arrow = Polygon([[-0.5, 2], [0.5, 2], [0, 1.0]], closed=True, color="#0000AA", zorder=10)
ax.add_patch(left_arrow)
ax.add_patch(right_arrow)

# 3. Min/Max Found Markers
min_marker = Circle((0, 0), 0.4, color="#FF4500", zorder=11)  # Orange for min
max_marker = Circle((0, 0), 0.4, color="#8A2BE2", zorder=11)  # Violet for max
ax.add_patch(min_marker)
ax.add_patch(max_marker)

# 4. Scanner Line
scanner_line = ax.vlines([], [], [], color="blue", alpha=0.3, linewidth=2, zorder=4)

# Global state
sorter_gen = bidirectional_selection_sort_generator(data.copy(), steps_per_frame=STEPS_PER_FRAME)


def init():
    line_signal.set_data([], [])
    left_arrow.set_xy([[-0.5, 2], [0.5, 2], [0, 1.0]])
    right_arrow.set_xy([[-0.5, 2], [0.5, 2], [0, 1.0]])
    min_marker.center = (-10, -10)
    max_marker.center = (-10, -10)
    return line_signal, left_arrow, right_arrow, min_marker, max_marker


def update(frame_data):
    arr, left, right, min_idx, max_idx, scan_j, state = frame_data

    # 1. Update Signal
    y_signal = get_alignment_signal(arr)
    line_signal.set_data(x_domain, y_signal)

    if state == "done":
        left_arrow.set_alpha(0)
        right_arrow.set_alpha(0)
        min_marker.set_alpha(0)
        max_marker.set_alpha(0)
        scanner_line.set_segments([])
        ax.set_title("Double Selection Sort: Complete", color="green")
        return line_signal, left_arrow, right_arrow, min_marker, max_marker, scanner_line

    # 2. Update Boundary Arrows
    # Left arrow at top (y=2 -> y=1)
    left_pos = np.array([[-0.5, 2], [0.5, 2], [0, 1.0]]) + [left, 0]
    left_arrow.set_xy(left_pos)

    # Right arrow at top (y=2 -> y=1)
    right_pos = np.array([[-0.5, 2], [0.5, 2], [0, 1.0]]) + [right, 0]
    right_arrow.set_xy(right_pos)

    # 3. Update Min/Max Markers
    # Show them at min_idx/max_idx.
    # Position them below the signal to avoid clutter
    if min_idx >= 0:
        min_marker.center = (min_idx, -1.5)
    if max_idx >= 0:
        max_marker.center = (max_idx, -1.5)

    # 4. Update Scanner
    if scan_j >= 0:
        scanner_line.set_segments([[[scan_j, -2], [scan_j, 2]]])
    else:
        scanner_line.set_segments([])

    # 5. Swap Flash Logic
    if state == "swap":
        min_marker.set_facecolor("#FFFF00")  # Yellow flash
        max_marker.set_facecolor("#FFFF00")
    else:
        min_marker.set_facecolor("#FF4500")  # Reset to Orange
        max_marker.set_facecolor("#8A2BE2")  # Reset to Violet

    return line_signal, left_arrow, right_arrow, min_marker, max_marker, scanner_line


ani = animation.FuncAnimation(
    fig, update, frames=sorter_gen, init_func=init, blit=False, interval=INTERVAL, repeat=False
)

print("Starting Double Selection Sort Animation...")
plt.show()
# ani.save('sort_selection.gif', writer='pillow', fps=30)
