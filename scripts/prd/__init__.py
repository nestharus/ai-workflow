"""PRD processing utilities.

This package contains tools for processing Product Requirements Documents (PRDs),
including chunking, parsing, classification, and element extraction workflows.
"""

from scripts.prd.chunker import (
    ChunkManifest,
    ChunkMetadata,
    ChunkMode,
    chunk_file,
)
from scripts.prd.classifier import (
    ClassificationResult,
    InputType,
    classify_by_heuristics,
    classify_input,
)

__all__ = [
    "ChunkManifest",
    "ChunkMetadata",
    "ChunkMode",
    "ClassificationResult",
    "InputType",
    "chunk_file",
    "classify_by_heuristics",
    "classify_input",
]
