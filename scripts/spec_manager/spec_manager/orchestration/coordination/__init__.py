"""Agent coordination package for cross-slice dependency management.

Provides signals (agent halt notifications), a wake-event queue,
a wait graph for tracking inter-slice dependencies, work items,
monitors, and monitor execution.
"""

from __future__ import annotations

from spec_manager.orchestration.coordination.signals import (
    CoordinationSignal,
    FunctionRef,
    LocalContext,
    SearchHints,
    SignalNeed,
    SignalProgress,
    SpecRef,
)
from spec_manager.orchestration.coordination.wait_graph import (
    CyclicDependencyError,
    WaitEdge,
    WaitGraph,
)
from spec_manager.orchestration.coordination.wake_queue import (
    WakeEvent,
    WakeQueue,
)

__all__ = [
    "CoordinationSignal",
    "CyclicDependencyError",
    "FunctionRef",
    "LocalContext",
    "SearchHints",
    "SignalNeed",
    "SignalProgress",
    "SpecRef",
    "WaitEdge",
    "WaitGraph",
    "WakeEvent",
    "WakeQueue",
]
