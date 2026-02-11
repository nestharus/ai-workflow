"""Comprehensive unit tests for the orchestration test_tiers module.

Tests cover:
- TierResult dataclass and to_dict serialization (including truncation)
- TierConfig defaults and custom values
- TierRunner.run_for_layer layer-to-tier mapping (l1, l2, l3, unknown)
- TierRunner skip behavior for unconfigured tiers
- TierRunner fail-fast on first failing tier
- TierRunner subprocess timeout and exception handling
- TierRunner with real passing and failing commands
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration.test_tiers import (
    _LAYER_TIERS,
    TierConfig,
    TierResult,
    TierRunner,
)

# ===================================================================
# 1. TierResult tests
# ===================================================================


class TestTierResultToDict:
    """Test TierResult.to_dict serialization."""

    def test_basic_fields_serialized(self) -> None:
        """Verify all fields appear in the dict with correct values."""
        result = TierResult(
            tier=2,
            passed=True,
            output="all tests passed",
            error="",
            duration_ms=1234.5,
        )
        d = result.to_dict()
        assert d["tier"] == 2
        assert d["passed"] is True
        assert d["output"] == "all tests passed"
        assert d["error"] == ""
        assert d["duration_ms"] == 1234.5

    def test_defaults_serialized(self) -> None:
        """Verify default TierResult serializes correctly."""
        result = TierResult()
        d = result.to_dict()
        assert d["tier"] == 0
        assert d["passed"] is True
        assert d["output"] == ""
        assert d["error"] == ""
        assert d["duration_ms"] == 0.0

    def test_truncates_long_output(self) -> None:
        """Verify output is truncated to 2000 characters in to_dict."""
        long_output = "x" * 5000
        result = TierResult(tier=1, output=long_output)
        d = result.to_dict()
        assert len(d["output"]) == 2000
        assert d["output"] == "x" * 2000

    def test_truncates_long_error(self) -> None:
        """Verify error is truncated to 1000 characters in to_dict."""
        long_error = "e" * 3000
        result = TierResult(tier=1, passed=False, error=long_error)
        d = result.to_dict()
        assert len(d["error"]) == 1000
        assert d["error"] == "e" * 1000

    def test_output_at_boundary_not_truncated(self) -> None:
        """Verify output of exactly 2000 chars is not truncated."""
        exact_output = "a" * 2000
        result = TierResult(output=exact_output)
        d = result.to_dict()
        assert len(d["output"]) == 2000
        assert d["output"] == exact_output

    def test_error_at_boundary_not_truncated(self) -> None:
        """Verify error of exactly 1000 chars is not truncated."""
        exact_error = "b" * 1000
        result = TierResult(error=exact_error)
        d = result.to_dict()
        assert len(d["error"]) == 1000
        assert d["error"] == exact_error

    def test_short_output_preserved(self) -> None:
        """Verify output shorter than 2000 chars is fully preserved."""
        short_output = "hello world"
        result = TierResult(output=short_output)
        d = result.to_dict()
        assert d["output"] == short_output

    def test_to_dict_returns_plain_dict(self) -> None:
        """Verify to_dict returns a plain dict, not a dataclass."""
        result = TierResult(tier=3, passed=False)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {"tier", "passed", "output", "error", "duration_ms"}


# ===================================================================
# 2. TierConfig tests
# ===================================================================


class TestTierConfigDefaults:
    """Test TierConfig default values."""

    def test_tier0_command_default(self) -> None:
        """Verify tier0_command defaults to 'python -m compileall -q .'."""
        config = TierConfig()
        assert config.tier0_command == "python -m compileall -q ."

    def test_other_commands_default_empty(self) -> None:
        """Verify tier1, tier2, tier3 commands default to empty string."""
        config = TierConfig()
        assert config.tier1_command == ""
        assert config.tier2_command == ""
        assert config.tier3_command == ""

    def test_timeout_defaults(self) -> None:
        """Verify default timeouts: 60, 300, 600, 1200 seconds."""
        config = TierConfig()
        assert config.tier0_timeout == 60
        assert config.tier1_timeout == 300
        assert config.tier2_timeout == 600
        assert config.tier3_timeout == 1200


class TestTierConfigCustom:
    """Test TierConfig with custom values."""

    def test_custom_commands(self) -> None:
        """Verify custom commands are stored correctly."""
        config = TierConfig(
            tier0_command="echo smoke",
            tier1_command="pytest tests/unit -x",
            tier2_command="pytest tests/integration -x",
            tier3_command="pytest tests/ --full",
        )
        assert config.tier0_command == "echo smoke"
        assert config.tier1_command == "pytest tests/unit -x"
        assert config.tier2_command == "pytest tests/integration -x"
        assert config.tier3_command == "pytest tests/ --full"

    def test_custom_timeouts(self) -> None:
        """Verify custom timeouts are stored correctly."""
        config = TierConfig(
            tier0_timeout=10,
            tier1_timeout=30,
            tier2_timeout=60,
            tier3_timeout=120,
        )
        assert config.tier0_timeout == 10
        assert config.tier1_timeout == 30
        assert config.tier2_timeout == 60
        assert config.tier3_timeout == 120


# ===================================================================
# 3. _LAYER_TIERS mapping tests
# ===================================================================


class TestLayerTiersMapping:
    """Test the _LAYER_TIERS constant."""

    def test_l1_tiers(self) -> None:
        """Verify l1 maps to tiers [0, 1]."""
        assert _LAYER_TIERS["l1"] == [0, 1]

    def test_l2_tiers(self) -> None:
        """Verify l2 maps to tiers [0, 1, 2]."""
        assert _LAYER_TIERS["l2"] == [0, 1, 2]

    def test_l3_tiers(self) -> None:
        """Verify l3 maps to tiers [0, 1, 2, 3]."""
        assert _LAYER_TIERS["l3"] == [0, 1, 2, 3]

    def test_only_three_layers(self) -> None:
        """Verify only l1, l2, l3 are defined."""
        assert set(_LAYER_TIERS.keys()) == {"l1", "l2", "l3"}


# ===================================================================
# 4. TierRunner.run_for_layer tests
# ===================================================================


class TestTierRunnerRunForLayer:
    """Test TierRunner.run_for_layer dispatches correct tiers per layer."""

    def test_l1_runs_tiers_0_and_1(self) -> None:
        """Verify l1 runs tiers 0 and 1."""
        config = TierConfig(
            tier0_command="echo tier0",
            tier1_command="echo tier1",
            tier2_command="echo tier2",
            tier3_command="echo tier3",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l1")
        assert len(results) == 2
        assert results[0].tier == 0
        assert results[1].tier == 1
        assert all(r.passed for r in results)

    def test_l2_runs_tiers_0_1_2(self) -> None:
        """Verify l2 runs tiers 0, 1, and 2."""
        config = TierConfig(
            tier0_command="echo tier0",
            tier1_command="echo tier1",
            tier2_command="echo tier2",
            tier3_command="echo tier3",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l2")
        assert len(results) == 3
        assert [r.tier for r in results] == [0, 1, 2]
        assert all(r.passed for r in results)

    def test_l3_runs_tiers_0_1_2_3(self) -> None:
        """Verify l3 runs all four tiers."""
        config = TierConfig(
            tier0_command="echo tier0",
            tier1_command="echo tier1",
            tier2_command="echo tier2",
            tier3_command="echo tier3",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l3")
        assert len(results) == 4
        assert [r.tier for r in results] == [0, 1, 2, 3]
        assert all(r.passed for r in results)

    def test_unknown_layer_defaults_to_tier_0(self) -> None:
        """Verify unknown layer falls back to [0] (tier 0 only)."""
        config = TierConfig(tier0_command="echo fallback")
        runner = TierRunner(config=config)
        results = runner.run_for_layer("unknown_layer")
        assert len(results) == 1
        assert results[0].tier == 0
        assert results[0].passed is True
        assert "fallback" in results[0].output


# ===================================================================
# 5. TierRunner skip behavior (unconfigured tiers)
# ===================================================================


class TestTierRunnerSkipUnconfigured:
    """Test that empty command strings produce a passing skip result."""

    def test_unconfigured_tier_skipped_with_pass(self) -> None:
        """Verify an unconfigured tier (empty command) returns passed=True with skip note."""
        config = TierConfig(
            tier0_command="echo smoke",
            tier1_command="",  # unconfigured
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l1")

        assert len(results) == 2
        # Tier 0 should run normally
        assert results[0].tier == 0
        assert results[0].passed is True

        # Tier 1 should be skipped
        assert results[1].tier == 1
        assert results[1].passed is True
        assert "skipped" in results[1].output.lower()

    def test_all_tiers_unconfigured(self) -> None:
        """Verify all-empty config results in all passes with skip notes."""
        config = TierConfig(
            tier0_command="",
            tier1_command="",
            tier2_command="",
            tier3_command="",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l3")

        assert len(results) == 4
        assert all(r.passed for r in results)
        assert all("skipped" in r.output.lower() for r in results)


# ===================================================================
# 6. TierRunner fail-fast behavior
# ===================================================================


class TestTierRunnerFailFast:
    """Test that TierRunner stops on first failing tier."""

    def test_stops_on_first_failure(self) -> None:
        """Verify execution stops at first failing tier and subsequent tiers are not run."""
        config = TierConfig(
            tier0_command="echo tier0",
            tier1_command="false",  # fails (exit code 1)
            tier2_command="echo tier2",  # should not be reached
            tier3_command="echo tier3",  # should not be reached
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l3")

        # Should stop after tier 1 fails
        assert len(results) == 2
        assert results[0].tier == 0
        assert results[0].passed is True
        assert results[1].tier == 1
        assert results[1].passed is False

    def test_fail_at_tier_0_stops_immediately(self) -> None:
        """Verify failure at tier 0 prevents all subsequent tiers."""
        config = TierConfig(
            tier0_command="false",
            tier1_command="echo tier1",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l1")

        assert len(results) == 1
        assert results[0].tier == 0
        assert results[0].passed is False


# ===================================================================
# 7. TierRunner subprocess timeout handling
# ===================================================================


class TestTierRunnerTimeout:
    """Test TierRunner handles subprocess.TimeoutExpired."""

    @patch("spec_manager.orchestration.test_tiers.subprocess.run")
    def test_timeout_returns_failed_result(self, mock_run: MagicMock) -> None:
        """Verify TimeoutExpired produces a failed TierResult with timeout message."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="slow_command", timeout=60)
        config = TierConfig(tier0_command="slow_command", tier0_timeout=60)
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        # Tier 0 should have failed due to timeout
        assert results[0].tier == 0
        assert results[0].passed is False
        assert "timed out" in results[0].error.lower()
        assert "60" in results[0].error
        assert results[0].duration_ms > 0 or results[0].duration_ms == 0  # non-negative

    @patch("spec_manager.orchestration.test_tiers.subprocess.run")
    def test_timeout_fail_fast_prevents_later_tiers(self, mock_run: MagicMock) -> None:
        """Verify timeout at tier 0 prevents subsequent tiers from running."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="slow_command", timeout=60)
        config = TierConfig(
            tier0_command="slow_command",
            tier1_command="echo fast",
        )
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")
        assert len(results) == 1
        assert results[0].passed is False


# ===================================================================
# 8. TierRunner subprocess exception handling
# ===================================================================


class TestTierRunnerException:
    """Test TierRunner handles generic subprocess exceptions."""

    @patch("spec_manager.orchestration.test_tiers.subprocess.run")
    def test_exception_returns_failed_result(self, mock_run: MagicMock) -> None:
        """Verify a generic exception produces a failed TierResult."""
        mock_run.side_effect = OSError("No such file or directory")
        config = TierConfig(tier0_command="nonexistent_command")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].tier == 0
        assert results[0].passed is False
        assert "No such file or directory" in results[0].error

    @patch("spec_manager.orchestration.test_tiers.subprocess.run")
    def test_runtime_error_handled(self, mock_run: MagicMock) -> None:
        """Verify RuntimeError is caught and converted to failed TierResult."""
        mock_run.side_effect = RuntimeError("unexpected failure")
        config = TierConfig(tier0_command="broken_command")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].passed is False
        assert "unexpected failure" in results[0].error


# ===================================================================
# 9. TierRunner with real commands
# ===================================================================


class TestTierRunnerRealCommands:
    """Test TierRunner with actual shell commands."""

    def test_passing_command_echo(self) -> None:
        """Verify 'echo hello' produces a passing result with captured output."""
        config = TierConfig(tier0_command="echo hello")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].tier == 0
        assert results[0].passed is True
        assert "hello" in results[0].output
        assert results[0].duration_ms >= 0

    def test_failing_command_false(self) -> None:
        """Verify 'false' produces a failing result (exit code 1)."""
        config = TierConfig(tier0_command="false")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].tier == 0
        assert results[0].passed is False
        assert results[0].duration_ms >= 0

    def test_passing_command_true(self) -> None:
        """Verify 'true' produces a passing result."""
        config = TierConfig(tier0_command="true")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].passed is True

    def test_command_captures_stderr(self) -> None:
        """Verify stderr from commands is captured."""
        config = TierConfig(tier0_command="echo error_msg >&2")
        runner = TierRunner(config=config)

        results = runner.run_for_layer("l1")

        assert results[0].passed is True
        assert "error_msg" in results[0].error


# ===================================================================
# 10. TierRunner with cwd parameter
# ===================================================================


class TestTierRunnerCwd:
    """Test TierRunner with a custom working directory."""

    def test_cwd_passed_to_subprocess(self, tmp_path: Path) -> None:
        """Verify TierRunner runs commands in the specified directory."""
        config = TierConfig(tier0_command="pwd")
        runner = TierRunner(config=config, cwd=tmp_path)

        results = runner.run_for_layer("l1")

        assert results[0].passed is True
        # The output should contain the tmp_path
        # (On some systems pwd resolves symlinks, so check the basename)
        assert tmp_path.name in results[0].output or str(tmp_path) in results[0].output

    def test_default_cwd_is_none(self) -> None:
        """Verify TierRunner defaults to cwd=None."""
        runner = TierRunner()
        assert runner.cwd is None

    def test_default_config_is_created(self) -> None:
        """Verify TierRunner creates a default TierConfig if none provided."""
        runner = TierRunner()
        assert isinstance(runner.config, TierConfig)
        assert runner.config.tier0_command == "python -m compileall -q ."


# ===================================================================
# 11. TierRunner._get_command and _get_timeout
# ===================================================================


class TestTierRunnerGetCommandAndTimeout:
    """Test the internal _get_command and _get_timeout methods."""

    def test_get_command_for_each_tier(self) -> None:
        """Verify _get_command returns the correct command for each tier."""
        config = TierConfig(
            tier0_command="cmd0",
            tier1_command="cmd1",
            tier2_command="cmd2",
            tier3_command="cmd3",
        )
        runner = TierRunner(config=config)

        assert runner._get_command(0) == "cmd0"
        assert runner._get_command(1) == "cmd1"
        assert runner._get_command(2) == "cmd2"
        assert runner._get_command(3) == "cmd3"

    def test_get_command_unknown_tier_returns_empty(self) -> None:
        """Verify _get_command returns empty string for unknown tier number."""
        runner = TierRunner()
        assert runner._get_command(99) == ""

    def test_get_timeout_for_each_tier(self) -> None:
        """Verify _get_timeout returns the correct timeout for each tier."""
        config = TierConfig(
            tier0_timeout=10,
            tier1_timeout=20,
            tier2_timeout=30,
            tier3_timeout=40,
        )
        runner = TierRunner(config=config)

        assert runner._get_timeout(0) == 10
        assert runner._get_timeout(1) == 20
        assert runner._get_timeout(2) == 30
        assert runner._get_timeout(3) == 40

    def test_get_timeout_unknown_tier_returns_300(self) -> None:
        """Verify _get_timeout returns 300 (default) for unknown tier number."""
        runner = TierRunner()
        assert runner._get_timeout(99) == 300


# ===================================================================
# 12. TierRunner._run_tier directly
# ===================================================================


class TestTierRunnerRunTierDirect:
    """Test _run_tier method directly for fine-grained behavior checks."""

    def test_run_tier_with_configured_command(self) -> None:
        """Verify _run_tier executes configured command and returns result."""
        config = TierConfig(tier0_command="echo direct_test")
        runner = TierRunner(config=config)

        result = runner._run_tier(0)

        assert result.tier == 0
        assert result.passed is True
        assert "direct_test" in result.output

    def test_run_tier_unconfigured_returns_skip(self) -> None:
        """Verify _run_tier with empty command returns skip result."""
        config = TierConfig(tier1_command="")
        runner = TierRunner(config=config)

        result = runner._run_tier(1)

        assert result.tier == 1
        assert result.passed is True
        assert "skipped" in result.output.lower()
        assert result.duration_ms == 0.0

    def test_run_tier_records_duration(self) -> None:
        """Verify _run_tier records a positive duration for real commands."""
        config = TierConfig(tier0_command="echo timing")
        runner = TierRunner(config=config)

        result = runner._run_tier(0)

        assert result.duration_ms >= 0

    def test_run_tier_failed_command(self) -> None:
        """Verify _run_tier with failing command returns passed=False."""
        config = TierConfig(tier0_command="false")
        runner = TierRunner(config=config)

        result = runner._run_tier(0)

        assert result.tier == 0
        assert result.passed is False


# ===================================================================
# 13. Integration: full layer run with mixed pass/skip/fail
# ===================================================================


class TestTierRunnerIntegration:
    """Integration tests combining multiple behaviors."""

    def test_l2_with_skip_at_tier2(self) -> None:
        """Verify l2 run with tier2 unconfigured: tiers 0,1 pass, tier 2 skipped."""
        config = TierConfig(
            tier0_command="echo smoke",
            tier1_command="echo unit",
            tier2_command="",  # unconfigured => skip
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l2")

        assert len(results) == 3
        assert results[0].passed is True
        assert results[1].passed is True
        assert results[2].passed is True
        assert "skipped" in results[2].output.lower()

    def test_l3_fail_at_tier2_skips_tier3(self) -> None:
        """Verify l3 run where tier2 fails: tier3 is never executed."""
        config = TierConfig(
            tier0_command="echo smoke",
            tier1_command="echo unit",
            tier2_command="false",  # fails
            tier3_command="echo full",  # should not run
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l3")

        assert len(results) == 3  # 0, 1, 2 (stopped at 2)
        assert results[0].passed is True
        assert results[1].passed is True
        assert results[2].passed is False
        assert results[2].tier == 2

    def test_all_tiers_pass_for_l3(self) -> None:
        """Verify a complete successful l3 run."""
        config = TierConfig(
            tier0_command="true",
            tier1_command="true",
            tier2_command="true",
            tier3_command="true",
        )
        runner = TierRunner(config=config)
        results = runner.run_for_layer("l3")

        assert len(results) == 4
        assert all(r.passed for r in results)
        assert [r.tier for r in results] == [0, 1, 2, 3]
