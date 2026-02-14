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

import json
import logging
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
    runs_per_model: int = 1


@dataclass
class RunManifestEntry:
    """A single entry in the comparison manifest."""

    profile_name: str = ""
    run_id: str = ""
    replicate: int = 0
    status: str = ""  # completed, failed
    duration_ms: float = 0.0
    arch_digest_path: str = ""
    code_digest_path: str = ""
    quality_scorecard_path: str = ""
    snapshot_manifest_path: str = ""


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
        runs_per_model: int = 1,
        allow_self_judge: bool = False,
    ) -> dict[str, Any]:
        """Run pipeline for each profile and return comparison manifest.

        Args:
            profiles: Model profiles to run.
            comparison_id: Unique comparison identifier.
            judge_model: Model ID for quality judges.
            compute_quality: Whether to compute quality scorecards.
            runs_per_model: Number of replicates per model.
            allow_self_judge: Allow judge model to match producer model.

        Returns:
            Comparison manifest dict.
        """
        if not comparison_id:
            comparison_id = f"cmp-{int(time.time())}"

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
                    replicate=rep,
                    judge_model=judge_model,
                    compute_quality=compute_quality,
                    allow_self_judge=allow_self_judge,
                )
                entries.append(entry)

        manifest = {
            "comparison_id": comparison_id,
            "profiles": [p.to_dict() for p in profiles],
            "runs_per_model": runs_per_model,
            "judge_model": judge_model,
            "entries": [asdict(e) for e in entries],
            "timestamp": time.time(),
        }

        # Write manifest
        manifest_dir = self.workspace_root / "reports" / "pdd" / "comparisons" / comparison_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        logger.info("Comparison manifest written: %s", manifest_path)
        return manifest

    def _run_single(
        self,
        profile: ModelProfile,
        run_id: str,
        replicate: int,
        judge_model: str,
        compute_quality: bool,
        allow_self_judge: bool,
    ) -> RunManifestEntry:
        """Run a single pipeline instance."""
        entry = RunManifestEntry(
            profile_name=profile.name,
            run_id=run_id,
            replicate=replicate,
        )

        start = time.time()
        try:
            manager = WorkspaceManager(
                run_id=run_id,
                input_folder=self.input_folder,
            )
            manager.initialize()

            lifecycle = PddLifecycle(manager, mode="auto", model_profile=profile)
            lifecycle.run()

            # Snapshot
            snap_path = snapshot_run(self.workspace_root, run_id)
            entry.snapshot_manifest_path = str(snap_path)

            # Digests
            arch_digest = build_architecture_digest(self.workspace_root, run_id)
            code_digest = build_code_digest(self.workspace_root, run_id)

            run_reports = self.workspace_root / "reports" / "pdd" / run_id
            run_reports.mkdir(parents=True, exist_ok=True)

            arch_path = run_reports / "architecture_digest.json"
            arch_path.write_text(json.dumps(arch_digest, indent=2), encoding="utf-8")
            entry.arch_digest_path = str(arch_path)

            code_path = run_reports / "code_digest.json"
            code_path.write_text(json.dumps(code_digest, indent=2), encoding="utf-8")
            entry.code_digest_path = str(code_path)

            # Quality scoring
            if compute_quality:
                arch_judge_output = None
                code_judge_output = None
                spec_judge_output = None

                if judge_model:
                    run_dir = self.workspace_root / ".pdd_runs" / run_id
                    snapshot_dir = run_dir / "snapshot" / "files"
                    judge_cache = JudgeCache(self.workspace_root / "analysis" / "judge_cache")

                    arch_judge = ArchitectureQualityJudge(
                        workspace=self.workspace_root,
                        cache=judge_cache,
                        model_id=judge_model,
                        producer_model_id=profile.producer_model_id,
                        allow_self_judge=allow_self_judge,
                    )
                    arch_judge_output = arch_judge.evaluate(arch_digest).model_dump()

                    code_judge = CodeQualityJudge(
                        workspace=self.workspace_root,
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
                            workspace=self.workspace_root,
                            cache=judge_cache,
                            model_id=judge_model,
                            producer_model_id=profile.producer_model_id,
                            allow_self_judge=allow_self_judge,
                        )
                        spec_judge_output = spec_judge.evaluate(
                            spec_summary=spec_summary,
                            code_digest=code_digest,
                        ).model_dump()

                reporter = QualityReporter(self.workspace_root, run_id)
                scorecard = reporter.compute(
                    arch_digest,
                    code_digest,
                    arch_judge_output=arch_judge_output,
                    code_judge_output=code_judge_output,
                    spec_judge_output=spec_judge_output,
                )
                json_path, _ = reporter.write(scorecard)
                entry.quality_scorecard_path = str(json_path)

            entry.status = "completed"

        except Exception:
            logger.exception("Run %s failed", run_id)
            entry.status = "failed"

        entry.duration_ms = (time.time() - start) * 1000
        return entry
