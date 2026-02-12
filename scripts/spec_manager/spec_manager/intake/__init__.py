"""Phase 0: Routing-based restructuring of freeform prose into PDD format."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_phase0(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Run the full Phase 0 routing pipeline.

    Steps:
        1. Summarize source files (LLM, for routing decisions only)
        2. Discover libraries from summaries (LLM)
        3. Route source spans to destinations (LLM with reimplementation test)
        4. Check coverage (deterministic — all lines routed or ignored)
        5. Assemble output by verbatim copy (deterministic)

    Args:
        source_dir: Directory containing freeform prose .md files.
        output_dir: Directory for all output artifacts.

    Returns:
        Stats dict with summary of what was produced.
    """
    from spec_manager.intake.assemble import assemble_output
    from spec_manager.intake.coverage import check_coverage
    from spec_manager.intake.discover import discover_libraries
    from spec_manager.intake.route import route_sources
    from spec_manager.intake.summarize import summarize_sources

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Summarize
    logger.info("Phase 0 Step 1: Summarizing source files...")
    summaries = summarize_sources(source_dir, output_dir)

    # Step 2: Discover libraries
    logger.info("Phase 0 Step 2: Discovering libraries...")
    libraries = discover_libraries(summaries, output_dir)

    # Step 3: Route (may re-run discovery if content doesn't fit any library)
    logger.info("Phase 0 Step 3: Routing source spans...")
    routes, libraries = route_sources(source_dir, libraries, output_dir)

    # Step 4: Coverage check
    logger.info("Phase 0 Step 4: Checking coverage...")
    ledger = check_coverage(source_dir, routes, output_dir)

    # Report coverage
    routed = sum(1 for e in ledger if e.status == "routed")
    uncovered = sum(1 for e in ledger if e.status == "uncovered")
    if uncovered > 0:
        logger.warning(
            "Coverage incomplete: %d routed ranges, %d uncovered ranges",
            routed,
            uncovered,
        )

    # Step 5: Assemble
    logger.info("Phase 0 Step 5: Assembling output...")
    libraries_dir = assemble_output(source_dir, routes, libraries, output_dir)

    return {
        "files_summarized": len(summaries),
        "libraries_discovered": len(libraries),
        "routes_created": len(routes),
        "coverage_routed": routed,
        "coverage_uncovered": uncovered,
        "output_dir": str(libraries_dir),
    }


__all__ = ["run_phase0"]
