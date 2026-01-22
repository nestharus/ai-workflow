import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

# --- Setup the Journey ---
# Keypoints: [Time, Angle]
# We map your spins to time steps for the wave
# 0->140, 140->90, 90->150, 150->180
keypoints = [
    (0, 0),  # Start
    (1, 140),  # Spin 1 (Vector A says +140)
    (2, 90),  # Spin 2 (Vector B says -50)
    (3, 150),  # Spin 3 (Vector C says +60)
    (4, 180),  # Spin 4 (Vector D says +30)
]

# Create the interpolation (The Wave)
times = [k[0] for k in keypoints]
angles = [k[1] for k in keypoints]

# High-resolution time for smooth curve
t_smooth = np.linspace(0, 4, 400)
angle_smooth = np.interp(t_smooth, times, angles)

# --- Define the Wobble (The Cloud) ---
# "Wobbling is strongest at 174 and stops at 176"
# This happens during the last leg (Time 3 to 4)
wobble_magnitude = np.zeros_like(t_smooth)

for i, angle in enumerate(angle_smooth):
    # If we are in the "Neighborhood" of 170-176
    if 170 <= angle <= 176:
        # Create a bell curve of uncertainty centered at 174
        dist = abs(angle - 174)
        # Closer to 174 = More Wobble (Max 15 degrees width)
        wobble_magnitude[i] = 15 * np.exp(-(dist**2) / 2)

# --- The "Extracted Vectors" (The Derivative) ---
# Calculate how much we spun at each moment
spins = np.diff(angle_smooth)

# --- Plotting ---
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)
plt.subplots_adjust(hspace=0.4)

# Plot 1: The Wave (Position/Heading)
(line,) = ax1.plot([], [], "b-", linewidth=2, label="The Wave (Your Heading)")
fill = ax1.fill_between(
    t_smooth, angle_smooth, angle_smooth, color="red", alpha=0.3, label="The Cloud (Wobble)"
)
(dot,) = ax1.plot([], [], "ro", markersize=8)

ax1.set_ylabel("Total Rotation (Degrees)")
ax1.set_title("The Wave: History of Movement")
ax1.grid(True)
ax1.legend(loc="upper left")
ax1.set_ylim(-10, 200)

# Plot 2: The Spins (The Encoded Vectors)
# This graph extracts the vectors from the wave slope
bar_container = ax2.bar(
    times[1:], np.diff(angles), color="green", alpha=0.6, width=0.3, label="Extracted Vectors"
)
ax2.axhline(0, color="black", linewidth=1)

ax2.set_ylabel("Spin Magnitude (Degrees)")
ax2.set_xlabel("Time Steps")
ax2.set_title("The Code: Vectors Extracted from Slope")
ax2.legend()
ax2.set_ylim(-100, 150)


def init():
    line.set_data([], [])
    dot.set_data([], [])
    return line, dot, fill


def update(frame):
    # Draw wave up to current frame
    current_t = t_smooth[:frame]
    current_angle = angle_smooth[:frame]
    current_wobble = wobble_magnitude[:frame]

    line.set_data(current_t, current_angle)
    # Guard against frame == 0 to avoid negative indexing
    if frame == 0:
        dot.set_data([], [])
    else:
        dot.set_data([t_smooth[frame - 1]], [angle_smooth[frame - 1]])

    # Update the "Cloud" (Fill Between)
    # We create the "Tube" by adding/subtracting wobble from the main line
    ax1.collections.clear()
    ax1.fill_between(
        current_t,
        current_angle - current_wobble,
        current_angle + current_wobble,
        color="red",
        alpha=0.3,
    )

    return line, dot


# Create Animation
ani = FuncAnimation(fig, update, frames=len(t_smooth), init_func=init, blit=False, interval=10)

plt.show()
