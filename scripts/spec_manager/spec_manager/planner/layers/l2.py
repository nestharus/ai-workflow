# TODO(single-layer): RESTRUCTURE -> merge into Architecture phase planner.
#   L2's architecture discovery (manifests, entrypoints, wiring declarations) and
#   decision-point planning maps to the Architecture phase: emit wiring work items,
#   component structure changes, contract/adapter tasks, import-boundary violations,
#   shape-drift work items. Pin registry references must be removed. The discovery
#   and planning logic survives as the Architecture phase's strategy.
# ALGORITHM(single-layer):
#   References: response3 Sections 9.2 and 6.3.
#   Data structures:
#     - Planner identity becomes ArchitecturePhasePlanner.
#     - ArchitectureFinding: {shape_id: ShapeId, category: str, required_change_type: Literal['wiring_only','spec_change','behavior_change'], evidence_refs: list[str], target_files: list[str]}.
#       behavior_change is allowed within existing library boundaries (in-place algorithm remediation, §9.3).
#   Interface contracts:
#     - def discover(self, ctx: PlanningContext) -> dict[str, Any]
#     - def build_plan(self, ctx: PlanningContext, gaps: list[dict[str, Any]], discovery: dict[str, Any]) -> dict[str, Any]
#   Control flow:
#     1. Keep topology discovery (manifests/entrypoints/wiring) but remove pin registry assumptions.
#     2. Convert findings into architecture-phase outputs: wiring fixes, boundary violations,
#        shape drift tasks, component structure, contracts, adapters.
#     3. Architecture phase edits code via PromotionLoop IMPLEMENT step — can edit component
#        structure AND algorithm implementations in-place.
#     4. Any refactor-only finding is outside Architecture authority: BLOCK with diagnostics
#        (no forward-routing to Quality phase; phases are forward-only but work items
#        do not route across phases).
#   Error handling:
#     - Missing topology evidence returns blocked architecture finding with diagnostic.
#   Integration points:
#     - Selected by PhaseRouter for phase='architecture'.
#     - Consumes ShapeMatchReport and dependency scans.
# IMPL(single-layer): Architecture findings converted to work items should target
# `shape_id` + `created_in_phase='architecture'` and include
# `required_change_type`/`evidence_refs`; persistence should use
# `WorkItemStore.create/upsert` so evidence merges stay explicit.
#   Test requirements:
#     - Emits only allowed change types for architecture phase.
#     - Out-of-authority findings (e.g. refactor-only) produce block, not cross-phase re-route.

"""L2 (architecture) layer planner.

L2 routes architecture source artifacts (manifests, entrypoints, wiring
declarations) into a decision-point planning loop.
Discovery is scoped to the current slice context rather than scanning
the full workspace graph up front.

Tools (research and integration) are injected at construction time and are
optional -- ``None`` means "skip that capability for now".
Actual LLM invocations will be wired through the tool callables later;
this module structures the data and delegates.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from spec_manager.compliance.promotion.config import PhaseId

logger = logging.getLogger(__name__)

# Type alias for injected tool callables (all are optional).
_ToolFn = Callable[..., Any] | None
_ARCHITECTURE_PHASE: PhaseId = "architecture"
_ALLOWED_ARCH_CHANGE_TYPES = frozenset({"wiring_only", "spec_change", "behavior_change"})


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _normalize_mode(mode_value: Any) -> str:
    mode = str(mode_value or "auto").strip().lower()
    if mode == "interactive":
        return "interactive"
    return "auto"


def _estimate_touched_files(gaps: list[dict[str, Any]]) -> int:
    files: set[str] = set()
    for gap in gaps:
        file_value = gap.get("file")
        if isinstance(file_value, str) and file_value.strip():
            files.add(file_value.strip())
        target_files = gap.get("target_files")
        if isinstance(target_files, list):
            for item in target_files:
                text = str(item).strip()
                if text:
                    files.add(text)
    return len(files)


# ---------------------------------------------------------------------------
# Architecture topology helpers
# ---------------------------------------------------------------------------

_ARCH_FILE_GLOBS: list[str] = [
    "**/component_manifest.yaml",
    "**/component_manifest.yml",
    "**/entrypoints.yaml",
    "**/entrypoints.yml",
    "**/wiring.yaml",
    "**/wiring.yml",
    "**/event_handlers.yaml",
    "**/event_handlers.yml",
    "**/event_handlers.json",
    "**/handlers.yaml",
    "**/handlers.yml",
    "**/handlers.json",
    "**/routes.yaml",
    "**/routes.yml",
    "**/routes.json",
    "**/*architecture*.yaml",
    "**/*architecture*.yml",
    "**/*architecture*.json",
    "**/*arch*.yaml",
    "**/*arch*.yml",
    "**/*arch*.json",
    "**/*handler*.py",
    "**/*route*.py",
]

_ARCH_FILE_BASENAMES = frozenset(
    {
        "component_manifest.yaml",
        "component_manifest.yml",
        "entrypoints.yaml",
        "entrypoints.yml",
        "wiring.yaml",
        "wiring.yml",
        "event_handlers.yaml",
        "event_handlers.yml",
        "event_handlers.json",
        "handlers.yaml",
        "handlers.yml",
        "handlers.json",
        "routes.yaml",
        "routes.yml",
        "routes.json",
    }
)

_ARCH_FILE_HINT_EXTS = frozenset({".yaml", ".yml", ".json", ".toml", ".py", ".md", ".txt"})
_ARCH_FILE_HINT_TOKENS = (
    "manifest",
    "registry",
    "entrypoint",
    "wiring",
    "handler",
    "route",
    "architecture",
    "arch",
)
_PLANNER_DISCOVERY_CHUNK_SIZE = 12000


def _empty_topology() -> dict[str, Any]:
    """Return an empty architecture topology skeleton."""
    return {
        "nodes": [],
        "edges": [],
        "arch_files": [],
    }


def _is_relative_to(path: Path, candidate_parent: Path) -> bool:
    try:
        path.relative_to(candidate_parent)
    except ValueError:
        return False
    return True


def _discover_arch_files(*, workspace_root: Path | None, scope_roots: list[Path]) -> list[str]:
    """Return architecture file paths scoped to the current slice roots."""
    found: list[str] = []
    for scope_root in scope_roots:
        if not scope_root.is_dir():
            continue
        for pattern in _ARCH_FILE_GLOBS:
            for match in sorted(scope_root.glob(pattern)):
                if workspace_root is not None and _is_relative_to(match, workspace_root):
                    found.append(str(match.relative_to(workspace_root)))
                else:
                    found.append(str(match.relative_to(scope_root)))

        for match in sorted(scope_root.rglob("*")):
            if not match.is_file():
                continue
            if not _looks_like_arch_file_ref(str(match)):
                continue
            if workspace_root is not None and _is_relative_to(match, workspace_root):
                found.append(str(match.relative_to(workspace_root)))
            else:
                found.append(str(match.relative_to(scope_root)))

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _normalize_arch_file_ref(
    raw_ref: str,
    *,
    workspace_root: Path | None,
    scope_roots: list[Path],
) -> str:
    text = str(raw_ref).strip()
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        return text.replace("\\", "/")

    if workspace_root is not None and _is_relative_to(candidate, workspace_root):
        return str(candidate.relative_to(workspace_root)).replace("\\", "/")

    for scope_root in scope_roots:
        if _is_relative_to(candidate, scope_root):
            if workspace_root is not None and _is_relative_to(scope_root, workspace_root):
                rel = scope_root.relative_to(workspace_root) / candidate.relative_to(scope_root)
                return str(rel).replace("\\", "/")
            return str(candidate.relative_to(scope_root)).replace("\\", "/")

    return str(candidate).replace("\\", "/")


def _looks_like_arch_file_ref(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
    if basename in _ARCH_FILE_BASENAMES:
        return True
    suffix = Path(basename).suffix.lower()
    if suffix not in _ARCH_FILE_HINT_EXTS:
        return False
    basename_lower = basename.lower()
    return any(token in basename_lower for token in _ARCH_FILE_HINT_TOKENS)


def _extract_arch_file_refs_from_integration_payload(payload: Any) -> list[str]:
    refs: list[str] = []
    queue: list[Any] = [payload]

    while queue:
        item = queue.pop(0)
        if isinstance(item, str):
            if _looks_like_arch_file_ref(item):
                refs.append(item.strip())
            continue
        if isinstance(item, (list, tuple, set)):
            queue.extend(item)
            continue
        if not isinstance(item, dict):
            continue

        for key, value in item.items():
            lowered = str(key).strip().lower()
            if lowered in {
                "arch_files",
                "artifact_refs",
                "files",
                "paths",
                "scoped_arch_files",
                "routed_arch_files",
                "source_artifacts",
            }:
                queue.append(value)
                continue
            if lowered in {"file", "path", "source_file", "target_file"}:
                queue.append(value)
                continue
            if lowered in {"nodes", "edges"} and isinstance(value, list):
                for row in value:
                    if isinstance(row, dict):
                        queue.append(row.get("file"))
                        queue.append(row.get("path"))
                        queue.append(row.get("source_file"))
                        queue.append(row.get("target_file"))

    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def _coerce_json_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        payload = raw.to_dict()
        if isinstance(payload, dict):
            return payload

    text = str(raw).strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    json_like = _extract_first_json_object(text)
    if not json_like:
        return None
    try:
        payload = json.loads(json_like)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _chunk_text_with_offsets(text: str, *, max_chars: int) -> list[tuple[int, int, str]]:
    if max_chars <= 0:
        return [(0, len(text), text)]
    if not text:
        return [(0, 0, "")]
    chunks: list[tuple[int, int, str]] = []
    for offset_start in range(0, len(text), max_chars):
        offset_end = min(offset_start + max_chars, len(text))
        chunks.append((offset_start, offset_end, text[offset_start:offset_end]))
    return chunks


def _normalize_topology_graph(
    payload: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    if payload is None:
        return [], [], [], []

    graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else payload

    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    if not isinstance(raw_edges, list):
        raw_edges = []

    allowed_node_kinds = {"component", "edge", "handler", "route"}
    allowed_edge_kinds = {"provides", "consumes", "wired_to", "declared_in"}

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, row in enumerate(raw_nodes):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
        if kind not in allowed_node_kinds:
            continue

        node_id = str(row.get("id", "") or "").strip()
        if not node_id:
            name = str(row.get("name", row.get("label", "")) or "").strip()
            node_id = f"{kind}:{name or index}"
        if node_id in node_ids:
            continue
        node_ids.add(node_id)

        normalized = {
            "id": node_id,
            "kind": kind,
            "name": str(row.get("name", row.get("label", "")) or "").strip(),
            "file": str(row.get("file", row.get("path", "")) or "").strip().replace("\\", "/"),
        }
        for field in ("component", "handler", "route", "metadata"):
            if field in row:
                normalized[field] = row[field]
        nodes.append(normalized)

    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for row in raw_edges:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
        if kind not in allowed_edge_kinds:
            continue
        source = str(row.get("source", "") or "").strip()
        target = str(row.get("target", "") or "").strip()
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        marker = (source, target, kind)
        if marker in seen_edges:
            continue
        seen_edges.add(marker)
        edges.append({"source": source, "target": target, "kind": kind})

    arch_files: list[str] = []
    raw_arch_files = graph.get("arch_files", payload.get("arch_files", []))
    if isinstance(raw_arch_files, list):
        for ref in raw_arch_files:
            text = str(ref).strip()
            if text:
                arch_files.append(text)

    issues: list[str] = []
    if not nodes:
        issues.append("No topology nodes were produced from architecture discovery input.")
    if not edges:
        issues.append("No topology edges were produced from architecture discovery input.")

    return nodes, edges, arch_files, issues


# ---------------------------------------------------------------------------
# L2Planner
# ---------------------------------------------------------------------------


class L2DiscoveryRouter:
    """Discovery collaborator for L2 architecture artifacts."""

    def __init__(self, discover_fn: Callable[[Any], dict[str, Any]]) -> None:
        self._discover_fn = discover_fn

    def discover(self, ctx: Any) -> dict[str, Any]:
        return self._discover_fn(ctx)


class L2SkeletonPlanner:
    """Plan-building collaborator for L2 architecture wiring intentions."""

    def __init__(
        self,
        build_plan_fn: Callable[[Any, list[dict[str, Any]], dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._build_plan_fn = build_plan_fn

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_plan_fn(ctx, gaps, discovery)


class L2LayerResearchAdapter:
    """Research + constraints adapter for L2 planning and under-spec flow."""

    def __init__(
        self,
        *,
        research_tool: Any = None,
        constraints_tool: Any = None,
        resolve_under_spec_fn: Callable[
            [Any, list[dict[str, Any]], dict[str, Any]], dict[str, Any]
        ],
        resolve_signal_fn: Callable[[Any, Any], dict[str, Any] | None],
    ) -> None:
        self._research_tool = research_tool
        self._constraints_tool = constraints_tool
        self._resolve_under_spec_fn = resolve_under_spec_fn
        self._resolve_signal_fn = resolve_signal_fn

    def run_agent(self, prompt: str, *, ctx: Any | None = None, hint: str = "") -> str:
        return self.run_agent_result(prompt, ctx=ctx, hint=hint)["answer"]

    def run_agent_result(
        self,
        prompt: str,
        *,
        ctx: Any | None = None,
        hint: str = "",
    ) -> dict[str, str]:
        question = str(prompt or "").strip()
        if not question or self._research_tool is None:
            return {"answer": "", "error": ""}
        try:
            if callable(self._research_tool):
                raw = self._research_tool(question)
                return {"answer": str(raw).strip(), "error": ""}
            if hasattr(self._research_tool, "research"):
                from spec_manager.planner.tools.research_tool import ResearchQuery

                layer_context = self._build_research_context(ctx, hint)
                result = self._research_tool.research(
                    ResearchQuery(
                        question=question,
                        context=layer_context,
                        dimension="auto",
                        layer="architecture",
                        slice_id=self._slice_id_from_ctx(ctx),
                        hints={"hint": hint} if hint else {},
                    )
                )
                synthesis = str(getattr(result, "synthesis", "") or "").strip()
                if synthesis:
                    return {"answer": synthesis, "error": ""}
            if hasattr(self._research_tool, "search"):
                raw_search = self._research_tool.search(question, max_results=1)
                best_hit = getattr(raw_search, "best_hit", None)
                if best_hit is not None:
                    return {"answer": str(getattr(best_hit, "text", "") or "").strip(), "error": ""}
        except Exception as exc:
            logger.warning("L2 research query failed", exc_info=True)
            return {"answer": "", "error": str(exc).strip() or "research tool failure"}
        return {"answer": "", "error": ""}

    @staticmethod
    def _slice_id_from_ctx(ctx: Any | None) -> str:
        if ctx is None:
            return ""
        return str(getattr(ctx, "slice_id", "") or "").strip()

    @staticmethod
    def _build_research_context(ctx: Any | None, hint: str) -> str:
        if ctx is None:
            return hint
        mode = str(getattr(ctx, "mode", "") or "").strip().lower()
        run_id = str(getattr(ctx, "run_id", "") or "").strip()
        context_parts = ["phase=architecture"]
        if mode:
            context_parts.append(f"mode={mode}")
        if run_id:
            context_parts.append(f"run_id={run_id}")
        if hint:
            context_parts.append(f"hint={hint}")
        return " ".join(context_parts)

    def resolve_from_constraints(self, ctx: Any, question: str) -> str:
        return self.resolve_from_constraints_result(ctx, question)["answer"]

    def resolve_from_constraints_result(self, ctx: Any, question: str) -> dict[str, str]:
        if not question or self._constraints_tool is None:
            return {"answer": "", "error": ""}
        slice_id = str(getattr(ctx, "slice_id", "") or "__system__")
        try:
            if hasattr(self._constraints_tool, "check_coverage"):
                coverage = self._constraints_tool.check_coverage(slice_id, [question])
                if isinstance(coverage, dict):
                    record = coverage.get(question)
                    answer = str(getattr(record, "answer", "") or "").strip()
                    if answer:
                        return {"answer": answer, "error": ""}
        except Exception as exc:
            logger.warning("L2 constraints tool failed", exc_info=True)
            return {"answer": "", "error": str(exc).strip() or "constraints tool failure"}
        return {"answer": "", "error": ""}

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        return self._resolve_under_spec_fn(ctx, events, discovery)

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return self._resolve_signal_fn(ctx, signal)

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        query = str(kwargs.get("query") or (args[0] if args else "")).strip()
        if not query:
            return ""
        return self.run_agent(query)

    def search(self, query: str, max_results: int = 1) -> list[dict[str, Any]]:
        text = self.run_agent(query)
        if not text:
            return []
        return [{"text": text, "score": 0.5, "max_results": max_results}]


class L2Planner:
    """Architecture-layer planner.

    Satisfies the ``LayerPlanner`` protocol defined in
    ``spec_manager.planner.router``.

    Parameters
    ----------
    research_tool:
        Optional callable for research queries (e.g. LLM-based arch
        reasoning).  ``None`` to skip.
    integration_tool:
        Optional callable for integration / artifact routing analysis.
        ``None`` to skip.
    constraints_store_adapter:
        Optional orchestration adapter handle. L2 planning always runs
        the strategy pipeline and bootstraps constraints from workspace
        state.
    """
    # IMPL(single-layer): This planner remains the PhaseRouter target for
    # `phase='architecture'`; rename to ArchitecturePhasePlanner only when
    # router/trace/tool payload schemas migrate together.

    def __init__(
        self,
        research_tool: _ToolFn = None,
        integration_tool: _ToolFn = None,
        constraints_tool: _ToolFn = None,
        constraints_store_adapter: Any = None,
        work_item_store: Any = None,
        wait_graph: Any = None,
    ) -> None:
        self.phase: PhaseId = _ARCHITECTURE_PHASE
        self.layer: Literal["l2"] = "l2"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._constraints_tool = constraints_tool
        self._constraints_store_adapter = constraints_store_adapter
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph
        self._trace: Any | None = None

        self.discovery_router = L2DiscoveryRouter(self._discover_impl)
        self.skeleton_planner = L2SkeletonPlanner(self._build_plan_impl)
        self.layer_research_adapter = L2LayerResearchAdapter(
            research_tool=research_tool,
            constraints_tool=constraints_tool,
            resolve_under_spec_fn=self._resolve_under_spec_impl,
            resolve_signal_fn=self._resolve_signal_impl,
        )

    # ------------------------------------------------------------------
    # LayerPlanner interface
    # ------------------------------------------------------------------

    def bind_trace(self, trace: Any | None) -> None:
        self._trace = trace

    def discover(self, ctx: Any) -> dict[str, Any]:
        # IMPL(single-layer): Discovery outputs are deterministic architecture
        # evidence inputs; missing scope/topology evidence should propagate as
        # blocked architecture diagnostics, never speculative defaults.
        discovery = self.discovery_router.discover(ctx)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="discover",
            payload={
                "arch_files": len(discovery.get("arch_files", [])),
                "issues": len(discovery.get("discovery_issues", [])),
            },
        )
        return discovery

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        # IMPL(single-layer): Treat this as architecture-phase skeleton state
        # (Section 9.2). Freeze criteria should align to component/contract
        # inventory + verifier suite, not pin-coverage heuristics.
        return {
            "architecture_topology_graph": {
                "nodes": [row for row in discovery.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in discovery.get("edges", []) if isinstance(row, dict)],
                "arch_files": [
                    str(path) for path in discovery.get("arch_files", []) if str(path).strip()
                ],
            }
        }

    def _discover_impl(self, ctx: Any) -> dict[str, Any]:
        """Route slice-scoped architecture artifacts into a topology graph."""
        # IMPL(single-layer): Keep topology discovery scoped by owned slice roots
        # and deterministic artifacts; call-graph/LLM outputs are targeting hints
        # and must not decide authority or convergence.
        workspace_root, scope_roots = self._resolve_discovery_roots(ctx)
        routed_arch_files = _discover_arch_files(
            workspace_root=workspace_root,
            scope_roots=scope_roots,
        )

        topology = _empty_topology()
        topology["arch_files"] = routed_arch_files
        topology["scope_roots"] = [str(root) for root in scope_roots]
        discovery_issues: list[str] = []

        if not scope_roots:
            discovery_issues.append("No scoped architecture roots were resolved for this slice.")

        if not routed_arch_files:
            discovery_issues.append(
                "No architecture manifest files were discovered in scoped roots "
                "(component_manifest/entrypoints/handlers/routes/wiring)."
            )

        topology_payload, artifact_issues = self._derive_arch_topology(
            workspace_root=workspace_root,
            scope_roots=scope_roots,
            arch_files=routed_arch_files,
        )
        discovery_issues.extend(artifact_issues)
        nodes, edges, payload_arch_files, topology_issues = _normalize_topology_graph(
            topology_payload
        )

        topology["nodes"] = nodes
        topology["edges"] = edges
        discovery_issues.extend(topology_issues)

        merged_payload_arch_files = [
            _normalize_arch_file_ref(
                ref,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            for ref in payload_arch_files
        ]
        normalized_payload_arch_files = [ref for ref in merged_payload_arch_files if ref]
        for ref in normalized_payload_arch_files:
            if ref not in topology["arch_files"]:
                topology["arch_files"].append(ref)
        if normalized_payload_arch_files:
            topology["integration_artifact_refs"] = normalized_payload_arch_files

        if topology_payload is None and self._integration_tool is None:
            discovery_issues.append("No integration tool is configured for L2 topology discovery.")
        elif topology_payload is None:
            discovery_issues.append(
                "Integration tool returned no topology payload for L2 discovery."
            )
        elif topology_payload is not None:
            try:
                integration_refs = _extract_arch_file_refs_from_integration_payload(
                    topology_payload
                )
                merged_refs = [
                    _normalize_arch_file_ref(
                        ref,
                        workspace_root=workspace_root,
                        scope_roots=scope_roots,
                    )
                    for ref in integration_refs
                ]
                normalized_refs = [ref for ref in merged_refs if ref]
                for ref in normalized_refs:
                    if ref not in topology["arch_files"]:
                        topology["arch_files"].append(ref)
                topology["integration_artifact_refs"] = normalized_refs
            except Exception:
                logger.warning(
                    "L2 integration_tool failed during architecture topology extraction",
                    exc_info=True,
                )
                discovery_issues.append(
                    "Integration tool failed during architecture topology extraction."
                )

        if routed_arch_files and not topology["nodes"]:
            discovery_issues.append(
                "Architecture files were discovered but topology nodes were not produced."
            )

        topology["discovery_status"] = "ready" if not discovery_issues else "incomplete"
        # IMPL(single-layer): `discovery_status='incomplete'` should map to
        # blocked architecture findings with diagnostics (Section 9.3/11), not
        # cross-phase routing/demotion behavior.
        topology["discovery_issues"] = discovery_issues

        logger.debug(
            "L2 discover: %d scoped roots, %d arch files, %d integration refs, %d issues",
            len(scope_roots),
            len(topology["arch_files"]),
            len(topology.get("integration_artifact_refs", [])),
            len(discovery_issues),
        )
        return topology

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        plan = self.skeleton_planner.build_plan(ctx, gaps, discovery)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="build_plan",
            payload={
                "intentions": len(plan.get("intentions", [])),
                "decision_requirements": len(plan.get("decision_requirements", [])),
            },
        )
        return plan

    def _build_plan_impl(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce wiring intentions from *gaps* and architecture *discovery*.

        Always runs the full strategy pipeline (impact classification,
        constraint loading, problem framing, architecture decisions,
        candidate evaluation, authority checks).
        """
        discovery_status = str(discovery.get("discovery_status", "")).strip().lower()
        nodes = discovery.get("nodes", [])
        edges = discovery.get("edges", [])
        discovery_issues = discovery.get("discovery_issues", [])
        issues = [
            str(issue).strip()
            for issue in discovery_issues
            if isinstance(issue, str) and str(issue).strip()
        ]
        has_topology = isinstance(nodes, list) and bool(nodes) and isinstance(edges, list) and bool(edges)
        if discovery_status == "incomplete" and not has_topology:
            fallback_shape_id = str(getattr(ctx, "slice_id", "")).strip()
            blocked_findings: list[dict[str, Any]] = []
            source_gaps = gaps if gaps else [{}]
            for gap in source_gaps:
                payload = gap if isinstance(gap, dict) else {}
                blocked_findings.append(
                    {
                        "shape_id": self._resolve_shape_id(payload, fallback=fallback_shape_id),
                        "category": "missing_topology_evidence",
                        "required_change_type": "spec_change",
                        "evidence_refs": self._collect_evidence_refs(payload),
                        "target_files": self._collect_target_files(payload),
                        "created_in_phase": _ARCHITECTURE_PHASE,
                        "diagnostic": "Missing topology evidence blocks architecture planning.",
                    }
                )
            return {
                "intentions": [],
                "blocked": True,
                "blocked_findings": blocked_findings,
                "diagnostics": issues
                or ["Missing topology evidence blocks architecture planning."],
            }
        return self._build_plan_via_strategies(ctx, gaps, discovery)

    @staticmethod
    def _resolve_discovery_roots(ctx: Any) -> tuple[Path | None, list[Path]]:
        """Resolve directory roots to scan for architecture artifacts."""
        roots: list[Path] = []
        seen: set[Path] = set()

        workspace_value = str(getattr(ctx, "workspace_root", "") or "").strip()
        workspace_root = Path(workspace_value) if workspace_value else None
        if workspace_root is not None:
            try:
                workspace_root = workspace_root.resolve()
            except OSError:
                workspace_root = None
        if workspace_root is not None and not workspace_root.is_dir():
            workspace_root = None

        def _append_root(path: Path | None) -> None:
            if path is None:
                return
            try:
                resolved = path.resolve()
            except OSError:
                return
            if not resolved.is_dir() or resolved in seen:
                return
            seen.add(resolved)
            roots.append(resolved)

        slice_root_value = str(getattr(ctx, "slice_root", "") or "").strip()
        if slice_root_value:
            _append_root(Path(slice_root_value))

        slice_id = str(getattr(ctx, "slice_id", "") or "").strip()
        if workspace_root is not None and slice_id:
            _append_root(workspace_root / "libraries" / slice_id)

        metadata = getattr(ctx, "metadata", {})
        if isinstance(metadata, dict) and workspace_root is not None:
            for key in ("focus_libraries", "libraries", "library_ids"):
                libs = metadata.get(key)
                if not isinstance(libs, list):
                    continue
                for lib in libs:
                    lib_name = str(lib).strip()
                    if lib_name:
                        _append_root(workspace_root / "libraries" / lib_name)

        # Treat workspace root as scoped only when no multi-library layout exists.
        if not roots and workspace_root is not None and not (workspace_root / "libraries").exists():
            _append_root(workspace_root)

        return workspace_root, roots

    def _derive_arch_topology(
        self,
        *,
        workspace_root: Path | None,
        scope_roots: list[Path],
        arch_files: list[str],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if self._integration_tool is None:
            return None, []

        arch_artifacts, artifact_issues = self._load_arch_artifacts(
            arch_files=arch_files,
            workspace_root=workspace_root,
            scope_roots=scope_roots,
        )
        payload = {
            "task": "architecture_discovery_topology",
            "phase": _ARCHITECTURE_PHASE,
            "workspace_root": str(workspace_root) if workspace_root is not None else "",
            "scope_roots": [str(root) for root in scope_roots],
            "arch_files": arch_artifacts,
        }
        # IMPL(single-layer): Migrate payload identity from `layer=l2` to
        # `phase=architecture` atomically with integration adapters and trace
        # readers so mixed schemas are never emitted within one run.
        prompt = (
            "Produce strict JSON topology with keys: nodes, edges, arch_files. "
            "Node kinds: component|edge|handler|route. "
            "Edge kinds: provides|consumes|wired_to|declared_in."
        )
        # IMPL(single-layer): `pin` node/edge semantics are transitional only;
        # architecture routing authority should shift to shape ownership +
        # dependency/contract matching outputs (proposal Section 6.3).

        raw: Any = None
        tool = self._integration_tool
        try:
            if callable(tool):
                for kwargs in (
                    {"task": "architecture_discovery_topology", "prompt": prompt, "payload": payload},
                    {"prompt": prompt, "payload": payload},
                    {"payload": payload},
                    {"query": prompt},
                ):
                    try:
                        raw = tool(**kwargs)
                        break
                    except TypeError:
                        continue
                if raw is None:
                    raw = tool(prompt)
            elif hasattr(tool, "discover_architecture_topology"):
                raw = tool.discover_architecture_topology(payload)
            elif hasattr(tool, "discover"):
                raw = tool.discover(payload)
            elif hasattr(tool, "build_graph"):
                absolute_paths = [
                    str(candidate)
                    for ref in arch_files
                    for candidate in self._resolve_arch_ref_paths(
                        ref,
                        workspace_root=workspace_root,
                        scope_roots=scope_roots,
                    )
                ]
                raw = self._coerce_integration_graph_payload(
                    tool.build_graph(absolute_paths), arch_files
                )
        except Exception:
            logger.warning("L2 integration tool failed during topology derivation", exc_info=True)
            return None, artifact_issues

        payload_dict = _coerce_json_payload(raw)
        if payload_dict is None:
            return None, artifact_issues
        if "arch_files" not in payload_dict:
            payload_dict["arch_files"] = list(arch_files)
        return payload_dict, artifact_issues

    @staticmethod
    def _load_arch_artifacts(
        *,
        arch_files: list[str],
        workspace_root: Path | None,
        scope_roots: list[Path],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        artifacts: list[dict[str, Any]] = []
        issues: list[str] = []
        for ref in arch_files:
            candidate_paths = L2Planner._resolve_arch_ref_paths(
                ref,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            if not candidate_paths:
                artifacts.append(
                    {
                        "path": ref,
                        "content": "",
                        "content_length": 0,
                        "chunk_count": 0,
                        "chunks": [],
                        "read_error": "No candidate path resolved for architecture artifact.",
                    }
                )
                issues.append(f"{ref}: no readable path resolved for architecture artifact")
                continue
            loaded = False
            for candidate in candidate_paths:
                try:
                    content = candidate.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    issues.append(f"{ref}: utf-8 decode failed at {candidate} ({exc.reason})")
                    continue
                except OSError as exc:
                    issues.append(f"{ref}: read failed at {candidate} ({exc})")
                    continue
                chunks = _chunk_text_with_offsets(content, max_chars=_PLANNER_DISCOVERY_CHUNK_SIZE)
                artifacts.append(
                    {
                        "path": ref,
                        "content": content,
                        "content_length": len(content),
                        "chunk_count": len(chunks),
                        "chunks": [
                            {
                                "chunk_index": index,
                                "chunk_count": len(chunks),
                                "offset_start": offset_start,
                                "offset_end": offset_end,
                                "content": chunk_text,
                            }
                            for index, (offset_start, offset_end, chunk_text) in enumerate(chunks)
                        ],
                    }
                )
                loaded = True
                break
            if not loaded:
                artifacts.append(
                    {
                        "path": ref,
                        "content": "",
                        "content_length": 0,
                        "chunk_count": 0,
                        "chunks": [],
                        "read_error": "Failed to read architecture artifact "
                        "from all candidate paths.",
                    }
                )
        return artifacts, issues

    @staticmethod
    def _coerce_integration_graph_payload(graph: Any, arch_files: list[str]) -> dict[str, Any]:
        payload: dict[str, Any]
        if hasattr(graph, "to_dict") and callable(graph.to_dict):
            payload = graph.to_dict()
        elif isinstance(graph, dict):
            payload = dict(graph)
        else:
            payload = {"nodes": [], "edges": []}

        raw_nodes = payload.get("nodes", [])
        raw_edges = payload.get("edges", [])
        if not isinstance(raw_nodes, list):
            raw_nodes = []
        if not isinstance(raw_edges, list):
            raw_edges = []

        node_kind_map = {"component": "component", "edge": "edge"}
        edge_kind_map = {
            "provides": "provides",
            "consumes": "consumes",
            "wired_to": "wired_to",
            "depends_on": "consumes",
            "declared_in": "declared_in",
        }

        nodes: list[dict[str, Any]] = []
        for index, row in enumerate(raw_nodes):
            if not isinstance(row, dict):
                continue
            raw_kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
            kind = node_kind_map.get(raw_kind)
            if not kind:
                continue
            node_id = str(row.get("id", row.get("node_id", "")) or "").strip()
            if not node_id:
                node_id = f"{kind}:{index}"
            nodes.append(
                {
                    "id": node_id,
                    "kind": kind,
                    "name": str(row.get("name", row.get("label", "")) or "").strip(),
                    "file": str(row.get("file", "") or "").strip(),
                }
            )

        node_ids = {node["id"] for node in nodes}
        edges: list[dict[str, Any]] = []
        for row in raw_edges:
            if not isinstance(row, dict):
                continue
            raw_kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
            kind = edge_kind_map.get(raw_kind)
            if not kind:
                continue
            source = str(row.get("source", "") or "").strip()
            target = str(row.get("target", "") or "").strip()
            if not source or not target:
                continue
            if source not in node_ids or target not in node_ids:
                continue
            edges.append({"source": source, "target": target, "kind": kind})

        return {
            "nodes": nodes,
            "edges": edges,
            "arch_files": list(arch_files),
        }

    @staticmethod
    def _dedupe_non_empty(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = str(value).strip().replace("\\", "/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @classmethod
    def _collect_target_files(cls, *payloads: dict[str, Any]) -> list[str]:
        files: list[str] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in ("file", "target_file", "path", "module_path"):
                value = str(payload.get(key, "")).strip()
                if value:
                    files.append(value)
            for key in ("target_files", "file_targets"):
                values = payload.get(key)
                if isinstance(values, list):
                    files.extend(str(item).strip() for item in values if str(item).strip())
            location = payload.get("location")
            if isinstance(location, dict):
                location_file = str(location.get("file_path") or location.get("file") or "").strip()
                if location_file:
                    files.append(location_file)
            file_locations = payload.get("file_locations")
            if isinstance(file_locations, list):
                for row in file_locations:
                    if not isinstance(row, dict):
                        continue
                    file_path = str(row.get("file_path") or row.get("file") or "").strip()
                    if file_path:
                        files.append(file_path)
        return cls._dedupe_non_empty(files)

    @classmethod
    def _collect_evidence_refs(cls, *payloads: dict[str, Any]) -> list[str]:
        refs: list[str] = []

        def _extend(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                text = value.strip()
                if text:
                    refs.append(text)
                return
            if isinstance(value, list | tuple | set):
                for item in value:
                    _extend(item)
                return
            if isinstance(value, dict):
                for key in (
                    "evidence_refs",
                    "trigger_evidence",
                    "source_refs",
                    "spec_ref",
                    "spec_comment_ref",
                    "ref",
                    "source_file",
                    "file",
                    "path",
                ):
                    if key in value:
                        _extend(value.get(key))

        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in (
                "evidence_refs",
                "trigger_evidence",
                "source_refs",
                "spec_refs",
                "spec_ref",
                "spec_comment_ref",
            ):
                _extend(payload.get(key))

        return cls._dedupe_non_empty(refs)

    @staticmethod
    def _resolve_shape_id(*payloads: dict[str, Any], fallback: str = "") -> str:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in ("shape_id", "owner_shape_id"):
                value = str(payload.get(key, "")).strip()
                if value:
                    return value
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                for key in ("shape_id", "owner_shape_id"):
                    value = str(metadata.get(key, "")).strip()
                    if value:
                        return value
            for key in ("component_id", "id"):
                value = str(payload.get(key, "")).strip()
                if value:
                    return value
        return str(fallback).strip()

    @staticmethod
    def _normalize_required_change_type(value: Any, *, default: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"behavior_change", "wiring_only", "spec_change", "refactor_only"}:
            return normalized
        return str(default).strip().lower() or "wiring_only"

    @staticmethod
    def _resolve_finding_detail(*payloads: dict[str, Any]) -> str:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in ("approach", "details", "summary", "description", "reason"):
                detail = str(payload.get(key, "")).strip()
                if not detail:
                    continue
                if detail in {"stub_proposal", "parse_error", "No LLM available"}:
                    continue
                return detail
        return ""

    @staticmethod
    def _resolve_finding_category(required_change_type: str, *payloads: dict[str, Any]) -> str:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in ("category", "kind"):
                category = str(payload.get(key, "")).strip().lower()
                if category:
                    return category
        if required_change_type == "wiring_only":
            return "wiring_fix"
        if required_change_type == "spec_change":
            return "contract_or_structure"
        if required_change_type == "behavior_change":
            return "behavior_remediation"
        return "architecture_change"

    @classmethod
    def _build_architecture_finding(
        cls,
        *,
        intention: dict[str, Any],
        gap: dict[str, Any],
        fallback_shape_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        required_change_type = cls._normalize_required_change_type(
            intention.get("required_change_type", gap.get("required_change_type", "")),
            default="wiring_only",
        )
        shape_id = cls._resolve_shape_id(intention, gap, fallback=fallback_shape_id)
        evidence_refs = cls._collect_evidence_refs(intention, gap)
        target_files = cls._collect_target_files(intention, gap)
        detail = cls._resolve_finding_detail(intention, gap)
        category = cls._resolve_finding_category(required_change_type, intention, gap)

        if required_change_type == "refactor_only":
            blocked = {
                "shape_id": shape_id,
                "category": category,
                "required_change_type": required_change_type,
                "evidence_refs": evidence_refs,
                "target_files": target_files,
                "created_in_phase": _ARCHITECTURE_PHASE,
                "diagnostic": (
                    "Refactor-only finding is outside architecture authority; "
                    "block for explicit quality-phase triage."
                ),
            }
            if detail:
                blocked["summary"] = detail
            return None, blocked

        if not shape_id:
            blocked = {
                "shape_id": "",
                "category": category,
                "required_change_type": required_change_type,
                "evidence_refs": evidence_refs,
                "target_files": target_files,
                "created_in_phase": _ARCHITECTURE_PHASE,
                "diagnostic": "Architecture finding is missing deterministic shape ownership.",
            }
            if detail:
                blocked["summary"] = detail
            return None, blocked

        finding = {
            "shape_id": shape_id,
            "category": category,
            "required_change_type": required_change_type,
            "evidence_refs": evidence_refs,
            "target_files": target_files,
            "created_in_phase": _ARCHITECTURE_PHASE,
        }
        if detail:
            finding["summary"] = detail
        return finding, None

    @classmethod
    def _build_gap_intentions(
        cls,
        gaps: list[dict[str, Any]],
        *,
        fallback_shape_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build architecture findings directly from gap payloads."""
        # IMPL(single-layer): Intention payloads should converge to architecture
        # work-item contracts (`shape_id`, `created_in_phase='architecture'`,
        # `required_change_type`, `evidence_refs`); file refs stay as hints.
        findings: list[dict[str, Any]] = []
        blocked_findings: list[dict[str, Any]] = []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            finding, blocked = cls._build_architecture_finding(
                intention={},
                gap=gap,
                fallback_shape_id=fallback_shape_id,
            )
            if finding is not None:
                findings.append(finding)
            if blocked is not None:
                blocked_findings.append(blocked)
        return findings, blocked_findings

    @classmethod
    def _normalize_intentions_for_output(
        cls,
        intentions: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
        *,
        fallback_shape_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Project strategy outputs onto architecture-phase finding contracts."""
        # IMPL(single-layer): Normalization is the migration seam where strategy
        # outputs must be projected onto shared phase-local work-item fields and
        # out-of-authority `refactor_only` findings surfaced as block diagnostics.
        normalized: list[dict[str, Any]] = []
        blocked_findings: list[dict[str, Any]] = []
        for index, intention in enumerate(intentions):
            if not isinstance(intention, dict):
                continue
            gap = gaps[index] if index < len(gaps) and isinstance(gaps[index], dict) else {}
            finding, blocked = cls._build_architecture_finding(
                intention=intention,
                gap=gap,
                fallback_shape_id=fallback_shape_id,
            )
            if finding is not None:
                normalized.append(finding)
            if blocked is not None:
                blocked_findings.append(blocked)
        return normalized, blocked_findings

    @staticmethod
    def _normalize_decision_requirements_for_output(
        requirements: list[Any],
    ) -> list[dict[str, Any]]:
        """Normalize decision requirements into a stable intention-embedded shape."""
        normalized: list[dict[str, Any]] = []
        for requirement in requirements:
            if isinstance(requirement, dict):
                payload = dict(requirement)
            elif hasattr(requirement, "to_dict") and callable(requirement.to_dict):
                raw_payload = requirement.to_dict()
                if not isinstance(raw_payload, dict):
                    continue
                payload = dict(raw_payload)
            else:
                continue

            decision_id = str(payload.get("decision_id", "")).strip()
            if not decision_id:
                continue
            payload["decision_id"] = decision_id
            payload["question"] = str(payload.get("question", "")).strip()
            payload["kind"] = str(payload.get("kind", "")).strip()
            payload["dimension"] = str(payload.get("dimension", "software")).strip() or "software"
            payload["impact"] = str(payload.get("impact", "")).strip()

            scope_hint = str(payload.get("scope_hint", "")).strip()
            if not scope_hint:
                scope_hint = str(payload.get("scope", "")).strip()
            if scope_hint:
                payload["scope_hint"] = scope_hint

            options = payload.get("options", [])
            payload["options"] = (
                [str(option).strip() for option in options if str(option).strip()]
                if isinstance(options, list)
                else []
            )

            needed_for_raw = payload.get("needed_for", [])
            if isinstance(needed_for_raw, list):
                needed_for = [
                    str(target).strip() for target in needed_for_raw if str(target).strip()
                ]
            elif str(needed_for_raw).strip():
                needed_for = [str(needed_for_raw).strip()]
            else:
                needed_for = []
            payload["needed_for"] = needed_for
            normalized.append(payload)
        return normalized

    @staticmethod
    def _find_requirement_intention_index(
        intentions: list[dict[str, Any]],
        requirement: dict[str, Any],
    ) -> int | None:
        needed_for = requirement.get("needed_for", [])
        needed_tokens = {
            str(target).strip().lower() for target in needed_for if str(target).strip()
        }
        if not needed_tokens:
            return None

        for index, intention in enumerate(intentions):
            shape_id = str(intention.get("shape_id", "")).strip().lower()
            if shape_id and shape_id in needed_tokens:
                return index

            target_files = intention.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            normalized_targets = [
                str(path).strip().lower() for path in target_files if str(path).strip()
            ]
            if any(
                any(token in target for target in normalized_targets) for token in needed_tokens
            ):
                return index

            target_file = str(intention.get("target_file", "")).strip().lower()
            if target_file and any(token in target_file for token in needed_tokens):
                return index

        return None

    @classmethod
    def _attach_decision_requirements_to_intentions(
        cls,
        intentions: list[dict[str, Any]],
        decision_requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not decision_requirements:
            return intentions

        if not intentions:
            return [
                {
                    "shape_id": "",
                    "target_files": [],
                    "category": "decision_requirement",
                    "required_change_type": "spec_change",
                    "created_in_phase": _ARCHITECTURE_PHASE,
                    "summary": "Resolve planning decision requirements before implementation.",
                    "evidence_refs": [],
                    "decision_requirements": [dict(item) for item in decision_requirements],
                }
            ]

        enriched_intentions = [dict(intention) for intention in intentions]
        for intention in enriched_intentions:
            decision_reqs = intention.get("decision_requirements", [])
            if isinstance(decision_reqs, list):
                intention["decision_requirements"] = [
                    dict(item) for item in decision_reqs if isinstance(item, dict)
                ]
            else:
                intention["decision_requirements"] = []

        for requirement in decision_requirements:
            target_index = cls._find_requirement_intention_index(enriched_intentions, requirement)
            if target_index is None:
                target_index = 0
            enriched_intentions[target_index]["decision_requirements"].append(dict(requirement))

        return enriched_intentions

    def _build_plan_via_strategies(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the strategy pipeline for L2 plan building."""
        from spec_manager.planner.strategies.architecture_strategy import (
            ArchitecturePlannerStrategy,
        )
        from spec_manager.planner.strategies.authority_strategy import AuthorityDeciderStrategy
        from spec_manager.planner.strategies.constraint_strategies import (
            CandidateEvaluatorStrategy,
            ConstraintBootstrapStrategy,
            ConstraintEnricherStrategy,
            ImpactClassifierStrategy,
            NonSoftwareChecklistStrategy,
            ProblemFramerStrategy,
            QuestionComposerStrategy,
            TradeoffMapperStrategy,
        )
        from spec_manager.planner.strategies.protocol import PlanningSession, PlanningSessionRunner

        workspace_root = Path(getattr(ctx, "workspace_root", "") or "")
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        security_privacy_compliance = _coerce_bool(
            metadata.get("security_privacy_compliance", False)
        )
        security_privacy_compliance = (
            security_privacy_compliance
            or _coerce_bool(metadata.get("introduces_security_privacy_compliance", False))
            or _coerce_bool(metadata.get("has_security_privacy_compliance_implication", False))
        )

        session_ctx: dict[str, Any] = {
            "phase": _ARCHITECTURE_PHASE,
            "layer": "L2",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
            "mode": mode,
            "interactive": mode == "interactive",
            "touched_files_count": _estimate_touched_files(gaps),
            "introduces_external_dep": _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": security_privacy_compliance,
            "bundle_ref": getattr(ctx, "bundle_ref", None),
            "metadata": metadata,
        }
        # IMPL(single-layer): Session context vocabulary must migrate
        # atomically (`layer=L2` -> `phase=architecture`) with planner strategy
        # consumers and persisted artifacts.

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )

        run_agent = self.layer_research_adapter.run_agent

        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=run_agent),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            ArchitecturePlannerStrategy(
                workspace_root,
                run_agent=run_agent,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
                evidence_tool=self.layer_research_adapter,
            ),
            CandidateEvaluatorStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=run_agent),
        ]

        runner = PlanningSessionRunner(strategies)
        fallback_shape_id = str(getattr(ctx, "slice_id", "")).strip()
        try:
            session = runner.run(session)
        except Exception as exc:
            logger.warning("L2 strategy pipeline failed; using gap-derived findings", exc_info=True)
            fallback_findings, blocked_findings = self._build_gap_intentions(
                gaps,
                fallback_shape_id=fallback_shape_id,
            )
            fallback_findings = [
                finding
                for finding in fallback_findings
                if finding.get("required_change_type") in _ALLOWED_ARCH_CHANGE_TYPES
            ]
            diagnostics = [
                "Architecture strategy pipeline failed; fallback findings were derived from gaps.",
                str(exc).strip() or "strategy_pipeline_failure",
            ]
            result: dict[str, Any] = {"intentions": fallback_findings}
            if blocked_findings:
                result["blocked"] = True
                result["blocked_findings"] = blocked_findings
            result["diagnostics"] = diagnostics
            return result

        intentions, blocked_findings = self._normalize_intentions_for_output(
            session.intentions,
            gaps,
            fallback_shape_id=fallback_shape_id,
        )
        if not intentions and gaps:
            gap_findings, gap_blocked = self._build_gap_intentions(
                gaps,
                fallback_shape_id=fallback_shape_id,
            )
            intentions = gap_findings
            blocked_findings.extend(gap_blocked)
        intentions = [
            finding
            for finding in intentions
            if finding.get("required_change_type") in _ALLOWED_ARCH_CHANGE_TYPES
        ]
        decision_requirements = self._normalize_decision_requirements_for_output(
            session.decision_requirements
        )
        intentions = self._attach_decision_requirements_to_intentions(
            intentions=intentions,
            decision_requirements=decision_requirements,
        )

        result: dict[str, Any] = {"intentions": intentions}
        if blocked_findings:
            result["blocked"] = True
            result["blocked_findings"] = blocked_findings
            result["diagnostics"] = [
                str(finding.get("diagnostic", "")).strip()
                for finding in blocked_findings
                if str(finding.get("diagnostic", "")).strip()
            ]
        # IMPL(single-layer): Architecture plan outputs should stay phase-local;
        # findings outside architecture authority must return blocked diagnostics
        # rather than being forwarded to other phases.
        if session.new_constraints:
            constraints_to_write = [
                constraint.to_dict()
                for constraint in session.new_constraints
                if constraint.authority_required != "planner_ok"
            ]
            if constraints_to_write:
                result["new_constraints_to_write"] = constraints_to_write
        if session.under_spec_events:
            result["under_spec_events"] = session.under_spec_event_dicts()
        if session.decision_outcomes:
            result["decision_outcomes"] = [o.to_dict() for o in session.decision_outcomes]
        return result

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        # IMPL(single-layer): Under-spec remains a block-or-resolve decision in
        # the active phase; unresolved ambiguity should not trigger cross-phase
        # rerouting.
        result = self.layer_research_adapter.resolve_under_spec(ctx, events, discovery)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="resolve_under_spec",
            payload={
                "blocked": bool(result.get("blocked", False)),
                "resolved_constraints": len(result.get("constraints", {})),
                "questions": len(result.get("questions", [])),
            },
        )
        return result

    def _resolve_under_spec_impl(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Try to resolve under-spec events using architecture context.

        Resolution strategy (in order):
        1. Query constraints first for authoritative answers.
        2. Use routed architecture artifacts from *discovery* when constraints
           do not already answer the question.
        3. Ask the shared research tool for additional evidence.
        4. If still unresolved, return ``blocked=True`` with questions
           for human input.
        """
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        if mode == "interactive":
            questions = self._compose_interactive_under_spec_questions(events, discovery)
            return {
                "blocked": bool(questions),
                "constraints": {},
                "questions": questions,
            }

        workspace_root = self._resolve_workspace_root(getattr(ctx, "workspace_root", ""))
        scope_roots = self._collect_discovery_scope_roots(discovery)
        arch_file_refs = self._collect_discovery_arch_file_refs(discovery)
        resolved_constraints: dict[str, str] = {}
        remaining_questions: list[str] = []
        resolution_failures: list[dict[str, str]] = []

        for event_index, event in enumerate(events):
            question = str(event.get("question", event.get("description", ""))).strip()
            constraint_key = self._event_resolution_key(event, event_index)

            # Strategy 1: constraints first.
            constraint_result = self.layer_research_adapter.resolve_from_constraints_result(
                ctx, question
            )
            constraint_answer = constraint_result["answer"]
            if constraint_answer:
                resolved_constraints[constraint_key] = constraint_answer
                continue
            if constraint_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "constraints_tool",
                        "event_key": constraint_key,
                        "question": question,
                        "error": constraint_result["error"],
                    }
                )

            # Strategy 2: gather routed architecture evidence (does not auto-resolve).
            artifact_refs = self._resolve_event_from_artifacts(
                event=event,
                question=question,
                arch_file_refs=arch_file_refs,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            artifact_context = self._format_artifact_ref_context(artifact_refs)

            # Strategy 3: shared research lookup.
            research_prompt = question
            if artifact_context:
                research_prompt = (
                    f"{question}\nKnown architecture evidence: {artifact_context}\n"
                    "Use this evidence only as context and avoid speculative commitments."
                )
            answer_result = self.layer_research_adapter.run_agent_result(
                research_prompt,
                ctx=ctx,
                hint="under_spec",
            )
            answer = answer_result["answer"]
            if answer:
                resolved_constraints[constraint_key] = answer
                continue
            if answer_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "research_tool",
                        "event_key": constraint_key,
                        "question": question,
                        "error": answer_result["error"],
                    }
                )

            # Strategy 4: cannot resolve -- block.
            if question:
                if artifact_context:
                    remaining_questions.append(
                        f"{question} Known architecture evidence: {artifact_context}"
                    )
                else:
                    remaining_questions.append(question)
            elif constraint_key:
                remaining_questions.append(f"Cannot resolve under-spec event: {constraint_key}")

        blocked = len(remaining_questions) > 0
        return {
            "blocked": blocked,
            "constraints": resolved_constraints,
            "questions": remaining_questions,
            "resolution_failures": resolution_failures,
        }

    def _compose_interactive_under_spec_questions(
        self,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> list[str]:
        """Build question-first under-spec prompts with routed artifact context."""
        arch_file_refs = self._collect_discovery_arch_file_refs(discovery)
        questions: list[str] = []

        for event in events:
            event_id = str(event.get("id", event.get("event_id", ""))).strip()
            base_question = str(event.get("question", event.get("description", ""))).strip()
            if not base_question and event_id:
                base_question = f"What requirement should resolve decision {event_id}?"
            if not base_question:
                base_question = "What requirement should resolve this architecture ambiguity?"

            artifact_refs = self._resolve_event_from_artifacts(
                event=event,
                question=base_question,
                arch_file_refs=arch_file_refs,
                workspace_root=None,
                scope_roots=[],
            )
            artifact_context = self._format_artifact_ref_context(artifact_refs)
            if artifact_context:
                questions.append(f"{base_question} Known artifacts: {artifact_context}")
                continue

            questions.append(
                f"{base_question} Missing routed artifact detail: specify "
                "source/target components, interfaces/contracts, and the "
                "architecture files that define them."
            )
        return questions

    @staticmethod
    def _event_resolution_key(event: dict[str, Any], event_index: int) -> str:
        event_id = str(event.get("event_id", event.get("id", ""))).strip()
        if event_id:
            return event_id
        question = str(event.get("question", event.get("description", ""))).strip()
        if question:
            digest = sha256(question.encode("utf-8")).hexdigest()[:12]
            return f"event:{event_index + 1}:{digest}"
        return f"event:{event_index + 1}"

    @staticmethod
    def _format_artifact_ref_context(refs: list[str], *, limit: int = 5) -> str:
        if not refs:
            return ""
        shown = refs[: max(limit, 1)]
        suffix = f" (+{len(refs) - len(shown)} more)" if len(refs) > len(shown) else ""
        return f"relevant_refs={', '.join(shown)}{suffix}"

    @staticmethod
    def _resolve_workspace_root(workspace_root_value: Any) -> Path | None:
        text = str(workspace_root_value or "").strip()
        if not text:
            return None
        try:
            path = Path(text).resolve()
        except OSError:
            return None
        return path if path.is_dir() else None

    @staticmethod
    def _collect_discovery_scope_roots(discovery: dict[str, Any]) -> list[Path]:
        raw_roots = discovery.get("scope_roots", [])
        if not isinstance(raw_roots, list):
            return []
        roots: list[Path] = []
        seen: set[Path] = set()
        for raw in raw_roots:
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                candidate = Path(text).resolve()
            except OSError:
                continue
            if not candidate.is_dir() or candidate in seen:
                continue
            seen.add(candidate)
            roots.append(candidate)
        return roots

    @staticmethod
    def _collect_discovery_arch_file_refs(discovery: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in ("arch_files", "integration_artifact_refs"):
            value = discovery.get(key, [])
            if not isinstance(value, list):
                continue
            refs.extend(str(item).strip() for item in value if str(item).strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped

    @staticmethod
    def _resolve_arch_ref_paths(
        ref: str,
        *,
        workspace_root: Path | None,
        scope_roots: list[Path],
    ) -> list[Path]:
        text = str(ref).strip()
        if not text:
            return []

        normalized = text.replace("\\", "/")
        candidates: list[Path] = []
        maybe_path = Path(normalized)
        if maybe_path.is_absolute():
            candidates.append(maybe_path)
        else:
            if workspace_root is not None:
                candidates.append(workspace_root / maybe_path)
            for scope_root in scope_roots:
                candidates.append(scope_root / maybe_path)

        resolved: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                path = candidate.resolve()
            except OSError:
                continue
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            resolved.append(path)
        return resolved

    @staticmethod
    def _collect_event_terms(event: dict[str, Any], question: str) -> set[str]:
        terms: set[str] = set()
        for key in (
            "component_id",
            "target",
            "file",
            "symbol",
            "source_component",
            "target_component",
            "event_id",
            "contract_name",
            "event_name",
        ):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                terms.add(value.strip().lower())

        question_text = str(question or "").strip().lower()
        if question_text:
            terms.add(question_text)
            for token in re.split(r"[^a-z0-9._:/#-]+", question_text):
                if len(token) >= 3:
                    terms.add(token)

        return {term for term in terms if term}

    @staticmethod
    def _resolve_event_from_artifacts(
        event: dict[str, Any],
        question: str,
        arch_file_refs: list[str],
        workspace_root: Path | None,
        scope_roots: list[Path],
    ) -> list[str]:
        """Return routed architecture refs that provide evidence for this event."""
        if not arch_file_refs:
            return []

        terms = L2Planner._collect_event_terms(event, question)
        if not terms:
            return []

        matched_refs: list[str] = []
        for ref in arch_file_refs[:80]:
            ref_text = ref.lower()
            if any(term in ref_text for term in terms):
                matched_refs.append(ref)
                continue

            if workspace_root is None and not scope_roots:
                continue

            candidate_paths = L2Planner._resolve_arch_ref_paths(
                ref,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            if not candidate_paths:
                continue

            for candidate in candidate_paths:
                try:
                    contents = candidate.read_text(encoding="utf-8").lower()
                except UnicodeDecodeError:
                    continue
                except OSError:
                    continue
                if any(term in contents for term in terms):
                    matched_refs.append(ref)
                    break

        if not matched_refs:
            return []
        return list(dict.fromkeys(matched_refs))

    @staticmethod
    def _coerce_evidence_answer(evidence_hit: Any) -> str:
        """Normalize evidence-tool responses to a persisted string answer."""
        if evidence_hit is None:
            return ""
        if isinstance(evidence_hit, str):
            return evidence_hit.strip()
        if isinstance(evidence_hit, dict):
            for key in ("answer", "text", "synthesis", "detail"):
                value = evidence_hit.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        best_hit = getattr(evidence_hit, "best_hit", None)
        if best_hit is not None:
            text = getattr(best_hit, "text", "")
            if isinstance(text, str) and text.strip():
                return text.strip()
        text = getattr(evidence_hit, "text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()
        rendered = str(evidence_hit).strip()
        return rendered[:1000] if rendered else ""

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return self.layer_research_adapter.resolve_signal(ctx, signal)

    def _resolve_signal_impl(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Attempt to resolve an ambiguity signal from architecture context.

        Uses the shared research adapter to fetch prior evidence that may
        clarify the signal. Returns ``None`` when unresolved.
        """
        if signal is None:
            return None

        signal_text = signal if isinstance(signal, str) else getattr(signal, "text", str(signal))
        result = self.layer_research_adapter.run_agent_result(
            str(signal_text),
            ctx=ctx,
            hint="signal",
        )
        if result["answer"]:
            return {
                "resolved": True,
                "source": "research_tool",
                "detail": result["answer"],
            }
        if result["error"]:
            return {
                "resolved": False,
                "source": "research_tool",
                "error": result["error"],
            }
        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal into scoped architecture decision work."""
        # IMPL(single-layer): Triage should persist architecture-scoped work items
        # through create/upsert semantics keyed by shape/scope with deterministic
        # evidence refs; avoid add-only flows that obscure evidence merges.
        if not isinstance(signal, dict):
            return {"action": "NOOP", "monitors": []}

        inter_scope = _extract_inter_scope_from_signal(signal)
        if inter_scope is None:
            return {"action": "NOOP", "monitors": []}

        summary = _extract_signal_summary(signal, scope=inter_scope)
        trigger_refs = _collect_signal_trigger_refs(signal)
        decision_hash = sha256(f"{inter_scope}|{summary}".encode()).hexdigest()[:12]
        decision_id = f"DEC-{decision_hash}"
        work_item_id = decision_id

        target_slice = str(getattr(ctx, "slice_id", "") or "").strip()
        if not target_slice:
            target_slice = _parse_inter_scope_components(inter_scope)[0]
        run_id = str(getattr(ctx, "run_id", "") or "").strip()
        routed_shape_id = self._resolve_shape_id(signal, fallback=target_slice)
        signal_id = str(signal.get("signal_id", "")).strip()

        location = _extract_signal_location(signal)
        routing_payload = _build_arch_decision_routing_payload(
            work_item_id=work_item_id,
            summary=summary,
            run_id=run_id,
            slice_id=target_slice,
            shape_id=routed_shape_id,
            scope=inter_scope,
            trigger_refs=trigger_refs,
            location=location,
        )

        existing_work_item_status = ""
        if self._work_item_store is not None:
            try:
                from spec_manager.orchestration.coordination.work_items import WorkItem

                work_item = WorkItem.from_dict(routing_payload)
                existing = self._work_item_store.get(work_item_id)
                if existing is None:
                    self._work_item_store.create(work_item)
                else:
                    existing_work_item_status = str(getattr(existing, "status", "")).strip().upper()
                    if existing_work_item_status != "DECIDED":
                        upsert_payload = work_item.to_dict()
                        if existing_work_item_status == "OPEN":
                            upsert_payload["status"] = "EXPLORING"
                        elif existing_work_item_status == "EXPLORING":
                            upsert_payload["status"] = "OPEN"
                        elif existing_work_item_status == "BLOCKED":
                            upsert_payload["status"] = "EXPLORING"
                        else:
                            upsert_payload["status"] = existing_work_item_status
                        self._work_item_store.upsert(
                            WorkItem.from_dict(upsert_payload),
                            merge_policy="append_evidence",
                        )
                    routing_payload = {}
            except Exception:
                logger.warning(
                    "Failed to persist L2 ARCH_DECISION triage work item for scope %s",
                    inter_scope,
                    exc_info=True,
                )

        if existing_work_item_status == "DECIDED":
            return {
                "action": "WAKE_IMMEDIATELY",
                "monitors": [],
                "routing": [],
                "scope": inter_scope,
                "why": "cross_boundary_decision_already_resolved",
            }

        monitor = {
            "type": "work_item_done",
            "work_item_id": work_item_id,
            "required_status": "DECIDED",
            "kind": "work_item_status",
            "signal_id": signal_id,
            "run_id": run_id,
            "timeout_seconds": 3600,
        }
        if routing_payload:
            return {
                "action": "ROUTE_AND_WAIT",
                "routing": [routing_payload],
                "monitors": [monitor],
                "scope": inter_scope,
                "why": "cross_boundary_evidence_requires_architecture_decision",
            }

        return {
            "action": "WAIT_ON_WORK_ITEM",
            "routing": [],
            "monitors": [monitor],
            "scope": inter_scope,
            "why": "cross_boundary_evidence_waiting_existing_architecture_decision",
        }


def _emit_trace_event(
    trace: Any | None,
    *,
    layer: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    if trace is None or not hasattr(trace, "add_artifact"):
        return
    existing = getattr(trace, "artifacts", {}).get("layer_events", [])
    events = (
        [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    )
    events.append({"layer": layer, "event": event, "payload": payload})
    trace.add_artifact("layer_events", events)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_inter_scope_from_signal(signal: dict[str, Any]) -> str | None:
    for mapping in _walk_mappings(signal):
        scope_candidate = _normalize_inter_scope(mapping.get("scope"))
        if scope_candidate:
            return scope_candidate

    for mapping in _walk_mappings(signal):
        source_lib, target_lib = _extract_library_pair(mapping)
        if not source_lib or not target_lib or source_lib == target_lib:
            continue
        interaction_handle = _extract_interaction_handle(mapping)
        if not interaction_handle:
            continue
        return f"inter:{source_lib}->{target_lib}:{interaction_handle}"

    return None


def _normalize_inter_scope(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.startswith("inter:"):
        return None
    body = text.removeprefix("inter:").strip()
    if "->" not in body or ":" not in body:
        return None
    source_part, remainder = body.split("->", 1)
    target_part, handle_part = remainder.split(":", 1)
    source_lib = _normalize_library_name(source_part)
    target_lib = _normalize_library_name(target_part)
    handle = _normalize_handle(handle_part)
    if not source_lib or not target_lib or not handle:
        return None
    if source_lib == target_lib:
        return None
    return f"inter:{source_lib}->{target_lib}:{handle}"


def _extract_library_pair(mapping: dict[str, Any]) -> tuple[str, str]:
    pair_keys = (
        ("source_library", "target_library"),
        ("producer_library", "consumer_library"),
        ("provider_library", "consumer_library"),
        ("from_library", "to_library"),
        ("source_lib", "target_lib"),
    )
    for source_key, target_key in pair_keys:
        source_lib = _normalize_library_name(mapping.get(source_key))
        target_lib = _normalize_library_name(mapping.get(target_key))
        if source_lib and target_lib:
            return source_lib, target_lib

    for list_key in ("libraries", "library_ids", "focus_libraries"):
        raw_value = mapping.get(list_key)
        if not isinstance(raw_value, list):
            continue
        normalized = [_normalize_library_name(item) for item in raw_value]
        libs = [lib for lib in normalized if lib]
        if len(libs) >= 2:
            return libs[0], libs[1]

    return "", ""


def _extract_interaction_handle(mapping: dict[str, Any]) -> str:
    preferred_keys = (
        "interaction_handle",
        "event_name",
        "contract_name",
        "import_path",
        "import_symbol",
        "call_symbol",
        "call_name",
        "event",
        "contract",
        "edge_id",
        "event_id",
    )
    for key in preferred_keys:
        handle = _normalize_handle(mapping.get(key))
        if handle:
            return handle
    return ""


def _normalize_library_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    token = text.replace("\\", "/")
    if token.lower().startswith("libraries/"):
        parts = [part for part in token.split("/") if part]
        if len(parts) >= 2:
            token = parts[1]
    elif "/" in token:
        token = token.rsplit("/", 1)[-1]
    token = token.strip()
    if not token:
        return ""
    lowered = token.lower()
    if lowered in {"lib", "library", "libraries", "unknown", "tbd"}:
        return ""
    return token


def _normalize_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"interaction", "handle", "unknown", "tbd", "todo"}:
        return ""
    compact = re.sub(r"\s+", "_", text)
    compact = re.sub(r"[^A-Za-z0-9._:/#-]+", "_", compact)
    compact = compact.strip("._:/#-")
    return compact


def _walk_mappings(value: Any) -> list[dict[str, Any]]:
    queue: list[Any] = [value]
    mappings: list[dict[str, Any]] = []
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            mappings.append(item)
            queue.extend(item.values())
            continue
        if isinstance(item, list):
            queue.extend(item)
    return mappings


def _parse_inter_scope_components(scope: str) -> tuple[str, str, str]:
    body = str(scope).removeprefix("inter:")
    source_part, remainder = body.split("->", 1)
    target_part, handle_part = remainder.split(":", 1)
    return source_part.strip(), target_part.strip(), handle_part.strip()


def _extract_signal_summary(signal: dict[str, Any], *, scope: str) -> str:
    need = signal.get("need", {})
    if isinstance(need, dict):
        for key in ("summary", "reason", "artifact_key"):
            text = str(need.get(key, "")).strip()
            if text:
                return text

    payload = signal.get("payload", {})
    if isinstance(payload, dict):
        under_spec_event = payload.get("under_spec_event")
        if isinstance(under_spec_event, dict):
            text = str(
                under_spec_event.get("question", under_spec_event.get("description", ""))
            ).strip()
            if text:
                return text
    question = str(signal.get("question", "")).strip()
    if question:
        return question
    return f"Resolve cross-library architecture decision for {scope}"


def _extract_signal_location(signal: dict[str, Any]) -> dict[str, Any]:
    spec_refs = signal.get("spec_refs", [])
    if isinstance(spec_refs, list):
        for row in spec_refs:
            if not isinstance(row, dict):
                continue
            file_hint = str(row.get("source_file", "")).strip()
            symbol = str(row.get("source_symbol", "")).strip()
            try:
                line_hint = int(row.get("source_line_hint", 0) or 0)
            except (TypeError, ValueError):
                line_hint = 0
            if file_hint or symbol:
                return {"file": file_hint, "symbol": symbol, "line_hint": line_hint}
    return {"file": "", "symbol": "", "line_hint": 0}


def _collect_signal_trigger_refs(signal: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    spec_refs = signal.get("spec_refs", [])
    if isinstance(spec_refs, list):
        for row in spec_refs:
            if not isinstance(row, dict):
                continue
            source_file = str(row.get("source_file", "")).strip()
            line_hint = str(row.get("source_line_hint", "")).strip()
            if source_file and line_hint:
                refs.append(f"{source_file}:{line_hint}")
            elif source_file:
                refs.append(source_file)

    for mapping in _walk_mappings(signal):
        for key in ("trigger_evidence", "evidence_refs", "event_id"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
            elif isinstance(value, list):
                refs.extend(str(item).strip() for item in value if str(item).strip())

    seen: set[str] = set()
    deduped: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def _build_arch_decision_routing_payload(
    *,
    work_item_id: str,
    summary: str,
    run_id: str,
    slice_id: str,
    shape_id: str,
    scope: str,
    trigger_refs: list[str],
    location: dict[str, Any],
) -> dict[str, Any]:
    # IMPL(single-layer): Routing payloads should carry shape-aware phase-local
    # identity (`shape_id`, `created_in_phase='architecture'`) once coordination
    # schemas complete migration from layer tokens.
    return {
        "work_item_id": work_item_id,
        "run_id": run_id,
        "slice_id": slice_id,
        "title": summary,
        "description": summary,
        "shape_id": shape_id,
        "created_in_phase": _ARCHITECTURE_PHASE,
        "required_change_type": "spec_change",
        "status": "OPEN",
        "kind": "ARCH_DECISION",
        "priority": "high",
        "file_locations": [
            {
                "file_path": str(location.get("file", "")).strip(),
                "symbol": str(location.get("symbol", "")).strip() or None,
                "line_start": int(location.get("line_hint", 0) or 0) or None,
                "line_end": None,
            }
        ],
        "evidence_refs": [str(ref).strip() for ref in trigger_refs if str(ref).strip()],
        "contract_ids": [],
        "verifier_ids": [],
        "metadata": {
            "scope": scope,
            "trigger_refs": [str(ref).strip() for ref in trigger_refs if str(ref).strip()],
        },
    }
