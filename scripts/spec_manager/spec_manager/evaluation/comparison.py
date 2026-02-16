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
import re
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
        """Run comparison on manifest runs.

        Args:
            manifest: Comparison manifest from MultiModelRunner.
            pairwise_arch_judge: Optional PairwiseArchJudge instance.
            pairwise_code_judge: Optional PairwiseCodeJudge instance.

        Returns:
            Comparison result dict.
        """
        runs = manifest.get("runs", [])
        completed = [
            entry
            for entry in runs
            if str(entry.get("status", "completed")).strip().lower() == "completed"
        ]

        # Load digests and scorecards
        run_data: dict[str, dict[str, Any]] = {}
        for entry in completed:
            run_id = str(entry.get("run_id", "")).strip()
            if not run_id:
                continue
            snapshot_manifest_path = str(entry.get("snapshot_manifest", "")).strip()
            snapshot_manifest = (
                self._load_json(str(self._workspace_path(snapshot_manifest_path)))
                if snapshot_manifest_path
                else None
            ) or {}
            reports_dir = self._resolve_reports_dir(
                run_id=run_id,
                snapshot_manifest=snapshot_manifest,
            )
            run_data[run_id] = {
                "model": entry.get("model", ""),
                "arch_digest": self._load_json(str(reports_dir / "architecture_digest.json")),
                "code_digest": self._load_json(str(reports_dir / "code_digest.json")),
                "quality_scorecard": self._load_json(str(reports_dir / "quality_scorecard.json")),
                "duration_ms": entry.get("duration_ms", 0.0),
            }

        # Summary table
        summary = self._build_summary(run_data)

        # Canonical responsibility alignment
        spec_payload = manifest.get("spec", {})
        responsibility_alignment = self._align_responsibilities(
            list(run_data.values()), spec_payload if isinstance(spec_payload, dict) else {}
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
            "spec": spec_payload if isinstance(spec_payload, dict) else {},
            "pipeline_git_sha": manifest.get("pipeline_git_sha", ""),
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
        spec_payload: Any,
    ) -> dict[str, Any]:
        """Build source-anchored responsibility set and map each run to it."""
        normalized_spec_payload = spec_payload if isinstance(spec_payload, dict) else {}
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

        canonical = self._source_defined_responsibilities(
            spec_payload=normalized_spec_payload,
            runs=runs,
        )
        if not canonical:
            canonical = sorted({r for run_map in per_run for r in run_map})
            if canonical:
                logger.warning(
                    "Spec-defined responsibilities unavailable; "
                    "using run-derived fallback for comparison."
                )
        if not canonical:
            return {
                "canonical_responsibilities": [],
                "responsibility_mapping": [],
                "responsibility_coverage_rate": 0.0,
                "duplication_rate": 0.0,
                "missing_responsibilities": [],
            }
        total = len(canonical)

        run_mappings: list[dict[str, list[str]]] = []
        coverage_rates: list[float] = []
        duplication_counts: list[int] = []

        for run_map in per_run:
            mapped = {r: self._match_components_for_responsibility(r, run_map) for r in canonical}
            run_mappings.append(mapped)

            covered = sum(1 for ids in mapped.values() if ids)
            coverage_rates.append(covered / total)

            duplication_counts.append(sum(1 for ids in mapped.values() if len(ids) > 1))

        avg_coverage = sum(coverage_rates) / len(coverage_rates) if coverage_rates else 0.0
        avg_duplication = (
            sum(duplication_counts) / (len(duplication_counts) * total)
            if duplication_counts
            else 0.0
        )

        all_covered: set[str] = set()
        for run_map in per_run:
            for responsibility in canonical:
                if self._match_components_for_responsibility(responsibility, run_map):
                    all_covered.add(responsibility)
        missing = sorted(set(canonical) - all_covered)

        return {
            "canonical_responsibilities": canonical,
            "responsibility_mapping": run_mappings,
            "responsibility_coverage_rate": round(avg_coverage, 4),
            "duplication_rate": round(avg_duplication, 4),
            "missing_responsibilities": missing,
        }

    def _source_defined_responsibilities(
        self,
        *,
        spec_payload: dict[str, Any],
        runs: list[dict[str, Any]],
    ) -> list[str]:
        """Resolve canonical responsibilities from source-oriented spec artifacts."""
        requirements: list[str] = []

        spec_path = str(spec_payload.get("path", "")).strip()
        if spec_path:
            requirements.extend(self._load_spec_requirements(self._workspace_path(spec_path)))

        for run in runs:
            digest = run.get("arch_digest") or {}
            spec_section = digest.get("spec", {})
            if not isinstance(spec_section, dict):
                continue
            rows = spec_section.get("requirements", [])
            if isinstance(rows, list):
                for item in rows:
                    if isinstance(item, str) and item.strip():
                        requirements.append(item.strip())
                    elif isinstance(item, dict):
                        text = str(
                            item.get("requirement")
                            or item.get("text")
                            or item.get("description")
                            or ""
                        ).strip()
                        if text:
                            requirements.append(text)

        normalized: list[str] = []
        seen: set[str] = set()
        for requirement in requirements:
            normed = self._normalize_responsibility_text(requirement)
            if normed and normed not in seen:
                seen.add(normed)
                normalized.append(normed)
        return sorted(normalized)

    def _load_spec_requirements(self, path: Path) -> list[str]:
        """Load requirements directly from source spec path when possible."""
        if not path.exists():
            logger.warning("Spec path missing for responsibility alignment: %s", path)
            return []

        candidates: list[Path]
        if path.is_file():
            candidates = [path]
        else:
            candidates = [
                path / "spec_summary.json",
                path / "spec.json",
                path / "requirements.json",
            ]

        for candidate in candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            payload = self._load_json(str(candidate))
            if not isinstance(payload, dict):
                continue
            rows = payload.get("requirements", payload.get("top_requirements", []))
            if not isinstance(rows, list):
                continue
            requirements: list[str] = []
            for item in rows:
                if isinstance(item, str) and item.strip():
                    requirements.append(item.strip())
                elif isinstance(item, dict):
                    text = str(
                        item.get("requirement")
                        or item.get("text")
                        or item.get("description")
                        or item.get("summary")
                        or ""
                    ).strip()
                    if text:
                        requirements.append(text)
            if requirements:
                return requirements

        return []

    def _match_components_for_responsibility(
        self,
        responsibility: str,
        run_map: dict[str, list[str]],
    ) -> list[str]:
        """Map one canonical responsibility to component IDs from a run."""
        if responsibility in run_map:
            return list(run_map.get(responsibility, []))

        matches: set[str] = set()
        for candidate, component_ids in run_map.items():
            if not candidate:
                continue
            if responsibility in candidate or candidate in responsibility:
                matches.update(component_ids)
                continue
            if self._token_overlap(responsibility, candidate) >= 0.6:
                matches.update(component_ids)
        return sorted(matches)

    @staticmethod
    def _normalize_responsibility_text(text: str) -> str:
        return " ".join(str(text).strip().lower().split())

    def _token_overlap(self, left: str, right: str) -> float:
        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        return overlap / float(max(len(left_tokens), len(right_tokens)))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}

    def _build_summary(self, run_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Build summary table entries for each run."""
        rows: list[dict[str, Any]] = []
        for run_id, data in run_data.items():
            sc = data.get("quality_scorecard") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "model": data.get("model", ""),
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
            "| Run | Model | Arch Score | Code Score | Spec Fidelity | Status | Duration |",
            "|-----|-------|-----------|-----------|---------------|--------|----------|",
        ]

        for row in result.get("summary", []):
            lines.append(
                f"| {row['run_id']} | {row['model']} "
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
                        model = run_data.get(run_id, {}).get("model", "?")
                        lines.append(f"- {run_id} ({model}): {count} wins")
                    lines.append("")

        return "\n".join(lines)

    def _resolve_reports_dir(
        self,
        *,
        run_id: str,
        snapshot_manifest: dict[str, Any],
    ) -> Path:
        """Resolve run-scoped reports directory from snapshot contract."""
        paths = snapshot_manifest.get("paths", {})
        if isinstance(paths, dict):
            reports_dir = paths.get("reports_dir", "")
            if isinstance(reports_dir, str) and reports_dir.strip():
                return self._workspace_path(reports_dir)

        return self.workspace_root / "reports" / "pdd" / run_id

    def _workspace_path(self, path_str: str) -> Path:
        """Resolve absolute or workspace-relative paths safely."""
        path = Path(path_str)
        if path.is_absolute():
            return path
        return self.workspace_root / path

    def _load_json(self, path_str: str) -> dict[str, Any] | None:
        """Load a JSON file, returning None on failure."""
        if not path_str:
            return None
        path = Path(path_str)
        if not path.exists():
            logger.warning("Comparison artifact missing: %s", path)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read comparison artifact: %s", path, exc_info=True)
            return None
