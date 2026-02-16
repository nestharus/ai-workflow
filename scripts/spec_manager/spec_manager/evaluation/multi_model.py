"""Multi-model runner for comparing pipeline outputs across models.

Runs the full PDD pipeline sequentially for each model profile,
generating unique run IDs and preserving artifacts for comparison.

Usage::

    runner = MultiModelRunner(
        workspace_root=Path("."),
        input_folder=Path("specs/my_spec"),
    )
    manifest = runner.run(profiles, comparison_id="cmp-001")
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.evaluation.digests import (
    build_architecture_digest,
    build_code_digest,
)
from spec_manager.evaluation.model_profile import ModelProfile
from spec_manager.evaluation.quality import QualityReporter
from spec_manager.evaluation.snapshot import snapshot_run
from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
from spec_manager.refinement.evals.judges.arch_quality import ArchitectureQualityJudge
from spec_manager.refinement.evals.judges.cache import JudgeCache
from spec_manager.refinement.evals.judges.code_quality import CodeQualityJudge
from spec_manager.refinement.evals.judges.spec_fidelity import SpecFidelityJudge
from spec_manager.refinement.evals.planner.harness import PlannerEvalHarness
from spec_manager.refinement.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


@dataclass
class MultiModelRunConfig:
    """Configuration for a multi-model comparison."""

    comparison_id: str = ""
    profiles: list[ModelProfile] = field(default_factory=list)
    input_folder: str = ""
    judge_model: str = ""
    compute_quality: bool = True
    enable_planner_eval: bool = True
    runs_per_model: int = 1


@dataclass
class RunManifestEntry:
    """A single entry in the comparison manifest."""

    model: str = ""
    run_id: str = ""
    snapshot_manifest: str = ""
    replicate: int = 0
    status: str = ""  # completed, failed
    duration_ms: float = 0.0


class MultiModelRunner:
    """Runs pipeline for each model profile and collects manifests."""

    def __init__(
        self,
        workspace_root: Path,
        input_folder: Path,
    ) -> None:
        self.workspace_root = workspace_root
        self.input_folder = input_folder

    def run(
        self,
        profiles: list[ModelProfile],
        comparison_id: str = "",
        judge_model: str = "",
        compute_quality: bool = True,
        enable_planner_eval: bool = True,
        runs_per_model: int = 1,
        allow_self_judge: bool = False,
    ) -> dict[str, Any]:
        """Run pipeline for each profile and return comparison manifest.

        Args:
            profiles: Model profiles to run.
            comparison_id: Unique comparison identifier.
            judge_model: Model ID for quality judges.
            compute_quality: Whether to compute quality scorecards.
            enable_planner_eval: Whether to compute planner scorecards.
            runs_per_model: Number of replicates per model.
            allow_self_judge: Allow judge model to match producer model.

        Returns:
            Comparison manifest dict.
        """
        if not comparison_id:
            comparison_id = f"cmp-{int(time.time())}"

        spec_hash = self._hash_input_path(self.input_folder)
        pipeline_git_sha = self._read_git_sha(self.workspace_root)
        entries: list[RunManifestEntry] = []

        for profile in profiles:
            for rep in range(runs_per_model):
                run_id = f"{comparison_id}.{profile.name}.{rep:02d}"
                logger.info(
                    "Starting run %s (profile=%s, replicate=%d)",
                    run_id,
                    profile.name,
                    rep,
                )

                entry = self._run_single(
                    profile=profile,
                    run_id=run_id,
                    comparison_id=comparison_id,
                    replicate=rep,
                    judge_model=judge_model,
                    pipeline_git_sha=pipeline_git_sha,
                    compute_quality=compute_quality,
                    enable_planner_eval=enable_planner_eval,
                    allow_self_judge=allow_self_judge,
                )
                entries.append(entry)

        manifest = {
            "comparison_id": comparison_id,
            "spec": {
                "path": str(self.input_folder),
                "hash": spec_hash,
            },
            "pipeline_git_sha": pipeline_git_sha,
            "runs": [asdict(e) for e in entries],
            "profiles": [p.to_dict() for p in profiles],
            "runs_per_model": runs_per_model,
            "judge_model_id": judge_model,
            "enable_planner_eval": enable_planner_eval,
            "created_at": time.time(),
        }

        # Write manifest
        manifest_dir = self.workspace_root / "reports" / "pdd" / "comparisons" / comparison_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "comparison_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        logger.info("Comparison manifest written: %s", manifest_path)
        return manifest

    def _run_single(
        self,
        profile: ModelProfile,
        run_id: str,
        comparison_id: str,
        replicate: int,
        judge_model: str,
        pipeline_git_sha: str,
        compute_quality: bool,
        enable_planner_eval: bool,
        allow_self_judge: bool,
    ) -> RunManifestEntry:
        """Run a single pipeline instance."""
        entry = RunManifestEntry(
            model=profile.name,
            run_id=run_id,
            replicate=replicate,
        )

        start = time.time()
        run_workspace = self.workspace_root
        try:
            manager = WorkspaceManager(
                run_id=run_id,
                input_folder=self.input_folder,
            )
            manager.initialize()
            workspace_candidate = manager.workspace_path
            if isinstance(workspace_candidate, Path):
                run_workspace = workspace_candidate

            lifecycle = PddLifecycle(manager, mode="auto", model_profile=profile)
            run_results = lifecycle.run()

            # Digests
            arch_digest = build_architecture_digest(
                run_workspace,
                run_id,
                git_sha=pipeline_git_sha,
                producer_model_id=profile.producer_model_id,
            )
            code_digest = build_code_digest(
                run_workspace,
                run_id,
                git_sha=pipeline_git_sha,
                producer_model_id=profile.producer_model_id,
            )

            run_reports = run_workspace / "reports" / "pdd" / run_id
            run_reports.mkdir(parents=True, exist_ok=True)

            arch_path = run_reports / "architecture_digest.json"
            arch_path.write_text(json.dumps(arch_digest, indent=2), encoding="utf-8")

            code_path = run_reports / "code_digest.json"
            code_path.write_text(json.dumps(code_digest, indent=2), encoding="utf-8")

            planner_scorecard = None
            if enable_planner_eval:
                try:
                    planner_eval = PlannerEvalHarness(run_workspace).score_existing_traces(run_id)
                    planner_scorecard = planner_eval.scorecard
                    if planner_eval.errors:
                        logger.warning(
                            "Planner eval for run %s reported issues: %s",
                            run_id,
                            "; ".join(planner_eval.errors),
                        )
                except Exception:
                    logger.exception("Planner eval failed for run %s", run_id)

            # Quality scoring
            if compute_quality:
                arch_judge_output = None
                code_judge_output = None
                spec_judge_output = None

                if judge_model:
                    run_dir = run_workspace / ".pdd_runs" / run_id
                    snapshot_dir = run_dir / "snapshot" / "files" / "spec_snapshot"
                    judge_cache = JudgeCache(run_workspace / "analysis" / "judge_cache")

                    arch_judge = ArchitectureQualityJudge(
                        workspace=run_workspace,
                        cache=judge_cache,
                        model_id=judge_model,
                        producer_model_id=profile.producer_model_id,
                        allow_self_judge=allow_self_judge,
                    )
                    arch_judge_output = arch_judge.evaluate(arch_digest).model_dump()

                    code_judge = CodeQualityJudge(
                        workspace=run_workspace,
                        cache=judge_cache,
                        model_id=judge_model,
                        producer_model_id=profile.producer_model_id,
                        allow_self_judge=allow_self_judge,
                    )
                    code_judge_output = code_judge.evaluate(
                        code_digest,
                        snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
                    ).model_dump()

                    spec_summary_path = run_dir / "spec_summary.json"
                    if spec_summary_path.exists():
                        spec_summary = json.loads(spec_summary_path.read_text(encoding="utf-8"))
                        spec_judge = SpecFidelityJudge(
                            workspace=run_workspace,
                            cache=judge_cache,
                            model_id=judge_model,
                            producer_model_id=profile.producer_model_id,
                            allow_self_judge=allow_self_judge,
                        )
                        spec_judge_output = spec_judge.evaluate(
                            spec_summary=spec_summary,
                            code_digest=code_digest,
                            snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
                        ).model_dump()

                reporter = QualityReporter(run_workspace, run_id)
                scorecard = reporter.compute(
                    arch_digest,
                    code_digest,
                    arch_judge_output=arch_judge_output,
                    code_judge_output=code_judge_output,
                    spec_judge_output=spec_judge_output,
                    pipeline_scorecard=(run_results or {}).get("scorecard"),
                    planner_scorecard=planner_scorecard,
                )
                reporter.write(scorecard)

            spec_hash = self._extract_spec_hash(arch_digest, run_workspace, run_id)
            snap_path = snapshot_run(
                run_workspace,
                run_id,
                comparison_id=comparison_id,
                spec_hash=spec_hash,
                pipeline_git_sha=pipeline_git_sha,
                producer_model_id=profile.producer_model_id,
                judge_model_id=judge_model,
            )
            entry.snapshot_manifest = str(snap_path)
            entry.status = "completed"

        except Exception:
            logger.exception("Run %s failed", run_id)
            entry.status = "failed"
            try:
                snap_path = snapshot_run(
                    run_workspace,
                    run_id,
                    comparison_id=comparison_id,
                    pipeline_git_sha=pipeline_git_sha,
                    producer_model_id=profile.producer_model_id,
                    judge_model_id=judge_model,
                )
                entry.snapshot_manifest = str(snap_path)
            except Exception:
                logger.exception("Snapshot failed for run %s after pipeline failure", run_id)

        entry.duration_ms = (time.time() - start) * 1000
        return entry

    @staticmethod
    def _extract_spec_hash(arch_digest: dict[str, Any], workspace: Path, run_id: str) -> str:
        """Resolve spec hash from digest first, then run summary artifact."""
        spec_payload = arch_digest.get("spec", {})
        if isinstance(spec_payload, dict):
            value = spec_payload.get("spec_hash", "")
            if isinstance(value, str) and value:
                return value

        if not isinstance(workspace, Path):
            return ""
        spec_summary_path = workspace / ".pdd_runs" / run_id / "spec_summary.json"
        if spec_summary_path.exists():
            try:
                raw_payload = spec_summary_path.read_text(encoding="utf-8")
                if not isinstance(raw_payload, str):
                    return ""
                data = json.loads(raw_payload)
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                return ""
            value = data.get("spec_hash", "") if isinstance(data, dict) else ""
            if isinstance(value, str):
                return value
        return ""

    @staticmethod
    def _read_git_sha(repo_root: Path) -> str:
        """Resolve HEAD SHA for reproducibility metadata."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return ""
        return result.stdout.strip()

    @staticmethod
    def _hash_input_path(path: Path) -> str:
        """Hash input spec path deterministically for comparison manifests."""
        if not path.exists():
            return ""
        if path.is_file():
            try:
                return hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                logger.warning("Failed to read input file for hashing: %s", path, exc_info=True)
                unreadable_marker = f"unreadable_file:{path.as_posix()}"
                return hashlib.sha256(unreadable_marker.encode("utf-8")).hexdigest()

        records: list[str] = []
        for fp in sorted(path.rglob("*")):
            if not fp.is_file():
                continue
            rel_path = fp.relative_to(path).as_posix()
            try:
                digest = hashlib.sha256(fp.read_bytes()).hexdigest()
            except OSError:
                logger.warning("Failed to read input file for hashing: %s", fp, exc_info=True)
                records.append(f"{rel_path}:<UNREADABLE>")
                continue
            records.append(f"{rel_path}:{digest}")

        if not records:
            return ""
        return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
