"""Meta-evaluation infrastructure for judge calibration.

Compares judge scores against human-rated examples to measure
rank correlation and calibration drift over time.

Usage:
    evaluator = JudgeMetaEvaluator(fixtures_dir)
    report = evaluator.evaluate(judge, judge_model_id)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetaEvalCase:
    """A single human-rated example for judge calibration."""

    case_id: str
    judge_type: str  # "arch_quality", "code_quality", etc.
    input_data: dict
    expected_scores: dict  # dimension -> score
    expected_overall: int
    notes: str = ""


@dataclass
class MetaEvalReport:
    """Results of meta-evaluation against human ratings."""

    judge_type: str
    judge_model_id: str
    cases_evaluated: int = 0
    rank_correlation: float = 0.0  # Spearman rho
    mean_absolute_error: float = 0.0
    per_dimension_correlation: dict[str, float] = field(default_factory=dict)
    calibration_drift: float = 0.0  # vs previous run
    cases: list[dict] = field(default_factory=list)


class JudgeMetaEvaluator:
    """Evaluates judge quality against human-rated fixtures."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures_dir = fixtures_dir

    def load_cases(self, judge_type: str) -> list[MetaEvalCase]:
        """Load human-rated cases for a judge type."""
        candidate_dirs = [
            self._fixtures_dir / judge_type,
            self._fixtures_dir / f"{judge_type}_cases",
        ]
        json_files: list[Path] = []

        for case_dir in candidate_dirs:
            if case_dir.exists():
                json_files.extend(sorted(case_dir.rglob("*.json")))

        if not json_files and self._fixtures_dir.exists():
            json_files.extend(sorted(self._fixtures_dir.glob(f"{judge_type}*.json")))

        cases: list[MetaEvalCase] = []
        for json_path in json_files:
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping invalid meta-eval fixture %s: %s", json_path, exc)
                continue

            if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
                raw_cases = payload["cases"]
            elif isinstance(payload, list):
                raw_cases = payload
            elif isinstance(payload, dict):
                raw_cases = [payload]
            else:
                continue

            for index, raw_case in enumerate(raw_cases):
                parsed = self._parse_case(
                    raw_case=raw_case,
                    judge_type=judge_type,
                    default_case_id=f"{json_path.stem}-{index}",
                )
                if parsed is not None:
                    cases.append(parsed)

        return cases

    def evaluate(self, judge_type: str, judge_model_id: str) -> MetaEvalReport:
        """Run meta-evaluation and return report."""
        report = MetaEvalReport(
            judge_type=judge_type,
            judge_model_id=judge_model_id,
        )
        cases = self.load_cases(judge_type)
        if not cases:
            return report

        expected_overall: list[float] = []
        predicted_overall: list[float] = []
        absolute_errors: list[float] = []
        per_dimension_pairs: dict[str, list[tuple[float, float]]] = {}
        case_rows: list[dict[str, Any]] = []

        for case in cases:
            predicted = self._extract_predicted_overall(case.input_data)
            row = {
                "case_id": case.case_id,
                "expected_overall": case.expected_overall,
                "predicted_overall": predicted,
            }

            if predicted is None:
                row["status"] = "skipped_no_prediction"
                case_rows.append(row)
                continue

            row["status"] = "scored"
            row["absolute_error"] = abs(predicted - case.expected_overall)
            case_rows.append(row)

            expected_overall.append(float(case.expected_overall))
            predicted_overall.append(float(predicted))
            absolute_errors.append(abs(float(predicted) - float(case.expected_overall)))

            predicted_scores = self._extract_predicted_scores(case.input_data)
            for dimension, expected in case.expected_scores.items():
                if dimension not in predicted_scores:
                    continue
                exp_val = self._to_float(expected)
                pred_val = self._to_float(predicted_scores[dimension])
                if exp_val is None or pred_val is None:
                    continue
                per_dimension_pairs.setdefault(dimension, []).append((exp_val, pred_val))

        report.cases_evaluated = len(expected_overall)
        report.rank_correlation = (
            self._spearman(expected_overall, predicted_overall)
            if len(expected_overall) >= 2
            else 0.0
        )
        report.mean_absolute_error = (
            sum(absolute_errors) / len(absolute_errors) if absolute_errors else 0.0
        )
        report.calibration_drift = (
            abs(
                sum(
                    pred - exp
                    for exp, pred in zip(expected_overall, predicted_overall, strict=False)
                )
                / len(expected_overall)
            )
            if expected_overall
            else 0.0
        )
        report.per_dimension_correlation = {
            dim: self._spearman(
                [pair[0] for pair in pairs],
                [pair[1] for pair in pairs],
            )
            for dim, pairs in per_dimension_pairs.items()
            if len(pairs) >= 2
        }
        report.cases = case_rows
        return report

    def _parse_case(
        self,
        raw_case: Any,
        judge_type: str,
        default_case_id: str,
    ) -> MetaEvalCase | None:
        if not isinstance(raw_case, dict):
            return None

        expected_scores_raw = raw_case.get("expected_scores", {})
        expected_scores = expected_scores_raw if isinstance(expected_scores_raw, dict) else {}
        expected_scores = {str(key): value for key, value in expected_scores.items()}

        expected_overall = self._to_float(raw_case.get("expected_overall"))
        if expected_overall is None and expected_scores:
            values = [self._to_float(value) for value in expected_scores.values()]
            numeric_values = [value for value in values if value is not None]
            if numeric_values:
                expected_overall = sum(numeric_values) / len(numeric_values)
        if expected_overall is None:
            return None

        input_data = raw_case.get("input_data", {})
        if not isinstance(input_data, dict):
            input_data = {}
        input_data = dict(input_data)

        for optional_key in (
            "judge_overall",
            "predicted_overall",
            "observed_overall",
            "judge_scores",
            "predicted_scores",
            "dimension_scores",
        ):
            if optional_key in raw_case and optional_key not in input_data:
                input_data[optional_key] = raw_case[optional_key]

        return MetaEvalCase(
            case_id=str(raw_case.get("case_id", default_case_id)),
            judge_type=str(raw_case.get("judge_type", judge_type)),
            input_data=input_data,
            expected_scores=expected_scores,
            expected_overall=round(expected_overall),
            notes=str(raw_case.get("notes", "")),
        )

    def _extract_predicted_overall(self, input_data: dict[str, Any]) -> float | None:
        for key in ("judge_overall", "predicted_overall", "observed_overall", "overall"):
            value = self._to_float(input_data.get(key))
            if value is not None:
                return value
        return None

    def _extract_predicted_scores(self, input_data: dict[str, Any]) -> dict[str, Any]:
        for key in ("judge_scores", "predicted_scores", "dimension_scores", "scores"):
            value = input_data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _spearman(self, xs: list[float], ys: list[float]) -> float:
        if len(xs) != len(ys) or len(xs) < 2:
            return 0.0
        rx = self._rank(xs)
        ry = self._rank(ys)
        return self._pearson(rx, ry)

    def _rank(self, values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda item: item[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    def _pearson(self, xs: list[float], ys: list[float]) -> float:
        if len(xs) != len(ys) or len(xs) < 2:
            return 0.0
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
        den_x = sum((x - mean_x) ** 2 for x in xs)
        den_y = sum((y - mean_y) ** 2 for y in ys)
        denom = (den_x * den_y) ** 0.5
        if denom == 0:
            return 0.0
        return num / denom

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None
