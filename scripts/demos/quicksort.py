import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Polygon, Rectangle

# --- Configuration ---
N = 100                
INTERVAL = 20          
STEPS_PER_FRAME = 2    
Y_LIMIT = 3

# --- Helper Functions ---

def quicksort_generator(arr, steps_per_frame=1):
    # Stack stores ranges (low, high)
    stack = [(0, len(arr) - 1)]
    
    while stack:
        low, high = stack.pop()
        
        if low < high:
            # Choose pivot (using last element)
            pivot = arr[high]
            i = low - 1
            
            yield arr.copy(), low, high, i, low, high, 'start_partition'
            
            for j in range(low, high):
                # Yield scanning state occasionally
                if (j - low) % steps_per_frame == 0:
                     yield arr.copy(), low, high, i, j, high, 'scan'
                
                if arr[j] <= pivot:
                    i += 1
                    arr[i], arr[j] = arr[j], arr[i]
                    if i != j:
                        yield arr.copy(), low, high, i, j, high, 'swap'
            
            # Place pivot
            arr[i + 1], arr[high] = arr[high], arr[i + 1]
            pi = i + 1
            yield arr.copy(), low, high, pi, high, pi, 'pivot_placed'
            
            # Push new ranges
            stack.append((pi + 1, high))
            stack.append((low, pi - 1))
            
    yield arr.copy(), -1, -1, -1, -1, -1, 'done'

def get_alignment_signal(arr):
    signal = []
    for k in range(len(arr) - 1):
        diff = arr[k+1] - arr[k]
        val = 1.0 if diff >= 0 else -1.0
        signal.append(val)
    signal.append(1.0)
    return np.array(signal)

# --- Setup Data & Plotting ---

data = np.random.rand(N)
x_domain = np.arange(N)

fig, ax = plt.subplots(figsize=(12, 6))
ax.set_facecolor('#f0f0f0') 
ax.set_ylim(-Y_LIMIT, Y_LIMIT)
ax.set_xlim(-5, N + 5)
ax.set_title("Quick Sort: Partitioning")
ax.set_yticks([])
ax.set_xticks([])

# --- Graphics Elements ---

# 1. Signal Line
line_signal, = ax.plot([], [], color='#222222', linewidth=1.5, alpha=0.8, zorder=5)

# 2. Active Range Background
range_rect = Rectangle((0, -Y_LIMIT), 0, 2*Y_LIMIT, color='blue', alpha=0.1, zorder=0)
ax.add_patch(range_rect)

# 3. Pivot Marker
pivot_marker = Polygon([[-0.5, 2.5], [0.5, 2.5], [0, 1.5]], closed=True, color='#FF00FF', zorder=10)
ax.add_patch(pivot_marker)

# 4. Pointers (i and j)
i_marker = Polygon([[-0.4, -2.5], [0.4, -2.5], [0, -1.5]], closed=True, color='#00AA00', zorder=10) # Green pointing up
j_marker = Polygon([[-0.4, -2.5], [0.4, -2.5], [0, -1.5]], closed=True, color='#0000AA', zorder=10) # Blue pointing up
ax.add_patch(i_marker)
ax.add_patch(j_marker)


# Global state
sorter_gen = quicksort_generator(data.copy(), steps_per_frame=STEPS_PER_FRAME)

def init():
    line_signal.set_data([], [])
    range_rect.set_width(0)
    pivot_marker.set_xy([[-0.5, 2.5], [0.5, 2.5], [0, 1.5]])
    return line_signal, range_rect, pivot_marker, i_marker, j_marker

def update(frame_data):
    arr, low, high, idx_i, idx_j, pivot_idx, state = frame_data
    
    # 1. Update Signal
    y_signal = get_alignment_signal(arr)
    line_signal.set_data(x_domain, y_signal)
    
    if state == 'done':
        range_rect.set_alpha(0)
        pivot_marker.set_alpha(0)
        i_marker.set_alpha(0)
        j_marker.set_alpha(0)
        ax.set_title("Quick Sort: Complete", color='green')
        return line_signal, range_rect, pivot_marker, i_marker, j_marker

    # 2. Update Range Highlight
    range_rect.set_x(low)
    range_rect.set_width(high - low + 1)
    
    # 3. Update Markers
    
    # Pivot (usually at 'high' during partition, or 'pi' when placed)
    new_pivot_pos = np.array([[-0.5, 2.5], [0.5, 2.5], [0, 1.5]]) + [pivot_idx, 0]
    pivot_marker.set_xy(new_pivot_pos)
    
    # Pointer i (low boundary of smaller elements)
    # i is actually the index of the last smaller element, so maybe shift it slightly?
    # Let's show it at i
    new_i_pos = np.array([[-0.4, -2.5], [0.4, -2.5], [0, -1.5]]) + [idx_i, 0]
    i_marker.set_xy(new_i_pos)
    
    # Pointer j (scanner)
    new_j_pos = np.array([[-0.4, -2.5], [0.4, -2.5], [0, -1.5]]) + [idx_j, 0]
    j_marker.set_xy(new_j_pos)
    
    # Color logic
    if state == 'swap':
        i_marker.set_color('#FFFF00') # Flash yellow
        j_marker.set_color('#FFFF00')
    elif state == 'pivot_placed':
        pivot_marker.set_facecolor('#00FF00') # Flash green
    else:
        i_marker.set_color('#00AA00')
        j_marker.set_color('#0000AA')
        pivot_marker.set_facecolor('#FF00FF')

    return line_signal, range_rect, pivot_marker, i_marker, j_marker

ani = animation.FuncAnimation(
    fig, 
    update, 
    frames=sorter_gen, 
    init_func=init,
    blit=False, 
    interval=INTERVAL,
    repeat=False
)

print("Starting Quick Sort Animation...")
plt.show()
#ani.save('sort_quick.gif', writer='pillow', fps=30)
