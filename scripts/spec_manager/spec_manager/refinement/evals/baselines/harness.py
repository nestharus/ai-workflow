"""Baseline evaluation harness - orchestrates model evaluation on labyrinths."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from spec_manager.labyrinth.generator.labyrinth_builder import LabyrinthBuilder
from spec_manager.refinement.evals.baselines.config import BaselineConfig
from spec_manager.refinement.evals.baselines.model_runners.base import ModelOutput, ModelRunner
from spec_manager.refinement.evals.baselines.model_runners.glm_runner import GLMRunner
from spec_manager.refinement.evals.baselines.model_runners.gpt_runner import GPTRunner
from spec_manager.refinement.evals.baselines.model_runners.opus_runner import OpusRunner
from spec_manager.refinement.evals.baselines.results.baseline_result import BaselineResult
from spec_manager.refinement.evals.baselines.scoring.scorer import BaselineScorer
from spec_manager.refinement.evals.baselines.scoring.test_runner import TestRunner


RUNNERS: dict[str, type] = {
    "glm": GLMRunner,
    "opus": OpusRunner,
    "gpt": GPTRunner,
}


class BaselineHarness:
    """Orchestrates baseline model evaluation on labyrinth instances."""

    def __init__(self, config: BaselineConfig) -> None:
        self._config = config
        self._builder = LabyrinthBuilder()
        self._test_runner = TestRunner()
        self._scorer = BaselineScorer()

    def run(self) -> BaselineResult:
        """Run a complete baseline evaluation.

        Steps:
        1. Build labyrinth at configured level
        2. Set up workspace: codebase dir with labyrinth source + tests
        3. Git init + commit base (pre-model state)
        4. Invoke model with dense spec + codebase
        5. Run tests on modified codebase (with PYTHONPATH)
        6. Score results

        Returns:
            BaselineResult with scores.
        """
        workspace = self._config.workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)

        start = time.perf_counter()
        errors: list[str] = []

        # Step 1: Build labyrinth
        labyrinth_dir = workspace / "labyrinth"
        instance = self._builder.build_and_save(
            level=self._config.level,
            seed=self._config.seed,
            output_dir=labyrinth_dir,
        )

        # Step 2: Set up workspace codebase directory
        # The codebase dir is what models see and modify.
        # It contains the generated tests and a place for the model
        # to write labyrinth_setup.py.
        codebase_dir = workspace / "codebase"
        if codebase_dir.exists():
            shutil.rmtree(codebase_dir)
        codebase_dir.mkdir(parents=True)

        # Copy generated tests into codebase
        tests_src = labyrinth_dir / "tests"
        tests_dst = codebase_dir / "tests"
        if tests_src.exists():
            shutil.copytree(tests_src, tests_dst, dirs_exist_ok=True)

        # Copy the dense spec for reference
        dense_spec_src = labyrinth_dir / "dense_spec.md"
        if dense_spec_src.exists():
            shutil.copy2(dense_spec_src, codebase_dir / "dense_spec.md")

        # Step 3: Git init and commit the base state
        self._git_init(codebase_dir)

        # Step 4: Invoke model
        runner_cls = RUNNERS.get(self._config.model)
        if runner_cls is None:
            return BaselineResult(
                model_name=self._config.model,
                level=self._config.level,
                errors=[f"Unknown model: {self._config.model}"],
            )

        runner = runner_cls()
        model_output = runner.invoke(
            spec_text=instance.dense_spec,
            codebase_path=codebase_dir,
            workspace=workspace,
        )

        if not model_output.success:
            errors.append(f"Model execution failed: {model_output.stderr[:500]}")

        # Step 5: Run tests
        # Tests are in codebase/tests/, PYTHONPATH includes codebase
        # so labyrinth_setup.py (written by model) is importable.
        test_dir = codebase_dir / "tests"
        test_results = self._test_runner.run(
            test_dir,
            cwd=codebase_dir,
            extra_pythonpath=[str(codebase_dir)],
        )

        # Step 6: Score
        scores = self._scorer.score(test_results)

        duration = (time.perf_counter() - start) * 1000

        result = BaselineResult(
            model_name=self._config.model,
            level=self._config.level,
            rule_accuracy=scores["rule_accuracy"],
            integration_completeness=scores["integration_completeness"],
            rule_tests_passed=scores["rule_tests_passed"],
            rule_tests_total=scores["rule_tests_total"],
            integration_tests_passed=scores["integration_tests_passed"],
            integration_tests_total=scores["integration_tests_total"],
            duration_ms=duration,
            broken=scores["broken"],
            seed=self._config.seed,
            errors=errors if errors else None,
        )

        # Save result
        result.save(workspace / "result.json")

        return result

    def run_with_spec(self, spec_text: str) -> BaselineResult:
        """Run evaluation using a provided spec instead of the generated dense spec.

        Same as run() but substitutes the spec text passed by the caller
        (e.g., a system-refined spec) in place of the labyrinth's dense_spec.
        """
        workspace = self._config.workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)

        start = time.perf_counter()
        errors: list[str] = []

        # Step 1: Build labyrinth (still need tests + structure)
        labyrinth_dir = workspace / "labyrinth"
        instance = self._builder.build_and_save(
            level=self._config.level,
            seed=self._config.seed,
            output_dir=labyrinth_dir,
        )

        # Step 2: Set up workspace codebase directory
        codebase_dir = workspace / "codebase"
        if codebase_dir.exists():
            shutil.rmtree(codebase_dir)
        codebase_dir.mkdir(parents=True)

        tests_src = labyrinth_dir / "tests"
        tests_dst = codebase_dir / "tests"
        if tests_src.exists():
            shutil.copytree(tests_src, tests_dst, dirs_exist_ok=True)

        dense_spec_src = labyrinth_dir / "dense_spec.md"
        if dense_spec_src.exists():
            shutil.copy2(dense_spec_src, codebase_dir / "dense_spec.md")

        # Step 3: Git init
        self._git_init(codebase_dir)

        # Step 4: Invoke model with the PROVIDED spec (not instance.dense_spec)
        runner_cls = RUNNERS.get(self._config.model)
        if runner_cls is None:
            return BaselineResult(
                model_name=self._config.model,
                level=self._config.level,
                errors=[f"Unknown model: {self._config.model}"],
            )

        runner = runner_cls()
        model_output = runner.invoke(
            spec_text=spec_text,
            codebase_path=codebase_dir,
            workspace=workspace,
        )

        if not model_output.success:
            errors.append(f"Model execution failed: {model_output.stderr[:500]}")

        # Step 5: Run tests
        test_dir = codebase_dir / "tests"
        test_results = self._test_runner.run(
            test_dir,
            cwd=codebase_dir,
            extra_pythonpath=[str(codebase_dir)],
        )

        # Step 6: Score
        scores = self._scorer.score(test_results)

        duration = (time.perf_counter() - start) * 1000

        result = BaselineResult(
            model_name=self._config.model,
            level=self._config.level,
            rule_accuracy=scores["rule_accuracy"],
            integration_completeness=scores["integration_completeness"],
            rule_tests_passed=scores["rule_tests_passed"],
            rule_tests_total=scores["rule_tests_total"],
            integration_tests_passed=scores["integration_tests_passed"],
            integration_tests_total=scores["integration_tests_total"],
            duration_ms=duration,
            broken=scores["broken"],
            seed=self._config.seed,
            errors=errors if errors else None,
        )

        result.save(workspace / "result.json")
        return result

    def _git_init(self, codebase_dir: Path) -> None:
        """Initialize a git repo and make initial commit."""
        subprocess.run(
            ["git", "init"],
            cwd=codebase_dir,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=codebase_dir,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial labyrinth codebase", "--no-gpg-sign"],
            cwd=codebase_dir,
            capture_output=True,
            check=False,
        )
