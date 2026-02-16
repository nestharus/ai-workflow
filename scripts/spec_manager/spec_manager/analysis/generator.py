"""Analysis file generator -- JSON persistence for analysis artifacts.

The ``generate_analysis_file`` orchestrator has been removed along with
its leaf modules (import_scanner, projection_classifier, data_flow).
Only the JSON read/write utilities remain.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.schemas.lineage import AnalysisFileSchema

logger = logging.getLogger(__name__)


class AnalysisGenerationUnavailableError(RuntimeError):
    """Raised when full analysis generation is requested but unavailable."""


def generate_analysis_file(
    algorithmic_dir: Path,
    architectural_dir: Path,
    atom_to_section: dict[str, dict[str, str]] | None = None,
    store_definitions: dict[str, list[str]] | None = None,
    run_id: str = "",
) -> AnalysisFileSchema:
    """Generate a full analysis artifact.

    The underlying generation pipeline was removed. Callers must not treat
    this as a successful no-op because that silently loses requirements.

    Args:
        algorithmic_dir: Root of algorithmic layer source files.
        architectural_dir: Root of architectural layer source files.
        atom_to_section: Optional pre-built atom-to-section index.
        store_definitions: Optional store-to-atoms mapping.
        run_id: Run identifier for the artifact.

    Raises:
        AnalysisGenerationUnavailableError: Always, until the generation
            pipeline is reintroduced.
    """
    message = (
        "Analysis generation is unavailable: the import-scanning/data-flow pipeline "
        "was removed and this API can no longer produce a faithful artifact. "
        "algorithmic_dir="
        f"{algorithmic_dir}, architectural_dir={architectural_dir}, run_id={run_id!r}."
    )
    logger.error(message)
    raise AnalysisGenerationUnavailableError(message)


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
