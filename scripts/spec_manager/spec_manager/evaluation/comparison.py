"""Cross-model comparison runner.

Loads per-run digests and scorecards, runs pairwise judges, and
aggregates rankings into a comparison report.

Includes canonical responsibility alignment (Section 4.2) so that
cross-model comparisons map to a shared responsibility vocabulary.

Usage::

    runner = ComparisonRunner(
        workspace_root=Path("."),
        comparison_id="cmp-001",
    )
    result = runner.compare(manifest)
"""

from __future__ import annotations

import json
import logging
from itertools import combinations
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ComparisonRunner:
    """Compares pipeline outputs from multiple model runs."""

    def __init__(
        self,
        workspace_root: Path,
        comparison_id: str,
    ) -> None:
        self.workspace_root = workspace_root
        self.comparison_id = comparison_id
        self._output_dir = workspace_root / "reports" / "pdd" / "comparisons" / comparison_id

    def compare(
        self,
        manifest: dict[str, Any],
        pairwise_arch_judge: Any | None = None,
        pairwise_code_judge: Any | None = None,
    ) -> dict[str, Any]:
        """Run comparison on manifest entries.

        Args:
            manifest: Comparison manifest from MultiModelRunner.
            pairwise_arch_judge: Optional PairwiseArchJudge instance.
            pairwise_code_judge: Optional PairwiseCodeJudge instance.

        Returns:
            Comparison result dict.
        """
        entries = manifest.get("entries", [])
        completed = [e for e in entries if e.get("status") == "completed"]

        # Load digests and scorecards
        run_data: dict[str, dict[str, Any]] = {}
        for entry in completed:
            run_id = entry["run_id"]
            run_data[run_id] = {
                "profile_name": entry.get("profile_name", ""),
                "arch_digest": self._load_json(entry.get("arch_digest_path", "")),
                "code_digest": self._load_json(entry.get("code_digest_path", "")),
                "quality_scorecard": self._load_json(entry.get("quality_scorecard_path", "")),
                "duration_ms": entry.get("duration_ms", 0.0),
            }

        # Summary table
        summary = self._build_summary(run_data)

        # Canonical responsibility alignment
        spec_summary = manifest.get("spec_summary", "")
        responsibility_alignment = self._align_responsibilities(
            list(run_data.values()), spec_summary
        )

        # Pairwise comparisons
        pairwise_results: list[dict[str, Any]] = []
        run_ids = list(run_data.keys())
        for run_a, run_b in combinations(run_ids, 2):
            pair: dict[str, Any] = {"run_a": run_a, "run_b": run_b}

            if (
                pairwise_arch_judge
                and run_data[run_a]["arch_digest"]
                and run_data[run_b]["arch_digest"]
            ):
                try:
                    result = pairwise_arch_judge.compare(
                        run_data[run_a]["arch_digest"],
                        run_data[run_b]["arch_digest"],
                    )
                    pair["arch_winner"] = result.winner
                    pair["arch_scores"] = result.scores
                except Exception as exc:
                    logger.warning("Pairwise arch comparison failed: %s", exc)
                    pair["arch_winner"] = "ERROR"

            if (
                pairwise_code_judge
                and run_data[run_a]["code_digest"]
                and run_data[run_b]["code_digest"]
            ):
                try:
                    result = pairwise_code_judge.compare(
                        run_data[run_a]["code_digest"],
                        run_data[run_b]["code_digest"],
                    )
                    pair["code_winner"] = result.winner
                    pair["code_scores"] = result.scores
                except Exception as exc:
                    logger.warning("Pairwise code comparison failed: %s", exc)
                    pair["code_winner"] = "ERROR"

            pairwise_results.append(pair)

        # Rankings
        rankings = self._compute_rankings(pairwise_results, run_data)

        result = {
            "comparison_id": self.comparison_id,
            "runs": list(run_data.keys()),
            "summary": summary,
            "responsibility_alignment": responsibility_alignment,
            "pairwise": pairwise_results,
            "rankings": rankings,
        }

        # Write outputs
        self._output_dir.mkdir(parents=True, exist_ok=True)

        json_path = self._output_dir / "comparison.json"
        json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        md_path = self._output_dir / "comparison_report.md"
        md_path.write_text(self._render_report(result, run_data), encoding="utf-8")

        logger.info("Comparison report written to %s", self._output_dir)
        return result

    # ------------------------------------------------------------------
    # Canonical responsibility alignment (Section 4.2)
    # ------------------------------------------------------------------

    def _align_responsibilities(
        self,
        runs: list[dict[str, Any]],
        spec_summary: str,
    ) -> dict[str, Any]:
        """Build canonical responsibility set and map each run to it.

        Mechanical v1: unions all ``topology.components[].responsibilities``
        across runs, then checks which runs cover each responsibility.

        Args:
            runs: List of per-run data dicts (from ``run_data.values()``).
            spec_summary: Spec summary text (unused in v1, reserved for
                future LLM-based canonicalization).

        Returns:
            Dict with ``canonical_responsibilities``, per-run
            ``responsibility_mapping``, ``responsibility_coverage_rate``,
            ``duplication_rate``, and ``missing_responsibilities``.
        """
        # Collect per-run responsibility → component_id mappings
        per_run: list[dict[str, list[str]]] = []
        for run in runs:
            resp_map: dict[str, list[str]] = {}
            digest = run.get("arch_digest") or {}
            components = digest.get("topology", {}).get("components", [])
            for comp in components:
                comp_id = comp.get("id", "")
                for resp in comp.get("responsibilities", []):
                    normed = resp.strip().lower()
                    if normed:
                        resp_map.setdefault(normed, []).append(comp_id)
            per_run.append(resp_map)

        # Build union set (canonical vocabulary)
        canonical: list[str] = sorted({r for run_map in per_run for r in run_map})
        total = len(canonical) if canonical else 1  # avoid division-by-zero

        # Per-run mapping and metrics
        run_mappings: list[dict[str, list[str]]] = []
        coverage_rates: list[float] = []
        duplication_counts: list[int] = []

        for run_map in per_run:
            mapped = {r: run_map.get(r, []) for r in canonical}
            run_mappings.append(mapped)

            covered = sum(1 for ids in mapped.values() if ids)
            coverage_rates.append(covered / total)

            # Duplication: responsibility mapped to >1 component
            duplication_counts.append(sum(1 for ids in mapped.values() if len(ids) > 1))

        avg_coverage = sum(coverage_rates) / len(coverage_rates) if coverage_rates else 0.0
        avg_duplication = (
            sum(duplication_counts) / (len(duplication_counts) * total)
            if duplication_counts
            else 0.0
        )

        # Missing: responsibilities not covered by any run
        all_covered: set[str] = set()
        for run_map in per_run:
            all_covered.update(r for r, ids in run_map.items() if ids)
        missing = sorted(set(canonical) - all_covered)

        return {
            "canonical_responsibilities": canonical,
            "responsibility_mapping": run_mappings,
            "responsibility_coverage_rate": round(avg_coverage, 4),
            "duplication_rate": round(avg_duplication, 4),
            "missing_responsibilities": missing,
        }

    def _build_summary(self, run_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Build summary table entries for each run."""
        rows: list[dict[str, Any]] = []
        for run_id, data in run_data.items():
            sc = data.get("quality_scorecard") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "profile_name": data.get("profile_name", ""),
                    "arch_quality_score": sc.get("arch_quality_score", 0.0),
                    "code_quality_score": sc.get("code_quality_score", 0.0),
                    "spec_fidelity_score": sc.get("spec_fidelity_score", 0.0),
                    "overall_status": sc.get("overall_status", "UNKNOWN"),
                    "duration_ms": data.get("duration_ms", 0.0),
                }
            )
        return rows

    def _compute_rankings(
        self,
        pairwise_results: list[dict[str, Any]],
        run_data: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute win-count rankings from pairwise results."""
        arch_wins: dict[str, int] = {r: 0 for r in run_data}
        code_wins: dict[str, int] = {r: 0 for r in run_data}

        for pair in pairwise_results:
            run_a = pair["run_a"]
            run_b = pair["run_b"]

            arch_winner = pair.get("arch_winner", "")
            if arch_winner == "A":
                arch_wins[run_a] = arch_wins.get(run_a, 0) + 1
            elif arch_winner == "B":
                arch_wins[run_b] = arch_wins.get(run_b, 0) + 1

            code_winner = pair.get("code_winner", "")
            if code_winner == "A":
                code_wins[run_a] = code_wins.get(run_a, 0) + 1
            elif code_winner == "B":
                code_wins[run_b] = code_wins.get(run_b, 0) + 1

        return {
            "arch_wins": arch_wins,
            "code_wins": code_wins,
        }

    def _render_report(self, result: dict[str, Any], run_data: dict[str, dict[str, Any]]) -> str:
        """Render comparison as markdown."""
        lines = [
            f"# Model Comparison Report -- `{self.comparison_id}`",
            "",
            "## Summary",
            "",
            "| Run | Profile | Arch Score | Code Score | Spec Fidelity | Status | Duration |",
            "|-----|---------|-----------|-----------|---------------|--------|----------|",
        ]

        for row in result.get("summary", []):
            lines.append(
                f"| {row['run_id']} | {row['profile_name']} "
                f"| {row['arch_quality_score']:.3f} "
                f"| {row['code_quality_score']:.3f} "
                f"| {row['spec_fidelity_score']:.3f} "
                f"| {row['overall_status']} "
                f"| {row['duration_ms']:.0f}ms |"
            )

        # Responsibility alignment section
        alignment = result.get("responsibility_alignment", {})
        canonical = alignment.get("canonical_responsibilities", [])
        if canonical:
            lines.extend(
                [
                    "",
                    "## Responsibility Alignment",
                    "",
                    f"**Canonical Responsibilities**: {len(canonical)}",
                    f"**Coverage Rate**: {alignment.get('responsibility_coverage_rate', 0.0):.2%}",
                    f"**Duplication Rate**: {alignment.get('duplication_rate', 0.0):.2%}",
                    "",
                ]
            )
            missing = alignment.get("missing_responsibilities", [])
            if missing:
                lines.append("**Missing Responsibilities**:")
                for m in missing:
                    lines.append(f"- {m}")
                lines.append("")

        # Pairwise section
        pairwise = result.get("pairwise", [])
        if pairwise:
            lines.extend(
                [
                    "",
                    "## Pairwise Comparisons",
                    "",
                    "| Run A | Run B | Arch Winner | Code Winner |",
                    "|-------|-------|-------------|-------------|",
                ]
            )
            for pair in pairwise:
                lines.append(
                    f"| {pair['run_a']} | {pair['run_b']} "
                    f"| {pair.get('arch_winner', 'N/A')} "
                    f"| {pair.get('code_winner', 'N/A')} |"
                )

        # Rankings
        rankings = result.get("rankings", {})
        if rankings:
            lines.extend(
                [
                    "",
                    "## Rankings",
                    "",
                ]
            )
            for category in ("arch_wins", "code_wins"):
                wins = rankings.get(category, {})
                if wins:
                    lines.append(f"### {category.replace('_', ' ').title()}")
                    lines.append("")
                    sorted_runs = sorted(wins.items(), key=lambda x: x[1], reverse=True)
                    for run_id, count in sorted_runs:
                        profile = run_data.get(run_id, {}).get("profile_name", "?")
                        lines.append(f"- {run_id} ({profile}): {count} wins")
                    lines.append("")

        return "\n".join(lines)

    def _load_json(self, path_str: str) -> dict[str, Any] | None:
        """Load a JSON file, returning None on failure."""
        if not path_str:
            return None
        path = Path(path_str)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
