#!/usr/bin/env python3
"""Lint a Markdown draft for banned AI tells and high-risk patterns.

This linter is intentionally heuristic. It is meant to:
- flag likely problems
- point to locations

It is not meant to automatically rewrite.

Usage:
  python lint_ai_tells.py path/to/draft.md
  python lint_ai_tells.py path/to/draft.md --output report.md
  python lint_ai_tells.py path/to/draft.md --format json --output report.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from md_utils import extract_sentences, offset_to_linecol, strip_markdown_noise


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # "fail" or "warn"
    line: int
    col: int
    excerpt: str


_EM_DASH_CHARS = ["\u2014", "\u2013"]  # em dash, en dash

_BANNED_SENTENCE_STARTS = {"but", "and", "so", "or"}
_BANNED_SENTENCE_START_SUBS = {"still", "yet", "however", "therefore"}

_HEDGE_WORDS = {"might", "could", "perhaps"}

_FILLER_PHRASES = [
    "it's worth noting",
    "it is worth noting",
    "the question becomes",
    "something like",
    "one of the few ways",
    "in today's world",
]

_STATUS_PHRASES = [
    "everyone gets this wrong",
    "people don't realize",
    "people do not realize",
    "the real truth is",
]

# Rationed patterns (warn, count)
_CONTRAST_PAIR_RE = re.compile(r"\b(not\s+[^.?!]+\s+but\s+[^.?!]+)\b", re.IGNORECASE)
_LESS_MORE_RE = re.compile(r"\bless\s+about\b.*?\bmore\s+about\b", re.IGNORECASE)
_RHET_Q_ANSWER_RE = re.compile(r"\?\s+(it\s+means|that\s+means|this\s+means)\b", re.IGNORECASE)
_IMPERATIVE_CHAIN_RE = re.compile(r"\b(do|pull|push|try|take|make)\b[^.?!]{0,80}\bthen\b[^.?!]{0,80}\bthen\b", re.IGNORECASE)

# Parallel clause triggers used in the original guide examples.
_PARALLEL_TRIGGER_WORDS = ["how", "where", "that", "every"]


def _clean_excerpt(text: str, max_len: int = 160) -> str:
    s = " ".join(text.strip().split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def lint_markdown(markdown: str) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []

    cleaned = strip_markdown_noise(markdown)
    sentences = extract_sentences(cleaned)

    counts: Dict[str, int] = {}

    def add(rule: str, severity: str, offset: int, excerpt: str) -> None:
        line, col = offset_to_linecol(cleaned, offset)
        findings.append(Finding(rule=rule, severity=severity, line=line, col=col, excerpt=_clean_excerpt(excerpt)))
        counts[rule] = counts.get(rule, 0) + 1

    # Rule: em dash characters
    # Search in cleaned text so line/col offsets align.
    for ch in _EM_DASH_CHARS:
        for m in re.finditer(re.escape(ch), cleaned):
            context_start = max(0, m.start() - 40)
            context_end = min(len(cleaned), m.end() + 40)
            add("em_dash_character", "fail", m.start(), cleaned[context_start:context_end])

    # Sentence start bans and hedges
    for s in sentences:
        raw = s.text.strip()
        # Strip leading quotes/parens/brackets.
        stripped = re.sub(r"^[\s\"'\(\[]+", "", raw)
        first_word_match = re.match(r"([A-Za-z]+)", stripped)
        if first_word_match:
            first = first_word_match.group(1).lower()
            if first in _BANNED_SENTENCE_STARTS:
                add("sentence_start_conjunction", "fail", s.span.start, raw)
            if first in _BANNED_SENTENCE_START_SUBS:
                add("sentence_start_conjunction_substitute", "fail", s.span.start, raw)

        # Hedge words
        for w in _HEDGE_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", raw, re.IGNORECASE):
                add("vague_hedge_word", "fail", s.span.start, raw)
                break

        # Filler phrases
        lowered = raw.lower()
        for phrase in _FILLER_PHRASES:
            if phrase in lowered:
                add("filler_phrase", "fail", s.span.start, raw)
                break

        # Status phrases
        for phrase in _STATUS_PHRASES:
            if phrase in lowered:
                add("status_or_moralizing", "fail", s.span.start, raw)
                break

        # Parallel clause heuristic: repeated trigger words after commas
        lower = raw.lower()
        # Count occurrences of trigger words at start or after comma.
        for t in _PARALLEL_TRIGGER_WORDS:
            occ = len(re.findall(rf"(?:^|,)\s*{t}\b", lower))
            if occ >= 3:
                add("parallel_clause_pseudolist", "fail", s.span.start, raw)
                break

        # Repeated first words in comma-separated segments
        segments = [seg.strip() for seg in raw.split(",") if seg.strip()]
        if len(segments) >= 3:
            first_words = []
            for seg in segments:
                m = re.match(r"([A-Za-z]+)", seg)
                if m:
                    first_words.append(m.group(1).lower())
            if len(first_words) >= 3:
                # Check if at least 3 segments share the same first word.
                for w in set(first_words):
                    if w and first_words.count(w) >= 3:
                        add("comma_parallel_segments", "fail", s.span.start, raw)
                        break

        # Rationed patterns (warn)
        if _CONTRAST_PAIR_RE.search(raw) or _LESS_MORE_RE.search(raw):
            add("contrast_pair", "warn", s.span.start, raw)

        if _RHET_Q_ANSWER_RE.search(raw):
            add("rhetorical_question_answer", "warn", s.span.start, raw)

        if _IMPERATIVE_CHAIN_RE.search(raw):
            add("imperative_chain", "warn", s.span.start, raw)

    # Repeated sentence starts: 3 in a row within a paragraph
    # Use the extracted sentences and paragraph_index to group.
    by_para: Dict[int, List[Tuple[int, str, int]]] = {}
    for s in sentences:
        stripped = re.sub(r"^[\s\"'\(\[]+", "", s.text.strip())
        m = re.match(r"([A-Za-z]+)", stripped)
        first = m.group(1).lower() if m else ""
        by_para.setdefault(s.paragraph_index, []).append((s.span.start, first, s.sentence_index))

    for p_idx, items in by_para.items():
        # items are in order by sentence_index already.
        for i in range(0, len(items) - 2):
            a_off, a_first, _ = items[i]
            b_off, b_first, _ = items[i + 1]
            c_off, c_first, _ = items[i + 2]
            if a_first and a_first == b_first == c_first:
                add("three_sentence_same_start", "fail", a_off, f"Starts with '{a_first}'")

    return findings, counts


def render_markdown(findings: List[Finding], counts: Dict[str, int]) -> str:
    lines: List[str] = []
    fails = [f for f in findings if f.severity == "fail"]
    warns = [f for f in findings if f.severity == "warn"]

    lines.append("# Lint report")
    lines.append("")
    lines.append(f"Fail findings: {len(fails)}")
    lines.append(f"Warn findings: {len(warns)}")
    lines.append("")

    if counts:
        lines.append("## Counts")
        lines.append("")
        for k in sorted(counts.keys()):
            lines.append(f"- {k}: {counts[k]}")
        lines.append("")

    def section(title: str, group: List[Finding]) -> None:
        if not group:
            return
        lines.append(f"## {title}")
        lines.append("")
        for f in sorted(group, key=lambda x: (x.line, x.col)):
            excerpt = f.excerpt
            lines.append(f"- **{f.rule}** at L{f.line}:C{f.col}: {excerpt}")
        lines.append("")

    section("Fail", fails)
    section("Warn", warns)

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Path to a Markdown file")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--output", default="", help="Write report to this path. Defaults to stdout.")

    args = ap.parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        md = f.read()

    findings, counts = lint_markdown(md)

    if args.format == "json":
        payload = {
            "counts": counts,
            "findings": [f.__dict__ for f in findings],
        }
        out = json.dumps(payload, indent=2)
    else:
        out = render_markdown(findings, counts)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)

    # Exit code: 1 if any fail findings.
    return 1 if any(f.severity == "fail" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
