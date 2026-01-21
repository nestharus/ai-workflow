#!/usr/bin/env python3
"""Generate a basic readability report for a Markdown draft.

This is intentionally lightweight (no external deps).

Metrics:
- word/sentence/paragraph counts
- words per sentence, words per paragraph
- estimated syllables (heuristic)
- Flesch Reading Ease
- Flesch-Kincaid Grade Level
- estimated reading time

Usage:
  python readability_report.py path/to/draft.md
  python readability_report.py path/to/draft.md --output report.md
  python readability_report.py path/to/draft.md --format json --output report.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics

from md_utils import extract_sentences, iter_paragraph_spans, strip_markdown_noise

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _count_syllables_word(word: str) -> int:
    """Heuristic syllable counter for English.

    Not perfect. Good enough for aggregate readability metrics.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0

    # Common short words
    if len(w) <= 3:
        return 1

    # Remove trailing 'e' (but keep 'le' endings like 'bottle')
    if w.endswith("e") and not w.endswith("le"):
        w = w[:-1]

    # Count vowel groups
    groups = re.findall(r"[aeiouy]+", w)
    count = len(groups)

    # Adjustments
    if w.endswith("le") and len(w) > 2 and w[-3] not in "aeiouy":
        count += 1

    # Clamp
    return max(1, count)


def analyze_readability(markdown: str) -> dict:
    cleaned = strip_markdown_noise(markdown)

    sentences = extract_sentences(cleaned)
    sent_texts = [s.text.strip() for s in sentences if s.text.strip()]

    paragraph_texts: list[str] = []
    for p in iter_paragraph_spans(cleaned):
        t = cleaned[p.start : p.end].strip()
        if t:
            paragraph_texts.append(t)

    words = _words(cleaned)
    word_count = len(words)
    sentence_count = max(1, len(sent_texts))
    paragraph_count = max(1, len(paragraph_texts))

    syllables = sum(_count_syllables_word(w) for w in words)

    wps = word_count / sentence_count if sentence_count else 0.0
    wpp = word_count / paragraph_count if paragraph_count else 0.0
    spw = syllables / word_count if word_count else 0.0

    # Flesch Reading Ease / FK Grade Level
    flesch = 206.835 - 1.015 * wps - 84.6 * spw
    fk_grade = 0.39 * wps + 11.8 * spw - 15.59

    # Reading time
    wpm = 200
    minutes = word_count / wpm if wpm else 0.0

    # Sentence length distribution
    sent_lens = [len(_words(t)) for t in sent_texts]
    mean_len = statistics.mean(sent_lens) if sent_lens else 0.0
    stdev_len = statistics.pstdev(sent_lens) if len(sent_lens) > 1 else 0.0

    return {
        "counts": {
            "words": word_count,
            "sentences": len(sent_texts),
            "paragraphs": len(paragraph_texts),
            "syllables_est": syllables,
        },
        "averages": {
            "words_per_sentence": wps,
            "words_per_paragraph": wpp,
            "syllables_per_word": spw,
        },
        "readability": {
            "flesch_reading_ease": flesch,
            "flesch_kincaid_grade": fk_grade,
        },
        "reading_time": {"wpm": wpm, "minutes_est": minutes},
        "sentence_length": {
            "mean": mean_len,
            "stdev": stdev_len,
            "min": min(sent_lens) if sent_lens else 0,
            "max": max(sent_lens) if sent_lens else 0,
        },
    }


def render_markdown(report: dict) -> str:
    c = report["counts"]
    a = report["averages"]
    r = report["readability"]
    t = report["reading_time"]
    sl = report["sentence_length"]

    lines: list[str] = []
    lines.append("# Readability report")
    lines.append("")

    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Words: {c['words']}")
    lines.append(f"- Sentences: {c['sentences']}")
    lines.append(f"- Paragraphs: {c['paragraphs']}")
    lines.append(f"- Estimated syllables: {c['syllables_est']}")

    lines.append("")
    lines.append("## Averages")
    lines.append("")
    lines.append(f"- Words per sentence: {a['words_per_sentence']:.2f}")
    lines.append(f"- Words per paragraph: {a['words_per_paragraph']:.2f}")
    lines.append(f"- Syllables per word: {a['syllables_per_word']:.2f}")

    lines.append("")
    lines.append("## Readability")
    lines.append("")
    lines.append(f"- Flesch Reading Ease: {r['flesch_reading_ease']:.2f}")
    lines.append(f"- Flesch-Kincaid Grade Level: {r['flesch_kincaid_grade']:.2f}")

    lines.append("")
    lines.append("## Sentence length")
    lines.append("")
    lines.append(f"- Mean: {sl['mean']:.2f}")
    lines.append(f"- Std dev: {sl['stdev']:.2f}")
    lines.append(f"- Min / max: {sl['min']} / {sl['max']}")

    lines.append("")
    lines.append("## Reading time")
    lines.append("")
    lines.append(f"- Estimated minutes at {t['wpm']} wpm: {t['minutes_est']:.1f}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as f:
        md = f.read()

    report = analyze_readability(md)

    if args.format == "json":
        out = json.dumps(report, indent=2)
    else:
        out = render_markdown(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
