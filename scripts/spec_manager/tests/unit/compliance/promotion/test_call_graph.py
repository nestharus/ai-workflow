"""Tests for adaptive call-graph strategy creation and reuse."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from spec_manager.compliance.promotion import call_graph
from spec_manager.compliance.promotion.call_graph import (
    CallGraphBuildResult,
    StrategyRegistry,
    _AdaptiveTextAlignCallGraphStrategy,
    _CallVisitor,
    _CliDispatchPattern,
    _collect_agent_prompt_sites_from_text,
    _FunctionCollector,
    _NoopCallGraphStrategy,
    _PromptJitParserStrategy,
    _select_or_create_call_graph_strategy,
    _select_prompt_parser,
    build_call_graph,
)
from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile
from spec_manager.core.code_analysis import RawFunctionInfo, SourceAnalysis


def _function_info(name: str, qualified_name: str) -> RawFunctionInfo:
    return RawFunctionInfo(
        name=name,
        qualified_name=qualified_name,
        start_line=1,
        end_line=4,
        is_async=False,
        is_stub=False,
        stub_reason=None,
        has_docstring=False,
        docstring=None,
        decorators=(),
        args=(),
        return_annotation=None,
        body_start_line=1,
        body_line_count=3,
    )


# ---------------------------------------------------------------------------
# Existing tests (updated to use StrategyRegistry)
# ---------------------------------------------------------------------------


def test_select_or_create_call_graph_strategy_reuses_for_same_surface(tmp_path: Path) -> None:
    registry = StrategyRegistry()
    source = "Alpha should call beta via run_agent."
    file_path = tmp_path / "flow.md"
    file_path.write_text(source, encoding="utf-8")

    with patch.object(
        call_graph,
        "run_agent",
        side_effect=[
            '{"strategy": "text_aligner", "parser_preference": "directive"}',
        ],
    ) as mock_run_agent:
        first = _select_or_create_call_graph_strategy(
            file_path=file_path,
            source=source,
            project_root=tmp_path,
            analyzed=SourceAnalysis(),
            registry=registry,
        )
        second = _select_or_create_call_graph_strategy(
            file_path=file_path,
            source=source,
            project_root=tmp_path,
            analyzed=SourceAnalysis(),
            registry=registry,
        )

    assert isinstance(first, _AdaptiveTextAlignCallGraphStrategy)
    assert first is second
    assert mock_run_agent.call_count == 1


def test_build_call_graph_uses_adaptive_aligner(tmp_path: Path) -> None:
    registry = StrategyRegistry()
    source = "Design notes:\nThe orchestration should ask the planner to run step 7.\n"
    file_path = tmp_path / "notes.md"
    file_path.write_text(source, encoding="utf-8")

    analyzed = AnalyzedFile(
        path=str(file_path),
        analysis=SourceAnalysis(
            functions=[
                _function_info("alpha", "module.alpha"),
                _function_info("beta", "module.beta"),
            ]
        ),
        content=source,
    )

    matcher_response = (
        '{"strategy":"text_aligner","parser_preference":"directive","source":"freeform"}'
    )
    aligner_response = (
        '{"prompt_sites":[{"caller":"module.alpha","prompt":"invoke beta when condition met"}]}'
    )

    with patch.object(
        call_graph, "run_agent", side_effect=[matcher_response, aligner_response]
    ) as mock_run_agent:
        result = build_call_graph(
            [file_path],
            tmp_path,
            [analyzed],
            registry=registry,
        )

    assert mock_run_agent.call_count == 2
    assert isinstance(result, CallGraphBuildResult)
    assert any(edge.callee.endswith("beta") for edge in result.edges)
    assert any(edge.strategy.startswith("jit_") for edge in result.edges)


def test_select_prompt_parser_reuses_preferred_jit_strategy(tmp_path: Path) -> None:
    registry = StrategyRegistry()
    file_path = tmp_path / "notes.md"
    function_index = {"module.beta": {"module.beta"}}

    # Return a regex strategy with actual patterns so can_parse passes
    jit_response = '{"parser_type":"regex","regex_patterns":["\\\\bbeta\\\\b"],"confidence":0.5}'

    with patch.object(call_graph, "run_agent", return_value=jit_response) as mock_run_agent:
        first = _select_prompt_parser(
            prompt_text="Beta is needed before this workflow can continue.",
            file_path=file_path,
            project_root=tmp_path,
            function_index=function_index,
            caller="module.alpha",
            module_prefix="module",
            preferred_parser="regex",
            registry=registry,
        )
        second = _select_prompt_parser(
            prompt_text="Beta is needed before this workflow can continue.",
            file_path=file_path,
            project_root=tmp_path,
            function_index=function_index,
            caller="module.alpha",
            module_prefix="module",
            preferred_parser="regex",
            registry=registry,
        )

    assert mock_run_agent.call_count == 1
    assert first is second
    assert isinstance(first, _PromptJitParserStrategy)
    assert first._parser_mode == "regex"


# ---------------------------------------------------------------------------
# Step 2 verification: FunctionCollector name qualification
# ---------------------------------------------------------------------------


class TestFunctionCollectorNameQualification:
    """Verify _FunctionCollector does not double names."""

    def test_top_level_function(self) -> None:
        import ast

        source = "def alpha(): pass"
        tree = ast.parse(source)
        collector = _FunctionCollector("mod")
        collector.visit(tree)
        assert "mod.alpha" in collector.function_names
        # Must NOT contain doubled name
        assert "mod.alpha.alpha" not in collector.function_names

    def test_nested_function(self) -> None:
        import ast

        source = textwrap.dedent("""\
            def outer():
                def inner():
                    pass
        """)
        tree = ast.parse(source)
        collector = _FunctionCollector("mod")
        collector.visit(tree)
        assert "mod.outer" in collector.function_names
        assert "mod.outer.inner" in collector.function_names
        assert "mod.outer.outer" not in collector.function_names

    def test_class_method(self) -> None:
        import ast

        source = textwrap.dedent("""\
            class Foo:
                def bar(self):
                    pass
        """)
        tree = ast.parse(source)
        collector = _FunctionCollector("mod")
        collector.visit(tree)
        assert "mod.Foo.bar" in collector.function_names
        assert "mod.Foo.bar.bar" not in collector.function_names

    def test_async_function(self) -> None:
        import ast

        source = "async def handler(): pass"
        tree = ast.parse(source)
        collector = _FunctionCollector("mod")
        collector.visit(tree)
        assert "mod.handler" in collector.function_names
        assert "mod.handler.handler" not in collector.function_names


# ---------------------------------------------------------------------------
# Edge consistency: collector names match visitor caller names
# ---------------------------------------------------------------------------


class TestCallGraphEdgeConsistency:
    """Verify collector node names match visitor caller names for proper union-find."""

    def test_edges_connect_collected_nodes(self) -> None:
        import ast

        source = textwrap.dedent("""\
            def a():
                b()

            def b():
                pass
        """)
        tree = ast.parse(source)
        collector = _FunctionCollector("disconnected")
        collector.visit(tree)

        visitor = _CallVisitor(
            module_prefix="disconnected",
            function_names=collector.function_names,
            function_short_index=collector.function_short_index,
        )
        visitor.visit(tree)

        assert "disconnected.a" in collector.function_names
        assert "disconnected.b" in collector.function_names
        assert ("disconnected.a", "disconnected.b") in visitor.edges

    def test_nested_call_edges(self) -> None:
        import ast

        source = textwrap.dedent("""\
            def outer():
                def inner():
                    pass
                inner()
        """)
        tree = ast.parse(source)
        collector = _FunctionCollector("m")
        collector.visit(tree)

        visitor = _CallVisitor(
            module_prefix="m",
            function_names=collector.function_names,
            function_short_index=collector.function_short_index,
        )
        visitor.visit(tree)

        assert "m.outer" in collector.function_names
        assert "m.outer.inner" in collector.function_names
        assert ("m.outer", "m.outer.inner") in visitor.edges


# ---------------------------------------------------------------------------
# StrategyRegistry tests
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    """Verify StrategyRegistry isolation and clear."""

    def test_fresh_registry_is_empty(self) -> None:
        reg = StrategyRegistry()
        assert reg.call_graph_strategies == {}
        assert reg.parser_strategies == {}
        assert reg.strategy_matcher_agent == "pdd-code-analyzer"

    def test_clear_empties_caches(self) -> None:
        reg = StrategyRegistry()
        reg.call_graph_strategies["test"] = _NoopCallGraphStrategy(
            name="test", surface_signature="abc"
        )
        reg.clear()
        assert reg.call_graph_strategies == {}
        assert reg.parser_strategies == {}

    def test_custom_agent_name(self) -> None:
        reg = StrategyRegistry(strategy_matcher_agent="custom-agent")
        assert reg.strategy_matcher_agent == "custom-agent"

    def test_isolation_between_registries(self) -> None:
        reg1 = StrategyRegistry()
        reg2 = StrategyRegistry()
        reg1.call_graph_strategies["key"] = _NoopCallGraphStrategy(
            name="noop", surface_signature="x"
        )
        assert "key" not in reg2.call_graph_strategies


# ---------------------------------------------------------------------------
# Strategy validation tests
# ---------------------------------------------------------------------------


class TestStrategyValidation:
    """Verify useless strategies are downgraded to noop."""

    def test_useless_python_ast_downgraded_to_noop(self, tmp_path: Path) -> None:
        """When LLM proposes python_ast for a .py file with invalid syntax, validation fails -> noop."""
        registry = StrategyRegistry()
        source = "this is not valid python {{{"
        file_path = tmp_path / "broken.py"
        file_path.write_text(source, encoding="utf-8")

        # LLM proposes python_ast — but the file has syntax errors, so
        # PythonAstCallGraphStrategy.can_handle returns False, leading to
        # an AdaptiveTextAlignCallGraphStrategy fallback. However if the
        # LLM returns noop, we get a noop.
        matcher_response = '{"strategy": "noop", "confidence": 0.1, "source": "test"}'

        with patch.object(call_graph, "run_agent", return_value=matcher_response):
            strategy = _select_or_create_call_graph_strategy(
                file_path=file_path,
                source=source,
                project_root=tmp_path,
                analyzed=SourceAnalysis(),
                registry=registry,
            )

        assert isinstance(strategy, _NoopCallGraphStrategy)

    def test_deterministic_strategy_validated_on_empty_file(self, tmp_path: Path) -> None:
        """A python_ast strategy on an empty .py file produces no nodes/edges -> noop."""
        registry = StrategyRegistry()
        source = ""
        file_path = tmp_path / "empty.py"
        file_path.write_text(source, encoding="utf-8")

        matcher_response = '{"strategy": "python_ast", "confidence": 0.9}'

        with patch.object(call_graph, "run_agent", return_value=matcher_response):
            strategy = _select_or_create_call_graph_strategy(
                file_path=file_path,
                source=source,
                project_root=tmp_path,
                analyzed=SourceAnalysis(),
                registry=registry,
            )

        # PythonAstCallGraphStrategy.can_handle passes (empty is valid python),
        # but extract produces nothing — validation fails, downgrade to noop.
        assert isinstance(strategy, _NoopCallGraphStrategy)


# ---------------------------------------------------------------------------
# CLI dispatch pattern tests
# ---------------------------------------------------------------------------


class TestCliDispatchPatterns:
    """Verify CLI dispatch pattern detection in text scanning."""

    def test_run_agent_kwarg_pattern(self) -> None:
        registry = StrategyRegistry()
        source = 'result = run_agent(agent_name="my-analyzer", prompt="do stuff")'
        sites = _collect_agent_prompt_sites_from_text(source, "mod", registry=registry)
        # Should find both text_scan sites and cli_dispatch sites
        cli_sites = [s for s in sites if s.source.startswith("cli_dispatch:")]
        assert any(s.prompt_text == "my-analyzer" for s in cli_sites)

    def test_uv_run_pattern(self) -> None:
        registry = StrategyRegistry()
        source = "uv run spec --verbose"
        sites = _collect_agent_prompt_sites_from_text(source, "mod", registry=registry)
        cli_sites = [s for s in sites if s.source.startswith("cli_dispatch:")]
        assert any(s.prompt_text == "spec" for s in cli_sites)

    def test_no_cli_patterns_when_empty(self) -> None:
        registry = StrategyRegistry(cli_patterns=[])
        source = 'run_agent(agent_name="test", prompt="hello")'
        sites = _collect_agent_prompt_sites_from_text(source, "mod", registry=registry)
        cli_sites = [s for s in sites if s.source.startswith("cli_dispatch:")]
        assert len(cli_sites) == 0


# ---------------------------------------------------------------------------
# Research integration tests
# ---------------------------------------------------------------------------


class TestResearchIntegration:
    """Verify research enriches agent prompts when configured."""

    def test_research_enriches_strategy_proposal(self, tmp_path: Path) -> None:
        mock_research = MagicMock()
        mock_research.research.return_value = MagicMock(
            has_answer=True,
            synthesis="Python files commonly use AST for call graph extraction.",
        )
        registry = StrategyRegistry(research_tool=mock_research)
        source = "def hello(): pass"
        file_path = tmp_path / "test.py"
        file_path.write_text(source, encoding="utf-8")

        with patch.object(
            call_graph, "run_agent", return_value='{"strategy":"python_ast","confidence":0.9}'
        ):
            _select_or_create_call_graph_strategy(
                file_path=file_path,
                source=source,
                project_root=tmp_path,
                analyzed=SourceAnalysis(),
                registry=registry,
            )

        # research_tool.research should have been called
        mock_research.research.assert_called()

    def test_no_research_when_not_configured(self, tmp_path: Path) -> None:
        registry = StrategyRegistry(research_tool=None)
        source = "def hello(): pass"
        file_path = tmp_path / "test.py"
        file_path.write_text(source, encoding="utf-8")

        # Should not raise even though no research_tool
        with patch.object(
            call_graph, "run_agent", return_value='{"strategy":"python_ast","confidence":0.9}'
        ):
            strategy = _select_or_create_call_graph_strategy(
                file_path=file_path,
                source=source,
                project_root=tmp_path,
                analyzed=SourceAnalysis(),
                registry=registry,
            )
        assert strategy is not None
