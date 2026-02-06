"""Ground truth definitions for spec evaluation.

Ground truth defines expected outputs per phase that can be compared against
actual refinement outputs to compute precision, recall, and F1 scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PhaseGroundTruth:
    """Expected outputs for a single phase.

    Attributes:
        expected_sections: List of section labels expected to be detected.
        expected_libraries: List of library names/IDs expected to be synthesized.
        expected_requirements: List of requirement descriptions expected to be extracted.
        expected_citations: List of citation patterns expected to be generated.
        expected_elements: List of element IDs expected to be created.
        expected_decisions: List of decision descriptions expected.
        expected_tasks: List of task descriptions expected.
        custom_expectations: Additional phase-specific expectations.
    """

    expected_sections: list[str] = field(default_factory=list)
    expected_libraries: list[str] = field(default_factory=list)
    expected_requirements: list[str] = field(default_factory=list)
    expected_citations: list[str] = field(default_factory=list)
    expected_elements: list[str] = field(default_factory=list)
    expected_decisions: list[str] = field(default_factory=list)
    expected_tasks: list[str] = field(default_factory=list)
    custom_expectations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "expected_sections": self.expected_sections,
            "expected_libraries": self.expected_libraries,
            "expected_requirements": self.expected_requirements,
            "expected_citations": self.expected_citations,
            "expected_elements": self.expected_elements,
            "expected_decisions": self.expected_decisions,
            "expected_tasks": self.expected_tasks,
            "custom_expectations": self.custom_expectations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseGroundTruth:
        """Deserialize from dictionary."""
        return cls(
            expected_sections=data.get("expected_sections", []),
            expected_libraries=data.get("expected_libraries", []),
            expected_requirements=data.get("expected_requirements", []),
            expected_citations=data.get("expected_citations", []),
            expected_elements=data.get("expected_elements", []),
            expected_decisions=data.get("expected_decisions", []),
            expected_tasks=data.get("expected_tasks", []),
            custom_expectations=data.get("custom_expectations", {}),
        )

    def get_all_expected_items(self, item_type: str) -> list[str]:
        """Get expected items of a specific type."""
        mapping = {
            "sections": self.expected_sections,
            "libraries": self.expected_libraries,
            "requirements": self.expected_requirements,
            "citations": self.expected_citations,
            "elements": self.expected_elements,
            "decisions": self.expected_decisions,
            "tasks": self.expected_tasks,
        }
        return mapping.get(item_type, [])


@dataclass
class GroundTruth:
    """Complete ground truth for a spec across all phases.

    Attributes:
        sectionization: Expected outputs for sectionization phase.
        summarization: Expected outputs for summarization phase.
        library_synthesis: Expected outputs for library synthesis phase.
        evidence_expansion: Expected outputs for evidence expansion phase.
        spec_building: Expected outputs for spec building phase.
        architecture: Expected outputs for architecture phases.
        interfaces: Expected outputs for interface phase.
        tasks: Expected outputs for task phase.
        overall_requirements_count: Total unique requirements expected across all phases.
        overall_elements_count: Total unique elements expected.
        convergence_iterations_max: Maximum iterations expected before convergence.
    """

    sectionization: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    summarization: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    library_synthesis: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    evidence_expansion: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    spec_building: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    architecture: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    interfaces: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    tasks: PhaseGroundTruth = field(default_factory=PhaseGroundTruth)
    overall_requirements_count: int = 0
    overall_elements_count: int = 0
    convergence_iterations_max: int = 10

    def get_phase_ground_truth(self, phase_name: str) -> PhaseGroundTruth | None:
        """Get ground truth for a specific phase."""
        mapping = {
            "sectionization": self.sectionization,
            "summarization": self.summarization,
            "library_synthesis": self.library_synthesis,
            "evidence_expansion": self.evidence_expansion,
            "spec_building": self.spec_building,
            "architecture": self.architecture,
            "interfaces": self.interfaces,
            "tasks": self.tasks,
        }
        return mapping.get(phase_name)

    def get_all_expected_requirements(self) -> list[str]:
        """Collect all expected requirements across phases."""
        requirements: set[str] = set()
        for phase in [
            self.sectionization,
            self.summarization,
            self.library_synthesis,
            self.evidence_expansion,
            self.spec_building,
        ]:
            requirements.update(phase.expected_requirements)
        return sorted(requirements)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "sectionization": self.sectionization.to_dict(),
            "summarization": self.summarization.to_dict(),
            "library_synthesis": self.library_synthesis.to_dict(),
            "evidence_expansion": self.evidence_expansion.to_dict(),
            "spec_building": self.spec_building.to_dict(),
            "architecture": self.architecture.to_dict(),
            "interfaces": self.interfaces.to_dict(),
            "tasks": self.tasks.to_dict(),
            "overall_requirements_count": self.overall_requirements_count,
            "overall_elements_count": self.overall_elements_count,
            "convergence_iterations_max": self.convergence_iterations_max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundTruth:
        """Deserialize from dictionary."""
        return cls(
            sectionization=PhaseGroundTruth.from_dict(data.get("sectionization", {})),
            summarization=PhaseGroundTruth.from_dict(data.get("summarization", {})),
            library_synthesis=PhaseGroundTruth.from_dict(data.get("library_synthesis", {})),
            evidence_expansion=PhaseGroundTruth.from_dict(data.get("evidence_expansion", {})),
            spec_building=PhaseGroundTruth.from_dict(data.get("spec_building", {})),
            architecture=PhaseGroundTruth.from_dict(data.get("architecture", {})),
            interfaces=PhaseGroundTruth.from_dict(data.get("interfaces", {})),
            tasks=PhaseGroundTruth.from_dict(data.get("tasks", {})),
            overall_requirements_count=data.get("overall_requirements_count", 0),
            overall_elements_count=data.get("overall_elements_count", 0),
            convergence_iterations_max=data.get("convergence_iterations_max", 10),
        )
