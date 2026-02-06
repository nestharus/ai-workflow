"""Token management utilities for model wrappers.

Provides token estimation, budget tracking, and chunking utilities
for optimizing model inputs and outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


# Rough token estimation ratios for different content types
TOKEN_RATIOS = {
    "english": 0.75,  # ~0.75 tokens per character
    "code": 0.5,  # Code tends to be more token-efficient
    "json": 0.6,  # JSON structure adds some overhead
    "markdown": 0.7,  # Markdown is similar to English
}


def estimate_tokens(text: str, content_type: str = "english") -> int:
    """Estimate token count for text.

    This is a rough estimation - actual token counts vary by model.

    Args:
        text: Text to estimate tokens for.
        content_type: Type of content (english, code, json, markdown).

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    ratio = TOKEN_RATIOS.get(content_type, TOKEN_RATIOS["english"])

    # Count characters and apply ratio
    char_count = len(text)
    base_estimate = int(char_count * ratio)

    # Add overhead for special patterns
    # Newlines and whitespace patterns
    newline_count = text.count("\n")
    whitespace_overhead = newline_count // 4

    return base_estimate + whitespace_overhead


@dataclass
class TokenBudget:
    """Token budget for a model interaction.

    Attributes:
        max_input_tokens: Maximum tokens for input.
        max_output_tokens: Maximum tokens for output.
        reserved_tokens: Tokens reserved for system prompts, etc.
        used_input_tokens: Tokens used in input so far.
        used_output_tokens: Tokens used in output so far.
    """

    max_input_tokens: int = 8000
    max_output_tokens: int = 4000
    reserved_tokens: int = 500
    used_input_tokens: int = 0
    used_output_tokens: int = 0

    @property
    def available_input_tokens(self) -> int:
        """Tokens available for additional input."""
        return max(0, self.max_input_tokens - self.used_input_tokens - self.reserved_tokens)

    @property
    def available_output_tokens(self) -> int:
        """Tokens available for output."""
        return max(0, self.max_output_tokens - self.used_output_tokens)

    @property
    def total_available(self) -> int:
        """Total available tokens."""
        return self.available_input_tokens + self.available_output_tokens

    def can_fit(self, text: str, content_type: str = "english") -> bool:
        """Check if text fits within available input budget.

        Args:
            text: Text to check.
            content_type: Type of content for estimation.

        Returns:
            True if text fits, False otherwise.
        """
        estimated = estimate_tokens(text, content_type)
        return estimated <= self.available_input_tokens

    def consume_input(self, text: str, content_type: str = "english") -> int:
        """Consume input tokens for text.

        Args:
            text: Text being added to input.
            content_type: Type of content for estimation.

        Returns:
            Number of tokens consumed.
        """
        tokens = estimate_tokens(text, content_type)
        self.used_input_tokens += tokens
        return tokens

    def consume_output(self, text: str, content_type: str = "english") -> int:
        """Consume output tokens for text.

        Args:
            text: Text received as output.
            content_type: Type of content for estimation.

        Returns:
            Number of tokens consumed.
        """
        tokens = estimate_tokens(text, content_type)
        self.used_output_tokens += tokens
        return tokens

    def reset(self) -> None:
        """Reset used token counts."""
        self.used_input_tokens = 0
        self.used_output_tokens = 0


@dataclass
class TokenManager:
    """Manager for token budgets across multiple interactions.

    Attributes:
        model_name: Name of the model being managed.
        default_budget: Default budget configuration.
        budgets: Active budgets by interaction ID.
        total_input_tokens: Total input tokens used across all interactions.
        total_output_tokens: Total output tokens used across all interactions.
    """

    model_name: str
    default_budget: TokenBudget = field(default_factory=TokenBudget)
    budgets: dict[str, TokenBudget] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def get_budget(self, interaction_id: str) -> TokenBudget:
        """Get or create budget for an interaction.

        Args:
            interaction_id: Unique identifier for the interaction.

        Returns:
            TokenBudget for the interaction.
        """
        if interaction_id not in self.budgets:
            self.budgets[interaction_id] = TokenBudget(
                max_input_tokens=self.default_budget.max_input_tokens,
                max_output_tokens=self.default_budget.max_output_tokens,
                reserved_tokens=self.default_budget.reserved_tokens,
            )
        return self.budgets[interaction_id]

    def finalize_interaction(self, interaction_id: str) -> dict[str, int]:
        """Finalize an interaction and accumulate totals.

        Args:
            interaction_id: Interaction to finalize.

        Returns:
            Dictionary with input/output token counts for the interaction.
        """
        if interaction_id not in self.budgets:
            return {"input_tokens": 0, "output_tokens": 0}

        budget = self.budgets[interaction_id]
        self.total_input_tokens += budget.used_input_tokens
        self.total_output_tokens += budget.used_output_tokens

        result = {
            "input_tokens": budget.used_input_tokens,
            "output_tokens": budget.used_output_tokens,
        }

        del self.budgets[interaction_id]
        return result

    def get_totals(self) -> dict[str, int]:
        """Get total token usage.

        Returns:
            Dictionary with total input/output tokens.
        """
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }

    def chunk_text(
        self,
        text: str,
        max_tokens: int | None = None,
        content_type: str = "english",
        overlap_tokens: int = 50,
    ) -> list[str]:
        """Split text into chunks that fit within token budget.

        Args:
            text: Text to chunk.
            max_tokens: Maximum tokens per chunk (default: available input).
            content_type: Type of content for estimation.
            overlap_tokens: Tokens of overlap between chunks.

        Returns:
            List of text chunks.
        """
        if max_tokens is None:
            max_tokens = self.default_budget.max_input_tokens - self.default_budget.reserved_tokens

        total_tokens = estimate_tokens(text, content_type)
        if total_tokens <= max_tokens:
            return [text]

        # Split by paragraphs first
        paragraphs = re.split(r"\n\n+", text)
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = estimate_tokens(para, content_type)

            if current_tokens + para_tokens <= max_tokens:
                current_chunk.append(para)
                current_tokens += para_tokens
            else:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))

                # Start new chunk with overlap
                if chunks and overlap_tokens > 0:
                    # Get last paragraph(s) for overlap
                    overlap_text = current_chunk[-1] if current_chunk else ""
                    overlap_actual = estimate_tokens(overlap_text, content_type)
                    if overlap_actual <= overlap_tokens:
                        current_chunk = [overlap_text, para]
                        current_tokens = overlap_actual + para_tokens
                    else:
                        current_chunk = [para]
                        current_tokens = para_tokens
                else:
                    current_chunk = [para]
                    current_tokens = para_tokens

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks
