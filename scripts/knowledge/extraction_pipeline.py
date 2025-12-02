"""Orchestrate the complete keyword extraction pipeline.

This module provides the main orchestrator for running the complete keyword
extraction pipeline, from candidate extraction through classification and
variant resolution.

The pipeline consists of five stages:

1. **Extract**: Extract keyword candidates from YAML documentation using spaCy NLP.
2. **Score**: (Optional) Score candidates using Qwen3-Reranker for relevance ranking.
3. **Classify**: Classification handled by keyword-filter sub-agent (prints instructions).
4. **Apply**: Apply classified keywords (keep='true') to YAML files and update index.
5. **Variants**: Track similar keywords, validate via sub-agent, apply merge decisions.

Usage:
    # Run full pipeline
    uv run extract-keywords

    # Run specific stages
    uv run extract-keywords --stage extract
    uv run extract-keywords --stage score
    uv run extract-keywords --stage classify
    uv run extract-keywords --stage apply
    uv run extract-keywords --stage variants

    # Run with specific source directory
    uv run extract-keywords --source docs/architecture/

    # Dry run mode (show changes without modifying files)
    uv run extract-keywords --dry-run

Args:
    --stage: Specific stage to run (extract, score, classify, apply, variants).
    --source: Source directory or file for extraction (default: docs/).
    --dry-run: Show what would be done without making changes.
    --knowledge-path: Base knowledge directory (default: .knowledge).
    --score-model: HuggingFace model for Qwen scoring (default: Qwen/Qwen3-Reranker-8B).
    --score-batch-size: Batch size for Qwen scoring inference (default: 32).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
    parser.add_argument(
        "--score-model",
        default="Qwen/Qwen3-Reranker-8B",
        dest="score_model",
        help="HuggingFace model for Qwen scoring (default: Qwen/Qwen3-Reranker-8B).",
    )
    parser.add_argument(
        "--score-batch-size",
        type=int,
        default=32,
        dest="score_batch_size",
        help="Batch size for Qwen scoring inference (default: 32).",
    )
    return parser.parse_args(argv)


def _create_args_namespace(**kwargs: Any) -> argparse.Namespace:
    """Create an argparse.Namespace with the specified keyword arguments.

    Args:
        **kwargs: Key-value pairs to set as namespace attributes.

    Returns:
        Namespace object with the specified attributes.
    """
    return argparse.Namespace(**kwargs)


def run_extract_stage(
    source_path: Path,
    knowledge_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Run the candidate extraction stage.

    Imports and calls candidate_extraction.extract_candidates_main to extract
    keyword candidates from YAML documentation using spaCy NLP.

    Args:
        source_path: Source directory containing YAML files.
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    from scripts.knowledge.candidate_extraction import extract_candidates_main

    print("Stage 1: Candidate Extraction")
    print(f"  Source: {source_path}")
    print(f"  Output: {knowledge_path / 'keywords' / 'candidates.csv'}")

    if dry_run:
        print("  (dry run - skipping extraction)")
        return 0

    try:
        args = _create_args_namespace(
            path=source_path,
            knowledge_path=knowledge_path,
        )
        result = extract_candidates_main(args)
        if result == 0:
            print("  ✓ Candidate extraction completed successfully")
        return result
    except Exception as exc:
        print(f"  Error during candidate extraction: {exc}", file=sys.stderr)
        return 1


def run_score_stage(
    knowledge_path: Path,
    *,
    dry_run: bool = False,
    model: str = "Qwen/Qwen3-Reranker-8B",
    batch_size: int = 32,
) -> int:
    """Run the Qwen scoring stage.

    Imports and calls qwen_scoring.score_candidates_main to score candidates
    using the Qwen3-Reranker model. This stage is optional and provides
    relevance scores to assist the classification sub-agent.

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.
        model: HuggingFace model for scoring (default: Qwen/Qwen3-Reranker-8B).
        batch_size: Batch size for inference (default: 32).

    Returns:
        0 on success, 1 on error.
    """
    from scripts.knowledge.qwen_scoring import score_candidates_main

    print("Stage 2: Qwen Scoring (Optional)")
    print(f"  Input: {knowledge_path / 'keywords' / 'candidates.csv'}")
    print(f"  Model: {model}")
    print(f"  Batch size: {batch_size}")

    if dry_run:
        print("  (dry run - skipping scoring)")
        return 0

    try:
        args = _create_args_namespace(
            model=model,
            batch_size=batch_size,
            knowledge_path=knowledge_path,
        )
        result = score_candidates_main(args)
        if result == 0:
            print("  ✓ Qwen scoring completed successfully")
        return result
    except Exception as exc:
        print(f"  Error during Qwen scoring: {exc}", file=sys.stderr)
        return 1


def run_classify_stage(knowledge_path: Path, *, dry_run: bool = False) -> int:
    """Run the classification stage.

    This stage is handled by the keyword-filter sub-agent. The orchestrator
    prints instructions for invoking the sub-agent, which classifies each
    candidate as keep='true' or keep='false'.

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success (always returns 0 as this is a manual step).
    """
    print("Stage 3: Classification (Sub-agent)")
    print(f"  Input: {knowledge_path / 'keywords' / 'candidates.csv'}")
    print()
    print("  This stage requires the keyword-filter sub-agent.")
    print("  The sub-agent will classify candidates as keywords or noise.")
    print()
    print("  To check for unclassified candidates:")
    print("    uv run knowledge.query-keyword-candidates --unclassified --format json")
    print()
    print("  To invoke the sub-agent:")
    print('    Task(subagent_type="keyword-filter", prompt="")')
    print()
    print("  The sub-agent will:")
    print("    1. Query unclassified candidates in batches")
    print("    2. Classify each as keep='true' (keyword) or keep='false' (noise)")
    print("    3. Use qwen_score (if available) as a classification signal")
    print("    4. Continue until all candidates are classified")
    print()

    if dry_run:
        print("  (dry run - classification is always manual)")

    print("  After classification, proceed to Stage 4 (apply) to update YAML files.")
    return 0


def run_apply_stage(
    target_path: Path,
    knowledge_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Run the keyword application stage.

    Imports and calls keyword_store.apply_keywords_main to apply classified
    keywords (keep='true') back to YAML documentation files and update the
    keyword index (keywords.csv).

    Args:
        target_path: Target directory for keyword application (unused, kept for API).
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    from scripts.knowledge.keyword_store import apply_keywords_main

    print("Stage 4: Apply Keywords to YAML")
    print(f"  Input: {knowledge_path / 'keywords' / 'candidates.csv'} (kept candidates)")
    print(f"  Output: {knowledge_path / 'keywords' / 'keywords.csv'} (keyword index)")
    print(f"  Target: YAML files referenced in candidates.csv")

    if dry_run:
        print("  (dry run - showing changes without modifying files)")

    try:
        args = _create_args_namespace(
            knowledge_path=knowledge_path,
            dry_run=dry_run,
        )
        result = apply_keywords_main(args)
        if result == 0:
            print("  ✓ Keywords applied successfully")
        return result
    except Exception as exc:
        print(f"  Error during keyword application: {exc}", file=sys.stderr)
        return 1


def run_variants_stage(knowledge_path: Path, *, dry_run: bool = False) -> int:
    """Run the variant resolution stage.

    This stage has three sub-steps:
    1. Track variants: Use Qwen embeddings to find similar keyword pairs
    2. Validate variants: Sub-agent reviews pairs and decides on merges
    3. Apply decisions: Apply validated merge decisions to keywords.csv and YAML

    Args:
        knowledge_path: Base knowledge directory.
        dry_run: If True, show what would be done without changes.

    Returns:
        0 on success, 1 on error.
    """
    from scripts.knowledge.variant_resolver import (
        apply_variant_decisions_main,
        track_variants_main,
    )

    keywords_csv = knowledge_path / "keywords" / "keywords.csv"
    variants_csv = knowledge_path / "keywords" / "variant_candidates.csv"

    print("Stage 5: Variant Resolution")
    print(f"  Input: {keywords_csv}")
    print(f"  Output: {variants_csv}")
    print()

    # Step 5a: Track variants using embeddings
    print("  Step 5a: Track Variant Candidates")
    print("  -" * 20)

    if dry_run:
        print("  (dry run - skipping variant tracking)")
    else:
        try:
            track_args = _create_args_namespace(
                threshold=0.85,
                model="Qwen/Qwen3-Embedding-8B",
                knowledge_path=knowledge_path,
            )
            result = track_variants_main(track_args)
            if result != 0:
                return result
            print("  ✓ Variant tracking completed")
        except Exception as exc:
            print(f"  Error during variant tracking: {exc}", file=sys.stderr)
            return 1

    print()

    # Step 5b: Sub-agent validation instructions
    print("  Step 5b: Variant Validation (Sub-agent)")
    print("  -" * 20)
    print()
    print("  This step requires the keyword-synonym-reviewer sub-agent.")
    print("  The sub-agent will review similar keyword pairs and decide on merges.")
    print()
    print("  To check for unvalidated pairs:")
    print("    uv run knowledge.query-variants --unvalidated --format json")
    print()
    print("  To invoke the sub-agent:")
    print('    Task(subagent_type="keyword-synonym-reviewer", prompt="")')
    print()
    print("  The sub-agent will:")
    print("    1. Query unvalidated variant pairs in batches")
    print("    2. Decide whether each pair should merge (true/false)")
    print("    3. Choose the canonical form for merges")
    print("    4. Continue until all pairs are validated")
    print()

    # Step 5c: Apply validated decisions
    print("  Step 5c: Apply Variant Decisions")
    print("  -" * 20)
    print()
    print("  After sub-agent validation, apply the merge decisions:")

    # In dry-run mode, check if required files exist before attempting to apply
    if dry_run:
        if not variants_csv.exists():
            print("  No variant_candidates.csv found; run Stage 5a without --dry-run first")
            return 0
        print("  (dry run - showing what would be applied)")

    try:
        apply_args = _create_args_namespace(
            knowledge_path=knowledge_path,
            dry_run=dry_run,
        )
        result = apply_variant_decisions_main(apply_args)
        if result == 0:
            print("  ✓ Variant decisions applied successfully")
        return result
    except Exception as exc:
        print(f"  Error applying variant decisions: {exc}", file=sys.stderr)
        return 1


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
            result = run_score_stage(
                knowledge_path,
                dry_run=args.dry_run,
                model=args.score_model,
                batch_size=args.score_batch_size,
            )
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
