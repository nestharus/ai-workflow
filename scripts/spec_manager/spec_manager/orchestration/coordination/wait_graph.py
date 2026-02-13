"""Directed wait graph for inter-slice dependency tracking.

The WaitGraph tracks which slices are waiting on which other slices.
It enforces acyclicity: adding an edge that would create a cycle raises
CyclicDependencyError immediately.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


class CyclicDependencyError(Exception):
    """Raised when adding an edge would create a cycle in the wait graph."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"Cyclic dependency detected: {' -> '.join(cycle)}")


@dataclass
class WaitEdge:
    """A directed edge: *waiting_slice* is blocked until *provider_slice* delivers."""

    waiting_slice: str = ""
    provider_slice: str = ""
    artifact_key: str = ""
    signal_id: str = ""
    monitor_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "waiting_slice": self.waiting_slice,
            "provider_slice": self.provider_slice,
            "artifact_key": self.artifact_key,
            "signal_id": self.signal_id,
            "monitor_id": self.monitor_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WaitEdge:
        return cls(
            waiting_slice=d.get("waiting_slice", ""),
            provider_slice=d.get("provider_slice", ""),
            artifact_key=d.get("artifact_key", ""),
            signal_id=d.get("signal_id", ""),
            monitor_id=d.get("monitor_id", ""),
        )


class WaitGraph:
    """In-memory directed graph of slice wait dependencies.

    Edges go from *waiting_slice* to *provider_slice*.  Cycle detection
    runs on every ``add_edge`` call using BFS reachability.
    """

    def __init__(self) -> None:
        self._edges: list[WaitEdge] = []
        # Adjacency: waiting_slice -> set of provider_slices
        self._adj: dict[str, set[str]] = defaultdict(set)

    def add_edge(self, edge: WaitEdge) -> None:
        """Add a wait edge.  Raises CyclicDependencyError if it creates a cycle."""
        # Would adding waiting->provider create a path provider->...->waiting?
        if edge.waiting_slice == edge.provider_slice:
            raise CyclicDependencyError([edge.waiting_slice, edge.provider_slice])

        # BFS from provider_slice in the existing graph to see if we can reach waiting_slice
        if self._can_reach(edge.provider_slice, edge.waiting_slice):
            cycle = self._find_cycle_path(edge.provider_slice, edge.waiting_slice)
            # cycle is provider -> ... -> waiting; prepend waiting and append provider
            raise CyclicDependencyError([edge.waiting_slice, *cycle, edge.waiting_slice])

        self._edges.append(edge)
        self._adj[edge.waiting_slice].add(edge.provider_slice)

    def _can_reach(self, start: str, target: str) -> bool:
        """BFS reachability from *start* to *target* in the existing graph."""
        visited: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            for neighbor in self._adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        return False

    def _find_cycle_path(self, start: str, target: str) -> list[str]:
        """BFS shortest path from *start* to *target*."""
        visited: set[str] = set()
        queue: deque[list[str]] = deque([[start]])
        while queue:
            path = queue.popleft()
            node = path[-1]
            if node == target:
                return path
            if node in visited:
                continue
            visited.add(node)
            for neighbor in self._adj.get(node, set()):
                if neighbor not in visited:
                    queue.append([*path, neighbor])
        return [start, target]  # fallback

    def remove_edge(self, signal_id: str) -> None:
        """Remove all edges with the given *signal_id*."""
        to_remove = [e for e in self._edges if e.signal_id == signal_id]
        for edge in to_remove:
            self._edges.remove(edge)
        # Rebuild adjacency
        self._rebuild_adj()

    def remove_edges_for_slice(self, slice_id: str) -> None:
        """Remove all edges where *slice_id* is the waiting slice."""
        self._edges = [e for e in self._edges if e.waiting_slice != slice_id]
        self._rebuild_adj()

    def _rebuild_adj(self) -> None:
        self._adj = defaultdict(set)
        for e in self._edges:
            self._adj[e.waiting_slice].add(e.provider_slice)

    def has_cycle(self) -> bool:
        """Check whether the current graph contains a cycle."""
        # Since we prevent cycles on add, this should always be False
        # unless edges were manipulated externally.  Use full DFS.
        all_nodes: set[str] = set()
        for e in self._edges:
            all_nodes.add(e.waiting_slice)
            all_nodes.add(e.provider_slice)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in all_nodes}

        def _dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbor in self._adj.get(node, set()):
                if color.get(neighbor, WHITE) == GRAY:
                    return True
                if color.get(neighbor, WHITE) == WHITE and _dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        return any(color[n] == WHITE and _dfs(n) for n in all_nodes)

    def get_cycle(self) -> list[str] | None:
        """Return one cycle path or None."""
        all_nodes: set[str] = set()
        for e in self._edges:
            all_nodes.add(e.waiting_slice)
            all_nodes.add(e.provider_slice)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in all_nodes}
        parent: dict[str, str | None] = {n: None for n in all_nodes}

        def _dfs(node: str) -> list[str] | None:
            color[node] = GRAY
            for neighbor in self._adj.get(node, set()):
                if color.get(neighbor, WHITE) == GRAY:
                    # Reconstruct cycle
                    cycle = [neighbor, node]
                    cur = node
                    while parent.get(cur) is not None and parent[cur] != neighbor:
                        cur = parent[cur]  # type: ignore[assignment]
                        cycle.append(cur)
                    cycle.reverse()
                    return cycle
                if color.get(neighbor, WHITE) == WHITE:
                    parent[neighbor] = node
                    result = _dfs(neighbor)
                    if result is not None:
                        return result
            color[node] = BLACK
            return None

        for n in all_nodes:
            if color[n] == WHITE:
                result = _dfs(n)
                if result is not None:
                    return result
        return None

    def get_waiting_on(self, slice_id: str) -> list[WaitEdge]:
        """Get all edges where *slice_id* is the waiting slice."""
        return [e for e in self._edges if e.waiting_slice == slice_id]

    def get_providers_for(self, slice_id: str) -> list[WaitEdge]:
        """Get all edges where *slice_id* is the provider slice."""
        return [e for e in self._edges if e.provider_slice == slice_id]

    def to_dict(self) -> dict[str, Any]:
        return {"edges": [e.to_dict() for e in self._edges]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WaitGraph:
        g = cls()
        for edge_data in d.get("edges", []):
            edge = WaitEdge.from_dict(edge_data)
            # Use direct append to skip cycle check during deserialization
            # (the persisted graph was valid when saved)
            g._edges.append(edge)
            g._adj[edge.waiting_slice].add(edge.provider_slice)
        return g
