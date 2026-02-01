"""Base classes for the strategy framework.

Strategies are the reasoning layer above tools. A tool does one thing
(e.g., split sentences). A strategy knows WHEN and WHY to use that tool,
and what risk it mitigates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from spec_manager.core.provenance import LineageTable, TrackedUnit


class StrategyPhase(Enum):
    """Phases where strategies can be applied.

    Note: These are strategy execution phases, distinct from workflow phases
    (CLEANING, DISCOVERY, REVIEW, FINALIZATION) defined in workspace.state.Phase.
    """

    CLEANING = "cleaning"  # Input normalization
    COMPOSITING = "compositing"  # Merge + remainder partition
    DECOMPOSITION = "decomposition"  # Breaking content into atoms
    EXTRACTION = "extraction"  # Pulling structured content
    RESOLUTION = "resolution"  # Resolving ambiguities
    LABELING = "labeling"  # Assigning to libraries
    VERIFICATION = "verification"  # Strategy verification, not workflow phase


@dataclass
class ProcessingContext:
    """Context passed to strategies.

    Contains everything a strategy needs to decide if it applies
    and to execute.
    """

    # Content being processed
    units: list[TrackedUnit]

    # Current phase
    phase: StrategyPhase

    # Source information
    source_file: str | None = None
    patch_id: str | None = None

    # Available reference content (for entity resolution)
    reference_files: dict[str, str] = field(default_factory=dict)

    # Results from previous strategies
    previous_results: dict[str, Any] = field(default_factory=dict)

    # Configuration
    config: dict[str, Any] = field(default_factory=dict)

    # Accumulated results during processing
    results: dict[str, Any] = field(default_factory=dict)

    # Compliance and evidence summaries for strategy gating
    compliance_summary: dict[str, Any] = field(default_factory=dict)
    evidence_summary: dict[str, float] = field(default_factory=dict)

    # Optional lineage tracking for derived units
    lineage_table: LineageTable | None = None


@dataclass
class StrategyResult:
    """Result of executing a strategy."""

    # Transformed units (may be more or fewer than input)
    units: list[TrackedUnit]

    # What the strategy did
    actions_taken: list[str]

    # Any issues found
    issues: list[str]

    # Metrics
    metrics: dict[str, Any] = field(default_factory=dict)

    # Whether strategy recommends re-running (iterative strategies)
    should_repeat: bool = False


class Strategy(ABC):
    """Base class for all strategies.

    A strategy encapsulates:
    - Knowledge of WHEN to apply (applies_to)
    - Knowledge of WHAT risk it mitigates (risk_addressed)
    - Implementation of HOW to execute (execute)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this strategy."""
        pass

    @property
    @abstractmethod
    def purpose(self) -> str:
        """What problem this strategy solves."""
        pass

    @property
    @abstractmethod
    def risk_addressed(self) -> str:
        """What risk this strategy mitigates."""
        pass

    @property
    @abstractmethod
    def phases(self) -> list[StrategyPhase]:
        """Which phases this strategy applies to."""
        pass

    @abstractmethod
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if this strategy should be applied to the given context.

        Returns True if the strategy is relevant for this content/phase.
        """
        pass

    @abstractmethod
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute the strategy.

        Takes TrackedUnits, returns transformed TrackedUnits with
        provenance tracking intact.
        """
        pass


class Tool(Protocol):
    """Protocol for tools that strategies use.

    Tools handle dynamic inputs and outputs, so the signature accepts
    arbitrary arguments. Strategies are responsible for passing
    arguments correctly based on the tool's documented interface.
    """

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Execute the tool."""
        ...


@dataclass
class StrategyDefinition:
    """Definition of a strategy loaded from YAML.

    This allows strategies to be defined declaratively and
    bound to implementations at runtime.
    """

    name: str
    purpose: str
    risk_addressed: str
    version: str = "1.0"

    # When to apply
    phases: list[str] = field(default_factory=list)
    when_conditions: list[str] = field(default_factory=list)
    risk_category: str | None = None

    # Implementation
    tools_used: list[str] = field(default_factory=list)
    implementation_class: str | None = None

    # Example for documentation
    example_input: str | None = None
    example_output: str | None = None

    # Metadata for runtime strategy management
    # Used by: capture_strategy_gap, propose_strategy_via_llm, promote_experimental
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize definition to dict for YAML persistence."""
        data: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "risk_addressed": self.risk_addressed,
            "phases": self.phases,
            "when_conditions": self.when_conditions,
            "tools_used": self.tools_used,
            "implementation_class": self.implementation_class,
        }
        if self.risk_category:
            data["risk_category"] = self.risk_category
        return data

    def to_strategy(self, tools: dict[str, Tool]) -> Strategy:
        """Convert definition to executable Strategy.

        The implementation_class is dynamically loaded and
        instantiated with the required tools.
        """
        if not self.implementation_class:
            raise ValueError(f"Strategy {self.name} has no implementation_class")

        # Dynamic import
        module_path, class_name = self.implementation_class.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        strategy_class = getattr(module, class_name)

        # Get required tools
        strategy_tools = {name: tools[name] for name in self.tools_used if name in tools}

        return strategy_class(definition=self, tools=strategy_tools)
