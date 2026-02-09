"""Analysis operations for spec management.

Goal: Detect patterns that suggest library restructuring.

Operations:
- detect_divergence: Find libraries that should be split
- detect_convergence: Find libraries that should be merged
- analyze_references: Analyze cross-library reference patterns
- suggest_restructuring: Generate restructuring recommendations
- run_adjacency_analysis: Detect algorithmic adjacency via graph analysis

Projection analysis (algorithmic-to-architectural mapping):
- generate_analysis_file: Compute the full analysis artifact on demand
- read_analysis_json / write_analysis_json: Persist and reload artifacts
"""

from spec_manager.analysis.adjacency.detector import AdjacencyReport
from spec_manager.analysis.adjacency.runner import run_adjacency_analysis
from spec_manager.analysis.generator import (
    generate_analysis_file,
    read_analysis_json,
    write_analysis_json,
)
from spec_manager.analysis.operations import (
    analyze_references,
    detect_convergence,
    detect_divergence,
    run_analysis,
    suggest_restructuring,
)

__all__ = [
    "AdjacencyReport",
    "analyze_references",
    "detect_convergence",
    "detect_divergence",
    "generate_analysis_file",
    "read_analysis_json",
    "run_adjacency_analysis",
    "run_analysis",
    "suggest_restructuring",
    "write_analysis_json",
]
