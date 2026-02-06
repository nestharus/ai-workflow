"""Loop detection for iterative refinement processes.

Detects exact repetition, cycling patterns, and stagnation to prevent
infinite loops in the spec refinement pipeline.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LoopStatus(Enum):
    """Status of loop detection check.

    PROGRESSING: System is making progress, no loop detected.
    STAGNANT: System has stopped making progress (same state for N iterations).
    CYCLING: System is cycling between a set of states.
    MAX_ITERATIONS: Maximum iteration count reached.
    """

    PROGRESSING = "progressing"
    STAGNANT = "stagnant"
    CYCLING = "cycling"
    MAX_ITERATIONS = "max_iterations"


@dataclass
class LoopDetector:
    """Detector for loops and stagnation in iterative processes.

    Tracks content hashes across iterations to detect:
    - Exact repetition (same state appears twice)
    - Cycling (state appears after N iterations)
    - Stagnation (no progress for N consecutive iterations)

    Attributes:
        content_hashes: History of state hashes.
        stagnation_threshold: Number of identical states to trigger stagnation.
        max_iterations: Maximum iterations before forced termination.
        cycle_detection_window: Window size for cycle detection.
    """

    content_hashes: list[str] = field(default_factory=list)
    stagnation_threshold: int = 3
    max_iterations: int = 50
    cycle_detection_window: int = 10
    _stagnation_count: int = field(default=0, repr=False)
    _last_hash: str = field(default="", repr=False)

    def reset(self) -> None:
        """Reset the detector state."""
        self.content_hashes.clear()
        self._stagnation_count = 0
        self._last_hash = ""

    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute deterministic hash of content.

        Args:
            content: Content to hash.

        Returns:
            16-character hex digest.
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def compute_state_hash(state: dict[str, Any]) -> str:
        """Compute deterministic hash of a state dictionary.

        Handles nested structures by sorting keys and converting to canonical string.

        Args:
            state: State dictionary to hash.

        Returns:
            16-character hex digest.
        """
        import json

        canonical = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def update(self, state_hash: str) -> LoopStatus:
        """Update detector with new state and check for loops.

        Args:
            state_hash: Hash of current state.

        Returns:
            LoopStatus indicating progress, stagnation, cycling, or max iterations.
        """
        iteration = len(self.content_hashes) + 1

        # Check max iterations
        if iteration > self.max_iterations:
            return LoopStatus.MAX_ITERATIONS

        # Check for exact repetition (cycling)
        if state_hash in self.content_hashes:
            return LoopStatus.CYCLING

        # Check for stagnation (same hash as previous)
        if state_hash == self._last_hash:
            self._stagnation_count += 1
            if self._stagnation_count >= self.stagnation_threshold:
                return LoopStatus.STAGNANT
        else:
            self._stagnation_count = 0

        # Check for cycling within detection window
        window_start = max(0, len(self.content_hashes) - self.cycle_detection_window)
        recent_hashes = set(self.content_hashes[window_start:])
        if state_hash in recent_hashes:
            return LoopStatus.CYCLING

        # Record state
        self.content_hashes.append(state_hash)
        self._last_hash = state_hash

        return LoopStatus.PROGRESSING

    def get_iteration_count(self) -> int:
        """Get the current iteration count."""
        return len(self.content_hashes)

    def get_stagnation_count(self) -> int:
        """Get the current stagnation count."""
        return self._stagnation_count

    def mark_progress(self) -> None:
        """Reset stagnation count after confirmed progress."""
        self._stagnation_count = 0

    def detect_cycle_pattern(self) -> list[str] | None:
        """Detect if there's a repeating cycle pattern.

        Returns:
            List of hashes in the cycle, or None if no cycle detected.
        """
        if len(self.content_hashes) < 4:
            return None

        # Look for cycle of length 2 to window/2
        max_cycle_len = min(self.cycle_detection_window // 2, len(self.content_hashes) // 2)

        for cycle_len in range(2, max_cycle_len + 1):
            recent = self.content_hashes[-cycle_len:]
            previous = self.content_hashes[-2 * cycle_len : -cycle_len]
            if recent == previous:
                return recent

        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "content_hashes": self.content_hashes,
            "stagnation_threshold": self.stagnation_threshold,
            "max_iterations": self.max_iterations,
            "cycle_detection_window": self.cycle_detection_window,
            "stagnation_count": self._stagnation_count,
            "last_hash": self._last_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopDetector:
        """Deserialize from dictionary."""
        detector = cls(
            content_hashes=data.get("content_hashes", []),
            stagnation_threshold=data.get("stagnation_threshold", 3),
            max_iterations=data.get("max_iterations", 50),
            cycle_detection_window=data.get("cycle_detection_window", 10),
        )
        detector._stagnation_count = data.get("stagnation_count", 0)
        detector._last_hash = data.get("last_hash", "")
        return detector
