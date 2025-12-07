"""Score keyword candidates using Qwen3-Reranker model.

This module provides optional scoring functionality using Qwen3-Reranker-8B
from HuggingFace. It scores candidates based on semantic relevance between
the candidate text and its surrounding sentence context.

The Qwen3-Reranker model evaluates how well the candidate keyword fits
within its sentence context, producing a relevance score from 0.0 to 1.0.
Higher scores indicate the candidate is more likely a meaningful keyword.

Usage:
    # Score all unscored candidates
    uv run knowledge.score-candidates-with-qwen

    # Score with custom batch size
    uv run knowledge.score-candidates-with-qwen --batch-size 16

    # Use alternative model
    uv run knowledge.score-candidates-with-qwen --model Qwen/Qwen3-Reranker-4B

Args:
    --model: HuggingFace model to use for scoring (default: Qwen/Qwen3-Reranker-8B).
    --batch-size: Batch size for inference (default: 32).
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from scripts.dev.utils import REPO_ROOT

if TYPE_CHECKING:
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )


def get_unscored_candidates(csv_path: Path) -> list[dict[str, str]]:
    """Get candidates that haven't been scored with Qwen yet.

    Args:
        csv_path: Path to the candidates CSV file.

    Returns:
        List of unscored candidate records.
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []

    query = """
        SELECT *
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE qwen_score = '' OR qwen_score IS NULL
    """
    try:
        with duckdb.connect() as conn:
            result = conn.execute(query, [str(csv_path)])
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]
    except duckdb.Error:
        return []


def update_candidate_scores_batch(
    csv_path: Path,
    scores: dict[str, float],
) -> bool:
    """Update Qwen scores for multiple candidates at once.

    Args:
        csv_path: Path to the candidates CSV file.
        scores: Dictionary mapping candidate_id to score.

    Returns:
        True if update succeeded, False otherwise.
    """
    if not csv_path.exists() or not scores:
        return False

    try:
        with duckdb.connect() as conn:
            conn.execute(f"""
                CREATE TABLE candidates AS
                SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
            """)

            for candidate_id, score in scores.items():
                conn.execute(
                    "UPDATE candidates SET qwen_score = ? WHERE candidate_id = ?",
                    [str(score), candidate_id],
                )

            conn.execute(f"COPY candidates TO '{csv_path}' (HEADER, DELIMITER ',')")
    except duckdb.Error:
        return False
    else:
        return True


def load_reranker_model(
    model_name: str,
) -> tuple[Any, Any, Any]:
    """Load the Qwen3-Reranker model and tokenizer.

    Args:
        model_name: HuggingFace model identifier.

    Returns:
        Tuple of (model, tokenizer, device).

    Raises:
        ImportError: If transformers or torch are not installed.
    """
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        msg = "transformers and torch are required for Qwen scoring"
        raise ImportError(msg) from exc

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )
    model.to(device)
    model.eval()

    return model, tokenizer, device


def score_batch(
    model: AutoModelForSequenceClassification,
    tokenizer: AutoTokenizer,
    device: torch.device,
    pairs: list[tuple[str, str]],
) -> list[float]:
    """Score a batch of (query, document) pairs using the reranker.

    For keyword extraction, the query is the candidate keyword and the
    document is the sentence context.

    Args:
        model: The reranker model.
        tokenizer: The tokenizer.
        device: The device to use.
        pairs: List of (candidate_text, sentence) pairs.

    Returns:
        List of relevance scores (0.0 to 1.0).
    """
    import torch

    if not pairs:
        return []

    # Format pairs for reranker - using sentence as query, candidate as doc
    # This measures how relevant the candidate is to the sentence context
    inputs = tokenizer(
        [p[1] for p in pairs],  # sentences as queries
        [p[0] for p in pairs],  # candidates as documents
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        # Get relevance scores (logits or scores depending on model)
        if hasattr(outputs, "logits"):
            scores = torch.sigmoid(outputs.logits.squeeze(-1))
        else:
            scores = outputs[0].squeeze(-1)

        # Normalize to 0-1 range if needed
        scores_result: Any = scores.cpu().numpy().tolist()

        # Handle single score case
        if isinstance(scores_result, float):
            return [scores_result]
        if isinstance(scores_result, list):
            return scores_result

    msg = "Unexpected scores_result type"
    raise TypeError(msg)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for Qwen scoring.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Score keyword candidates using Qwen3-Reranker model.",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-Reranker-8B",
        help="HuggingFace model to use for scoring (default: Qwen/Qwen3-Reranker-8B).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        dest="batch_size",
        help="Batch size for inference (default: 32).",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        dest="knowledge_path",
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def score_candidates_main(args: argparse.Namespace) -> int:
    """Run Qwen-based candidate scoring.

    Args:
        args: Parsed command-line arguments.

    Returns:
        0 on success, 1 on error.
    """
    if args.knowledge_path.is_absolute():
        knowledge_path = args.knowledge_path.resolve()
    else:
        knowledge_path = (REPO_ROOT / args.knowledge_path).resolve()

    candidates_csv = knowledge_path / "keywords" / "candidates.csv"

    if not candidates_csv.exists():
        print(f"Error: Candidates CSV not found: {candidates_csv}", file=sys.stderr)
        return 1

    # Get unscored candidates
    candidates = get_unscored_candidates(candidates_csv)
    if not candidates:
        print("No unscored candidates found.")
        return 0

    print(f"Found {len(candidates)} unscored candidates")
    print(f"Loading model: {args.model}")

    try:
        model, tokenizer, device = load_reranker_model(args.model)
        print(f"Model loaded on device: {device}")
    except ImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error loading model: {exc}", file=sys.stderr)
        return 1

    # Process in batches
    batch_size = args.batch_size
    total_scored = 0
    all_scores: dict[str, float] = {}

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]

        # Prepare (candidate_text, sentence) pairs
        pairs = [(c.get("candidate_text", ""), c.get("sentence", "")) for c in batch]

        # Score the batch
        scores = score_batch(model, tokenizer, device, pairs)

        # Map scores back to candidate IDs
        for candidate, score in zip(batch, scores, strict=False):
            candidate_id = candidate.get("candidate_id", "")
            if candidate_id:
                all_scores[candidate_id] = score
                total_scored += 1

        print(f"Scored batch {i // batch_size + 1}: {len(batch)} candidates")

    # Update all scores at once
    if all_scores:
        success = update_candidate_scores_batch(candidates_csv, all_scores)
        if not success:
            print("Error: Failed to update scores in CSV", file=sys.stderr)
            return 1

    print(f"\nTotal scored: {total_scored} candidates")
    print(f"Output: {candidates_csv}")

    return 0


def main() -> int:
    """Entry point for knowledge.score-candidates-with-qwen command.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    args = parse_args()
    return score_candidates_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
