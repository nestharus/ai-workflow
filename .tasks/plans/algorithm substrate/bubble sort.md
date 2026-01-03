You are right. I split the final function (the `bubble_sort` usage code) into two conceptual parts ("Policy" and "Actuator") which is an unnecessary level of abstraction for the code block itself.

The `bubble_sort` function *is* the Algorithm. It is the consumer that configures the machine.

Here is the corrected code block with the proper decomposition of responsibilities.

```python
# ==========================================
# COMPONENT 1: THE LENS (Data Interface)
# Responsibility: Restricts access to a specific window of data.
# ==========================================
class MutableWindow:
    def __init__(self, data, idx_a, idx_b):
        self._data = data
        self._a = idx_a
        self._b = idx_b

    @property
    def left(self): return self._data[self._a]
    @left.setter
    def left(self, val): self._data[self._a] = val
        
    @property
    def right(self): return self._data[self._b]
    @right.setter
    def right(self, val): self._data[self._b] = val

# ==========================================
# COMPONENT 2: THE STATE MACHINE (Lifecycle)
# Responsibility: Determines when the system is stable (Done).
# ==========================================
class StabilityMonitor:
    def __init__(self):
        self.dirty = False

    def check_stability(self, dims):
        _, _, is_end_of_epoch = dims
        
        if is_end_of_epoch:
            if not self.dirty:
                return False # Stop signal
            self.dirty = False # Reset for next pass
            
        return True # Continue signal

# ==========================================
# COMPONENT 3: THE CONTROLLER (Orchestrator)
# Responsibility: Binds Topology (Walker) to State (Monitor).
# ==========================================
class SortController:
    def __init__(self, data):
        self._data = data
        self._monitor = StabilityMonitor()

    # COMPONENT 3a: THE WALKER (Internal Topology)
    # Responsibility: Generates the 2D coordinate stream.
    def _walker(self):
        rows = len(self._data)
        for y in range(rows):
            cols = rows - 1 - y
            for x in range(cols):
                yield (y, x, x == cols - 1), MutableWindow(self._data, x, x + 1)

    def filter(self, predicate):
        for dims, pair in self._walker():
            if not self._monitor.check_stability(dims):
                return

            if predicate(pair):
                self._monitor.dirty = True
                yield pair

# ==========================================
# COMPONENT 4: THE ALGORITHM (The Usage)
# Responsibility: Defines the business logic (Compare & Swap).
# ==========================================
def bubble_sort(arr):
    controller = SortController(arr)

    # The Algorithm: Iterate over violations and fix them.
    for pair in controller.filter(lambda p: p.left > p.right):
        pair.left, pair.right = pair.right, pair.left
        
    return arr

```

### The Responsibilities (Corrected)

1. **The Lens (`MutableWindow`):** Provides the specific "Subject" that can be manipulated.
2. **The State Machine (`StabilityMonitor`):** Tracks the "Entropy" to determine if the job is finished.
3. **The Controller (`SortController`):** Provides the "Mechanism" of traversal and integrates the state machine.
* *Includes the Walker:* Defines the "Shape" of the traversal.


4. **The Algorithm (`bubble_sort`):** Defines the "Behavior." It is the implementation logic that says "If Left > Right, Swap."