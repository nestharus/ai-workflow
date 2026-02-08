"""Tests for spec_manager.decomposition.graph module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spec_manager.spec_manager.utils.graph import (
    build_dependency_graph,
    find_cycles,
    generate_mermaid_diagram,
    get_topological_order,
    save_dependency_graph,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace with required structure."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "output").mkdir()
    return ws


@pytest.fixture
def populated_workspace(workspace: Path) -> Path:
    """Create workspace with entity index and id_map."""
    # Create entity index
    entity_index = {
        "E-001": {
            "name": "AuthService",
            "keywords": ["auth", "login"],
            "aliases": [],
            "sources": ["spec.md:5"],
        },
        "E-002": {
            "name": "UserStore",
            "keywords": ["user", "store"],
            "aliases": [],
            "sources": ["spec.md:20"],
        },
        "E-003": {
            "name": "TokenService",
            "keywords": ["token", "jwt"],
            "aliases": [],
            "sources": ["spec.md:35"],
        },
    }
    (workspace / "entity_index.json").write_text(json.dumps(entity_index))

    # Create id_map with relations
    id_map = {
        "E-001": [{"file": "spec.md", "line": 5, "type": "entity"}],
        "E-002": [{"file": "spec.md", "line": 20, "type": "entity"}],
        "E-003": [{"file": "spec.md", "line": 35, "type": "entity"}],
        "R-001": [
            {
                "file": "spec.md",
                "line": 10,
                "type": "relation",
                "from": "E-001",
                "to": "E-002",
                "relation_type": "uses",
            }
        ],
        "R-002": [
            {
                "file": "spec.md",
                "line": 12,
                "type": "relation",
                "from": "E-001",
                "to": "E-003",
                "relation_type": "depends_on",
            }
        ],
    }
    (workspace / "id_map.json").write_text(json.dumps(id_map))

    return workspace


class TestBuildDependencyGraph:
    """Tests for build_dependency_graph function."""

    def test_empty_workspace(self, workspace: Path):
        """Test building graph from empty workspace."""
        (workspace / "entity_index.json").write_text("{}")
        (workspace / "id_map.json").write_text("{}")

        graph = build_dependency_graph(workspace)
        assert graph["nodes"] == {}
        assert graph["edges"] == []
        assert graph["statistics"]["node_count"] == 0
        assert graph["statistics"]["edge_count"] == 0

    def test_builds_nodes_from_entities(self, populated_workspace: Path):
        """Test nodes are built from entity index."""
        graph = build_dependency_graph(populated_workspace)

        assert len(graph["nodes"]) == 3
        assert "E-001" in graph["nodes"]
        assert "E-002" in graph["nodes"]
        assert "E-003" in graph["nodes"]
        assert graph["nodes"]["E-001"]["name"] == "AuthService"

    def test_builds_edges_from_relations(self, populated_workspace: Path):
        """Test edges are built from relations in id_map."""
        graph = build_dependency_graph(populated_workspace)

        assert len(graph["edges"]) == 2
        edge_ids = {e["id"] for e in graph["edges"]}
        assert "R-001" in edge_ids
        assert "R-002" in edge_ids

    def test_builds_adjacency_lists(self, populated_workspace: Path):
        """Test adjacency lists are correctly built."""
        graph = build_dependency_graph(populated_workspace)

        # E-001 has outgoing to E-002 and E-003
        outgoing = graph["adjacency"]["E-001"]["outgoing"]
        targets = {e["target"] for e in outgoing}
        assert targets == {"E-002", "E-003"}

        # E-002 has incoming from E-001
        incoming = graph["adjacency"]["E-002"]["incoming"]
        sources = {e["source"] for e in incoming}
        assert "E-001" in sources

    def test_edge_includes_type(self, populated_workspace: Path):
        """Test edges include relation type."""
        graph = build_dependency_graph(populated_workspace)

        r001 = next(e for e in graph["edges"] if e["id"] == "R-001")
        assert r001["type"] == "uses"

        r002 = next(e for e in graph["edges"] if e["id"] == "R-002")
        assert r002["type"] == "depends_on"

    def test_statistics_correct(self, populated_workspace: Path):
        """Test statistics are calculated correctly."""
        graph = build_dependency_graph(populated_workspace)

        assert graph["statistics"]["node_count"] == 3
        assert graph["statistics"]["edge_count"] == 2


class TestSaveDependencyGraph:
    """Tests for save_dependency_graph function."""

    def test_saves_json_file(self, workspace: Path):
        """Test saves dependency_graph.json."""
        graph = {
            "nodes": {"E-001": {"id": "E-001", "name": "Test"}},
            "edges": [],
            "adjacency": {"E-001": {"outgoing": [], "incoming": []}},
            "statistics": {"node_count": 1, "edge_count": 0},
        }

        save_dependency_graph(workspace, graph)

        json_file = workspace / "output" / "dependency_graph.json"
        assert json_file.exists()
        loaded = json.loads(json_file.read_text())
        assert loaded == graph

    def test_saves_mermaid_file(self, workspace: Path):
        """Test saves dependency_graph.mermaid."""
        graph = {
            "nodes": {"E-001": {"id": "E-001", "name": "Test"}},
            "edges": [],
            "adjacency": {},
            "statistics": {},
        }

        save_dependency_graph(workspace, graph)

        mermaid_file = workspace / "output" / "dependency_graph.mermaid"
        assert mermaid_file.exists()
        content = mermaid_file.read_text()
        assert "graph TD" in content


class TestGenerateMermaidDiagram:
    """Tests for generate_mermaid_diagram function."""

    def test_generates_valid_mermaid(self):
        """Test generates valid Mermaid syntax."""
        graph = {
            "nodes": {
                "E-001": {"id": "E-001", "name": "AuthService"},
                "E-002": {"id": "E-002", "name": "UserStore"},
            },
            "edges": [
                {"id": "R-001", "from": "E-001", "to": "E-002", "type": "uses"},
            ],
        }

        mermaid = generate_mermaid_diagram(graph)
        assert mermaid.startswith("graph TD")
        assert 'E-001["AuthService"]' in mermaid
        assert 'E-002["UserStore"]' in mermaid
        assert "E-001" in mermaid and "E-002" in mermaid

    def test_escapes_quotes_in_names(self):
        """Test quotes in names are escaped."""
        graph = {
            "nodes": {
                "E-001": {"id": "E-001", "name": 'Auth "Service"'},
            },
            "edges": [],
        }

        mermaid = generate_mermaid_diagram(graph)
        assert "\"Auth 'Service'\"" in mermaid  # Quotes replaced with single quotes

    def test_uses_different_arrow_styles(self):
        """Test different relation types use different arrows."""
        graph = {
            "nodes": {
                "E-001": {"id": "E-001", "name": "A"},
                "E-002": {"id": "E-002", "name": "B"},
                "E-003": {"id": "E-003", "name": "C"},
            },
            "edges": [
                {"id": "R-001", "from": "E-001", "to": "E-002", "type": "uses"},
                {"id": "R-002", "from": "E-001", "to": "E-003", "type": "depends_on"},
            ],
        }

        mermaid = generate_mermaid_diagram(graph)
        # Uses should have -->
        assert "-->|uses|" in mermaid
        # depends_on should have -.->
        assert "-.->|depends_on|" in mermaid


class TestGetTopologicalOrder:
    """Tests for get_topological_order function."""

    def test_simple_chain(self):
        """Test topological order of simple A -> B -> C chain."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "B"}], "incoming": []},
                "B": {"outgoing": [{"target": "C"}], "incoming": [{"source": "A"}]},
                "C": {"outgoing": [], "incoming": [{"source": "B"}]},
            },
        }

        order = get_topological_order(graph)
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_multiple_roots(self):
        """Test with multiple root nodes (no dependencies)."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "C"}], "incoming": []},
                "B": {"outgoing": [{"target": "C"}], "incoming": []},
                "C": {"outgoing": [], "incoming": [{"source": "A"}, {"source": "B"}]},
            },
        }

        order = get_topological_order(graph)
        # A and B should both come before C
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("C")

    def test_handles_isolated_nodes(self):
        """Test handles nodes with no edges."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [], "incoming": []},
                "B": {"outgoing": [], "incoming": []},
                "C": {"outgoing": [], "incoming": []},
            },
        }

        order = get_topological_order(graph)
        assert set(order) == {"A", "B", "C"}

    def test_handles_cycle(self):
        """Test handles cyclic graph (returns all nodes)."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "B"}], "incoming": [{"source": "C"}]},
                "B": {"outgoing": [{"target": "C"}], "incoming": [{"source": "A"}]},
                "C": {"outgoing": [{"target": "A"}], "incoming": [{"source": "B"}]},
            },
        }

        order = get_topological_order(graph)
        # Should still return all nodes even with cycle
        assert set(order) == {"A", "B", "C"}


class TestFindCycles:
    """Tests for find_cycles function."""

    def test_no_cycles(self):
        """Test returns empty list for acyclic graph."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "B"}], "incoming": []},
                "B": {"outgoing": [{"target": "C"}], "incoming": [{"source": "A"}]},
                "C": {"outgoing": [], "incoming": [{"source": "B"}]},
            },
        }

        cycles = find_cycles(graph)
        assert cycles == []

    def test_finds_simple_cycle(self):
        """Test finds A -> B -> A cycle."""
        graph = {
            "nodes": {"A": {}, "B": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "B"}], "incoming": [{"source": "B"}]},
                "B": {"outgoing": [{"target": "A"}], "incoming": [{"source": "A"}]},
            },
        }

        cycles = find_cycles(graph)
        assert len(cycles) >= 1
        # At least one cycle should contain both A and B
        cycle_nodes = set()
        for cycle in cycles:
            cycle_nodes.update(cycle)
        assert "A" in cycle_nodes or "B" in cycle_nodes

    def test_finds_three_node_cycle(self):
        """Test finds A -> B -> C -> A cycle."""
        graph = {
            "nodes": {"A": {}, "B": {}, "C": {}},
            "adjacency": {
                "A": {"outgoing": [{"target": "B"}], "incoming": [{"source": "C"}]},
                "B": {"outgoing": [{"target": "C"}], "incoming": [{"source": "A"}]},
                "C": {"outgoing": [{"target": "A"}], "incoming": [{"source": "B"}]},
            },
        }

        cycles = find_cycles(graph)
        assert len(cycles) >= 1

    def test_empty_graph(self):
        """Test empty graph has no cycles."""
        graph = {
            "nodes": {},
            "adjacency": {},
        }

        cycles = find_cycles(graph)
        assert cycles == []
