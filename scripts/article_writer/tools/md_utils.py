"""Utility helpers for Markdown-based writing lint.

These helpers intentionally avoid heavy NLP dependencies.
They aim to be:
- dependency-free
- fast
- good enough for draft linting

They are not a replacement for a full syntactic parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, List, Tuple


# Fenced code blocks: ```...``` or ~~~...~~~
_CODE_FENCE_BLOCK_RE = re.compile(r"(^```[\s\S]*?^```\s*$)|(^~~~[\s\S]*?^~~~\s*$)", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class Span:
    """A span within a text."""

    start: int
    end: int


@dataclass(frozen=True)
class Sentence:
    text: str
    span: Span
    paragraph_index: int
    sentence_index: int


def strip_code_blocks(markdown: str) -> str:
    """Remove fenced code blocks while preserving line count.

    The removed region is replaced with blank lines, which keeps offsets
    roughly stable for line-number reporting.
    """

    def _blank_out(match: re.Match[str]) -> str:
        block = match.group(0)
        # Preserve line breaks to keep line numbers stable.
        return "\n" * block.count("\n")

    return _CODE_FENCE_BLOCK_RE.sub(_blank_out, markdown)


def strip_inline_code(markdown: str) -> str:
    """Blank out inline code spans enclosed by backticks.

    Offsets are preserved by replacing the span with spaces.
    """

    def _blank_out(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    return _INLINE_CODE_RE.sub(_blank_out, markdown)


def strip_markdown_noise(markdown: str) -> str:
    """Strip code blocks and inline code."""
    return strip_inline_code(strip_code_blocks(markdown))


def iter_paragraph_spans(text: str) -> Iterator[Span]:
    """Yield paragraph spans.

    Paragraphs are separated by one or more blank lines.
    """
    # Normalize Windows line endings.
    text = text.replace("\r\n", "\n")

    # Paragraph definition: maximal non-blank chunks.
    pattern = re.compile(r"(?:^|\n)([^\n].*?)(?=\n\s*\n|\Z)", re.S)
    for match in pattern.finditer(text):
        start = match.start(1)
        end = match.end(1)
        yield Span(start=start, end=end)


def _is_probable_abbreviation(token: str) -> bool:
    token = token.strip().lower()
    if not token:
        return False
    # Common abbreviations that should not split sentences.
    return token in {
        "e.g.",
        "i.e.",
        "etc.",
        "vs.",
        "mr.",
        "mrs.",
        "ms.",
        "dr.",
        "prof.",
        "sr.",
        "jr.",
        "st.",
        "u.s.",
        "u.k.",
    }


def split_sentences(paragraph_text: str, base_offset: int, paragraph_index: int) -> List[Sentence]:
    """Naively split a paragraph into sentences.

    Heuristics:
    - Split on ., !, ? followed by whitespace.
    - Avoid splitting on a small set of common abbreviations.

    Returns Sentence objects with spans relative to the full document.
    """

    # Work with normalized whitespace but keep offsets by operating on original.
    sentences: List[Sentence] = []

    # Candidate boundaries are punctuation followed by whitespace.
    boundary_re = re.compile(r"([.!?])\s+")

    start = 0
    idx = 0
    for match in boundary_re.finditer(paragraph_text):
        end = match.end(1)  # include punctuation
        chunk = paragraph_text[start:end].strip()

        # Check abbreviation: look at last ~10 chars.
        tail = chunk[-10:]
        # Find last token that ends with a period.
        last_word_match = re.search(r"\b\S+\.$", tail)
        if last_word_match and _is_probable_abbreviation(last_word_match.group(0)):
            continue

        if chunk:
            span = Span(start=base_offset + start, end=base_offset + end)
            sentences.append(
                Sentence(text=chunk, span=span, paragraph_index=paragraph_index, sentence_index=idx)
            )
            idx += 1
        start = match.end(0)

    # Remainder
    remainder = paragraph_text[start:].strip()
    if remainder:
        span = Span(start=base_offset + start, end=base_offset + len(paragraph_text))
        sentences.append(Sentence(text=remainder, span=span, paragraph_index=paragraph_index, sentence_index=idx))

    return sentences


def extract_sentences(text: str) -> List[Sentence]:
    """Extract sentences from text by splitting each paragraph."""
    sentences: List[Sentence] = []
    for p_idx, p_span in enumerate(iter_paragraph_spans(text)):
        paragraph = text[p_span.start : p_span.end]
        sentences.extend(split_sentences(paragraph, base_offset=p_span.start, paragraph_index=p_idx))
    return sentences


def offset_to_linecol(text: str, offset: int) -> Tuple[int, int]:
    """Convert a character offset into 1-based (line, col)."""
    # Normalize.
    text = text.replace("\r\n", "\n")
    if offset < 0:
        offset = 0
    if offset > len(text):
        offset = len(text)

    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    if last_nl == -1:
        col = offset + 1
    else:
        col = offset - last_nl
    return line, col
