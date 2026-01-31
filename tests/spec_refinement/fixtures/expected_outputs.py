from __future__ import annotations

EXPECTED_PHASE_OUTPUTS = {
    "summarization": {
        "required_keys": {"summaries_count", "files_processed"},
    },
    "library_synthesis": {
        "required_keys": {"libraries_count", "overlap_resolutions"},
    },
    "evidence_expansion": {
        "required_keys": {"libraries_expanded", "evidence_sources_added"},
    },
    "spec_building": {
        "required_keys": {
            "libraries_built",
            "total_iterations",
            "converged_count",
            "total_patches_applied",
            "total_coverage_ratio",
            "coverage_metrics",
        },
    },
    "sublibrary_detection": {
        "required_keys": {"sublibraries_created"},
    },
    "architecture_proposal": {
        "required_keys": {"candidates_count"},
    },
    "architecture_selection": {
        "required_keys": {"selected_arch_id"},
    },
    "architecture_mapping": {
        "required_keys": {"libraries_mapped", "components_count"},
    },
}

EXPECTED_GAP_CONVERGENCE_RATIO = 0.8

EXPECTED_COVERAGE_METRICS = {
    "min_library_convergence_ratio": 0.8,
    "min_total_convergence_ratio": 0.8,
}

EXPECTED_PERFORMANCE_BOUNDS = {
    "total_seconds": 60.0,
    "phase_seconds": {
        "summarization": 10.0,
        "library_synthesis": 15.0,
        "evidence_expansion": 15.0,
        "spec_building": 20.0,
        "sublibrary_detection": 10.0,
        "architecture": 10.0,
    },
}
