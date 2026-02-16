"""Token management utilities for model wrappers.

Provides token estimation, budget tracking, and chunking utilities
for optimizing model inputs and outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Rough token estimation ratios for different content types
TOKEN_RATIOS = {
    "english": 0.75,  # ~0.75 tokens per character
    "code": 0.5,  # Code tends to be more token-efficient
    "json": 0.6,  # JSON structure adds some overhead
    "markdown": 0.7,  # Markdown is similar to English
}


def _max_prefix_length_within_tokens(text: str, max_tokens: int, content_type: str) -> int:
    """Find the longest prefix length whose token estimate fits max_tokens."""
    low = 1
    high = len(text)
    best = 0

    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if estimate_tokens(candidate, content_type) <= max_tokens:
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    return best


def _max_suffix_length_within_tokens(text: str, max_tokens: int, content_type: str) -> int:
    """Find the longest suffix length whose token estimate fits max_tokens."""
    low = 1
    high = len(text)
    best = 0

    while low <= high:
        mid = (low + high) // 2
        candidate = text[-mid:]
        if estimate_tokens(candidate, content_type) <= max_tokens:
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    return best


def _split_text_to_token_budget(text: str, max_tokens: int, content_type: str) -> list[str]:
    """Split text into pieces where every piece is <= max_tokens."""
    remaining = text.strip()
    if not remaining:
        return []

    pieces: list[str] = []
    while remaining:
        if estimate_tokens(remaining, content_type) <= max_tokens:
            pieces.append(remaining)
            break

        prefix_len = _max_prefix_length_within_tokens(remaining, max_tokens, content_type)
        if prefix_len <= 0:
            raise ValueError(
                "Unable to split text into chunks within token budget; "
                "max_tokens is too small for the content estimator"
            )

        split_idx = max(
            remaining.rfind("\n", 0, prefix_len + 1),
            remaining.rfind(" ", 0, prefix_len + 1),
        )
        if split_idx <= 0:
            split_idx = prefix_len

        piece = remaining[:split_idx].strip()
        if not piece:
            split_idx = prefix_len
            piece = remaining[:split_idx].strip()
            if not piece:
                raise ValueError("Failed to create non-empty chunk within token budget")

        pieces.append(piece)
        remaining = remaining[split_idx:].strip()

    return pieces


def _tail_within_token_budget(text: str, max_tokens: int, content_type: str) -> str:
    """Return the largest tail section that fits max_tokens."""
    trimmed = text.strip()
    if not trimmed or max_tokens <= 0:
        return ""

    if estimate_tokens(trimmed, content_type) <= max_tokens:
        return trimmed

    suffix_len = _max_suffix_length_within_tokens(trimmed, max_tokens, content_type)
    if suffix_len <= 0:
        return ""

    return trimmed[-suffix_len:].strip()


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
        if tokens > self.available_input_tokens:
            raise ValueError(
                "Input token budget exceeded: "
                f"requested={tokens}, available={self.available_input_tokens}"
            )
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
        if tokens > self.available_output_tokens:
            raise ValueError(
                "Output token budget exceeded: "
                f"requested={tokens}, available={self.available_output_tokens}"
            )
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
            raise KeyError(f"Unknown interaction_id '{interaction_id}'")

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
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0")
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens must be >= 0")

        if max_tokens is None:
            max_tokens = self.default_budget.max_input_tokens - self.default_budget.reserved_tokens

        if not text:
            return [text]

        total_tokens = estimate_tokens(text, content_type)
        if total_tokens <= max_tokens:
            return [text]

        paragraphs = [p for p in re.split(r"\n\n+", text) if p.strip()]
        units: list[str] = []
        for paragraph in paragraphs:
            units.extend(_split_text_to_token_budget(paragraph, max_tokens, content_type))

        if not units:
            units = _split_text_to_token_budget(text, max_tokens, content_type)

        chunks: list[str] = []
        current_chunk = ""

        for unit in units:
            if not current_chunk:
                current_chunk = unit
                continue

            candidate = f"{current_chunk}\n\n{unit}"
            if estimate_tokens(candidate, content_type) <= max_tokens:
                current_chunk = candidate
                continue

            chunks.append(current_chunk)

            overlap_budget = min(overlap_tokens, max_tokens)
            overlap_text = _tail_within_token_budget(current_chunk, overlap_budget, content_type)
            if overlap_text:
                overlap_candidate = f"{overlap_text}\n\n{unit}"
                if estimate_tokens(overlap_candidate, content_type) <= max_tokens:
                    current_chunk = overlap_candidate
                    continue

            current_chunk = unit

        if current_chunk:
            chunks.append(current_chunk)

        oversized_chunks: list[int] = []
        for chunk in chunks:
            chunk_tokens = estimate_tokens(chunk, content_type)
            if chunk_tokens > max_tokens:
                oversized_chunks.append(chunk_tokens)
        if oversized_chunks:
            raise RuntimeError(
                f"chunk_text produced oversized chunks despite enforcement: {oversized_chunks}"
            )

        return chunks
