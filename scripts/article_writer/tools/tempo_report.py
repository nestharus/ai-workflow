#!/usr/bin/env python3
"""Generate a tempo report for a Markdown draft.

Tempo here is a proxy:
- sentence length distribution
- paragraph length distribution
- repeated rhetorical moves that create rhythm

Usage:
  python tempo_report.py path/to/draft.md
  python tempo_report.py path/to/draft.md --output report.md
  python tempo_report.py path/to/draft.md --format json --output report.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics

from md_utils import extract_sentences, iter_paragraph_spans, strip_markdown_noise


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _summary_stats(values: list[int]) -> dict[str, float]:
    if not values:
        return {"count": 0}
    mean = statistics.mean(values)
    median = statistics.median(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    cv = (stdev / mean) if mean else 0.0
    return {
        "count": len(values),
        "mean": mean,
        "median": median,
        "stdev": stdev,
        "cv": cv,
        "min": min(values),
        "max": max(values),
    }


def analyze_tempo(markdown: str) -> dict:
    cleaned = strip_markdown_noise(markdown)

    sentences = extract_sentences(cleaned)
    sent_lens = [_word_count(s.text) for s in sentences]

    # Paragraph lengths
    para_lens: list[int] = []
    for p_span in iter_paragraph_spans(cleaned):
        p_text = cleaned[p_span.start : p_span.end].strip()
        if not p_text:
            continue
        para_lens.append(_word_count(p_text))

    # Runs of similarly-sized sentences can feel metronomic.
    run_threshold = 2  # words
    min_run = 4
    runs: list[dict] = []
    current: list[int] = []
    for l in sent_lens:
        if not current:
            current = [l]
            continue
        if abs(l - current[-1]) <= run_threshold:
            current.append(l)
        else:
            if len(current) >= min_run:
                runs.append({"length": len(current), "values": current[:]})
            current = [l]
    if len(current) >= min_run:
        runs.append({"length": len(current), "values": current[:]})

    # Short / long balance
    short = sum(1 for l in sent_lens if l <= 7)
    medium = sum(1 for l in sent_lens if 8 <= l <= 20)
    long = sum(1 for l in sent_lens if l >= 21)

    return {
        "sentences": {
            "stats": _summary_stats(sent_lens),
            "buckets": {"short<=7": short, "medium8-20": medium, "long>=21": long},
        },
        "paragraphs": {"stats": _summary_stats(para_lens)},
        "runs": runs,
        "heuristics": {
            "metronomic_sentence_cv_lt_0.35": (
                _summary_stats(sent_lens).get("cv", 0.0) < 0.35 if sent_lens else False
            ),
            "metronomic_paragraph_cv_lt_0.45": (
                _summary_stats(para_lens).get("cv", 0.0) < 0.45 if para_lens else False
            ),
        },
    }


def render_markdown(report: dict) -> str:
    s_stats = report["sentences"]["stats"]
    p_stats = report["paragraphs"]["stats"]
    buckets = report["sentences"]["buckets"]

    lines: list[str] = ["# Tempo report", ""]

    lines.append("## Sentence length")
    lines.append("")
    if s_stats.get("count", 0) == 0:
        lines.append("No sentences detected.")
    else:
        lines.append(f"Count: {s_stats['count']}")
        lines.append(f"Mean words: {s_stats['mean']:.2f}")
        lines.append(f"Median words: {s_stats['median']:.2f}")
        lines.append(f"Std dev: {s_stats['stdev']:.2f}")
        lines.append(f"Coeff var: {s_stats['cv']:.2f}")
        lines.append(f"Min / max: {s_stats['min']} / {s_stats['max']}")
        lines.append("")
        lines.append(f"Short (<=7): {buckets['short<=7']}")
        lines.append(f"Medium (8-20): {buckets['medium8-20']}")
        lines.append(f"Long (>=21): {buckets['long>=21']}")

    lines.append("")
    lines.append("## Paragraph length")
    lines.append("")
    if p_stats.get("count", 0) == 0:
        lines.append("No paragraphs detected.")
    else:
        lines.append(f"Count: {p_stats['count']}")
        lines.append(f"Mean words: {p_stats['mean']:.2f}")
        lines.append(f"Median words: {p_stats['median']:.2f}")
        lines.append(f"Std dev: {p_stats['stdev']:.2f}")
        lines.append(f"Coeff var: {p_stats['cv']:.2f}")
        lines.append(f"Min / max: {p_stats['min']} / {p_stats['max']}")

    lines.append("")
    lines.append("## Heuristics")
    lines.append("")
    for k, v in report["heuristics"].items():
        lines.append(f"- {k}: {v}")

    runs = report.get("runs", [])
    if runs:
        lines.append("")
        lines.append("## Similar-length sentence runs")
        lines.append("")
        lines.append(
            "Runs of 4+ sentences where each sentence length is within 2 words of the prior one."
        )
        lines.append("These can create metronomic cadence.")
        lines.append("")
        for r in runs[:10]:
            lines.append(f"- run length {r['length']}: {r['values']}")

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

    report = analyze_tempo(md)

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
