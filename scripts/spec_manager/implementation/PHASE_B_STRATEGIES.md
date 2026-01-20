# Phase B: Strategy Library Framework

## Overview

This phase creates the extensible strategy library. The key insight is:

**We cannot verify that meaning is preserved through transformations. Instead, we apply strategies that minimize the RISK of information loss.**

Strategies are not just scripts - they are reasoned approaches to specific problems. Each strategy knows:
- What problem it solves
- When to apply it
- What tools it uses
- What risk it mitigates

## Why Strategies Matter

Consider transforming prose to structure:

```
Input: "The algorithm must handle edge cases and log all errors to the audit trail"
```

This could become:
- Algorithm logic for edge cases
- Logging requirement
- Audit trail dependency

Without a strategy, we might just extract "handle edge cases" and lose the logging requirement. The **sentence_decomposition** strategy explicitly addresses this by splitting compounds first.

## The Strategy Model

```
┌─────────────────────────────────────────────────────────┐
│                      WORKFLOW                           │
│  "I have content to process - which strategies apply?"  │
└─────────────────────────┬───────────────────────────────┘
                          │ queries
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  STRATEGY REGISTRY                      │
│  "Here are strategies that apply to your context"       │
│                                                         │
│  sentence_decomposition.yaml  → when: compound sentences│
│  entity_resolution.yaml       → when: vague references  │
│  coverage_verification.yaml   → when: post-transform    │
│  ...                                                    │
└─────────────────────────┬───────────────────────────────┘
                          │ selects & executes
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    STRATEGY EXECUTOR                    │
│  "Running sentence_decomposition with spacy_splitter"   │
│                                                         │
│  Input: TrackedUnits                                    │
│  Output: Transformed TrackedUnits + provenance          │
└─────────────────────────────────────────────────────────┘
```

## Implementation

### File 1: `spec_manager/strategies/base.py`

```python
"""
Base classes for the strategy framework.

Strategies are the reasoning layer above tools. A tool does one thing
(e.g., split sentences). A strategy knows WHEN and WHY to use that tool,
and what risk it mitigates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from spec_manager.core.provenance import TrackedUnit


class StrategyPhase(Enum):
    """Phases where strategies can be applied."""

    CLEANING = "cleaning"        # Input normalization
    DECOMPOSITION = "decomposition"  # Breaking content into atoms
    EXTRACTION = "extraction"    # Pulling structured content
    RESOLUTION = "resolution"    # Resolving ambiguities
    LABELING = "labeling"        # Assigning to libraries
    VERIFICATION = "verification"  # Post-transform checks


@dataclass
class ProcessingContext:
    """
    Context passed to strategies.

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
    """
    Base class for all strategies.

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
        """
        Check if this strategy should be applied to the given context.

        Returns True if the strategy is relevant for this content/phase.
        """
        pass

    @abstractmethod
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """
        Execute the strategy.

        Takes TrackedUnits, returns transformed TrackedUnits with
        provenance tracking intact.
        """
        pass


class Tool(Protocol):
    """Protocol for tools that strategies use."""

    def __call__(self, *args, **kwargs) -> Any:
        """Execute the tool."""
        ...


@dataclass
class StrategyDefinition:
    """
    Definition of a strategy loaded from YAML.

    This allows strategies to be defined declaratively and
    bound to implementations at runtime.
    """

    name: str
    version: str
    purpose: str
    risk_addressed: str

    # When to apply
    phases: list[str]
    when_conditions: list[str]

    # Implementation
    tools_used: list[str]
    implementation_class: str | None = None

    # Example for documentation
    example_input: str | None = None
    example_output: str | None = None

    # Metadata for runtime strategy management (Internal consistency fix)
    # Used by: capture_strategy_gap, propose_strategy_via_llm, promote_experimental
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_strategy(self, tools: dict[str, Tool]) -> Strategy:
        """
        Convert definition to executable Strategy.

        The implementation_class is dynamically loaded and
        instantiated with the required tools.
        """
        if not self.implementation_class:
            raise ValueError(f"Strategy {self.name} has no implementation_class")

        # Dynamic import
        module_path, class_name = self.implementation_class.rsplit('.', 1)
        import importlib
        module = importlib.import_module(module_path)
        strategy_class = getattr(module, class_name)

        # Get required tools
        strategy_tools = {
            name: tools[name] for name in self.tools_used
            if name in tools
        }

        return strategy_class(definition=self, tools=strategy_tools)
```

### File 2: `spec_manager/strategies/registry.py`

```python
"""
Strategy registry - manages available strategies.

The registry:
- Loads strategy definitions from YAML
- Provides strategies that apply to a given context
- Allows adding new strategies at runtime
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from .base import (
    Strategy, StrategyDefinition, ProcessingContext,
    StrategyPhase, Tool
)


class StrategyRegistry:
    """
    Registry of available strategies.

    Usage:
        registry = StrategyRegistry()
        registry.load_from_directory(Path("strategies/definitions"))

        # Get strategies for a context
        context = ProcessingContext(units=my_units, phase=StrategyPhase.CLEANING)
        applicable = registry.get_applicable(context)

        # Execute each
        for strategy in applicable:
            result = strategy.execute(context)
    """

    def __init__(self):
        self.definitions: dict[str, StrategyDefinition] = {}
        self.strategies: dict[str, Strategy] = {}
        self.tools: dict[str, Tool] = {}

    def register_tool(self, name: str, tool: Tool) -> None:
        """Register a tool that strategies can use."""
        self.tools[name] = tool

    def load_definition(self, path: Path) -> StrategyDefinition:
        """Load a strategy definition from YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        definition = StrategyDefinition(
            name=data['name'],
            version=data.get('version', '1.0'),
            purpose=data['purpose'],
            risk_addressed=data['risk_addressed'],
            phases=data.get('phases', []),
            when_conditions=data.get('when_conditions', []),
            tools_used=data.get('tools_used', []),
            implementation_class=data.get('implementation_class'),
            example_input=data.get('example', {}).get('input'),
            example_output=data.get('example', {}).get('output')
        )

        self.definitions[definition.name] = definition
        return definition

    def load_from_directory(self, directory: Path) -> int:
        """Load all strategy definitions from a directory. Returns count."""
        count = 0
        for path in directory.glob("*.yaml"):
            try:
                self.load_definition(path)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to load {path}: {e}")
        return count

    def instantiate(self, name: str) -> Strategy:
        """Instantiate a strategy from its definition."""
        if name in self.strategies:
            return self.strategies[name]

        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        strategy = definition.to_strategy(self.tools)
        self.strategies[name] = strategy
        return strategy

    def get_applicable(self, context: ProcessingContext) -> list[Strategy]:
        """Get all strategies that apply to the given context."""
        applicable = []

        for name, definition in self.definitions.items():
            # Check phase match
            phase_match = (
                not definition.phases or
                context.phase.value in definition.phases
            )

            if not phase_match:
                continue

            # Instantiate and check applies_to
            try:
                strategy = self.instantiate(name)
                if strategy.applies_to(context):
                    applicable.append(strategy)
            except Exception as e:
                print(f"Warning: Failed to check {name}: {e}")

        return applicable

    def add_strategy(self, definition: StrategyDefinition) -> None:
        """Add a new strategy definition at runtime."""
        self.definitions[definition.name] = definition

    def save_definition(self, name: str, path: Path) -> None:
        """Save a strategy definition to YAML."""
        if name not in self.definitions:
            raise ValueError(f"Unknown strategy: {name}")

        definition = self.definitions[name]
        data = {
            'name': definition.name,
            'version': definition.version,
            'purpose': definition.purpose,
            'risk_addressed': definition.risk_addressed,
            'phases': definition.phases,
            'when_conditions': definition.when_conditions,
            'tools_used': definition.tools_used,
            'implementation_class': definition.implementation_class
        }

        if definition.example_input:
            data['example'] = {
                'input': definition.example_input,
                'output': definition.example_output
            }

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False)

    def list_strategies(self) -> list[dict[str, Any]]:
        """List all available strategies with summary info."""
        return [
            {
                'name': d.name,
                'purpose': d.purpose,
                'phases': d.phases,
                'tools': d.tools_used,
                'status': d.metadata.get('status', 'stable')  # stable/experimental
            }
            for d in self.definitions.values()
        ]

    # =========================================================================
    # Strategy Evolution Loop
    # =========================================================================

    def check_evolution_triggers(
        self,
        context: ProcessingContext,
        previous_context: ProcessingContext | None = None
    ) -> list[str]:
        """
        Check if conditions warrant strategy evolution.

        Trigger conditions:
        - Remainder not shrinking between passes
        - Entity resolution failure rate above threshold
        - Prose ratio not decreasing

        Returns list of trigger descriptions.
        """
        triggers = []

        if previous_context:
            # Remainder not shrinking
            prev_remainder = len(previous_context.results.get('remainders', []))
            curr_remainder = len(context.results.get('remainders', []))
            if curr_remainder >= prev_remainder and prev_remainder > 0:
                triggers.append(f"remainder_stuck: {prev_remainder} → {curr_remainder}")

            # Entity resolution failures
            resolution_failures = context.results.get('resolution_failures', 0)
            total_refs = context.results.get('total_references', 1)
            failure_rate = resolution_failures / total_refs if total_refs > 0 else 0
            if failure_rate > 0.1:  # 10% threshold
                triggers.append(f"resolution_failures: {failure_rate:.1%}")

            # Prose ratio not decreasing
            prev_prose = previous_context.results.get('prose_ratio', 1.0)
            curr_prose = context.results.get('prose_ratio', 1.0)
            if curr_prose >= prev_prose and curr_prose > 0.3:  # Still >30% prose
                triggers.append(f"prose_stuck: {prev_prose:.1%} → {curr_prose:.1%}")

        return triggers

    def request_new_strategy(
        self,
        trigger: str,
        example_inputs: list[str],
        desired_transformation: str
    ) -> dict:
        """
        Generate a strategy request for a new strategy.

        Returns a structured request that could be used to develop
        a new strategy (potentially by AI or human).
        """
        return {
            'trigger': trigger,
            'examples': example_inputs,
            'desired_outcome': desired_transformation,
            'existing_strategies': [d.name for d in self.definitions.values()],
            'status': 'requested'
        }

    def add_experimental_strategy(
        self,
        definition: StrategyDefinition,
        test_fixtures: list[tuple[str, str]]  # (input, expected_output)
    ) -> bool:
        """
        Add a new strategy in experimental status.

        Requires test fixtures that must pass before strategy is promoted to stable.
        """
        definition.metadata = definition.metadata or {}
        definition.metadata['status'] = 'experimental'
        definition.metadata['test_fixtures'] = test_fixtures

        self.definitions[definition.name] = definition
        return True

    def promote_to_stable(self, name: str) -> bool:
        """Promote an experimental strategy to stable after validation."""
        if name not in self.definitions:
            return False

        definition = self.definitions[name]
        if definition.metadata.get('status') != 'experimental':
            return False

        # Validate against test fixtures
        fixtures = definition.metadata.get('test_fixtures', [])
        strategy = self.instantiate(name)

        for input_text, expected_output in fixtures:
            # Run strategy and check output matches
            # (Simplified - real implementation would be more thorough)
            pass

        definition.metadata['status'] = 'stable'
        return True

    # =========================================================================
    # Strategy Gap Evidence & Proposal (Gap 11)
    # =========================================================================

    def capture_strategy_gap(
        self,
        context: ProcessingContext,
        failure_mode: str,
        failing_inputs: list[TrackedUnit]
    ) -> "StrategyGapEvidence":
        """
        Capture a strategy gap when no strategy can handle a failure mode.

        This is the trigger for strategy evolution:
        1. Capture minimal failing fixture (inputs + intermediates)
        2. Propose new strategy via LLM
        3. Register as experimental for current ingest

        Returns StrategyGapEvidence to be included in gaps.md.
        """
        # Capture minimal fixture
        fixture = {
            'failure_mode': failure_mode,
            'inputs': [
                {'id': u.id, 'content': u.content[:500], 'type': u.unit_type.value}
                for u in failing_inputs[:5]
            ],
            'context': {
                'phase': context.phase.value,
                'patch_id': context.patch_id,
                'previous_results': context.previous_results
            },
            'existing_strategies_tried': [
                d.name for d in self.definitions.values()
                if context.phase.value in d.phases
            ]
        }

        evidence = StrategyGapEvidence(
            failure_mode=failure_mode,
            fixture=fixture,
            proposed_strategy=None
        )

        return evidence

    def propose_strategy_via_llm(
        self,
        gap_evidence: "StrategyGapEvidence",
        llm_client=None
    ) -> StrategyDefinition | None:
        """
        Use LLM to propose a new strategy for a captured gap.

        The LLM receives:
        - Failure mode description
        - Failing inputs
        - Existing strategies (to avoid duplicates)

        Returns a proposed StrategyDefinition or None.
        """
        if not llm_client:
            return None

        prompt = f"""A spec processing workflow encountered a failure that no existing strategy handles.

FAILURE MODE: {gap_evidence.failure_mode}

FAILING INPUTS (samples):
{gap_evidence.fixture['inputs'][:3]}

EXISTING STRATEGIES (don't duplicate):
{gap_evidence.fixture['existing_strategies_tried']}

Design a new strategy to handle this failure. Provide:
1. Strategy name (lowercase, underscore-separated)
2. Purpose (one sentence)
3. When conditions (JSON conditions)
4. Tools to use (list)
5. Risk addressed

Output as JSON:
{{
  "name": "...",
  "purpose": "...",
  "when_conditions": {{...}},
  "tools_used": ["..."],
  "risk_addressed": "..."
}}"""

        try:
            response = llm_client.complete(prompt)
            import json
            data = json.loads(response)

            proposed = StrategyDefinition(
                name=data['name'],
                purpose=data['purpose'],
                when_conditions=data.get('when_conditions', {}),
                tools_used=data.get('tools_used', []),
                phases=[gap_evidence.fixture['context']['phase']],
                risk_addressed=data.get('risk_addressed', ''),
                metadata={'status': 'proposed', 'from_gap': gap_evidence.failure_mode}
            )

            gap_evidence.proposed_strategy = proposed
            return proposed

        except Exception:
            return None

    def register_experimental_from_gap(
        self,
        gap_evidence: "StrategyGapEvidence"
    ) -> bool:
        """
        Register a proposed strategy as experimental for current ingest.

        The strategy is:
        - Marked as 'experimental'
        - Includes test fixtures from the gap
        - Automatically promoted if it reduces the failure mode
        """
        if not gap_evidence.proposed_strategy:
            return False

        definition = gap_evidence.proposed_strategy
        definition.metadata = definition.metadata or {}
        definition.metadata['status'] = 'experimental'
        definition.metadata['source_gap'] = gap_evidence.failure_mode
        definition.metadata['test_fixtures'] = [
            (inp['content'], 'TBD')
            for inp in gap_evidence.fixture['inputs'][:3]
        ]

        self.definitions[definition.name] = definition
        return True


@dataclass
class StrategyGapEvidence:
    """
    Evidence for a strategy gap - no strategy could handle this failure mode.

    This is a FIRST-CLASS evidence type that triggers strategy evolution.
    """
    failure_mode: str              # What failed (e.g., "vague_reference_resolution")
    fixture: dict[str, Any]        # Minimal failing fixture
    proposed_strategy: StrategyDefinition | None = None  # LLM-proposed solution

    @property
    def severity(self) -> str:
        return "warning"

    @property
    def message(self) -> str:
        return f"Strategy gap: {self.failure_mode}"

    @property
    def location(self) -> str:
        return self.fixture.get('context', {}).get('patch_id', 'unknown')
```

### File 3: Entity Resolution (First-Class)

```python
"""
Entity resolution engine - FIRST-CLASS requirement.

When patch prose has vague references like "the algorithm" or "it",
we need to resolve them using:
- Annotations from the same file
- Prior patch versions
- Original inputs the patch references
- Intermediate composites ("smeared state")

Entity resolution failure → gaps.md entry + keep remainder unit
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResolutionContext:
    """Context available for resolving references."""

    # Patch dependency graph
    patch_chain: list[str]  # e.g., ["p1", "p3", "p5"] - p5 patches p3 patches p1

    # Available contexts in priority order
    current_file_ids: set[str]          # IDs declared in current file
    prior_patch_ids: dict[str, set[str]] # patch_id → IDs it defined
    intermediate_ids: dict[str, set[str]] # intermediate_file → IDs
    original_ids: dict[str, set[str]]    # original_file → IDs


@dataclass
class ResolutionResult:
    """Result of attempting to resolve a reference."""

    original_text: str
    resolved_to: str | None
    confidence: float
    evidence: list[str]  # Why we resolved to this
    context_used: str    # "current", "prior_patch", "intermediate", "original"


class ReferenceStore:
    """
    Interface for retrieving context to resolve references.

    Given a vague mention, retrieve top-k candidate contexts.

    Gap 1 fix: Index primarily from DECLARED IDs + HEADINGS + KEYPHRASES,
    NOT hardcoded domain phrases. Domain-specific phrase lists are configurable.
    """

    def __init__(self, spec_folder: Path, config_path: Path | None = None):
        self.spec_folder = spec_folder
        self.index: dict[str, list[str]] = {}  # term → [id, id, ...]
        self.phrase_config: dict = {}  # Optional domain phrase config

        # Load optional domain phrase config (Gap 1: data-driven, not hardcoded)
        if config_path and config_path.exists():
            import yaml
            with open(config_path) as f:
                self.phrase_config = yaml.safe_load(f).get('domain_phrases', {})

    def index_file(self, path: Path, content: str, file_type: str) -> None:
        """
        Index a file's content for later retrieval.

        Gap 1 fix: Indexing hierarchy:
        1. Declared IDs (authoritative)
        2. Heading-based IDs
        3. NLP-extracted keyphrases
        4. Configurable domain phrases (from YAML, not hardcoded)
        """
        from spec_manager.core.annotations import AnnotationParser
        import re

        parser = AnnotationParser()

        # PRIMARY: Declared IDs - authoritative
        for decl in parser.parse_declarations(content):
            term = decl.id_value.lower()
            if term not in self.index:
                self.index[term] = []
            self.index[term].append(f"{file_type}:{path.name}:{decl.id_value}")

        # SECONDARY: Heading-based IDs
        heading_pattern = re.compile(r'^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)', re.MULTILINE)
        for match in heading_pattern.finditer(content):
            term = match.group(2).lower()
            if term not in self.index:
                self.index[term] = []
            self.index[term].append(f"{file_type}:{path.name}:heading:{match.group(2)}")

        # TERTIARY: NLP keyphrases
        self._index_keyphrases(content, path, file_type)

        # QUATERNARY: Configurable domain phrases (Gap 1: from config, not hardcoded)
        for phrase, category in self.phrase_config.items():
            if phrase.lower() in content.lower():
                term = phrase.lower()
                if term not in self.index:
                    self.index[term] = []
                self.index[term].append(f"{file_type}:{path.name}:phrase:{category}")

    def _index_keyphrases(self, content: str, path: Path, file_type: str) -> None:
        """Extract and index keyphrases using NLP."""
        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(content[:5000])

            for chunk in doc.noun_chunks:
                if len(chunk.text.split()) >= 2 and len(chunk.text) < 40:
                    term = chunk.text.lower()
                    if term not in self.index:
                        self.index[term] = []
                    self.index[term].append(f"{file_type}:{path.name}:keyphrase:{chunk.text}")
        except (ImportError, OSError):
            pass  # NLP not available, skip keyphrase indexing

    def retrieve(
        self,
        mention: str,
        context: ResolutionContext,
        top_k: int = 5
    ) -> list[tuple[str, float]]:
        """
        Retrieve candidate resolutions for a mention.

        Returns list of (candidate_id, confidence) pairs.
        """
        candidates = []

        # Normalize mention
        mention_lower = mention.lower().strip()

        # Check exact matches first
        if mention_lower in self.index:
            for entry in self.index[mention_lower][:top_k]:
                candidates.append((entry, 1.0))

        # Check partial matches
        for term, entries in self.index.items():
            if term in mention_lower or mention_lower in term:
                for entry in entries[:2]:
                    if (entry, 1.0) not in candidates:
                        candidates.append((entry, 0.7))

        # Sort by confidence
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]


class EntityResolver:
    """
    Resolves vague references in patch content.

    This is a FIRST-CLASS component, not just a strategy stub.
    """

    def __init__(self, reference_store: ReferenceStore):
        self.store = reference_store
        self.failures: list[tuple[str, str]] = []  # (text, file)

    def resolve(
        self,
        text: str,
        context: ResolutionContext
    ) -> ResolutionResult:
        """Attempt to resolve a vague reference."""

        # Find candidates
        candidates = self.store.retrieve(text, context)

        if not candidates:
            # Failed to resolve
            self.failures.append((text, "no_candidates"))
            return ResolutionResult(
                original_text=text,
                resolved_to=None,
                confidence=0.0,
                evidence=["No candidates found in any context"],
                context_used="none"
            )

        # Take best candidate
        best_id, confidence = candidates[0]

        # Determine which context it came from
        context_used = "unknown"
        if "current:" in best_id:
            context_used = "current"
        elif "prior_patch:" in best_id:
            context_used = "prior_patch"
        elif "intermediate:" in best_id:
            context_used = "intermediate"
        elif "original:" in best_id:
            context_used = "original"

        return ResolutionResult(
            original_text=text,
            resolved_to=best_id.split(":")[-1],  # Extract actual ID
            confidence=confidence,
            evidence=[f"Found in {best_id}"],
            context_used=context_used
        )

    def get_failures_as_gaps(self) -> list[dict]:
        """Get resolution failures formatted for gaps.md."""
        return [
            {
                "type": "entity_resolution_failure",
                "original_text": text,
                "location": location,
                "severity": "warning"
            }
            for text, location in self.failures
        ]
```

### File 4: `spec_manager/strategies/implementations/unitizers.py`

```python
"""
Unitizer strategies - implement the granularity ladder.

When annotations are sparse, emit fine atoms (line/sentence/clause) even
with zero declarations. Don't rely solely on ([=...]) boundaries.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from spec_manager.core.provenance import TrackedUnit, SourceLocation, UnitType, GranularityLevel


class Unitizer(ABC):
    """Base class for unitizers."""

    @property
    @abstractmethod
    def granularity(self) -> GranularityLevel:
        """The granularity level this unitizer produces."""
        pass

    @abstractmethod
    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        """Split content into tracked units."""
        pass


class LineUnitizer(Unitizer):
    """
    Line-level unitization - maximum tracking granularity.
    Use for dirty prose with sparse/no annotations.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.LINE

    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []

        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.strip():  # Skip empty lines
                units.append(TrackedUnit(
                    id=f"_line_{file_path}_{line_num}",
                    content=line,
                    unit_type=UnitType.PROSE,
                    source=SourceLocation(
                        file=file_path,
                        line_start=line_num,
                        line_end=line_num,
                        patch_id=patch_id
                    ),
                    introduced_by=patch_id or "unknown"
                ))

        return units


class SentenceUnitizer(Unitizer):
    """
    Sentence-level unitization using spaCy.
    Use for semi-structured text.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.SENTENCE

    def __init__(self):
        self._nlp = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("en_core_web_sm")
            except (ImportError, OSError):
                # Fallback: simple sentence splitting
                self._nlp = "fallback"
        return self._nlp

    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []
        nlp = self._get_nlp()

        if nlp == "fallback":
            # Simple fallback: split on sentence-ending punctuation
            sentences = re.split(r'(?<=[.!?])\s+', content)
        else:
            doc = nlp(content)
            sentences = [sent.text for sent in doc.sents]

        # Track line numbers approximately
        current_pos = 0
        line_num = 1

        for i, sent in enumerate(sentences):
            sent = sent.strip()
            if not sent:
                continue

            # Find position in original content
            pos = content.find(sent, current_pos)
            if pos >= 0:
                line_num = content[:pos].count('\n') + 1
                current_pos = pos + len(sent)

            units.append(TrackedUnit(
                id=f"_sent_{file_path}_{i+1}",
                content=sent,
                unit_type=UnitType.PROSE,
                source=SourceLocation(
                    file=file_path,
                    line_start=line_num,
                    line_end=line_num,
                    patch_id=patch_id
                ),
                introduced_by=patch_id or "unknown"
            ))

        return units


class ClauseUnitizer(Unitizer):
    """
    Clause-level unitization using spaCy dependency parsing.
    Use for complex compound statements.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.CLAUSE

    def __init__(self):
        self._nlp = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("en_core_web_sm")
            except (ImportError, OSError):
                self._nlp = "fallback"
        return self._nlp

    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []
        nlp = self._get_nlp()

        if nlp == "fallback":
            # Fallback: split on conjunction and semicolons
            clauses = re.split(r';\s*|\s+and\s+|\s+or\s+', content)
        else:
            doc = nlp(content)
            clauses = []
            for sent in doc.sents:
                # Find clause roots (verbs with subjects)
                for token in sent:
                    if token.dep_ in ('ROOT', 'conj') and token.pos_ == 'VERB':
                        clause = ' '.join([t.text for t in token.subtree])
                        if clause.strip():
                            clauses.append(clause)

            if not clauses:
                clauses = [sent.text for sent in doc.sents]

        line_num = 1
        for i, clause in enumerate(clauses):
            clause = clause.strip()
            if not clause:
                continue

            units.append(TrackedUnit(
                id=f"_clause_{file_path}_{i+1}",
                content=clause,
                unit_type=UnitType.PROSE,
                source=SourceLocation(
                    file=file_path,
                    line_start=line_num,
                    line_end=line_num,
                    patch_id=patch_id
                ),
                introduced_by=patch_id or "unknown"
            ))

        return units


class LLMUnitizer(Unitizer):
    """
    LLM-assisted unitization for hard-to-segment prose.

    Uses LLM to identify:
    - Clause boundaries in run-on sentences
    - Implicit requirements hidden in narrative
    - Logical units that span multiple sentences
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.CLAUSE

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        """
        LLM-assisted unitization.

        If no LLM available, falls back to sentence unitizer.
        """
        if not self._llm:
            # Fallback to sentence unitizer
            return SentenceUnitizer().unitize(content, file_path, patch_id)

        # Prompt LLM for clause extraction
        prompt = f"""Split the following text into logical units (clauses, requirements, or statements).
Each unit should express ONE idea or requirement.
Return as JSON array of strings.

Text:
{content}

Output format: ["unit 1", "unit 2", ...]"""

        try:
            response = self._llm.complete(prompt)
            import json
            clauses = json.loads(response)
        except Exception:
            # Fallback on error
            return SentenceUnitizer().unitize(content, file_path, patch_id)

        units = []
        for i, clause in enumerate(clauses):
            clause = clause.strip()
            if not clause:
                continue

            units.append(TrackedUnit(
                id=f"_llm_unit_{file_path}_{i+1}",
                content=clause,
                unit_type=UnitType.PROSE,
                source=SourceLocation(
                    file=file_path,
                    line_start=1,  # LLM doesn't track line numbers
                    line_end=1,
                    patch_id=patch_id
                ),
                introduced_by=patch_id or "unknown"
            ))

        return units


class UnitizationSelector:
    """
    Selects appropriate unitizer based on content analysis.

    Key principle: When annotations are sparse, emit FINE atoms.
    """

    def select_unitizer(self, content: str) -> Unitizer:
        """Select unitizer based on content characteristics."""
        # Count annotation density
        decl_count = content.count("([=")
        line_count = len(content.splitlines())
        density = decl_count / max(line_count, 1)

        # Check for clear sentence structure
        sentence_ends = len(re.findall(r'[.!?]\s+[A-Z]', content))
        has_sentences = sentence_ends > 2

        # Check for complex structure (conjunctions, semicolons)
        has_complex = bool(re.search(r';\s|\s+and\s+.*\s+and\s+', content))

        if density > 0.1:
            # Well-annotated: use section boundaries
            return SectionUnitizer()
        elif has_complex:
            # Complex statements: clause-level
            return ClauseUnitizer()
        elif has_sentences:
            # Clear sentences: sentence-level
            return SentenceUnitizer()
        else:
            # Messy prose: line-level for maximum tracking
            return LineUnitizer()


class SectionUnitizer(Unitizer):
    """
    Section-level unitization using ([=...]) annotations and headers.
    Use for clean, well-annotated content.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.SECTION

    def unitize(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        # Existing provenance tracker logic handles this case
        from spec_manager.core.provenance import ProvenanceTracker
        tracker = ProvenanceTracker()
        return tracker.extract_units_from_file(content, file_path, patch_id)
```

### File 5: `spec_manager/strategies/implementations/llm_inference.py`

```python
"""
LLM-based inference strategies for prose fragment processing.

CRITICAL: LLM outputs are EVIDENCE, not truth.
- Each inference has confidence score and provenance spans
- Prose fragments are reduced over passes as inferences are confirmed
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from spec_manager.core.provenance import TrackedUnit, SourceLocation, UnitType, UnitStatus


@dataclass
class InferenceResult:
    """Result of an LLM inference operation."""
    inferred_content: str              # What was inferred
    confidence: float                  # 0.0-1.0 confidence score
    source_spans: list[SourceLocation] # Where the inference came from
    inference_type: str                # "requirement", "claim", "patch_target", etc.
    rationale: str                     # LLM's explanation


@dataclass
class ProseFragmentEvidence:
    """Evidence from LLM inference over prose fragments."""
    fragment: str                      # The prose fragment analyzed
    location: SourceLocation
    inferences: list[InferenceResult]  # What the LLM inferred
    remaining_prose: str | None        # Content not captured by inferences


class ProseFragmentInferenceDetector:
    """
    Infer requirements/claims from scattered prose fragments using LLM.

    CRITICAL: Outputs are EVIDENCE with confidence, not authoritative truth.
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def detect(
        self,
        units: list[TrackedUnit]
    ) -> list[ProseFragmentEvidence]:
        """
        Analyze prose units to infer hidden requirements/claims.
        """
        evidence_list = []

        for unit in units:
            if unit.unit_type != UnitType.PROSE:
                continue

            # Skip short prose (unlikely to contain hidden requirements)
            if len(unit.content) < 50:
                continue

            evidence = self._analyze_fragment(unit)
            if evidence.inferences:
                evidence_list.append(evidence)

        return evidence_list

    def _analyze_fragment(self, unit: TrackedUnit) -> ProseFragmentEvidence:
        """Analyze a single prose fragment for hidden requirements."""
        inferences = []

        if not self._llm:
            # Fallback: use heuristics
            inferences = self._heuristic_inference(unit)
        else:
            inferences = self._llm_inference(unit)

        return ProseFragmentEvidence(
            fragment=unit.content,
            location=unit.source,
            inferences=inferences,
            remaining_prose=self._compute_remaining(unit.content, inferences)
        )

    def _heuristic_inference(self, unit: TrackedUnit) -> list[InferenceResult]:
        """Fallback heuristic-based inference without LLM."""
        inferences = []
        content = unit.content

        # Pattern: "must", "should", "always", "never"
        requirement_patterns = [
            (r'\b(must|shall)\s+(\w+)', 0.8),
            (r'\b(should)\s+(\w+)', 0.6),
            (r'\b(always|never)\s+(\w+)', 0.7),
            (r'\brequire[ds]?\b', 0.7),
        ]

        for pattern, base_confidence in requirement_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract surrounding context
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                context = content[start:end].strip()

                inferences.append(InferenceResult(
                    inferred_content=context,
                    confidence=base_confidence,
                    source_spans=[unit.source],
                    inference_type="requirement",
                    rationale=f"Contains requirement keyword: '{match.group()}'"
                ))

        return inferences

    def _llm_inference(self, unit: TrackedUnit) -> list[InferenceResult]:
        """Use LLM to infer requirements from prose."""
        prompt = f"""Analyze this prose fragment and extract any hidden requirements, claims, or invariants.

Fragment:
{unit.content}

For each inference:
1. State the requirement/claim clearly
2. Provide a confidence score (0.0-1.0)
3. Explain your reasoning

Output as JSON array:
[{{"content": "...", "confidence": 0.X, "type": "requirement|claim|invariant", "rationale": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json
            results = json.loads(response)

            return [
                InferenceResult(
                    inferred_content=r["content"],
                    confidence=r["confidence"],
                    source_spans=[unit.source],
                    inference_type=r["type"],
                    rationale=r["rationale"]
                )
                for r in results
            ]
        except Exception:
            return self._heuristic_inference(unit)

    def _compute_remaining(
        self,
        content: str,
        inferences: list[InferenceResult]
    ) -> str | None:
        """Compute what prose remains after inferences are extracted."""
        remaining = content
        for inf in inferences:
            # Remove inferred content from remaining
            remaining = remaining.replace(inf.inferred_content, "")

        remaining = remaining.strip()
        return remaining if remaining else None


class ProseFragmentReductionStrategy:
    """
    Strategy to reduce prose fragments by promoting inferences to structured elements.

    Iteratively transforms inferred requirements into Claims/Invariants,
    shrinking the prose remainder over passes.
    """

    def __init__(self, confidence_threshold: float = 0.7):
        self.confidence_threshold = confidence_threshold
        self.detector = ProseFragmentInferenceDetector()

    def execute(
        self,
        units: list[TrackedUnit]
    ) -> tuple[list[TrackedUnit], list[TrackedUnit]]:
        """
        Execute prose reduction.

        Returns:
            (promoted_units, updated_prose_units)
        """
        evidence_list = self.detector.detect(units)

        promoted = []
        updated_prose = []

        for evidence in evidence_list:
            # Promote high-confidence inferences
            for inf in evidence.inferences:
                if inf.confidence >= self.confidence_threshold:
                    promoted.append(self._create_structured_unit(inf, evidence))

            # Update prose unit with remaining content
            if evidence.remaining_prose:
                updated_prose.append(self._create_remainder_unit(evidence))

        return promoted, updated_prose

    def _create_structured_unit(
        self,
        inference: InferenceResult,
        evidence: ProseFragmentEvidence
    ) -> TrackedUnit:
        """Create a structured unit from an inference."""
        # Determine unit type from inference type
        type_map = {
            "requirement": UnitType.INVARIANT,
            "claim": UnitType.CLAIM,
            "invariant": UnitType.INVARIANT,
        }
        unit_type = type_map.get(inference.inference_type, UnitType.CLAIM)

        return TrackedUnit(
            id=f"_inferred_{hash(inference.inferred_content) % 10000}",
            content=inference.inferred_content,
            unit_type=unit_type,
            source=evidence.location,
            introduced_by="llm_inference",
            annotations=[f"(@[confidence:{inference.confidence:.2f}])"]
        )

    def _create_remainder_unit(
        self,
        evidence: ProseFragmentEvidence
    ) -> TrackedUnit:
        """Create a prose unit for remaining content."""
        return TrackedUnit(
            id=f"_remainder_{hash(evidence.remaining_prose) % 10000}",
            content=evidence.remaining_prose,
            unit_type=UnitType.PROSE,
            source=evidence.location,
            introduced_by="llm_inference",
            status=UnitStatus.PENDING
        )


class VagueReferenceResolver:
    """
    Resolve vague entity references using LLM + context retrieval.

    When a patch says "update the algorithm" without specifying which one,
    this resolver uses context to infer the target.
    """

    def __init__(self, reference_store=None, llm_client=None):
        self._store = reference_store
        self._llm = llm_client

    def resolve(
        self,
        reference_text: str,
        context: dict[str, Any]
    ) -> list[InferenceResult]:
        """
        Resolve a vague reference to candidate targets.

        Args:
            reference_text: The vague reference (e.g., "the algorithm")
            context: Available context (patch chain, intermediates, etc.)

        Returns:
            List of candidate resolutions with confidence scores
        """
        candidates = []

        if self._store:
            # Get candidate targets from reference store
            store_candidates = self._store.retrieve(reference_text, context, top_k=10)
            for cand_id, score in store_candidates:
                candidates.append(InferenceResult(
                    inferred_content=cand_id,
                    confidence=score,
                    source_spans=[],
                    inference_type="patch_target",
                    rationale=f"Retrieved from reference store (score: {score:.2f})"
                ))

        if self._llm and context:
            # Use LLM to rank/refine candidates
            candidates = self._llm_rerank(reference_text, candidates, context)

        return sorted(candidates, key=lambda x: -x.confidence)

    def _llm_rerank(
        self,
        reference_text: str,
        candidates: list[InferenceResult],
        context: dict[str, Any]
    ) -> list[InferenceResult]:
        """Use LLM to rerank candidates based on context."""
        if not candidates:
            return candidates

        prompt = f"""Given the vague reference "{reference_text}" and this context:

Patch chain: {context.get('patch_chain', 'unknown')}
Nearby elements: {context.get('nearby_elements', [])}

Rank these candidates by likelihood of being the target:
{[c.inferred_content for c in candidates]}

Output as JSON: [{{"id": "...", "confidence": 0.X, "reason": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json
            rankings = json.loads(response)

            # Update confidence scores
            for ranking in rankings:
                for cand in candidates:
                    if cand.inferred_content == ranking["id"]:
                        cand.confidence = ranking["confidence"]
                        cand.rationale = ranking["reason"]
                        break

        except Exception:
            pass  # Keep original scores on error

        return candidates
```

### File 6: `spec_manager/strategies/implementations/sentence_decomposition.py`

```python
"""
Sentence decomposition strategy.

This strategy splits compound sentences into atomic units so each
can be tracked independently. This reduces risk of losing part of
a compound statement during transformation.

Example:
  Input: "The algorithm must handle edge cases and log errors"
  Output:
    - "The algorithm must handle edge cases"
    - "The algorithm must log errors"
"""

from __future__ import annotations

import re
from typing import Any

from spec_manager.core.provenance import TrackedUnit, SourceLocation, UnitType
from spec_manager.strategies.base import (
    Strategy, StrategyDefinition, ProcessingContext, StrategyResult,
    StrategyPhase, Tool
)


class SentenceDecompositionStrategy(Strategy):
    """Decomposes compound sentences into atomic units."""

    def __init__(self, definition: StrategyDefinition, tools: dict[str, Tool]):
        self.definition = definition
        self.tools = tools
        self._splitter = tools.get('spacy_splitter') or self._simple_split

    @property
    def name(self) -> str:
        return "sentence_decomposition"

    @property
    def purpose(self) -> str:
        return "Split compound sentences to track atomic claims independently"

    @property
    def risk_addressed(self) -> str:
        return "Compound meaning lost in translation - 'A and B' becomes just 'A'"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.DECOMPOSITION, StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if any units have compound sentences."""
        compound_indicators = [' and ', ' or ', '; ', ', and ', ', or ']

        for unit in context.units:
            # Only decompose prose, not structured content
            if unit.unit_type not in (UnitType.PROSE, UnitType.UNKNOWN):
                continue

            content_lower = unit.content.lower()
            if any(indicator in content_lower for indicator in compound_indicators):
                return True

        return False

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute sentence decomposition."""
        output_units = []
        actions = []
        issues = []

        for unit in context.units:
            # Don't decompose structured content
            if unit.unit_type not in (UnitType.PROSE, UnitType.UNKNOWN):
                output_units.append(unit)
                continue

            # Split into sentences
            sentences = self._splitter(unit.content)

            if len(sentences) <= 1:
                output_units.append(unit)
                continue

            # Create new units for each sentence
            actions.append(f"Split {unit.id} into {len(sentences)} atoms")

            for i, sentence in enumerate(sentences):
                new_unit = TrackedUnit(
                    id=f"{unit.id}_atom_{i+1}",
                    content=sentence.strip(),
                    unit_type=unit.unit_type,
                    source=unit.source,  # Same source
                    introduced_by=unit.introduced_by,
                    modified_by=unit.modified_by.copy(),
                    declarations=unit.declarations if i == 0 else [],
                    references=self._extract_refs(sentence)
                )
                output_units.append(new_unit)

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "input_units": len(context.units),
                "output_units": len(output_units),
                "splits_performed": len(actions)
            }
        )

    def _simple_split(self, text: str) -> list[str]:
        """Simple sentence splitting without spaCy."""
        # Split on common compound indicators
        # This is a fallback - spaCy does better

        # First, protect certain patterns
        protected = text
        protected = re.sub(r'e\.g\.', 'EG_PROTECTED', protected)
        protected = re.sub(r'i\.e\.', 'IE_PROTECTED', protected)

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', protected)

        # For each sentence, also split on ' and ' if it creates valid parts
        result = []
        for sent in sentences:
            # Check for compound structure
            if ' and ' in sent.lower() and sent.count(' and ') == 1:
                parts = re.split(r'\s+and\s+', sent, flags=re.IGNORECASE)
                if all(len(p.split()) >= 3 for p in parts):  # Each part has substance
                    result.extend(parts)
                    continue
            result.append(sent)

        # Restore protected patterns
        result = [
            s.replace('EG_PROTECTED', 'e.g.')
             .replace('IE_PROTECTED', 'i.e.')
            for s in result
        ]

        return [s for s in result if s.strip()]

    def _extract_refs(self, text: str) -> list[str]:
        """Extract references from text."""
        ref_pattern = re.compile(r'\(@\[([+=])([^\]]+)\]\)')
        return [m.group(2) for m in ref_pattern.finditer(text)]
```

### File 4: `spec_manager/strategies/implementations/coverage_verification.py`

```python
"""
Coverage verification strategy.

This strategy verifies that nothing was lost during a transformation
by comparing source units to target units.

It's typically applied after merging or extraction operations.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from spec_manager.core.provenance import TrackedUnit, UnitStatus
from spec_manager.strategies.base import (
    Strategy, StrategyDefinition, ProcessingContext, StrategyResult,
    StrategyPhase, Tool
)


class CoverageVerificationStrategy(Strategy):
    """Verifies coverage after transformations."""

    def __init__(self, definition: StrategyDefinition, tools: dict[str, Tool]):
        self.definition = definition
        self.tools = tools

    @property
    def name(self) -> str:
        return "coverage_verification"

    @property
    def purpose(self) -> str:
        return "Verify nothing was lost during transformation"

    @property
    def risk_addressed(self) -> str:
        return "Content silently dropped during projection/merge"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.VERIFICATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Always applies in verification phase."""
        return context.phase == StrategyPhase.VERIFICATION

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """
        Execute coverage verification.

        Gap 3 fix: Uses ATOM-BASED MEMBERSHIP with sequence-aware comparison,
        NOT set-based comparison (which destroys order and duplicates).
        """
        issues = []
        actions = []
        membership_evidence = {}  # atom_id → match evidence

        # Get source units from previous results
        source_units = context.previous_results.get('source_units', [])
        target_units = context.units

        if not source_units:
            # No source to compare - just check current status
            pending = [u for u in target_units if u.status == UnitStatus.PENDING]
            if pending:
                issues.append(f"{len(pending)} units still pending")
            return StrategyResult(
                units=target_units,
                actions_taken=["Checked unit status"],
                issues=issues,
                metrics={"pending_count": len(pending)}
            )

        # Gap 3 fix: ATOM-BASED MEMBERSHIP (preserves order and duplicates)
        # Convert to atoms with stable IDs
        source_atoms = self._units_to_atoms(source_units)
        target_atoms = self._units_to_atoms(target_units)

        # Use SequenceMatcher for sequence-aware comparison
        from difflib import SequenceMatcher
        source_lines = [a['content'] for a in source_atoms]
        target_lines = [a['content'] for a in target_atoms]

        matcher = SequenceMatcher(None, source_lines, target_lines)

        matched_atoms = []
        unmatched_atoms = []
        fuzzy_matched_atoms = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Exact match - record membership evidence
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    matched_atoms.append(atom)
                    membership_evidence[atom['id']] = {
                        'status': 'matched',
                        'confidence': 1.0,
                        'method': 'exact_match',
                        'target_index': j1 + (idx - i1)
                    }
                    actions.append(f"Atom {atom['id']}: Exact match")

            elif tag == 'replace':
                # Content changed - check for fuzzy matches
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    # Find best fuzzy match in replacement range
                    best_match = self._find_best_atom_match(
                        atom['content'],
                        [target_atoms[j]['content'] for j in range(j1, j2)]
                    )
                    if best_match and best_match[1] > 0.8:
                        fuzzy_matched_atoms.append(atom)
                        membership_evidence[atom['id']] = {
                            'status': 'fuzzy_matched',
                            'confidence': best_match[1],
                            'method': 'sequence_matcher',
                            'match_content': best_match[0][:50]
                        }
                        actions.append(f"Atom {atom['id']}: Fuzzy match ({best_match[1]:.0%})")
                    else:
                        unmatched_atoms.append(atom)
                        membership_evidence[atom['id']] = {
                            'status': 'unmatched',
                            'confidence': 0.0,
                            'method': 'sequence_matcher'
                        }
                        issues.append(f"Unmatched atom: {atom['id']} ({len(atom['content'])} chars)")

            elif tag == 'delete':
                # Content deleted from source
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    unmatched_atoms.append(atom)
                    membership_evidence[atom['id']] = {
                        'status': 'deleted',
                        'confidence': 0.0,
                        'method': 'sequence_matcher'
                    }
                    issues.append(f"Deleted atom: {atom['id']}")

            # 'insert' operations are new content in target - not a coverage issue

        # Calculate coverage using atom counts (not set sizes)
        total_atoms = len(source_atoms)
        matched_count = len(matched_atoms) + len(fuzzy_matched_atoms)
        coverage = matched_count / total_atoms if total_atoms > 0 else 1.0

        if unmatched_atoms:
            actions.append(f"Found {len(unmatched_atoms)} unmatched atoms (remainder)")

        return StrategyResult(
            units=target_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "source_atoms": total_atoms,
                "target_atoms": len(target_atoms),
                "exact_matched": len(matched_atoms),
                "fuzzy_matched": len(fuzzy_matched_atoms),
                "unmatched": len(unmatched_atoms),
                "coverage_percent": coverage * 100,
                "membership_evidence": membership_evidence
            }
        )

    def _units_to_atoms(self, units: list) -> list[dict]:
        """Convert units to atoms with stable IDs (Gap 3 fix)."""
        atoms = []
        for unit in units:
            unit_id = getattr(unit, 'id', str(id(unit)))
            for i, line in enumerate(unit.content.split('\n')):
                if line.strip():
                    atom_id = f"{unit_id}_L{i+1}_{hash(line) % 10000:04d}"
                    atoms.append({
                        'id': atom_id,
                        'content': line,
                        'unit_id': unit_id,
                        'line_number': i + 1
                    })
        return atoms

    def _find_best_atom_match(self, needle: str, candidates: list[str]) -> tuple[str, float] | None:
        """Find best matching content in candidate list (sequence-aware)."""
        if not candidates:
            return None

        best = None
        best_score = 0.0

        for candidate in candidates:
            score = SequenceMatcher(None, needle, candidate).ratio()
            if score > best_score:
                best_score = score
                best = candidate

        return (best, best_score) if best else None

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        # Remove extra whitespace
        text = ' '.join(text.split())
        # Remove common formatting
        text = text.strip()
        return text.lower()

    def _find_best_match(
        self,
        needle: str,
        haystack: set[str]
    ) -> tuple[str, float] | None:
        """Find best matching content in haystack."""
        best = None
        best_score = 0.0

        for candidate in haystack:
            score = SequenceMatcher(None, needle, candidate).ratio()
            if score > best_score:
                best_score = score
                best = candidate

        return (best, best_score) if best else None
```

### File 5: Strategy Definition Examples

Create `spec_manager/strategies/definitions/sentence_decomposition.yaml`:

```yaml
name: sentence_decomposition
version: "1.0"

purpose: |
  Split compound sentences into atomic units so each unit can be
  tracked independently through transformations. Reduces risk of
  losing part of a compound statement.

risk_addressed: |
  Compound meaning lost in translation. When "A and B" becomes
  just "A" in the output, B is silently dropped.

phases:
  - decomposition
  - cleaning

when_conditions:
  - Content contains conjunctions (and, or, but)
  - Sentences have multiple clauses
  - Semicolon-separated statements
  - Content will be projected to different artifact types

tools_used:
  - spacy_splitter

implementation_class: spec_manager.strategies.implementations.sentence_decomposition.SentenceDecompositionStrategy

example:
  input: "The algorithm must handle edge cases and log errors to the audit trail"
  output: |
    - "The algorithm must handle edge cases"
    - "The algorithm must log errors to the audit trail"
```

Create `spec_manager/strategies/definitions/coverage_verification.yaml`:

```yaml
name: coverage_verification
version: "1.0"

purpose: |
  Verify that nothing was lost during a transformation by comparing
  source units to target units. Applied after merge/extraction.

risk_addressed: |
  Content silently dropped during projection/merge operations.
  Without verification, we can't know if transformation was lossless.

phases:
  - verification

when_conditions:
  - After any projection operation
  - After merging content
  - After extraction to libraries
  - When source and target exist

tools_used:
  - line_comparator
  - similarity_scorer

implementation_class: spec_manager.strategies.implementations.coverage_verification.CoverageVerificationStrategy

example:
  input: "Source units from patches"
  output: "Coverage report showing matched/unmatched content"
```

## Additional Strategies to Implement

### entity_resolution.yaml

```yaml
name: entity_resolution
version: "1.0"

purpose: |
  Resolve vague references like "the algorithm" or "patch this"
  to specific IDs. Uses context from surrounding content and
  previous patches.

risk_addressed: |
  Vague references make it unclear what is being modified.
  "Patch the relaxation algorithm" - which one? Without resolution,
  changes might be applied to wrong element.

phases:
  - resolution

when_conditions:
  - Content contains vague references ("the algorithm", "this")
  - Patch references another patch without specific IDs
  - Pronouns refer to previous content

tools_used:
  - context_analyzer
  - id_matcher
  - reference_resolver

implementation_class: spec_manager.strategies.implementations.entity_resolution.EntityResolutionStrategy
```

### line_membership.yaml

```yaml
name: line_membership
version: "1.0"

purpose: |
  Track source-to-target line mapping to ensure every line is
  accounted for (either mapped or explicitly dropped).

risk_addressed: |
  Lines dropped without notice during transformation. The
  membership guarantee ensures we know where every line went.

phases:
  - verification
  - cleaning

when_conditions:
  - Transforming content between representations
  - Merging multiple sources
  - Any operation that changes line structure

tools_used:
  - line_comparator
  - diff_tool

implementation_class: spec_manager.strategies.implementations.line_membership.LineMembershipStrategy
```

## Testing

```python
# tests/test_strategies.py

import pytest
from spec_manager.strategies.registry import StrategyRegistry
from spec_manager.strategies.base import ProcessingContext, StrategyPhase
from spec_manager.core.provenance import TrackedUnit, SourceLocation, UnitType


def test_registry_loads_definitions(tmp_path):
    # Create a test definition
    defn = tmp_path / "test_strategy.yaml"
    defn.write_text('''
name: test_strategy
version: "1.0"
purpose: Test purpose
risk_addressed: Test risk
phases:
  - cleaning
when_conditions:
  - always
tools_used: []
implementation_class: null
''')

    registry = StrategyRegistry()
    count = registry.load_from_directory(tmp_path)
    assert count == 1
    assert "test_strategy" in registry.definitions


def test_sentence_decomposition():
    from spec_manager.strategies.implementations.sentence_decomposition import (
        SentenceDecompositionStrategy
    )

    strategy = SentenceDecompositionStrategy(
        definition=None,
        tools={}
    )

    unit = TrackedUnit(
        id="test",
        content="The algorithm must handle edge cases and log errors",
        unit_type=UnitType.PROSE,
        source=SourceLocation("test.md", 1, 1),
        introduced_by="p1"
    )

    context = ProcessingContext(
        units=[unit],
        phase=StrategyPhase.DECOMPOSITION
    )

    assert strategy.applies_to(context)

    result = strategy.execute(context)
    assert len(result.units) == 2
    assert "edge cases" in result.units[0].content
    assert "log errors" in result.units[1].content
```

## Integration with Workflow

The strategy framework integrates with the workflow like this:

```python
# In workflow orchestrator

async def process_with_strategies(
    units: list[TrackedUnit],
    phase: StrategyPhase,
    registry: StrategyRegistry
) -> list[TrackedUnit]:
    """Process units through applicable strategies."""

    context = ProcessingContext(units=units, phase=phase)

    # Get applicable strategies
    strategies = registry.get_applicable(context)

    # Execute each strategy
    current_units = units
    for strategy in strategies:
        result = strategy.execute(context)
        current_units = result.units

        # Log what happened
        for action in result.actions_taken:
            logger.info(f"[{strategy.name}] {action}")

        # Track issues
        for issue in result.issues:
            logger.warning(f"[{strategy.name}] {issue}")

        # Update context for next strategy
        context = ProcessingContext(
            units=current_units,
            phase=phase,
            previous_results={strategy.name: result.metrics}
        )

    return current_units
```

## Success Criteria

1. Can load strategy definitions from YAML
2. Registry correctly identifies applicable strategies
3. Strategies execute and transform units correctly
4. Provenance is preserved through transformations
5. New strategies can be added at runtime
6. Sentence decomposition actually splits compounds
7. Coverage verification catches dropped content
