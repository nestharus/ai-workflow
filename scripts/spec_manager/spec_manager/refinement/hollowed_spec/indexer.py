"""Build and manage the evidence index over hollowed-out specs.

Re-exports from core.evidence_index for backwards compatibility within refinement.
"""

from spec_manager.core.evidence_index import EvidenceIndex as EvidenceIndex
from spec_manager.core.evidence_index import (
    build_evidence_index as build_evidence_index,
)
