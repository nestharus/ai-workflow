"""Orchestrate the complete keyword extraction pipeline.

This module provides the main orchestrator for running the complete keyword
extraction pipeline, from candidate extraction through classification and
variant resolution.

Usage:
    # Run full pipeline
    uv run extract-keywords

    # Run specific stages
    uv run extract-keywords --stage extract
    uv run extract-keywords --stage classify
    uv run extract-keywords --stage variants

    # Run with specific source
    uv run extract-keywords --source docs/architecture/

Args:
    --stage: Specific stage to run (extract, score, classify, apply, variants).
    --source: Source directory for extraction (default: docs/).
    --dry-run: Show what would be done without making changes.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.dev.utils import REPO_ROOT

STAGES = ["extract", "score", "classify", "apply", "variants"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the extraction pipeline.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Run the keyword extraction pipeline.",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        help="Specific stage to run (default: all stages).",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("docs"),
        help="Source directory for extraction (default: docs/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be done without making changes.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def run_extract_stage(
    source_path: Path,
    knowledge_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Run the candidate extraction stage.

    Args:
        source_path: Source directory containing YAML files.
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    print("Stage 1: Candidate Extraction")
    print(f"  Source: {source_path}")
    print(f"  Output: {knowledge_path / 'keywords' / 'candidates.csv'}")
    if dry_run:
        print("  (dry run)")
    print("  Status: Not yet implemented")
    return 0


def run_score_stage(knowledge_path: Path, *, dry_run: bool = False) -> int:
    """Run the Qwen scoring stage.

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    print("Stage 2: Qwen Scoring (Optional)")
    print(f"  Input: {knowledge_path / 'keywords' / 'candidates.csv'}")
    if dry_run:
        print("  (dry run)")
    print("  Status: Not yet implemented")
    return 0


def run_classify_stage(knowledge_path: Path, *, dry_run: bool = False) -> int:
    """Run the classification stage.

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    print("Stage 3: Classification")
    print(f"  Input: {knowledge_path / 'keywords' / 'candidates.csv'}")
    print(f"  Output: {knowledge_path / 'keywords' / 'keywords.csv'}")
    if dry_run:
        print("  (dry run)")
    print("  Status: Not yet implemented")
    return 0


def run_apply_stage(
    target_path: Path,
    knowledge_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Run the keyword application stage.

    Args:
        target_path: Target directory for keyword application.
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    print("Stage 4: Apply Keywords")
    print(f"  Input: {knowledge_path / 'keywords' / 'keywords.csv'}")
    print(f"  Target: {target_path}")
    if dry_run:
        print("  (dry run)")
    print("  Status: Not yet implemented")
    return 0


def run_variants_stage(knowledge_path: Path, *, dry_run: bool = False) -> int:
    """Run the variant resolution stage.

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    print("Stage 5: Variant Resolution")
    print(f"  Input: {knowledge_path / 'keywords' / 'keywords.csv'}")
    print(f"  Output: {knowledge_path / 'keywords' / 'variant_candidates.csv'}")
    if dry_run:
        print("  (dry run)")
    print("  Status: Not yet implemented")
    return 0


def extraction_pipeline_main(args: argparse.Namespace) -> int:
    """Run the keyword extraction pipeline.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    if args.source.is_absolute():
        source_path = args.source.resolve()
    else:
        source_path = (REPO_ROOT / args.source).resolve()

    if not source_path.exists():
        print(f"Error: Source directory not found: {source_path}", file=sys.stderr)
        return 1

    print("Keyword Extraction Pipeline")
    print("=" * 40)
    print(f"Knowledge path: {knowledge_path}")
    print(f"Source path: {source_path}")
    if args.dry_run:
        print("Mode: Dry run")
    print()

    stages_to_run = [args.stage] if args.stage else STAGES

    for stage in stages_to_run:
        if stage == "extract":
            result = run_extract_stage(source_path, knowledge_path, dry_run=args.dry_run)
        elif stage == "score":
            result = run_score_stage(knowledge_path, dry_run=args.dry_run)
        elif stage == "classify":
            result = run_classify_stage(knowledge_path, dry_run=args.dry_run)
        elif stage == "apply":
            result = run_apply_stage(source_path, knowledge_path, dry_run=args.dry_run)
        elif stage == "variants":
            result = run_variants_stage(knowledge_path, dry_run=args.dry_run)
        else:
            print(f"Unknown stage: {stage}", file=sys.stderr)
            result = 1

        if result != 0:
            return result
        print()

    print("Pipeline complete.")
    return 0


def main() -> int:
    """Entry point for extract-keywords command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return extraction_pipeline_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
