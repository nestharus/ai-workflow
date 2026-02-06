"""Spec refinement workflows across all phases."""

from .architecture import (
    map_libraries_to_architecture,
    propose_architectures,
    select_architecture,
)
from .atom_emitter import (
    AtomEmissionResult,
    emit_atoms,
    emit_atoms_with_evidence,
)
from .evidence_builder import (
    build_evidence_graph,
    build_evidence_ranges_from_spans,
    create_unknown_span_for_uncovered,
)
from .evidence_expansion import expand_evidence, spotcheck_evidence
from .library_labeling import (
    CharterResults,
    aggregate_labels,
    detect_overlaps,
    generate_all_charters,
    generate_library_charter,
    label_all_files,
    label_file_to_libraries,
    refine_library_labels,
    resolve_all_overlaps,
)
from .library_structure_review import review_library_structure
from .library_synthesis import synthesize_libraries
from .phase_01_sectionization import sectionize_all
from .spec_building import build_specs
from .spec_patches import (
    CITATION_REQUIRED_SECTIONS,
    LEGACY_SECTION_MAP,
    VALID_SPEC_SECTIONS,
    PatchOperation,
    SpecDocument,
    SpecPatchSet,
    apply_patch,
    parse_patch_json,
    render_spec,
    validate_patch_citations,
    validate_patch_operation,
)
from .spec_stabilization import stabilize_specs
from .sublibrary_detection import detect_sublibraries
from .summarization import summarize_all

__all__ = [
    "CITATION_REQUIRED_SECTIONS",
    "LEGACY_SECTION_MAP",
    "VALID_SPEC_SECTIONS",
    "AtomEmissionResult",
    "CharterResults",
    "PatchOperation",
    "SpecDocument",
    "SpecPatchSet",
    "aggregate_labels",
    "apply_patch",
    "build_evidence_graph",
    "build_evidence_ranges_from_spans",
    "build_specs",
    "create_unknown_span_for_uncovered",
    "detect_overlaps",
    "detect_sublibraries",
    "emit_atoms",
    "emit_atoms_with_evidence",
    "expand_evidence",
    "generate_all_charters",
    "generate_library_charter",
    "label_all_files",
    "label_file_to_libraries",
    "map_libraries_to_architecture",
    "parse_patch_json",
    "propose_architectures",
    "refine_library_labels",
    "render_spec",
    "resolve_all_overlaps",
    "review_library_structure",
    "sectionize_all",
    "select_architecture",
    "spotcheck_evidence",
    "stabilize_specs",
    "summarize_all",
    "synthesize_libraries",
    "validate_patch_citations",
    "validate_patch_operation",
]
