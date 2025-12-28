import pytest

from scripts.dev.test_runner.run_coverage_batches import (
    generate_agent_prompt,
    main,
    print_summary,
    run_batching,
    run_test_coverage,
)


class TestGenerateAgentPrompt:
    def test_generates_prompt_with_batch_file(self) -> None:
        """Test that prompt includes batch file path."""
        prompt = generate_agent_prompt("batch_001.json", None)
        assert "batch_001.json" in prompt

    def test_generates_prompt_with_tier(self) -> None:
        """Test that prompt is generated correctly with tier parameter."""
        # The tier parameter is currently reserved for future use
        prompt = generate_agent_prompt("batch_001.json", "unit")
        assert "batch_001.json" in prompt

    def test_prompt_contains_key_instructions(self) -> None:
        """Test that prompt contains key instructions."""
        prompt = generate_agent_prompt("batch_001.json", None)
        assert "coverage improvement task" in prompt
        assert "functions_by_test_file" in prompt
        assert "NEVER use --cov flags" in prompt
        assert "Do NOT change source code" in prompt


class TestPrintSummary:
    def test_prints_summary_with_passing_tier(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test summary output with passing tier."""
        summary = {"unit": {"failing": 0, "total": 10, "pass": True}}
        print_summary(summary, 1)
        captured = capsys.readouterr()
        assert "Iteration 1 Summary" in captured.out
        assert "unit: PASS" in captured.out
        assert "(0/10 failing)" in captured.out

    def test_prints_summary_with_failing_tier(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test summary output with failing tier."""
        summary = {"scripts": {"failing": 5, "total": 20, "pass": False}}
        print_summary(summary, 2)
        captured = capsys.readouterr()
        assert "Iteration 2 Summary" in captured.out
        assert "scripts: FAIL" in captured.out
        assert "(5/20 failing)" in captured.out

    def test_prints_summary_with_multiple_tiers(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test summary output with multiple tiers."""
        summary = {
            "unit": {"failing": 0, "total": 10, "pass": True},
            "component": {"failing": 2, "total": 15, "pass": False},
            "scripts": {"failing": 3, "total": 20, "pass": False},
        }
        print_summary(summary, 3)
        captured = capsys.readouterr()
        assert "unit: PASS" in captured.out
        assert "component: FAIL" in captured.out
        assert "scripts: FAIL" in captured.out
