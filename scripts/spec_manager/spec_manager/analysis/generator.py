"""Analysis file generator -- JSON persistence for analysis artifacts.

The ``generate_analysis_file`` orchestrator has been removed along with
its leaf modules (import_scanner, projection_classifier, data_flow).
Only the JSON read/write utilities remain.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from spec_manager.schemas.lineage import AnalysisFileSchema

logger = logging.getLogger(__name__)


def generate_analysis_file(
    algorithmic_dir: Path,
    architectural_dir: Path,
    atom_to_section: dict[str, dict[str, str]] | None = None,
    store_definitions: dict[str, list[str]] | None = None,
    run_id: str = "",
) -> AnalysisFileSchema:
    """Generate a minimal analysis file artifact.

    The full analysis pipeline (import scanning, projection classification,
    data-flow extraction) has been removed.  This stub returns a valid but
    empty schema so that callers continue to work.

    Args:
        algorithmic_dir: Root of algorithmic layer source files (unused).
        architectural_dir: Root of architectural layer source files (unused).
        atom_to_section: Optional pre-built atom-to-section index (unused).
        store_definitions: Optional store-to-atoms mapping (unused).
        run_id: Run identifier for the artifact.

    Returns:
        Minimal AnalysisFileSchema artifact.
    """
    generated_at = datetime.now(UTC).isoformat()

    return AnalysisFileSchema(
        run_id=run_id,
        generated_at=generated_at,
        atoms=[],
        orphaned_architecture=[],
        summary={
            "total_atoms": 0,
            "implemented_atoms": 0,
            "unimplemented_atoms": 0,
            "orphaned_architecture": 0,
            "pass_through_imports": 0,
            "wrap_imports": 0,
            "smear_imports": 0,
            "total_lineage_edges": 0,
        },
    )


def write_analysis_json(
    analysis: AnalysisFileSchema,
    output_path: Path,
) -> None:
    """Write analysis artifact as JSON.

    Args:
        analysis: The analysis schema to serialize.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_analysis_json(input_path: Path) -> AnalysisFileSchema:
    """Read and validate an analysis artifact.

    Args:
        input_path: Path to the JSON file.

    Returns:
        Validated AnalysisFileSchema.
    """
    content = input_path.read_text(encoding="utf-8")
    return AnalysisFileSchema.model_validate(json.loads(content))
