import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Polygon, Rectangle, Circle
import bisect

# --- Configuration ---
N = 100
INTERVAL = 15
STEPS_PER_FRAME = 4

# --- Helper Functions ---

def scale_cannon_generator(source_data, speed=1):
    """
    Single scale spans both boundaries. Pans rigged to cannons.
    Heavier side tilts -> element flies up into cannon -> fires.
    """
    n = len(source_data)
    sorted_buffer = []

    mid = n // 2
    left_pool = list(source_data[:mid])
    right_pool = list(source_data[mid:])

    # Track which element is staged on each pan
    left_staged = None
    right_staged = None

    while left_pool or right_pool:
        # Calculate boundaries based on actual positions
        # Left boundary: first index of ordered zone
        # Right boundary: last index of ordered zone
        left_bound = len(left_pool)
        right_bound = len(left_pool) + len(sorted_buffer) - 1

        full_array = np.concatenate([
            left_pool if left_pool else [],
            sorted_buffer if sorted_buffer else [],
            right_pool if right_pool else []
        ])
        if len(full_array) == 0:
            full_array = np.array([])

        # Stage elements onto pans if not already staged
        need_left_load = left_staged is None and left_pool
        need_right_load = right_staged is None and right_pool

        # Loading phase - slide elements onto pans
        if need_left_load or need_right_load:
            if need_left_load:
                left_staged = left_pool[-1]
            if need_right_load:
                right_staged = right_pool[0]

            for frame in range(2):
                load_progress = (frame + 1) / 2
                yield (full_array.copy(), left_bound, right_bound,
                       left_staged, right_staged,
                       None, 'loading', -1, None, load_progress,
                       need_left_load, need_right_load)

        # Staging - both elements on pans, comparing
        for _ in range(2):
            yield (full_array.copy(), left_bound, right_bound,
                   left_staged, right_staged,
                   None, 'staging', -1, None, 0, False, False)

        # Determine heavier side
        if left_staged is not None and right_staged is not None:
            tilt_side = 'left' if left_staged > right_staged else 'right'
        elif left_staged is not None:
            tilt_side = 'left'
        else:
            tilt_side = 'right'

        # Tilting phase
        for frame in range(3):
            tilt_progress = (frame + 1) / 3
            yield (full_array.copy(), left_bound, right_bound,
                   left_staged, right_staged,
                   tilt_side, 'tilting', -1, None, tilt_progress, False, False)

        # Launch phase
        for frame in range(2):
            launch_progress = (frame + 1) / 2
            yield (full_array.copy(), left_bound, right_bound,
                   left_staged, right_staged,
                   tilt_side, 'launching', -1, None, launch_progress, False, False)

        # Remove from pool and clear staged
        if tilt_side == 'left':
            firing_val = left_pool.pop()
            left_staged = None
            firing_side = 'left'
        else:
            firing_val = right_pool.pop(0)
            right_staged = None
            firing_side = 'right'

        target_idx = bisect.bisect_left(sorted_buffer, firing_val)

        # Recalculate boundaries after removal
        left_bound = len(left_pool)
        right_bound = len(left_pool) + len(sorted_buffer) - 1

        # Firing phase
        for _ in range(2):
            temp_buffer = sorted_buffer.copy()
            if firing_side == 'left':
                temp_buffer.insert(0, firing_val)
                element_pos = left_bound
            else:
                temp_buffer.append(firing_val)
                element_pos = left_bound + len(temp_buffer) - 1

            full_array = np.concatenate([
                left_pool if left_pool else [],
                temp_buffer,
                right_pool if right_pool else []
            ])

            # Right boundary is last index of temp ordered zone
            temp_right_bound = len(left_pool) + len(temp_buffer) - 1

            yield (full_array, left_bound, temp_right_bound,
                   left_staged, right_staged,
                   tilt_side, 'firing', element_pos, firing_side, 0, False, False)

        # Traveling phase
        if firing_side == 'left':
            path = list(range(0, target_idx + 1, speed))
            if not path or path[-1] != target_idx:
                path.append(target_idx)
        else:
            start_pos = len(sorted_buffer)
            path = list(range(start_pos, target_idx - 1, -speed))
            if not path or path[-1] != target_idx:
                path.append(target_idx)

        for pos in path:
            temp_buffer = sorted_buffer.copy()
            insert_pos = max(0, min(pos, len(temp_buffer)))
            temp_buffer.insert(insert_pos, firing_val)

            full_array = np.concatenate([
                left_pool if left_pool else [],
                temp_buffer,
                right_pool if right_pool else []
            ])

            element_display = left_bound + insert_pos
            temp_right_bound = len(left_pool) + len(temp_buffer) - 1

            yield (full_array, left_bound, temp_right_bound,
                   left_staged, right_staged,
                   None, 'traveling', element_display, firing_side, 0, False, False)

        # Lock in
        sorted_buffer.insert(target_idx, firing_val)
        right_bound = len(left_pool) + len(sorted_buffer) - 1

        full_array = np.concatenate([
            left_pool if left_pool else [],
            sorted_buffer,
            right_pool if right_pool else []
        ])

        yield (full_array, left_bound, right_bound,
               left_staged, right_staged,
               None, 'rest', -1, None, 0, False, False)

    yield (np.array(sorted_buffer), 0, n - 1, None, None, None, 'done', -1, None, 0, False, False)


def get_alignment_signal(arr):
    if len(arr) == 0:
        return np.array([])
    signal = []
    for k in range(len(arr) - 1):
        val = 1.0 if arr[k] <= arr[k+1] else -1.0
        signal.append(val)
    signal.append(1.0)
    return np.array(signal)


# --- Setup Data & Plotting ---

data = np.random.rand(N)

fig, ax = plt.subplots(figsize=(16, 8))
ax.set_facecolor('#0d1117')
ax.set_ylim(-3, 5)
ax.set_xlim(-12, N + 12)
ax.set_title("Insertion Sort: Scale-Rigged Cannons", color='#c9d1d9', fontsize=14)
ax.set_yticks([])
ax.set_xticks([])
for spine in ax.spines.values():
    spine.set_visible(False)

# --- Graphics Elements ---

# Signal line
line_signal, = ax.plot([], [], color='#00ff88', linewidth=1.5, alpha=0.9, zorder=5)

# Crystal fill for ordered zone
crystal_fill = ax.fill_between([], [], color='#00FFFF', alpha=0.15)

# Boundaries
left_boundary = ax.axvline(x=0, color='#00FFFF', linewidth=2, alpha=0.6)
right_boundary = ax.axvline(x=N, color='#00FFFF', linewidth=2, alpha=0.6)

# Scale beam
scale_beam, = ax.plot([], [], color='#8b949e', linewidth=4, zorder=14)
scale_pivot, = ax.plot([], [], 's', color='#6e7681', markersize=10, zorder=15)

# Chains
left_chain, = ax.plot([], [], color='#484f58', linewidth=2, zorder=13)
right_chain, = ax.plot([], [], color='#484f58', linewidth=2, zorder=13)

# Scale pans (bowls)
pan_width = 5
pan_height = 0.8
left_pan = Polygon(np.array([[0, 0], [pan_width, 0], [pan_width-0.5, -pan_height], [0.5, -pan_height]]),
                   closed=True, facecolor='#b08030', edgecolor='#8b6914', linewidth=2, zorder=12)
right_pan = Polygon(np.array([[0, 0], [pan_width, 0], [pan_width-0.5, -pan_height], [0.5, -pan_height]]),
                    closed=True, facecolor='#b08030', edgecolor='#8b6914', linewidth=2, zorder=12)
ax.add_patch(left_pan)
ax.add_patch(right_pan)

# Weight balls on pans
left_ball = Circle((0, 0), 0.4, facecolor='#ff6b6b', edgecolor='#cc4444', linewidth=2, zorder=17)
right_ball = Circle((0, 0), 0.4, facecolor='#6b9fff', edgecolor='#4477cc', linewidth=2, zorder=17)
ax.add_patch(left_ball)
ax.add_patch(right_ball)

# Weight text (on balls)
left_weight = ax.text(0, 0, '', ha='center', va='center', fontsize=7,
                      color='white', fontweight='bold', zorder=18)
right_weight = ax.text(0, 0, '', ha='center', va='center', fontsize=7,
                       color='white', fontweight='bold', zorder=18)

# Flying element
flying_element = Circle((0, 0), 0.4, facecolor='#ff6b6b', edgecolor='#cc4444', linewidth=2, zorder=25, visible=False)
ax.add_patch(flying_element)

# Cannons at boundaries
cannon_shape_right = np.array([[-3, -0.4], [0, -0.2], [0, 0.2], [-3, 0.4], [-3.5, 0]])
cannon_shape_left = np.array([[3, -0.4], [0, -0.2], [0, 0.2], [3, 0.4], [3.5, 0]])

left_cannon = Polygon(cannon_shape_right, closed=True, color='#484f58', ec='#30363d', lw=2, zorder=18)
right_cannon = Polygon(cannon_shape_left, closed=True, color='#484f58', ec='#30363d', lw=2, zorder=18)
ax.add_patch(left_cannon)
ax.add_patch(right_cannon)

# Generator
sorter_gen = scale_cannon_generator(data.copy(), speed=STEPS_PER_FRAME)


def init():
    line_signal.set_data([], [])
    return [line_signal]


def update(frame_data):
    (arr, left_bound, right_bound, left_val, right_val,
     tilt_side, phase, element_pos, firing_side, progress,
     loading_left, loading_right) = frame_data
    global crystal_fill

    # Signal line
    y_signal = get_alignment_signal(arr)
    x_display = np.arange(len(y_signal)) if len(y_signal) > 0 else np.array([])
    line_signal.set_data(x_display, y_signal)

    # Boundaries at noise edges
    # left_bound is first index of ordered zone
    # right_bound is last index of ordered zone
    left_boundary.set_xdata([left_bound - 0.5])
    right_boundary.set_xdata([right_bound - 1])

    # Crystal fill
    crystal_fill.remove()
    if len(x_display) > 0 and right_bound >= left_bound:
        mask = (x_display >= left_bound) & (x_display <= right_bound)
        if np.any(mask):
            crystal_fill = ax.fill_between(x_display[mask], -3, 5, color='#00FFFF', alpha=0.08)
        else:
            crystal_fill = ax.fill_between([], [], color='#00FFFF', alpha=0.08)
    else:
        crystal_fill = ax.fill_between([], [], color='#00FFFF', alpha=0.08)

    # Scale geometry
    pivot_x = (left_bound - 0.5 + right_bound - 1) / 2
    pivot_y = 4.0
    left_beam_x = left_bound - 0.5
    right_beam_x = right_bound - 1

    # Calculate tilt
    tilt_angle = 0
    if phase in ['tilting', 'launching', 'firing'] and tilt_side:
        max_tilt = 15
        if phase == 'tilting':
            tilt_angle = max_tilt * progress
        else:
            tilt_angle = max_tilt
        if tilt_side == 'right':
            tilt_angle = -tilt_angle

    angle_rad = np.radians(tilt_angle)
    left_beam_y = pivot_y - np.sin(angle_rad) * 1.2
    right_beam_y = pivot_y + np.sin(angle_rad) * 1.2

    scale_beam.set_data([left_beam_x, right_beam_x], [left_beam_y, right_beam_y])
    scale_pivot.set_data([pivot_x], [pivot_y])

    # Chain and pan positions
    chain_length = 1.0
    cannon_y = 1.0

    left_pan_y = left_beam_y - chain_length
    right_pan_y = right_beam_y - chain_length

    left_chain.set_data([left_beam_x, left_beam_x], [left_beam_y, left_pan_y])
    right_chain.set_data([right_beam_x, right_beam_x], [right_beam_y, right_pan_y])

    # Pan positions (trapezoid bowls)
    def set_pan_position(pan, x, y):
        verts = np.array([
            [x - pan_width/2, y],
            [x + pan_width/2, y],
            [x + pan_width/2 - 0.5, y - pan_height],
            [x - pan_width/2 + 0.5, y - pan_height]
        ])
        pan.set_xy(verts)

    set_pan_position(left_pan, left_beam_x, left_pan_y)
    set_pan_position(right_pan, right_beam_x, right_pan_y)

    # Ball positions (sitting in pans)
    ball_y_offset = -pan_height/2 - 0.1

    # Left ball - show if we have a value and not currently launching/firing this side
    show_left_ball = (left_val is not None and
                      (phase not in ['launching', 'firing'] or
                       (phase in ['launching', 'firing'] and tilt_side != 'left')))
    if show_left_ball:
        if phase == 'loading' and loading_left:
            # Slide in from left
            start_x = left_beam_x - 3
            end_x = left_beam_x
            ball_x = start_x + (end_x - start_x) * progress
        else:
            ball_x = left_beam_x
        left_ball.set_center((ball_x, left_pan_y + ball_y_offset))
        left_ball.set_radius(0.3 + left_val * 0.3)  # Size based on weight
        left_ball.set_visible(True)
        left_weight.set_position((ball_x, left_pan_y + ball_y_offset))
        left_weight.set_text(f'{left_val:.2f}')
    else:
        left_ball.set_visible(False)
        left_weight.set_text('')

    # Right ball - show if we have a value and not currently launching/firing this side
    show_right_ball = (right_val is not None and
                       (phase not in ['launching', 'firing'] or
                        (phase in ['launching', 'firing'] and tilt_side != 'right')))
    if show_right_ball:
        if phase == 'loading' and loading_right:
            # Slide in from right
            start_x = right_beam_x + 3
            end_x = right_beam_x
            ball_x = start_x + (end_x - start_x) * progress
        else:
            ball_x = right_beam_x
        right_ball.set_center((ball_x, right_pan_y + ball_y_offset))
        right_ball.set_radius(0.3 + right_val * 0.3)  # Size based on weight
        right_ball.set_visible(True)
        right_weight.set_position((ball_x, right_pan_y + ball_y_offset))
        right_weight.set_text(f'{right_val:.2f}')
    else:
        right_ball.set_visible(False)
        right_weight.set_text('')

    # Flying element (during launch)
    if phase == 'launching' and tilt_side:
        if tilt_side == 'left':
            start_x, start_y = left_beam_x, left_pan_y + ball_y_offset
            end_x, end_y = left_beam_x, cannon_y + 0.3
            flying_element.set_facecolor('#ff6b6b')
        else:
            start_x, start_y = right_beam_x, right_pan_y + ball_y_offset
            end_x, end_y = right_beam_x, cannon_y + 0.3
            flying_element.set_facecolor('#6b9fff')

        t = progress
        fly_x = start_x
        fly_y = start_y + (end_y - start_y) * t + 0.8 * np.sin(np.pi * t)

        flying_element.set_center((fly_x, fly_y))
        flying_element.set_visible(True)
    else:
        flying_element.set_visible(False)

    # Cannon positions at boundaries
    left_cannon.set_xy(cannon_shape_right + [left_bound - 0.5, cannon_y])
    right_cannon.set_xy(cannon_shape_left + [right_bound - 1, cannon_y])

    # Cannon firing effect (recoil)
    if phase == 'firing':
        if firing_side == 'left':
            left_cannon.set_xy(cannon_shape_right + [left_bound - 1.5, cannon_y])
            left_cannon.set_facecolor('#ff4500')
        else:
            right_cannon.set_xy(cannon_shape_left + [right_bound, cannon_y])
            right_cannon.set_facecolor('#ff4500')
    else:
        left_cannon.set_facecolor('#484f58')
        right_cannon.set_facecolor('#484f58')

    return ([line_signal, crystal_fill, left_boundary, right_boundary,
             scale_beam, scale_pivot, left_chain, right_chain,
             left_pan, right_pan, left_cannon, right_cannon,
             left_ball, right_ball, flying_element])


ani = animation.FuncAnimation(
    fig, update, frames=sorter_gen, init_func=init,
    blit=False, interval=INTERVAL, repeat=False, cache_frame_data=False
)

print("Starting Scale-Rigged Cannon Animation...")
ani.save('sort_insertion.gif', writer='pillow', fps=30)
#plt.show()
