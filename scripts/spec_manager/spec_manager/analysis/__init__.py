"""Analysis operations for spec management.

Goal: Detect patterns that suggest library restructuring.

Operations:
- detect_divergence: Find libraries that should be split
- detect_convergence: Find libraries that should be merged
- analyze_references: Analyze cross-library reference patterns
- suggest_restructuring: Generate restructuring recommendations
"""

from spec_manager.analysis.operations import (
    analyze_references,
    detect_convergence,
    detect_divergence,
    run_analysis,
    suggest_restructuring,
)

__all__ = [
    "analyze_references",
    "detect_convergence",
    "detect_divergence",
    "run_analysis",
    "suggest_restructuring",
]
