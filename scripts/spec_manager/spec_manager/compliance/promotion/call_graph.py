"""Adaptive call-graph extraction for promotion gates.

This module implements a strategy-driven call graph extractor.
It prefers deterministic extraction for known surfaces and only uses LLM-driven
parser strategy creation when existing deterministic strategies do not fit the
prompt surface.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.code_analysis import SourceAnalysis
from spec_manager.core.json_extraction import _extract_json_payload

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile

logger = logging.getLogger(__name__)

_CALL_NAME_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
)
_RUN_AGENT_NAME_RE = re.compile(r"\brun_agent\b")
_CODE_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]*\n)?(.*?)(?:```)", re.DOTALL)
_RUN_AGENT_CALL_RE = re.compile(r"\brun_agent\s*\((.*?)\)", re.DOTALL)
_CALL_DIRECTIVE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:call|invoke|execute|run)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
)
_STRING_LITERAL_RE = re.compile(
    r"""(?x)
    (\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')
    """
)
_PROMPT_KEYWORD_RE = re.compile(
    r'(?is)(?:^|[,{]\s*)(prompt|instruction|task|query|prompt_text)\s*:\s*("([^"\\\\]|\\.)*"|\'([^\'\\\\]|\\.)*\'|"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')'
)
_JSON_CALL_KEYS = {
    "call",
    "calls",
    "invoke",
    "invocations",
    "targets",
    "target",
    "callee",
    "callees",
}
_JIT_STRATEGY_PREFIX = "jit_"
_STRATEGY_MATCHER_AGENT = "pdd-code-analyzer"
_ALLOWED_STRATEGY_KINDS = frozenset({"python_ast", "agent_prompt", "text_aligner", "noop"})
_ALLOWED_PARSER_HINTS = frozenset({"json", "directive", "regex", "fence_ast"})
_DEFAULT_MATCHER_CONFIDENCE = 0.55


@dataclass
class _CliDispatchPattern:
    """Frozen descriptor for CLI-based dispatch calls."""

    name: str
    description: str
    pattern: re.Pattern[str]
    callee_group: int = 1


_DEFAULT_CLI_PATTERNS: list[_CliDispatchPattern] = [
    _CliDispatchPattern(
        name="run_agent_kwarg",
        description="run_agent(agent_name=...)",
        pattern=re.compile(r"\brun_agent\s*\([^)]*agent_name\s*=\s*[\"']([^\"']+)[\"']"),
        callee_group=1,
    ),
    _CliDispatchPattern(
        name="uv_run",
        description="uv run <command>",
        pattern=re.compile(r"\buv\s+run\s+([A-Za-z_][A-Za-z0-9_-]*)"),
        callee_group=1,
    ),
]


@dataclass
class StrategyRegistry:
    """Injectable registry that encapsulates all mutable strategy state."""

    call_graph_strategies: dict[str, _CallGraphStrategy] = field(default_factory=dict)
    parser_strategies: dict[str, _PromptParserStrategy] = field(default_factory=dict)
    strategy_matcher_agent: str = "pdd-code-analyzer"
    research_tool: Any = None
    cli_patterns: list[_CliDispatchPattern] = field(
        default_factory=lambda: list(_DEFAULT_CLI_PATTERNS)
    )

    def clear(self) -> None:
        self.call_graph_strategies.clear()
        self.parser_strategies.clear()


_DEFAULT_REGISTRY = StrategyRegistry()


@dataclass(frozen=True)
class CallGraphEdge:
    """One extracted call edge with provenance."""

    caller: str
    callee: str
    strategy: str
    surface: str
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallGraphBuildResult:
    """Aggregated extraction results from one strategy pass."""

    nodes: set[str] = field(default_factory=set)
    edges: list[CallGraphEdge] = field(default_factory=list)
    skipped_files: list[dict[str, Any]] = field(default_factory=list)
    unsupported_calls: list[dict[str, Any]] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _PromptParseResult:
    """Parser output for one prompt payload."""

    resolved: set[tuple[str, str]] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(frozen=True)
class _PromptCallSite:
    caller: str
    prompt_text: str
    source: str


@dataclass(frozen=True)
class _CallGraphStrategyProposal:
    """Proposal returned by the LLM strategy matcher."""

    strategy: str
    confidence: float = _DEFAULT_MATCHER_CONFIDENCE
    parser_preference: str | None = None
    source: str = ""


def build_call_graph(
    algorithmic_files: list[Path],
    project_root: Path,
    analyzed: list[AnalyzedFile] | None = None,
    registry: StrategyRegistry | None = None,
) -> CallGraphBuildResult:
    """Build a strategy-driven function call graph from source files.

    Args:
        algorithmic_files: Source files to analyze.
        project_root: Used for module-id normalization and JIT strategy workspace.
        analyzed: Optional preloaded analyses.
        registry: Optional strategy registry; defaults to the module-level registry.

    Returns:
        CallGraphBuildResult with deduplicated nodes and strategy-provenanced edges.
    """
    if registry is None:
        registry = _DEFAULT_REGISTRY
    strategy_list = _build_strategy_registry(registry)
    analyzed_by_path: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        analyzed_by_path = {Path(a.path).resolve().as_posix(): a for a in analyzed}

    output = CallGraphBuildResult()

    for file_path in algorithmic_files:
        resolved = file_path.resolve()
        af = analyzed_by_path.get(resolved.as_posix())
        if af is None:
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.debug("Skipping file in call graph extraction: %s (%s)", file_path, exc)
                output.skipped_files.append(
                    {
                        "path": str(file_path),
                        "reason": "read_error",
                    }
                )
                continue
            analysis = SourceAnalysis()
        else:
            source = af.content
            analysis = af.analysis

        source_analysis = analysis if isinstance(analysis, SourceAnalysis) else SourceAnalysis()
        strategies = [
            strategy
            for strategy in strategy_list
            if strategy.can_handle(file_path, source, project_root, source_analysis)
        ]
        if not strategies:
            created = _select_or_create_call_graph_strategy(
                file_path=file_path,
                source=source,
                project_root=project_root,
                analyzed=source_analysis,
                registry=registry,
            )
            if created is not None:
                strategies = [created]
            else:
                output.skipped_files.append(
                    {
                        "path": str(file_path),
                        "strategy": "none",
                        "reason": "no_matching_strategy",
                    }
                )
                continue

        for strategy in strategies:
            try:
                file_result = strategy.extract(
                    file_path=file_path,
                    source=source,
                    project_root=project_root,
                    analyzed=source_analysis,
                )
            except Exception as exc:
                logger.warning("Strategy %s failed for %s: %s", strategy.name, file_path, exc)
                output.skipped_files.append(
                    {
                        "path": str(file_path),
                        "strategy": strategy.name,
                        "reason": f"extract_error:{type(exc).__name__}",
                    }
                )
                continue

            output.nodes |= file_result.nodes
            output.edges.extend(file_result.edges)
            output.skipped_files.extend(file_result.skipped_files)
            output.unsupported_calls.extend(file_result.unsupported_calls)
            output.provenance.extend(file_result.provenance)

    return output


class _CallGraphStrategy:
    """Call-graph extraction strategy."""

    name: str = "base"

    def can_handle(
        self,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> bool:
        return False

    def extract(
        self,
        *,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> CallGraphBuildResult:
        raise NotImplementedError


class _PythonAstCallGraphStrategy(_CallGraphStrategy):
    """Deterministic AST-based call extraction for Python sources."""

    name = "python_ast"

    def can_handle(
        self,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> bool:
        if file_path.suffix != ".py":
            return False
        try:
            ast.parse(source)
            return True
        except SyntaxError:
            return False

    def extract(
        self,
        *,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> CallGraphBuildResult:
        module_prefix = _module_name_from_path(file_path, project_root)
        result = CallGraphBuildResult(
            provenance=[{"file": str(file_path), "strategy": self.name, "surface": "python_ast"}]
        )

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result.skipped_files.append(
                {
                    "path": str(file_path),
                    "strategy": self.name,
                    "reason": f"syntax_error:{exc.lineno}:{exc.offset}",
                }
            )
            return result

        collector = _FunctionCollector(module_prefix)
        collector.visit(tree)
        if not collector.function_names:
            return result

        result.nodes.update(collector.function_names)

        call_visitor = _CallVisitor(
            module_prefix=module_prefix,
            function_names=collector.function_names,
            function_short_index=collector.function_short_index,
        )
        call_visitor.visit(tree)
        result.unsupported_calls.extend(call_visitor.unsupported_calls)

        for caller, callee in sorted(call_visitor.edges):
            if caller == callee:
                continue
            result.edges.append(
                CallGraphEdge(
                    caller=caller,
                    callee=callee,
                    strategy=self.name,
                    surface="code_ast",
                    confidence=1.0,
                    evidence={"resolved": True},
                )
            )

        return result


class _AgentPromptCallGraphStrategy(_CallGraphStrategy):
    """Prompt-driven parser strategy for run_agent() instructions."""

    name = "agent_prompt"

    def can_handle(
        self,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> bool:
        return _RUN_AGENT_NAME_RE.search(source) is not None

    def extract(
        self,
        *,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> CallGraphBuildResult:
        module_prefix = _module_name_from_path(file_path, project_root)
        result = CallGraphBuildResult(
            provenance=[{"file": str(file_path), "strategy": self.name, "surface": "agent_prompt"}]
        )

        functions = _collect_function_names(file_path, source, analyzed, module_prefix)
        function_index = _build_function_index(functions, module_prefix)
        if functions:
            result.nodes.update(functions)

        prompt_sites = _collect_agent_prompt_sites(
            file_path=file_path, source=source, source_analysis=analyzed, project_root=project_root
        )
        if not prompt_sites:
            result.unsupported_calls.append(
                {
                    "file": str(file_path),
                    "strategy": self.name,
                    "reason": "no_prompt_sites",
                }
            )
            return result

        for site in prompt_sites:
            parser = _select_prompt_parser(
                prompt_text=site.prompt_text,
                file_path=file_path,
                project_root=project_root,
                function_index=function_index,
                caller=site.caller,
                module_prefix=module_prefix,
            )

            parsed = parser.parse(
                prompt_text=site.prompt_text,
                function_index=function_index,
                module_prefix=module_prefix,
                caller=site.caller,
            )
            caller = site.caller or (module_prefix or file_path.stem)

            for callee in sorted(parsed.resolved):
                result.edges.append(
                    CallGraphEdge(
                        caller=caller,
                        callee=callee[1],
                        strategy=self.name,
                        surface=f"agent_prompt:{parser.name}",
                        confidence=parsed.confidence,
                        evidence={
                            "parser": parser.name,
                            "parser_confidence": parsed.confidence,
                            "source": site.source,
                            **parsed.evidence,
                        },
                    )
                )

            for token in sorted(parsed.unresolved):
                result.unsupported_calls.append(
                    {
                        "file": str(file_path),
                        "strategy": self.name,
                        "caller": caller,
                        "token": token,
                        "reason": "prompt_target_unresolved",
                    }
                )

        return result


class _NoopCallGraphStrategy(_CallGraphStrategy):
    """Fallback strategy for unknown/unsupported surfaces."""

    def __init__(self, name: str, surface_signature: str) -> None:
        self.name = name
        self._surface_signature = surface_signature

    def can_handle(
        self,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> bool:
        return (
            _surface_signature(file_path=file_path, source=source, project_root=project_root)
            == self._surface_signature
        )

    def extract(
        self,
        *,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> CallGraphBuildResult:
        return CallGraphBuildResult(
            provenance=[{"file": str(file_path), "strategy": self.name, "surface": "noop"}]
        )


class _AdaptiveTextAlignCallGraphStrategy(_CallGraphStrategy):
    """JIT-created strategy for freeform prompt-bearing files."""

    def __init__(
        self,
        name: str,
        *,
        surface_signature: str,
        parser_hint: str | None = None,
        aligner_prompt: str = "extractor",
    ) -> None:
        self.name = name
        self._surface_signature = surface_signature
        self._parser_hint = parser_hint
        self._aligner_prompt = aligner_prompt

    def can_handle(
        self,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> bool:
        return (
            _surface_signature(file_path=file_path, source=source, project_root=project_root)
            == self._surface_signature
        )

    def extract(
        self,
        *,
        file_path: Path,
        source: str,
        project_root: Path,
        analyzed: SourceAnalysis,
    ) -> CallGraphBuildResult:
        module_prefix = _module_name_from_path(file_path, project_root)
        result = CallGraphBuildResult(
            provenance=[{"file": str(file_path), "strategy": self.name, "surface": "text_aligner"}]
        )

        function_sites = _collect_agent_prompt_sites(
            file_path=file_path,
            source=source,
            source_analysis=analyzed,
            project_root=project_root,
        )
        if not function_sites:
            function_sites = _align_prompt_sites(
                file_path=file_path,
                source=source,
                project_root=project_root,
                module_prefix=module_prefix,
            )
        if not function_sites:
            result.unsupported_calls.append(
                {
                    "file": str(file_path),
                    "strategy": self.name,
                    "reason": "no_prompt_sites_detected",
                }
            )
            return result

        functions = _collect_function_names(file_path, source, analyzed, module_prefix)
        function_index = _build_function_index(functions, module_prefix)
        if functions:
            result.nodes.update(functions)

        for site in function_sites:
            caller = site.caller or module_prefix or file_path.stem
            parser = _select_prompt_parser(
                prompt_text=site.prompt_text,
                file_path=file_path,
                project_root=project_root,
                function_index=function_index,
                caller=caller,
                module_prefix=module_prefix,
                preferred_parser=self._parser_hint,
            )
            parsed = parser.parse(
                prompt_text=site.prompt_text,
                function_index=function_index,
                module_prefix=module_prefix,
                caller=caller,
            )

            for callee in sorted(parsed.resolved):
                result.edges.append(
                    CallGraphEdge(
                        caller=caller,
                        callee=callee[1],
                        strategy=self.name,
                        surface=f"text_align:{parser.name}",
                        confidence=parsed.confidence,
                        evidence={
                            "parser": parser.name,
                            "parser_confidence": parsed.confidence,
                            "source": site.source,
                            "aligner_prompt": self._aligner_prompt,
                        },
                    )
                )

            for token in sorted(parsed.unresolved):
                result.unsupported_calls.append(
                    {
                        "file": str(file_path),
                        "strategy": self.name,
                        "caller": caller,
                        "token": token,
                        "reason": "align_prompt_target_unresolved",
                    }
                )

        return result


class _PromptParserStrategy:
    """Base interface for deterministic prompt parser strategies."""

    name = "base"
    default_confidence = 0.0

    def can_parse(self, prompt_text: str) -> bool:
        return False

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        raise NotImplementedError


class _PromptJsonParserStrategy(_PromptParserStrategy):
    """Parser that extracts identifiers from structured prompt payloads."""

    name = "prompt_json"
    default_confidence = 0.95

    def can_parse(self, prompt_text: str) -> bool:
        payload = _extract_json_payload(prompt_text)
        if not payload:
            return False
        try:
            json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return False
        return True

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        payload = _extract_json_payload(prompt_text)
        if not payload:
            return _PromptParseResult(confidence=0.0, evidence={"reason": "empty_payload"})

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return _PromptParseResult(confidence=0.0, evidence={"reason": "invalid_payload"})

        tokens = _collect_identifier_tokens_from_payload(data, target_fields=_JSON_CALL_KEYS)
        return _resolve_prompt_tokens(
            tokens=tokens,
            function_index=function_index,
            module_prefix=module_prefix,
            caller=caller,
            parser=self.name,
        )


class _PromptCodeFenceAstParserStrategy(_PromptParserStrategy):
    """Parser that extracts AST call shapes from Python code blocks inside prompts."""

    name = "prompt_code_fence_ast"
    default_confidence = 0.75

    def can_parse(self, prompt_text: str) -> bool:
        if not _CODE_FENCE_RE.search(prompt_text):
            return False
        for block in _CODE_FENCE_RE.findall(prompt_text):
            try:
                ast.parse(block)
                return True
            except SyntaxError:
                continue
        return False

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        tokens: set[str] = set()
        for block in _CODE_FENCE_RE.findall(prompt_text):
            try:
                tree = ast.parse(block)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    token = _extract_call_expression_name(node.func)
                    if token:
                        tokens.add(token)

        if not tokens:
            return _PromptParseResult(confidence=0.15, evidence={"reason": "no_ast_calls"})
        return _resolve_prompt_tokens(
            tokens=tokens,
            function_index=function_index,
            module_prefix=module_prefix,
            caller=caller,
            parser=self.name,
        )


class _PromptDirectiveParserStrategy(_PromptParserStrategy):
    """Parser for explicit call-like directives in free text."""

    name = "prompt_directive"
    default_confidence = 0.55

    def can_parse(self, prompt_text: str) -> bool:
        return _CALL_DIRECTIVE_RE.search(prompt_text) is not None

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        tokens = {m.group(1) for m in _CALL_DIRECTIVE_RE.finditer(prompt_text)}
        if not tokens:
            return _PromptParseResult(confidence=0.15, evidence={"reason": "no_directive_tokens"})
        return _resolve_prompt_tokens(
            tokens=tokens,
            function_index=function_index,
            module_prefix=module_prefix,
            caller=caller,
            parser=self.name,
        )


class _PromptNoopParserStrategy(_PromptParserStrategy):
    """Non-matching strategy that intentionally emits nothing."""

    name = "prompt_noop"
    default_confidence = 0.0

    def can_parse(self, prompt_text: str) -> bool:
        return True

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        return _PromptParseResult(
            confidence=0.0,
            unresolved=set(),
            resolved=set(),
            evidence={"reason": "no_matching_prompt_parser"},
        )


class _PromptJitParserStrategy(_PromptParserStrategy):
    """LLM-authored parser strategy used only after deterministic parsers fail."""

    def __init__(
        self,
        *,
        name: str,
        parser_mode: str,
        regex_patterns: list[str] | None = None,
        json_fields: list[str] | None = None,
        confidence: float = 0.4,
    ) -> None:
        self.name = name
        self._parser_mode = parser_mode
        self._regex_patterns = regex_patterns or []
        self._json_fields = json_fields or []
        self.default_confidence = confidence

    def can_parse(self, prompt_text: str) -> bool:
        if self._parser_mode == "regex":
            return bool(self._regex_patterns)
        if self._parser_mode == "json":
            return bool(_extract_json_payload(prompt_text))
        if self._parser_mode == "fence_ast":
            return bool(_CODE_FENCE_RE.search(prompt_text))
        if self._parser_mode == "directive":
            return bool(_CALL_DIRECTIVE_RE.search(prompt_text))
        return False

    def parse(
        self,
        *,
        prompt_text: str,
        function_index: dict[str, set[str]],
        module_prefix: str,
        caller: str,
    ) -> _PromptParseResult:
        if self._parser_mode == "json":
            payload = _extract_json_payload(prompt_text)
            if not payload:
                return _PromptParseResult(
                    confidence=0.2,
                    evidence={"reason": "jit_parser_json_no_payload", "mode": "json"},
                )
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return _PromptParseResult(
                    confidence=0.2, evidence={"reason": "jit_parser_json_invalid", "mode": "json"}
                )

            keys = set(_JSON_CALL_KEYS)
            keys.update(self._json_fields)
            tokens = _collect_identifier_tokens_from_payload(data, target_fields=keys)
            return _resolve_prompt_tokens(
                tokens=tokens,
                function_index=function_index,
                module_prefix=module_prefix,
                caller=caller,
                parser=self.name,
            )

        if self._parser_mode in {"directive", "regex"}:
            patterns = self._regex_patterns or [
                r"(?im)^\s*(?:[-*]\s*)?(?:call|invoke|execute|run)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
            ]
            tokens: set[str] = set()
            for pattern in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    continue
                for match in regex.finditer(prompt_text):
                    token = match.group(1)
                    if token:
                        tokens.add(token.strip())
            if not tokens:
                return _PromptParseResult(
                    confidence=0.2,
                    evidence={"reason": "jit_parser_no_tokens", "mode": self._parser_mode},
                )
            return _resolve_prompt_tokens(
                tokens=tokens,
                function_index=function_index,
                module_prefix=module_prefix,
                caller=caller,
                parser=self.name,
            )

        if self._parser_mode == "fence_ast":
            return _PromptCodeFenceAstParserStrategy().parse(
                prompt_text=prompt_text,
                function_index=function_index,
                module_prefix=module_prefix,
                caller=caller,
            )

        return _PromptParseResult(confidence=0.0, evidence={"reason": "jit_parser_unknown_mode"})


def _surface_signature(
    file_path: Path,
    source: str,
    project_root: Path,
) -> str:
    """Compute a stable file-surface signature for strategy reuse."""
    try:
        relative = file_path.resolve().relative_to(project_root.resolve())
        relative_hint = str(relative)
    except ValueError:
        relative_hint = str(file_path)

    normalized = " ".join(source.split())
    signature = (
        f"{file_path.suffix}|{len(source)}|"
        f"{relative_hint}|{_RUN_AGENT_NAME_RE.search(source) is not None}|"
        f"{_RUN_AGENT_CALL_RE.findall(source).__len__()}|{normalized[:200]}"
    )
    return _hash_id(signature)


def _build_strategy_registry(registry: StrategyRegistry | None = None) -> list[_CallGraphStrategy]:
    """Create the built-in + registered adaptive strategy registry."""
    if registry is None:
        registry = _DEFAULT_REGISTRY
    builtins: list[_CallGraphStrategy] = [
        _PythonAstCallGraphStrategy(),
        _AgentPromptCallGraphStrategy(),
    ]
    return builtins + list(registry.call_graph_strategies.values())


def _select_or_create_call_graph_strategy(
    *,
    file_path: Path,
    source: str,
    project_root: Path,
    analyzed: SourceAnalysis,
    registry: StrategyRegistry | None = None,
) -> _CallGraphStrategy | None:
    """Select a matching strategy by LLM, otherwise create a noop fallback."""
    if registry is None:
        registry = _DEFAULT_REGISTRY
    surface = _surface_signature(file_path=file_path, source=source, project_root=project_root)
    cached = registry.call_graph_strategies.get(surface)
    if cached is not None:
        return cached

    proposal = _propose_call_graph_strategy(
        file_path=file_path,
        source=source,
        project_root=project_root,
        registry=registry,
    )
    if proposal is None:
        strategy: _CallGraphStrategy = _NoopCallGraphStrategy(
            name=f"{_JIT_STRATEGY_PREFIX}{surface}",
            surface_signature=surface,
        )
        registry.call_graph_strategies[surface] = strategy
        return strategy

    if proposal.strategy == "agent_prompt":
        strategy = _AgentPromptCallGraphStrategy()
        if not strategy.can_handle(
            file_path=file_path,
            source=source,
            project_root=project_root,
            analyzed=analyzed,
        ):
            strategy = _AdaptiveTextAlignCallGraphStrategy(
                name=f"{_JIT_STRATEGY_PREFIX}{surface}",
                surface_signature=surface,
                parser_hint=proposal.parser_preference,
                aligner_prompt=proposal.source or "agent_prompt_fallback",
            )
    elif proposal.strategy == "text_aligner":
        strategy = _AdaptiveTextAlignCallGraphStrategy(
            name=f"{_JIT_STRATEGY_PREFIX}{surface}",
            surface_signature=surface,
            parser_hint=proposal.parser_preference,
            aligner_prompt=proposal.source or "text_aligner",
        )
    elif proposal.strategy == "python_ast":
        strategy = _PythonAstCallGraphStrategy()
        if not strategy.can_handle(
            file_path=file_path,
            source=source,
            project_root=project_root,
            analyzed=analyzed,
        ):
            strategy = _AdaptiveTextAlignCallGraphStrategy(
                name=f"{_JIT_STRATEGY_PREFIX}{surface}",
                surface_signature=surface,
                parser_hint=proposal.parser_preference,
                aligner_prompt=proposal.source or "python_ast_fallback",
            )
    else:
        strategy = _NoopCallGraphStrategy(
            name=f"{_JIT_STRATEGY_PREFIX}{surface}",
            surface_signature=surface,
        )

    # Validate: if the strategy produces nothing useful on the triggering file, downgrade to noop.
    if not _validate_strategy(strategy, file_path, source, project_root, analyzed):
        strategy = _NoopCallGraphStrategy(
            name=f"{_JIT_STRATEGY_PREFIX}{surface}",
            surface_signature=surface,
        )

    # Cache created decisions for this surface so future files can reuse the
    # same matcher output and strategy selection.
    registry.call_graph_strategies[surface] = strategy
    return strategy


def _propose_call_graph_strategy(
    *,
    file_path: Path,
    source: str,
    project_root: Path,
    registry: StrategyRegistry | None = None,
) -> _CallGraphStrategyProposal | None:
    """Ask an agent to choose a call-graph strategy for this surface."""
    if registry is None:
        registry = _DEFAULT_REGISTRY
    strategy_hint = (
        "python_ast" if file_path.suffix == ".py" and source.count("run_agent") else "text_aligner"
    )
    if _RUN_AGENT_NAME_RE.search(source):
        strategy_hint = "agent_prompt"

    candidate_lines = [
        line.strip() for line in source.splitlines() if line and "run_agent" in line
    ][:3]
    snippet = "\n".join(candidate_lines)

    source_excerpt = source[:3000]

    # Optional research enrichment
    research_context = ""
    if registry.research_tool is not None:
        research_context = _query_research(
            registry.research_tool,
            (
                f"What call dispatch patterns are used in {file_path.suffix} files "
                f"for agent invocations?"
            ),
        )

    prompt = (
        "You are a call-graph surface matcher.\n"
        "Return JSON only.\n"
        "Choose one strategy for extracting caller -> callee edges.\n\n"
        "{\n"
        '  "strategy": "python_ast" | "agent_prompt" | "text_aligner" | "noop",\n'
        '  "parser_preference": "json" | "directive" | "regex" | "fence_ast",\n'
        '  "parser_preference_description": "optional note",\n'
        '  "confidence": 0.0,\n'
        '  "source": "short reason"\n'
        "}\n\n"
        "Rules:\n"
        "- agent_prompt for files that pass prompt payloads to run_agent.\n"
        "- python_ast for deterministic python call-graph extraction.\n"
        "- text_aligner for freeform files that still describe run_agent-like calls.\n"
        "- parser_preference should only be one of json, directive, regex, fence_ast.\n"
        "- Do not emit call edges.\n"
        "Choose based on the entire file and this hint: "
        f"{strategy_hint}\n\n"
        "File path: "
        f"{file_path}\n"
        "File extension: "
        f"{file_path.suffix}\n"
        "Sample snippet:\n"
        f"{snippet}\n\n"
        "If the file has no call-bearing shape, return noop.\n"
    )
    if research_context:
        prompt += f"Research context:\n{research_context}\n\n"
    prompt += f"Source:\n{source_excerpt}"

    try:
        raw_output = run_agent(
            agent_name=registry.strategy_matcher_agent,
            prompt=prompt,
            workspace=project_root,
        )
        output = _parse_llm_json_output(raw_output)
    except Exception as exc:
        logger.debug("Strategy matching failed for %s: %s", file_path, exc)
        output = None

    if not isinstance(output, dict):
        return _CallGraphStrategyProposal(
            strategy="text_aligner" if strategy_hint == "text_aligner" else strategy_hint,
            confidence=_DEFAULT_MATCHER_CONFIDENCE,
            parser_preference=None,
            source="fallback",
        )

    strategy = str(output.get("strategy", strategy_hint)).strip().lower()
    if strategy not in _ALLOWED_STRATEGY_KINDS:
        strategy = strategy_hint

    parser_preference = output.get("parser_preference")
    if isinstance(parser_preference, str):
        parser_preference = parser_preference.strip().lower()
        if parser_preference not in _ALLOWED_PARSER_HINTS:
            parser_preference = None
    else:
        parser_preference = None

    return _CallGraphStrategyProposal(
        strategy=strategy,
        confidence=_coerce_confidence(output.get("confidence", _DEFAULT_MATCHER_CONFIDENCE)),
        parser_preference=parser_preference,
        source=str(output.get("source", "")),
    )


def _preferred_prompt_parser_strategy(preferred_parser: str | None) -> str:
    """Normalize parser preference into deterministic strategy names."""
    match = (preferred_parser or "").strip().lower()
    if match == "json":
        return _PromptJsonParserStrategy.name
    if match == "directive":
        return _PromptDirectiveParserStrategy.name
    if match == "fence_ast":
        return _PromptCodeFenceAstParserStrategy.name
    if match == "regex":
        return "regex"
    return ""


def _select_prompt_parser(
    *,
    prompt_text: str,
    file_path: Path,
    project_root: Path,
    function_index: dict[str, set[str]],
    caller: str,
    module_prefix: str,
    preferred_parser: str | None = None,
    registry: StrategyRegistry | None = None,
) -> _PromptParserStrategy:
    if registry is None:
        registry = _DEFAULT_REGISTRY
    preferred = (preferred_parser or "").strip().lower()
    if preferred:
        normalized_preferred = _preferred_prompt_parser_strategy(preferred)
        if normalized_preferred != "regex" and normalized_preferred:
            for strategy in _build_prompt_parser_strategies():
                if strategy.name != normalized_preferred:
                    continue
                if strategy.can_parse(prompt_text):
                    return strategy

    candidates: list[_PromptParserStrategy] = []
    for strategy in _build_prompt_parser_strategies():
        if strategy.can_parse(prompt_text):
            candidates.append(strategy)

    if candidates:
        candidates.sort(key=lambda item: item.default_confidence, reverse=True)
        best = candidates[0]
        if best.default_confidence >= 0.4:
            return best

    jit = _create_jit_prompt_parser_strategy(
        file_path=file_path,
        prompt_text=prompt_text,
        project_root=project_root,
        caller=caller,
        module_prefix=module_prefix,
        function_index=function_index,
        preferred_parser=preferred,
        registry=registry,
    )
    return jit if jit is not None else _PromptNoopParserStrategy()


def _build_prompt_parser_strategies() -> list[_PromptParserStrategy]:
    return [
        _PromptJsonParserStrategy(),
        _PromptCodeFenceAstParserStrategy(),
        _PromptDirectiveParserStrategy(),
    ]


def _create_jit_prompt_parser_strategy(
    *,
    file_path: Path,
    prompt_text: str,
    project_root: Path,
    caller: str,
    module_prefix: str,
    function_index: dict[str, set[str]],
    preferred_parser: str | None = None,
    registry: StrategyRegistry | None = None,
) -> _PromptParserStrategy | None:
    if registry is None:
        registry = _DEFAULT_REGISTRY
    if not prompt_text.strip():
        return None

    normalized_preferred = (preferred_parser or "").strip().lower()
    normalized_preferred = (
        normalized_preferred
        if normalized_preferred in {"json", "directive", "regex", "fence_ast"}
        else ""
    )
    parser_signature = _hash_id(
        " ".join(
            [
                str(file_path),
                caller,
                module_prefix,
                normalized_preferred,
                prompt_text.strip()[:600],
            ]
        )
    )
    cached = registry.parser_strategies.get(parser_signature)
    if cached is not None:
        return cached

    context_summary = (
        f"module_prefix={module_prefix}; "
        f"caller={caller or '<unknown>'}; "
        f"known_functions={sorted(function_index.keys())[:20]}"
    )

    # Optional research enrichment
    research_context = ""
    if registry.research_tool is not None:
        research_context = _query_research(
            registry.research_tool,
            (
                f"What parser patterns work best for extracting call "
                f"targets from prompts like: {prompt_text[:200]}"
            ),
        )

    prompt = (
        "You are a call-edge parser strategy matcher.\n"
        "Do not infer any call edges.\n"
        "Return JSON only.\n"
        "Given the following extracted prompt text, return a parser strategy "
        "for deterministic extraction:\n"
        "{\n"
        '  "parser_type": "json" | "directive" | "regex" | "fence_ast",\n'
        '  "regex_patterns": ["<regex>"] optional,\n'
        '  "json_fields": ["calls", "call", "targets"] optional,\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "Rules:\n"
        "- Emit at most one parser type.\n"
        "- Use regex only when deterministic directive-like tokens are visible.\n"
        "- For json-like text, prefer parser_type=json.\n"
        "- No invented identifiers.\n"
        "- Confidence should reflect extraction certainty.\n"
        f"{context_summary}\n\n"
    )
    if research_context:
        prompt += f"Research context:\n{research_context}\n\n"
    prompt += f"Prompt text:\n{prompt_text}\n"

    if preferred_parser:
        prompt += f"Parser preference from strategy matcher: {preferred_parser}\n"

    try:
        raw_output = run_agent(
            agent_name=registry.strategy_matcher_agent,
            prompt=prompt,
            workspace=project_root,
        )
        output = _parse_llm_json_output(raw_output)
    except Exception as exc:
        logger.debug(
            "LLM parser matching failed for %s (%s): %s",
            file_path,
            caller or "<unknown>",
            exc,
        )
        return None

    if not isinstance(output, dict):
        output = {}

    parser_type = str(output.get("parser_type", preferred_parser or "")).strip().lower()
    allowed = {"json", "directive", "regex", "fence_ast"}
    if parser_type not in allowed:
        parser_type = normalized_preferred if normalized_preferred in allowed else "directive"

    confidence = _coerce_confidence(output.get("confidence", 0.45))
    regex_patterns = (
        output.get("regex_patterns") if isinstance(output.get("regex_patterns"), list) else []
    )
    if not isinstance(regex_patterns, list):
        regex_patterns = []
    json_fields = output.get("json_fields") if isinstance(output.get("json_fields"), list) else []
    if not isinstance(json_fields, list):
        json_fields = []

    shape = f"{file_path}:{caller}:{module_prefix}:{parser_type}:{confidence}:{len(prompt_text)}"
    strategy_id = _hash_id(shape)
    strategy = _PromptJitParserStrategy(
        name=f"{_JIT_STRATEGY_PREFIX}{strategy_id}",
        parser_mode=parser_type,
        regex_patterns=list(regex_patterns),
        json_fields=list(json_fields),
        confidence=confidence,
    )
    # Validate: check can_parse on the triggering prompt before caching.
    if not strategy.can_parse(prompt_text):
        strategy = _PromptJitParserStrategy(
            name=f"{_JIT_STRATEGY_PREFIX}{strategy_id}_noop",
            parser_mode="directive",
            confidence=0.0,
        )
    registry.parser_strategies[parser_signature] = strategy
    return strategy


def _parse_llm_json_output(raw_output: str) -> dict[str, Any] | list[Any]:
    cleaned = raw_output.strip()
    data = None
    if cleaned:
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            extracted = _extract_json_payload(cleaned)
            if extracted:
                with contextlib.suppress(json.JSONDecodeError, ValueError):
                    data = json.loads(extracted)
    return data if isinstance(data, dict | list) else {}


def _validate_strategy(
    strategy: _CallGraphStrategy,
    file_path: Path,
    source: str,
    project_root: Path,
    analyzed: SourceAnalysis,
) -> bool:
    """Validate a JIT strategy produces useful output on the triggering file.

    Skips validation for strategies that require LLM calls during extraction
    (e.g. _AdaptiveTextAlignCallGraphStrategy), since those cannot be cheaply
    validated without consuming agent budget.
    """
    if isinstance(strategy, (_AdaptiveTextAlignCallGraphStrategy, _AgentPromptCallGraphStrategy)):
        # These strategies call run_agent during extract — trust the LLM
        # proposal and skip pre-validation.
        return True
    try:
        result = strategy.extract(
            file_path=file_path,
            source=source,
            project_root=project_root,
            analyzed=analyzed,
        )
        return bool(result.nodes) or bool(result.edges)
    except Exception:
        return False


def _query_research(research_tool: Any, question: str) -> str:
    """Query the research tool if available. Returns empty string on failure."""
    try:
        from spec_manager.planner.tools.research_tool import ResearchQuery

        result = research_tool.research(ResearchQuery(question=question, dimension="local"))
        if result.has_answer:
            return result.synthesis
    except Exception as exc:
        logger.debug("Research query failed: %s", exc)
    return ""


def _collect_function_names(
    file_path: Path,
    source: str,
    source_analysis: SourceAnalysis,
    module_prefix: str,
) -> set[str]:
    functions: set[str] = set()
    raw_function_names = {f.qualified_name for f in source_analysis.functions if f.qualified_name}
    if not raw_function_names:
        raw_function_names = {f.name for f in source_analysis.functions if f.name}
    functions.update(raw_function_names)

    if not functions and file_path.suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            collector = _FunctionCollector(module_prefix)
            collector.visit(tree)
            functions.update(collector.function_names)

    return functions


def _build_function_index(functions: set[str], module_prefix: str) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for full in functions:
        if not full:
            continue
        norm = _qualify_name(full, module_prefix)
        index.setdefault(norm, set()).add(norm)
        short = norm.rsplit(".", 1)[-1]
        index.setdefault(short, set()).add(norm)
    return index


def _resolve_prompt_tokens(
    *,
    tokens: set[str],
    function_index: dict[str, set[str]],
    module_prefix: str,
    caller: str,
    parser: str,
) -> _PromptParseResult:
    resolved: set[tuple[str, str]] = set()
    unresolved: set[str] = set()

    for token in sorted(tokens):
        normalized = _normalize_call_token(token, module_prefix)
        if not normalized:
            continue
        callee = _resolve_call_target(normalized, function_index)
        if callee:
            if caller and caller != callee:
                resolved.add((caller, callee))
        else:
            unresolved.add(normalized)

    return _PromptParseResult(
        resolved=resolved,
        unresolved=unresolved,
        evidence={
            "candidate_count": len(tokens),
            "resolved_count": len(resolved),
            "unresolved_count": len(unresolved),
            "parser": parser,
        },
        confidence=0.9 if resolved else 0.3,
    )


def _resolve_call_target(token: str, function_index: dict[str, set[str]]) -> str | None:
    exact = function_index.get(token)
    if exact and len(exact) == 1:
        return next(iter(exact))

    if "." in token:
        short = token.rsplit(".", 1)[-1]
        matches = function_index.get(short, set())
        if len(matches) == 1:
            return next(iter(matches))
        if token in matches:
            return token
        same_module = [entry for entry in matches if "." in entry and entry.endswith(f".{short}")]
        if len(same_module) == 1:
            return same_module[0]
    return None


def _collect_identifier_tokens_from_payload(
    data: Any,
    target_fields: set[str] | None = None,
) -> set[str]:
    tokens: set[str] = set()
    if target_fields is None:
        target_fields = _JSON_CALL_KEYS

    if isinstance(data, str):
        if _CALL_NAME_TOKEN_RE.fullmatch(data.strip()):
            tokens.add(data.strip())
        return tokens
    if isinstance(data, list):
        for item in data:
            tokens |= _collect_identifier_tokens_from_payload(item, target_fields)
        return tokens
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower() if isinstance(key, str) else ""
            if key_lower in target_fields and isinstance(value, str):
                if _CALL_NAME_TOKEN_RE.fullmatch(value.strip()):
                    tokens.add(value.strip())
                continue
            child_tokens = _collect_identifier_tokens_from_payload(value, target_fields)
            tokens |= child_tokens
            if (
                key_lower not in target_fields
                and isinstance(value, str)
                and value.strip()
                and _CALL_NAME_TOKEN_RE.fullmatch(value.strip())
            ):
                tokens.add(value.strip())
        return tokens
    return tokens


def _align_prompt_sites(
    *,
    file_path: Path,
    source: str,
    project_root: Path,
    module_prefix: str,
    registry: StrategyRegistry | None = None,
) -> list[_PromptCallSite]:
    """Align free-form text into explicit caller/prompt sites."""
    if registry is None:
        registry = _DEFAULT_REGISTRY
    if not source.strip():
        return []

    cli_hint = ""
    if registry.cli_patterns:
        pattern_descs = [f"- {p.name}: {p.description}" for p in registry.cli_patterns]
        cli_hint = "\nKnown CLI dispatch patterns:\n" + "\n".join(pattern_descs) + "\n"

    prompt = (
        "You are an agent that aligns free-form content into explicit call-site payloads.\n"
        "Do not infer call edges.\n"
        "Return JSON only.\n"
        "{\n"
        '  "prompt_sites": [\n'
        '    {"caller": "module.or.function", "prompt": "text"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- caller is optional; if omitted, extraction will infer module/function context.\n"
        "- prompt should preserve the original text that defines the downstream action.\n"
        "- Include only lines that can be interpreted as potential agent calls.\n"
        f"{cli_hint}\n"
        "Source:\n"
        f"{source}"
    )

    try:
        raw_output = run_agent(
            agent_name=registry.strategy_matcher_agent,
            prompt=prompt,
            workspace=project_root,
        )
        output = _parse_llm_json_output(raw_output)
    except Exception as exc:
        logger.debug("Prompt alignment failed for %s: %s", file_path, exc)
        output = None

    sites: list[_PromptCallSite] = []
    if isinstance(output, dict):
        raw_sites = output.get("prompt_sites")
        if isinstance(raw_sites, list):
            for raw_site in raw_sites:
                if not isinstance(raw_site, dict):
                    continue
                prompt_text = raw_site.get("prompt") or raw_site.get("prompt_text")
                if not isinstance(prompt_text, str):
                    continue
                caller = str(raw_site.get("caller", "")).strip()
                sites.append(
                    _PromptCallSite(
                        caller=caller,
                        prompt_text=prompt_text.strip(),
                        source="aligned_prompt",
                    )
                )

    if not sites:
        # Last-ditch fallback: return regex-extracted prompt-like segments.
        sites.extend(
            _collect_agent_prompt_sites_from_text(source, module_prefix, registry=registry)
        )
    return sites


def _collect_agent_prompt_sites(
    *,
    file_path: Path,
    source: str,
    source_analysis: SourceAnalysis,
    project_root: Path,
    registry: StrategyRegistry | None = None,
) -> list[_PromptCallSite]:
    module_prefix = _module_name_from_path(file_path, project_root)
    sites: list[_PromptCallSite] = []
    sites.extend(_collect_agent_prompt_sites_from_ast(file_path, source))
    if not sites:
        sites.extend(
            _collect_agent_prompt_sites_from_text(source, module_prefix, registry=registry)
        )
    return sites


def _collect_agent_prompt_sites_from_ast(file_path: Path, source: str) -> list[_PromptCallSite]:
    if file_path.suffix != ".py":
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    collector = _RunAgentPromptCollector()
    collector.visit(tree)
    return [site for site in collector.sites if site.prompt_text]


def _collect_agent_prompt_sites_from_text(
    source: str,
    module_prefix: str,
    registry: StrategyRegistry | None = None,
) -> list[_PromptCallSite]:
    if registry is None:
        registry = _DEFAULT_REGISTRY
    sites: list[_PromptCallSite] = []
    if _RUN_AGENT_NAME_RE.search(source):
        for call_body in _RUN_AGENT_CALL_RE.findall(source):
            prompts = _extract_prompt_text_from_call_body(call_body)
            for prompt_text in prompts:
                sites.append(
                    _PromptCallSite(
                        caller=module_prefix, prompt_text=prompt_text, source="text_scan"
                    )
                )

    # Also scan for CLI dispatch patterns
    for cli_pattern in registry.cli_patterns:
        for match in cli_pattern.pattern.finditer(source):
            callee = match.group(cli_pattern.callee_group)
            if callee:
                sites.append(
                    _PromptCallSite(
                        caller=module_prefix,
                        prompt_text=callee,
                        source=f"cli_dispatch:{cli_pattern.name}",
                    )
                )

    return sites


def _extract_prompt_text_from_call_body(call_body: str) -> list[str]:
    prompts: list[str] = []
    payload = _extract_json_payload(
        f"{{{call_body}}}" if "{" in call_body and call_body.count("{") > 0 else call_body
    )
    if payload:
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            data = json.loads(payload)
            if isinstance(data, dict):
                for key in ("prompt", "instruction", "task", "query", "prompt_text"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        prompts.append(val.strip())

    for match in _PROMPT_KEYWORD_RE.finditer(call_body):
        prompt = match.group(2)
        if prompt:
            prompts.append(_strip_quotes(prompt).strip())

    for raw in _STRING_LITERAL_RE.findall(call_body):
        value = _strip_quotes(raw[0] if isinstance(raw, tuple) else raw)
        if value and len(value.strip()) > 12:
            prompts.append(value.strip())

    if not prompts:
        for raw in _STRING_LITERAL_RE.findall(call_body):
            value = _strip_quotes(raw[0] if isinstance(raw, tuple) else raw)
            if value and len(value.strip()) > 4:
                prompts.append(value.strip())

    return [p for p in prompts if p]


def _strip_quotes(value: str) -> str:
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    if value.startswith("'''") and value.endswith("'''"):
        return value[3:-3]
    if value.startswith('"""') and value.endswith('"""'):
        return value[3:-3]
    return value


def _module_name_from_path(file_path: Path, project_root: Path) -> str:
    resolved = file_path.resolve()
    try:
        relative = resolved.relative_to(project_root.resolve())
        parts = list(relative.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
    except ValueError:
        parts = [p for p in resolved.with_suffix("").parts if p]
    return ".".join(part for part in parts if part and part != "__init__")


def _qualify_name(name: str, module_prefix: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return ""
    if "." in cleaned or cleaned.startswith(f"{module_prefix}."):
        return cleaned
    return f"{module_prefix}.{cleaned}" if module_prefix else cleaned


def _normalize_call_token(token: str, module_prefix: str) -> str:
    cleaned = token.strip("`\"' \t\r\n")
    if cleaned.startswith("."):
        cleaned = cleaned[1:]
    if cleaned.startswith(f"{module_prefix}."):
        return cleaned
    if "." not in cleaned and _CALL_NAME_TOKEN_RE.fullmatch(cleaned):
        return cleaned
    return cleaned


def _coerce_confidence(value: Any) -> float:
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value_float < 0:
        return 0.0
    if value_float > 1:
        return 1.0
    return value_float


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _extract_call_expression_name(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        parts: list[str] = []
        current = expr
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        return None
    if isinstance(expr, ast.Call):
        return _extract_call_expression_name(expr.func)
    if isinstance(expr, ast.Subscript):
        return _extract_call_expression_name(expr.value)
    return None


class _FunctionCollector(ast.NodeVisitor):
    """Collect function defs and indexes from AST."""

    def __init__(self, module_prefix: str) -> None:
        self.module_prefix = module_prefix
        self.function_names: set[str] = set()
        self.function_short_index: dict[str, set[str]] = {}
        self._scope_stack: list[str] = []

    def _current_scope(self) -> str:
        return ".".join(self._scope_stack)

    def _qualified(self, name: str) -> str:
        prefix = self._current_scope()
        if prefix:
            return f"{self.module_prefix}.{prefix}.{name}"
        return f"{self.module_prefix}.{name}"

    def _register(self, name: str) -> None:
        self.function_names.add(name)
        short = name.rsplit(".", 1)[-1]
        self.function_short_index.setdefault(short, set()).add(name)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        full = self._qualified(node.name)
        self._register(full)
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        """Handle async function definitions as regular functions."""
        full = self._qualified(node.name)
        self._register(full)
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()


class _CallVisitor(ast.NodeVisitor):
    """Collect call graph edges from AST."""

    def __init__(
        self,
        *,
        module_prefix: str,
        function_names: set[str],
        function_short_index: dict[str, set[str]],
    ) -> None:
        self.module_prefix = module_prefix
        self.function_full = set(function_names)
        self.function_short_index = function_short_index
        self.edges: set[tuple[str, str]] = set()
        self.unsupported_calls: list[dict[str, Any]] = []
        self._scope_stack: list[str] = []

    def _current_scope(self) -> str:
        return ".".join(self._scope_stack)

    def _caller_name(self) -> str:
        prefix = self._current_scope()
        return f"{self.module_prefix}.{prefix}" if prefix else ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        """Handle async function definitions as regular functions."""
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> Any:
        caller = self._caller_name()
        if not caller:
            self.generic_visit(node)
            return

        target_name = _extract_call_expression_name(node.func)
        if target_name:
            resolved = self._resolve_call_target(target_name)
            if resolved:
                if caller != resolved:
                    self.edges.add((caller, resolved))
            else:
                self.unsupported_calls.append(
                    {"caller": caller, "target": target_name, "reason": "unresolved_call"}
                )

        self.generic_visit(node)

    def _resolve_call_target(self, token: str) -> str | None:
        if token in self.function_full:
            return token
        if token in self.function_short_index:
            candidates = sorted(self.function_short_index[token])
            if len(candidates) == 1:
                return candidates[0]
        if "." in token:
            same_suffix = [
                name for name in self.function_short_index.get(token.rsplit(".", 1)[-1], set())
            ]
            if len(same_suffix) == 1:
                return same_suffix[0]
        return None


class _RunAgentPromptCollector(ast.NodeVisitor):
    """Collect prompt payloads passed to run_agent() calls."""

    def __init__(self) -> None:
        self._scope_stack: list[str] = []
        self.sites: list[_PromptCallSite] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        """Handle async function definitions as regular functions."""
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def _caller_name(self) -> str:
        return ".".join(self._scope_stack)

    def visit_Call(self, node: ast.Call) -> Any:
        if not _is_run_agent_call(node):
            self.generic_visit(node)
            return

        caller = self._caller_name()
        for prompt_text in _extract_prompt_call_args(node):
            self.sites.append(_PromptCallSite(caller=caller, prompt_text=prompt_text, source="ast"))

        self.generic_visit(node)


def _extract_text_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _extract_prompt_call_args(node: ast.Call) -> list[str]:
    results: list[str] = []
    for keyword in node.keywords:
        if keyword.arg != "prompt" or keyword.value is None:
            continue
        prompt_literal = _extract_text_literal(keyword.value)
        if prompt_literal:
            results.append(prompt_literal)

    for arg in node.args:
        if len(results) >= 2:
            break
        prompt_literal = _extract_text_literal(arg)
        if prompt_literal:
            results.append(prompt_literal)
    return results


def _is_run_agent_call(node: ast.Call) -> bool:
    name = _extract_call_expression_name(node.func)
    if not name:
        return False
    return name.endswith("run_agent") or name == "run_agent"
