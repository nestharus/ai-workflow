#!/usr/bin/env python3
"""Extract a draft "skeleton" from Markdown.

Skeleton = heading outline + first sentence of each paragraph.

Also produces a "borders" view: last sentence of one section paired with the first sentence of the next.

Usage:
  python extract_skeleton.py path/to/draft.md --outdir out

Outputs:
  out/skeleton.md
  out/borders.md
  out/outline.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass

from md_utils import (
    extract_sentences,
    iter_paragraph_spans,
    split_sentences,
    strip_code_blocks,
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class Section:
    level: int
    title: str
    start_offset: int
    end_offset: int


def find_sections(md: str) -> list[Section]:
    """Return top-down sections based on Markdown headings.

    End offset is set later once next heading is known.
    """
    sections: list[Section] = []

    # Work on code-stripped text so headings inside code fences are ignored.
    text = strip_code_blocks(md)

    offset = 0
    for line in text.splitlines(keepends=True):
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m:
            hashes, title = m.group(1), m.group(2).strip()
            level = len(hashes)
            sections.append(
                Section(level=level, title=title, start_offset=offset, end_offset=len(text))
            )
        offset += len(line)

    # Set end offsets.
    for i in range(len(sections)):
        if i + 1 < len(sections):
            sections[i].end_offset = sections[i + 1].start_offset
        else:
            sections[i].end_offset = len(text)

    return sections


def _first_sentence_of_paragraph(paragraph: str, base_offset: int) -> str | None:
    sents = split_sentences(paragraph, base_offset=base_offset, paragraph_index=0)
    if not sents:
        return None
    return sents[0].text


def build_skeleton(md: str) -> tuple[str, str, dict]:
    text = strip_code_blocks(md)
    sections = find_sections(md)

    # If there are no headings, treat entire document as one section.
    if not sections:
        sections = [Section(level=1, title="(no headings)", start_offset=0, end_offset=len(text))]

    skeleton_lines: list[str] = ["# Skeleton", ""]
    borders_lines: list[str] = [
        "# Borders",
        "",
        "Each block shows the last sentence of one section and the first sentence of the next.",
        "",
    ]

    outline = {"sections": []}

    # Build per-section paragraph first sentences.
    section_firsts: list[dict] = []

    for s_idx, sec in enumerate(sections):
        sec_text = text[sec.start_offset : sec.end_offset]

        # Gather paragraphs inside section.
        first_sentences: list[str] = []
        for p_span in iter_paragraph_spans(sec_text):
            p_text = sec_text[p_span.start : p_span.end].strip()
            if not p_text:
                continue
            # Skip headings-as-paragraphs.
            if _HEADING_RE.match(p_text.splitlines()[0]):
                continue
            first = _first_sentence_of_paragraph(
                p_text, base_offset=sec.start_offset + p_span.start
            )
            if first:
                first_sentences.append(first)

        section_firsts.append(
            {
                "level": sec.level,
                "title": sec.title,
                "start_offset": sec.start_offset,
                "end_offset": sec.end_offset,
                "first_sentences": first_sentences,
            }
        )

        indent = "  " * (sec.level - 1)
        skeleton_lines.append(f"{indent}- {sec.title}")
        for fs in first_sentences:
            skeleton_lines.append(f"{indent}  - {fs}")
        skeleton_lines.append("")

    # Borders view
    # Use last sentence of each section and first sentence of next.
    for i in range(len(section_firsts) - 1):
        a = section_firsts[i]
        b = section_firsts[i + 1]

        a_text = text[a["start_offset"] : a["end_offset"]].strip()
        b_text = text[b["start_offset"] : b["end_offset"]].strip()

        a_sents = extract_sentences(a_text)
        last_a = a_sents[-1].text if a_sents else ""

        # First sentence of next section: prefer first paragraph first sentence.
        if b["first_sentences"]:
            first_b = b["first_sentences"][0]
        else:
            b_sents = extract_sentences(b_text)
            first_b = b_sents[0].text if b_sents else ""

        borders_lines.append(f"## {a['title']} -> {b['title']}")
        borders_lines.append("")
        borders_lines.append("**Last of previous section:**")
        borders_lines.append("")
        borders_lines.append(f"> {last_a}")
        borders_lines.append("")
        borders_lines.append("**First of next section:**")
        borders_lines.append("")
        borders_lines.append(f"> {first_b}")
        borders_lines.append("")

    outline["sections"] = section_firsts
    skeleton_md = "\n".join(skeleton_lines).rstrip() + "\n"
    borders_md = "\n".join(borders_lines).rstrip() + "\n"

    return skeleton_md, borders_md, outline


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Path to Markdown draft")
    ap.add_argument("--outdir", default=".", help="Directory for outputs")
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as f:
        md = f.read()

    skeleton_md, borders_md, outline = build_skeleton(md)

    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "skeleton.md"), "w", encoding="utf-8") as f:
        f.write(skeleton_md)
    with open(os.path.join(args.outdir, "borders.md"), "w", encoding="utf-8") as f:
        f.write(borders_md)
    with open(os.path.join(args.outdir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump(outline, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
