import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon

# --- Configuration ---
N = 80  # Number of data points
INTERVAL = 10  # Frame delay in ms (Very fast refresh)
STEPS_PER_FRAME = 5  # Speed multiplier (Processes 5 indexes per frame)
ARC_HEIGHT = 4.0
ARC_CURVATURE = 0.3

# --- Helper Functions ---


def bubble_sort_generator(arr, steps_per_frame=1):
    l = len(arr)
    for i in range(l - 1):
        is_new_pass_start = True

        # We iterate through the array, but we only yield every 'steps_per_frame'
        j = 0
        while j < (l - i - 1):
            # Process a batch of steps to speed up animation
            # We process 'steps_per_frame' moves, or until we hit the end of the pass
            batch_limit = min(j + steps_per_frame, l - i - 1)

            current_cursor = j

            # Execute the batch of swaps silently
            for k in range(j, batch_limit):
                if arr[k] > arr[k + 1]:
                    arr[k], arr[k + 1] = arr[k + 1], arr[k]
                current_cursor = k

            # Yield the state after the batch is done
            # We force a yield if it's the start of a pass (to show the cannon fire)
            yield arr.copy(), current_cursor, l - i - 1, is_new_pass_start

            is_new_pass_start = False
            j = batch_limit  # Jump forward

    yield arr.copy(), -1, 0, False


def get_alignment_signal(arr):
    signal = []
    for k in range(len(arr) - 1):
        val = -1.0 if arr[k] > arr[k + 1] else 1.0
        signal.append(val)
    signal.append(1.0)
    return np.array(signal)


# --- Setup Data & Plotting ---

data = np.random.rand(N)
x_domain = np.arange(N)

fig, ax = plt.subplots(figsize=(12, 6))
ax.set_facecolor("#f0f0f0")
ax.set_ylim(-4, 4)
ax.set_xlim(-10, N)
ax.set_title("Bubble Sort: High Speed Denoising")
ax.set_yticks([-1, 1])
ax.set_yticklabels(["Misaligned (-1)", "Aligned (1)"])
ax.set_xticks([])

# --- Graphics Elements ---

# 1. The Cannon
cannon_shape = np.array([[-6, -0.7], [0, -0.3], [0, 0.3], [-6, 0.7], [-7, 0]])
cannon_rest_pos = cannon_shape + [-2, 0]
cannon_recoil_pos = cannon_shape + [-4, 0]
cannon_patch = Polygon(cannon_rest_pos, closed=True, color="#555555", ec="black", zorder=10)
ax.add_patch(cannon_patch)

# 2. The Alignment Line
(line_signal,) = ax.plot([], [], color="#222222", linewidth=1.5, alpha=0.8, zorder=5)

# 3. The Arc Pulse
(wave_line,) = ax.plot([], [], color="#00FFFF", linewidth=3, alpha=0.9, zorder=20)
wave_poly = Polygon(np.zeros((3, 2)), closed=True, color="#00FFFF", alpha=0.15, zorder=19)
ax.add_patch(wave_poly)

y_arc = np.linspace(-ARC_HEIGHT, ARC_HEIGHT, 50)

# Global state
cannon_state = {"firing_frames_left": 0}

# Initialize generator with speed multiplier
sorter_gen = bubble_sort_generator(data.copy(), steps_per_frame=STEPS_PER_FRAME)


def init():
    line_signal.set_data([], [])
    wave_line.set_data([], [])
    wave_poly.set_xy(np.zeros((3, 2)))
    cannon_patch.set_xy(cannon_rest_pos)
    return line_signal, wave_line, wave_poly, cannon_patch


def update(frame_data):
    arr, cursor, sorted_boundary, is_new_pass_start = frame_data
    global cannon_state

    # 1. Cannon Logic
    if is_new_pass_start:
        cannon_state["firing_frames_left"] = 3  # Reduced flash time for faster speed

    if cannon_state["firing_frames_left"] > 0:
        cannon_patch.set_xy(cannon_recoil_pos)
        cannon_patch.set_facecolor("#FF4500")
        cannon_state["firing_frames_left"] -= 1
    else:
        cannon_patch.set_xy(cannon_rest_pos)
        cannon_patch.set_facecolor("#555555")

    # 2. Data Line Logic
    y_signal = get_alignment_signal(arr)
    mask = x_domain < sorted_boundary

    y_display_signal = np.interp(np.arange(0, N, 0.5), x_domain[mask], y_signal[mask])
    x_display_signal = np.arange(0, N, 0.5)

    if sorted_boundary < N:
        x_flat = np.arange(sorted_boundary, N)
        y_flat = np.ones_like(x_flat)
        x_final = np.concatenate([x_display_signal, x_flat])
        y_final = np.concatenate([y_display_signal, y_flat])
    else:
        x_final = x_display_signal
        y_final = y_display_signal

    line_signal.set_data(x_final, y_final)

    # 3. Arc Pulse Logic
    if cursor >= 0:
        x_arc = cursor - (ARC_CURVATURE * y_arc**2)
        wave_line.set_data(x_arc, y_arc)

        verts = np.column_stack([x_arc, y_arc])
        wave_poly.set_xy(verts)
        wave_poly.set_alpha(0.15)
    else:
        wave_line.set_data([], [])
        wave_poly.set_alpha(0)

    return line_signal, wave_line, wave_poly, cannon_patch


ani = animation.FuncAnimation(
    fig, update, frames=sorter_gen, init_func=init, blit=False, interval=INTERVAL, repeat=False
)

print("Starting High-Speed Animation...")
ani.save("sort_bubble.gif", writer="pillow", fps=30)
# plt.show()
