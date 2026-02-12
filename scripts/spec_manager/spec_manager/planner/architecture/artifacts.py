"""Architecture decision artifact persistence and retrieval.

Persists candidates, assessments, and outcomes under
``reports/pdd/<run_id>/architecture/decisions/<decision_id>/``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
)

logger = logging.getLogger(__name__)


def persist_decision_artifacts(
    workspace_root: Path,
    run_id: str,
    decision_id: str,
    candidates: list[ArchitectureCandidate],
    assessments: list[CandidateAssessment],
    outcome: DecisionOutcome,
) -> Path:
    """Persist architecture decision artifacts to disk.

    Creates the directory structure and writes three JSON files:
    - ``candidates.json`` — all proposed candidates
    - ``assessments.json`` — evaluation results
    - ``outcome.json`` — the final decision outcome

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    run_id:
        Run identifier.
    decision_id:
        Decision identifier.
    candidates:
        List of proposed candidates.
    assessments:
        List of candidate assessments.
    outcome:
        The decision outcome.

    Returns
    -------
    Path
        The decision directory where artifacts were written.
    """
    decision_dir = (
        workspace_root / "reports" / "pdd" / run_id / "architecture" / "decisions" / decision_id
    )
    decision_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        decision_dir / "candidates.json",
        [c.to_dict() for c in candidates],
    )
    _write_json(
        decision_dir / "assessments.json",
        [a.to_dict() for a in assessments],
    )
    _write_json(
        decision_dir / "outcome.json",
        outcome.to_dict(),
    )

    logger.debug("Persisted decision artifacts for %s at %s", decision_id, decision_dir)
    return decision_dir


def load_committed_decisions(
    workspace_root: Path,
    run_id: str,
) -> list[DecisionOutcome]:
    """Load all committed decision outcomes for a run.

    Scans ``reports/pdd/<run_id>/architecture/decisions/*/outcome.json``
    and returns only outcomes where ``committed`` is ``True``.

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    run_id:
        Run identifier.

    Returns
    -------
    list[DecisionOutcome]
        Committed outcomes, sorted by decision_id.
    """
    decisions_dir = workspace_root / "reports" / "pdd" / run_id / "architecture" / "decisions"
    if not decisions_dir.is_dir():
        return []

    outcomes: list[DecisionOutcome] = []
    for outcome_path in sorted(decisions_dir.glob("*/outcome.json")):
        try:
            data = json.loads(outcome_path.read_text(encoding="utf-8"))
            outcome = DecisionOutcome.from_dict(data)
            if outcome.committed:
                outcomes.append(outcome)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load outcome from %s: %s", outcome_path, exc)

    return outcomes


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    """Write JSON data to a file."""
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
