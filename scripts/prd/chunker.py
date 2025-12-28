r"""PRD chunker: Split messy PRD input into logical chunks for processing.

This module provides chunking strategies for PRD documents, splitting them into
manageable pieces for downstream element-extractor agents.

Chunking Modes:
- headers: Split on markdown headers (# ## ### etc.)
- fixed: Fixed character count with overlap
- paragraphs: Split on paragraph boundaries

Usage:
    python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks --mode headers
    python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks \
        --mode fixed --chunk-size 2000
    python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks \
        --mode paragraphs --min-size 500

Output Format:
    Creates numbered chunk files (chunk_001.md, chunk_002.md, ...) and a
    manifest.json file containing metadata about the chunking operation.

Architectural References:
- Python 3.11+ stdlib only (no external dependencies)
- Follows project conventions from docs/development/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Type aliases for clarity
ChunkMode = Literal["headers", "fixed", "paragraphs"]


@dataclass
class ChunkMetadata:
    """Metadata for a single chunk.

    Attributes:
        id: Chunk identifier (e.g., "chunk_001").
        file: Filename for this chunk (e.g., "chunk_001.md").
        start_line: Starting line number in source file (1-indexed).
        end_line: Ending line number in source file (1-indexed).
        char_count: Number of characters in the chunk.
        sequence_number: Absolute position in document (0-indexed).
        header: Header text if mode=headers, else empty string.
        header_level: Header level (1-6) if mode=headers, else 0.
        source_document_id: Identifier for the source document (basename without extension).
        preceding_chunk_id: ID of chunk that came immediately before.
        following_chunk_id: ID of chunk that comes immediately after.
    """

    id: str
    file: str
    start_line: int
    end_line: int
    char_count: int
    sequence_number: int
    header: str = ""
    header_level: int = 0
    source_document_id: str = ""
    preceding_chunk_id: str | None = None
    following_chunk_id: str | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of chunk metadata.
        """
        return {
            "id": self.id,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "char_count": self.char_count,
            "sequence_number": self.sequence_number,
            "header": self.header,
            "header_level": self.header_level,
            "source_document_id": self.source_document_id,
            "preceding_chunk_id": self.preceding_chunk_id,
            "following_chunk_id": self.following_chunk_id,
        }


@dataclass
class ChunkManifest:
    """Manifest describing all chunks created from a source file.

    Attributes:
        source_file: Path to the original input file.
        mode: Chunking mode used (headers, fixed, paragraphs).
        total_chunks: Total number of chunks created.
        chunks: List of chunk metadata.
        chunk_size: For fixed mode, the target chunk size.
        min_size: For paragraphs mode, the minimum chunk size.
        overlap: For fixed mode, the overlap size in characters.
    """

    source_file: str
    mode: str
    total_chunks: int
    chunks: list[ChunkMetadata]
    chunk_size: int = 0
    min_size: int = 0
    overlap: int = 0

    def to_dict(self) -> dict[str, str | int | list[dict[str, str | int | None]]]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of manifest.
        """
        result: dict[str, str | int | list[dict[str, str | int | None]]] = {
            "source_file": self.source_file,
            "mode": self.mode,
            "total_chunks": self.total_chunks,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }

        if self.chunk_size > 0:
            result["chunk_size"] = self.chunk_size
        if self.min_size > 0:
            result["min_size"] = self.min_size
        if self.overlap > 0:
            result["overlap"] = self.overlap

        return result


def _read_file_utf8(file_path: Path) -> str:
    """Read file content as UTF-8.

    Args:
        file_path: Path to the file to read.

    Returns:
        File content as string.

    Raises:
        FileNotFoundError: If file does not exist.
        UnicodeDecodeError: If file is not valid UTF-8.
    """
    return file_path.read_text(encoding="utf-8")


def _write_chunk_file(
    output_dir: Path,
    chunk_id: str,
    content: str,
) -> None:
    """Write chunk content to numbered file.

    Args:
        output_dir: Directory to write chunk file to.
        chunk_id: Chunk identifier (e.g., "chunk_001").
        content: Chunk content to write.
    """
    chunk_file = output_dir / f"{chunk_id}.md"
    chunk_file.write_text(content, encoding="utf-8")


def _write_manifest(
    output_dir: Path,
    manifest: ChunkManifest,
) -> None:
    """Write manifest.json file.

    Args:
        output_dir: Directory to write manifest to.
        manifest: Manifest data to write.
    """
    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _get_line_number_at_offset(content: str, offset: int) -> int:
    """Get line number (1-indexed) for character offset.

    Args:
        content: Full text content.
        offset: Character offset into content.

    Returns:
        Line number (1-indexed) at the given offset.
    """
    # Handle empty content explicitly
    if not content:
        return 1

    # Clamp offset to valid range [0, len(content)]
    # Allow offset == len(content) for "point just past last character" (end-of-file)
    offset = max(0, min(offset, len(content)))

    return content[:offset].count("\n") + 1


def _extract_header_info(line: str) -> tuple[int, str]:
    """Extract header level and text from a markdown header line.

    Args:
        line: Line of text to check for header.

    Returns:
        Tuple of (header_level, header_text). Returns (0, "") if not a header.

    Examples:
        >>> _extract_header_info("# Introduction")
        (1, "# Introduction")
        >>> _extract_header_info("## Features")
        (2, "## Features")
        >>> _extract_header_info("Regular text")
        (0, "")
    """
    # Match ATX-style headers: 1-6 # symbols followed by space
    match = re.match(r"^(#{1,6})\s+(.+)$", line)
    if match:
        hashes = match.group(1)
        text = match.group(2)
        return (len(hashes), f"{hashes} {text}")
    return (0, "")


def _link_adjacent_chunks(chunks: list[ChunkMetadata]) -> None:
    """Link adjacent chunks by setting preceding/following chunk IDs.

    Modifies chunks in place to set preceding_chunk_id and following_chunk_id.

    Args:
        chunks: List of chunk metadata to link.
    """
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk.preceding_chunk_id = chunks[i - 1].id
        if i < len(chunks) - 1:
            chunk.following_chunk_id = chunks[i + 1].id


def _get_source_document_id(source_file: str) -> str:
    """Extract source document ID from file path.

    Returns the basename of the file without its extension.

    Args:
        source_file: Path to the source file.

    Returns:
        Basename without extension.
    """
    return Path(source_file).stem


def _chunk_by_headers(
    content: str,
    output_dir: Path,
    source_file: str,
) -> ChunkManifest:
    """Split content by markdown headers.

    Each header starts a new chunk. Headers are included in their chunk.
    Preserves header hierarchy information in metadata.

    Args:
        content: Full text content to chunk.
        output_dir: Directory to write chunks to.
        source_file: Path to source file for manifest.

    Returns:
        ChunkManifest with metadata for all created chunks.
    """
    # Short-circuit for empty content to avoid creating phantom chunks.
    # content.split("\n") yields [""] for empty strings, which would create
    # a single chunk with empty content. Return empty manifest instead.
    if not content.strip():
        return ChunkManifest(
            source_file=source_file,
            mode="headers",
            total_chunks=0,
            chunks=[],
        )

    lines = content.split("\n")
    chunks: list[ChunkMetadata] = []
    current_chunk_lines: list[str] = []
    current_start_line = 1
    current_header = ""
    current_header_level = 0
    source_document_id = _get_source_document_id(source_file)

    # Process each line
    for line_idx, line in enumerate(lines, start=1):
        header_level, header_text = _extract_header_info(line)

        # If we hit a header and have accumulated lines, save current chunk
        if header_level > 0 and current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines)
            chunk_id = f"chunk_{len(chunks) + 1:03d}"

            metadata = ChunkMetadata(
                id=chunk_id,
                file=f"{chunk_id}.md",
                start_line=current_start_line,
                end_line=line_idx - 1,
                char_count=len(chunk_text),
                sequence_number=len(chunks),
                header=current_header,
                header_level=current_header_level,
                source_document_id=source_document_id,
            )
            chunks.append(metadata)
            _write_chunk_file(output_dir, chunk_id, chunk_text)

            # Start new chunk
            current_chunk_lines = [line]
            current_start_line = line_idx
            current_header = header_text
            current_header_level = header_level
        else:
            # Add line to current chunk
            current_chunk_lines.append(line)
            if header_level > 0:
                current_header = header_text
                current_header_level = header_level

    # Save final chunk if any lines remain
    if current_chunk_lines:
        chunk_text = "\n".join(current_chunk_lines)
        chunk_id = f"chunk_{len(chunks) + 1:03d}"

        metadata = ChunkMetadata(
            id=chunk_id,
            file=f"{chunk_id}.md",
            start_line=current_start_line,
            end_line=len(lines),
            char_count=len(chunk_text),
            sequence_number=len(chunks),
            header=current_header,
            header_level=current_header_level,
            source_document_id=source_document_id,
        )
        chunks.append(metadata)
        _write_chunk_file(output_dir, chunk_id, chunk_text)

    # Link adjacent chunks
    _link_adjacent_chunks(chunks)

    return ChunkManifest(
        source_file=source_file,
        mode="headers",
        total_chunks=len(chunks),
        chunks=chunks,
    )


def _find_word_boundary(text: str, target_pos: int, direction: str = "backward") -> int:
    """Find nearest word boundary to target position.

    Args:
        text: Text to search in.
        target_pos: Target character position.
        direction: Search direction ("backward" or "forward").

    Returns:
        Position of nearest word boundary.
    """
    if target_pos >= len(text):
        return len(text)
    if target_pos <= 0:
        return 0

    if direction == "backward":
        # Search backward for whitespace or start of text
        pos = target_pos
        while pos > 0 and not text[pos - 1].isspace():
            pos -= 1
        return pos
    else:  # forward
        # Search forward for whitespace or end of text
        pos = target_pos
        while pos < len(text) and not text[pos].isspace():
            pos += 1
        return pos


def _chunk_by_fixed_size(
    content: str,
    output_dir: Path,
    source_file: str,
    chunk_size: int,
    overlap: int = 100,
) -> ChunkManifest:
    """Split content by fixed character count with overlap.

    Splits at word boundaries near chunk_size to avoid cutting words.
    Overlaps chunks by specified amount to preserve context.

    Args:
        content: Full text content to chunk.
        output_dir: Directory to write chunks to.
        source_file: Path to source file for manifest.
        chunk_size: Target size for each chunk in characters.
        overlap: Number of characters to overlap between chunks.

    Returns:
        ChunkManifest with metadata for all created chunks.

    Raises:
        ValueError: If overlap is greater than or equal to chunk_size.
    """
    # Defensive check: public API (chunk_file) validates this, but raise here
    # to catch any direct calls to this internal function in production.
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be < chunk_size ({chunk_size})")

    chunks: list[ChunkMetadata] = []
    pos = 0
    chunk_num = 1
    source_document_id = _get_source_document_id(source_file)

    while pos < len(content):
        # Determine end position for this chunk
        target_end = min(pos + chunk_size, len(content))

        # Find word boundary near target end
        if target_end < len(content):
            chunk_end = _find_word_boundary(content, target_end, "backward")
            # If boundary is too far back, try forward
            if chunk_end <= pos:
                chunk_end = _find_word_boundary(content, target_end, "forward")
        else:
            chunk_end = len(content)

        # Extract chunk
        chunk_text = content[pos:chunk_end]
        chunk_id = f"chunk_{chunk_num:03d}"

        # Calculate line numbers
        start_line = _get_line_number_at_offset(content, pos)
        end_line = _get_line_number_at_offset(content, chunk_end - 1)

        metadata = ChunkMetadata(
            id=chunk_id,
            file=f"{chunk_id}.md",
            start_line=start_line,
            end_line=end_line,
            char_count=len(chunk_text),
            sequence_number=len(chunks),
            source_document_id=source_document_id,
        )
        chunks.append(metadata)
        _write_chunk_file(output_dir, chunk_id, chunk_text)

        # Move position forward with overlap
        pos = max(chunk_end - overlap, pos + 1) if chunk_end < len(content) else chunk_end

        chunk_num += 1

    # Link adjacent chunks
    _link_adjacent_chunks(chunks)

    return ChunkManifest(
        source_file=source_file,
        mode="fixed",
        total_chunks=len(chunks),
        chunks=chunks,
        chunk_size=chunk_size,
        overlap=overlap,
    )


@dataclass
class _ParagraphInfo:
    """Information about a paragraph's position in the source content.

    Attributes:
        text: The paragraph text content.
        start_offset: Character offset where paragraph starts in source.
        end_offset: Character offset where paragraph ends in source (exclusive).
    """

    text: str
    start_offset: int
    end_offset: int


def _save_paragraph_chunk(
    output_dir: Path,
    chunks: list[ChunkMetadata],
    chunk_paras: list[_ParagraphInfo],
    content: str,
    source_document_id: str,
) -> None:
    """Save a paragraph chunk to disk and append its metadata to chunks list.

    Encapsulates the repeated logic of joining paragraphs, computing line numbers,
    creating metadata, and writing the chunk file.

    Args:
        output_dir: Directory to write chunk file to.
        chunks: List to append the new chunk metadata to (modified in place).
        chunk_paras: List of paragraph info objects to include in the chunk.
        content: Full source content (used for line number calculation).
        source_document_id: Identifier for the source document.
    """
    chunk_text = "\n\n".join(p.text for p in chunk_paras)
    chunk_id = f"chunk_{len(chunks) + 1:03d}"

    start_offset = chunk_paras[0].start_offset
    end_offset = chunk_paras[-1].end_offset
    start_line = _get_line_number_at_offset(content, start_offset)
    end_line = _get_line_number_at_offset(content, end_offset - 1)

    metadata = ChunkMetadata(
        id=chunk_id,
        file=f"{chunk_id}.md",
        start_line=start_line,
        end_line=end_line,
        char_count=len(chunk_text),
        sequence_number=len(chunks),
        source_document_id=source_document_id,
    )
    chunks.append(metadata)
    _write_chunk_file(output_dir, chunk_id, chunk_text)


def _find_paragraphs_with_offsets(content: str) -> list[_ParagraphInfo]:
    """Find paragraphs and their exact positions in the source content.

    Uses regex to locate paragraph separators (variable-length whitespace between
    newlines) and computes accurate start/end offsets for each paragraph.

    Args:
        content: Full text content to parse.

    Returns:
        List of _ParagraphInfo with text and accurate offsets for each paragraph.
    """
    paragraphs: list[_ParagraphInfo] = []
    separator_pattern = re.compile(r"\n\s*\n")

    current_pos = 0
    for match in separator_pattern.finditer(content):
        sep_start = match.start()
        sep_end = match.end()

        # Extract paragraph text from current_pos to separator start
        para_text = content[current_pos:sep_start]
        if para_text:  # Only add non-empty paragraphs
            paragraphs.append(
                _ParagraphInfo(
                    text=para_text,
                    start_offset=current_pos,
                    end_offset=sep_start,
                )
            )

        # Move past the separator
        current_pos = sep_end

    # Add final paragraph (after last separator or entire content if no separators)
    if current_pos < len(content):
        para_text = content[current_pos:]
        if para_text:
            paragraphs.append(
                _ParagraphInfo(
                    text=para_text,
                    start_offset=current_pos,
                    end_offset=len(content),
                )
            )

    return paragraphs


def _chunk_by_paragraphs(
    content: str,
    output_dir: Path,
    source_file: str,
    min_size: int = 500,
) -> ChunkManifest:
    """Split content by paragraph boundaries.

    Combines small paragraphs until min_size is reached.
    Never splits within a paragraph.

    Chunk Size Behavior:
        Chunks are targeted to reach at least min_size characters. However, if
        adding the next paragraph would cause a chunk to exceed min_size * 3
        (the implicit maximum chunk size), the current chunk is saved and a new
        chunk is started. This hard cap prevents excessively large chunks when
        paragraphs vary significantly in size, ensuring chunks remain within a
        reasonable size range for downstream processing.

    Args:
        content: Full text content to chunk.
        output_dir: Directory to write chunks to.
        source_file: Path to source file for manifest.
        min_size: Minimum size for each chunk in characters. The implicit
            maximum chunk size is min_size * 3.

    Returns:
        ChunkManifest with metadata for all created chunks.
    """
    # Find paragraphs with their exact offsets in the source
    paragraph_infos = _find_paragraphs_with_offsets(content)

    chunks: list[ChunkMetadata] = []
    current_chunk_paras: list[_ParagraphInfo] = []
    current_size = 0
    source_document_id = _get_source_document_id(source_file)

    # Separator length is 2 characters for "\n\n"
    separator_len = 2

    for para_info in paragraph_infos:
        para_size = len(para_info.text)
        # Account for separator when adding to non-empty chunk
        size_to_add = para_size + (separator_len if current_chunk_paras else 0)

        # Chunking priority: (1) enforce hard cap at min_size*3 to avoid oversized chunks,
        # (2) flush when current chunk reaches min_size, (3) otherwise accumulate paragraphs.
        if current_chunk_paras and current_size + size_to_add > min_size * 3:
            _save_paragraph_chunk(
                output_dir, chunks, current_chunk_paras, content, source_document_id
            )
            current_chunk_paras = [para_info]
            current_size = para_size
        elif current_size >= min_size:
            # Current chunk meets min_size, save and start new chunk
            _save_paragraph_chunk(
                output_dir, chunks, current_chunk_paras, content, source_document_id
            )
            current_chunk_paras = [para_info]
            current_size = para_size
        else:
            # Add paragraph to current chunk
            current_chunk_paras.append(para_info)
            current_size += size_to_add

    # Save final chunk if any paragraphs remain
    if current_chunk_paras:
        _save_paragraph_chunk(output_dir, chunks, current_chunk_paras, content, source_document_id)

    # Link adjacent chunks
    _link_adjacent_chunks(chunks)

    return ChunkManifest(
        source_file=source_file,
        mode="paragraphs",
        total_chunks=len(chunks),
        chunks=chunks,
        min_size=min_size,
    )


def chunk_file(
    input_file: Path,
    output_dir: Path,
    mode: ChunkMode,
    chunk_size: int = 2000,
    min_size: int = 500,
    overlap: int = 100,
) -> ChunkManifest:
    """Chunk a file using specified mode.

    Reads the input file and splits it into chunks based on the specified mode.
    Writes chunk files (chunk_001.md, chunk_002.md, ...) to output_dir as a side effect.

    Args:
        input_file: Path to input file to chunk.
        output_dir: Directory to write chunk files to.
        mode: Chunking mode (headers, fixed, paragraphs).
        chunk_size: For fixed mode, target chunk size in characters.
        min_size: For paragraphs mode, minimum chunk size in characters.
        overlap: For fixed mode, number of characters to overlap between chunks
            (default: 100). Must be less than chunk_size.

    Returns:
        ChunkManifest describing the chunking operation.

    Raises:
        FileNotFoundError: If input file does not exist.
        ValueError: If mode is invalid, if chunk_size/min_size/overlap is not a
            positive integer, or if overlap >= chunk_size in fixed mode.
    """
    if not input_file.exists():
        msg = f"Input file not found: {input_file}"
        raise FileNotFoundError(msg)

    # Validate numeric parameters based on mode
    if mode == "fixed":
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            msg = "chunk_size must be a positive integer"
            raise ValueError(msg)
        if not isinstance(overlap, int) or overlap < 0:
            msg = "overlap must be a non-negative integer"
            raise ValueError(msg)
        if overlap >= chunk_size:
            msg = f"overlap ({overlap}) must be less than chunk_size ({chunk_size})"
            raise ValueError(msg)
    elif mode == "paragraphs":
        if not isinstance(min_size, int) or min_size <= 0:
            msg = "min_size must be a positive integer"
            raise ValueError(msg)

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read input file
    content = _read_file_utf8(input_file)
    source_file = str(input_file)

    # Chunk based on mode
    if mode == "headers":
        return _chunk_by_headers(content, output_dir, source_file)
    elif mode == "fixed":
        return _chunk_by_fixed_size(content, output_dir, source_file, chunk_size, overlap)
    elif mode == "paragraphs":
        return _chunk_by_paragraphs(content, output_dir, source_file, min_size)
    else:
        msg = f"Invalid chunking mode: {mode}"
        raise ValueError(msg)


def main() -> int:
    """Main entry point for CLI.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    parser = argparse.ArgumentParser(
        description="Split PRD input into logical chunks for processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split by markdown headers
  python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks --mode headers

  # Split by fixed size
  python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks \\
      --mode fixed --chunk-size 2000

  # Split by paragraph boundaries
  python -m scripts.prd.chunker input.md --output-dir .tmp/prd/chunks \\
      --mode paragraphs --min-size 500
""",
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="Input file to chunk (markdown or text)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for chunk files and manifest",
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["headers", "fixed", "paragraphs"],
        required=True,
        help="Chunking mode: headers, fixed, or paragraphs",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2000,
        help="Target chunk size in characters (for fixed mode, default: 2000)",
    )

    parser.add_argument(
        "--min-size",
        type=int,
        default=500,
        help="Minimum chunk size in characters (for paragraphs mode, default: 500)",
    )

    parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Overlap size in characters (for fixed mode, default: 100)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output including full tracebacks on error",
    )

    args = parser.parse_args()

    # Check for debug mode via flag or environment variable
    debug_mode = args.verbose or os.environ.get("CHUNKER_DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )

    try:
        # Perform chunking
        manifest = chunk_file(
            input_file=args.input_file,
            output_dir=args.output_dir,
            mode=args.mode,
            chunk_size=args.chunk_size,
            min_size=args.min_size,
            overlap=args.overlap,
        )

        # Write manifest
        _write_manifest(args.output_dir, manifest)

        # Print summary
        print(f"Chunking complete: {manifest.total_chunks} chunks created")
        print(f"Output directory: {args.output_dir}")
        print(f"Mode: {manifest.mode}")

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Emit structured error for programmatic consumers
        error_info = {
            "type": type(e).__name__,
            "message": str(e),
        }
        print(json.dumps(error_info), file=sys.stderr)
        # Print full traceback only in verbose/debug mode
        if debug_mode:
            traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
