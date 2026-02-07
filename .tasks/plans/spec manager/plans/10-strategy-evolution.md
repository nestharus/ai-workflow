# Implementation Plan

## Overview

Design and implement a strategy evolution system that captures translation/projection failures as first-class evidence, proposes new strategies automatically, registers them experimentally, and promotes successful ones to permanent status.

## Current State (Problems)

The existing strategies module (`scripts/spec_manager/spec_manager/strategies/`) has scaffold-level support for strategy evolution but lacks complete implementation:

1. **`StrategyRegistry.capture_strategy_gap()`** (registry.py:375-408) captures gap evidence but stores only minimal fixture data. It does not classify the failure type or connect to the new algorithmic-projection paradigm (translation failures, projection failures, comment ambiguity).

2. **`StrategyRegistry.propose_strategy_via_llm()`** (registry.py:410-467) sends a basic prompt to an LLM but produces a `StrategyDefinition` without an `implementation_class`, making the proposed strategy inert (it cannot be instantiated or executed).

3. **`StrategyRegistry.register_experimental_from_gap()`** (registry.py:469-489) registers the proposed definition but relies on `metadata["test_fixtures"]` as `(content, "TBD")` tuples -- fixtures have no expected output and are never validated.

4. **`StrategyRegistry.promote_to_stable()`** (registry.py:357-369) is a stub with `pass` in the validation loop -- no actual fixture validation occurs.

5. **`StrategyRegistry.check_evolution_triggers()`** (registry.py:289-323) checks three stagnation signals (remainder, resolution failures, prose ratio) but does not connect these triggers to gap capture or strategy proposal.

6. **No dedicated StrategyPhase for translation/projection** -- the existing `StrategyPhase` enum (base.py:18-32) covers CLEANING through VERIFICATION but lacks TRANSLATION and PROJECTION phases that the algorithmic-projection model requires (design doc Section 14).

7. **No paradigm-specific strategies** -- the five key strategies from Section 14 (sentence decomposition for multi-concern comments, entity resolution for vague references, ambiguity research against hollowed-out specs, adjacency detection for shared stores, stub promotion) either exist only for the old spec-compositing model (sentence_decomposition, entity_resolution) or do not exist at all (ambiguity_research, adjacency_detection, stub_promotion).

8. **ProcessingContext** (base.py:34-69) lacks fields for the algorithmic-projection paradigm: no comment text, no function signatures, no store dependency graphs, no hollowed-out spec reference.

## Target State

A complete strategy evolution loop where:
- Translation/projection failures are captured with rich evidence (the failing comment, surrounding code context, function signature, attempted strategy)
- New strategies are proposed with executable implementation stubs that use template patterns
- Experimental strategies execute within the current processing run
- Promotion is gated by measurable success criteria (fixture pass rate, failure mode reduction)
- Five paradigm-specific strategies are defined with YAML definitions and implementation classes

## Additional Info

- The design document (Section 14 of `algorithmic-projection-patch.md`) defines the strategy evolution loop: attempt -> fail -> capture gap -> propose -> register experimental -> retry -> promote if successful.
- Phase B (`PHASE_B_STRATEGIES.md`) provides the existing framework design. The evolution system must extend (not replace) the existing `Strategy`, `StrategyDefinition`, `StrategyRegistry`, and `ProcessingContext` classes.
- `LineageTable` (provenance.py:471+) supports transformation types: "split", "merge", "infer", "transform". Strategy evolution should use "transform" for strategy-applied changes.
- Existing YAML strategy definitions in `strategies/definitions/` establish the pattern: name, version, purpose, risk_addressed, risk_category, phases, when_conditions, tools_used, implementation_class, example.
- Existing strategy implementations in `strategies/implementations/` establish the class pattern: `Strategy` subclass with `definition`/`tools` constructor, property implementations, `applies_to()`, and `execute()`.

## Plans

### Plan 1: Extend ProcessingContext and StrategyPhase for Translation/Projection

Add the fields and phases needed by the algorithmic-projection paradigm.

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/base.py`:

```python
# Add to StrategyPhase enum:
class StrategyPhase(Enum):
    CLEANING = "cleaning"
    COMPOSITING = "compositing"
    DECOMPOSITION = "decomposition"
    EXTRACTION = "extraction"
    RESOLUTION = "resolution"
    LABELING = "labeling"
    VERIFICATION = "verification"
    TRANSLATION = "translation"      # NEW: pseudocode comment -> code
    PROJECTION = "projection"        # NEW: algorithmic -> architectural

# Add to ProcessingContext:
@dataclass
class TranslationContext:
    """Context specific to translation failures."""
    comment_text: str                          # The pseudocode comment being translated
    function_signature: str | None = None      # Enclosing function signature
    surrounding_code: list[str] = field(default_factory=list)  # Lines before/after
    file_path: str | None = None               # Source file
    line_number: int | None = None             # Comment line number
    hollowed_spec_path: str | None = None      # Path to hollowed-out spec for research
    store_dependencies: list[str] = field(default_factory=list)  # Stores this function touches
    call_graph_neighbors: list[str] = field(default_factory=list)  # Adjacent functions

# Add field to ProcessingContext:
    translation_context: TranslationContext | None = None
```

**`scripts/spec_manager/spec_manager/strategies/__init__.py`**: Export `TranslationContext`.

**Tests:**
- `scripts/spec_manager/tests/strategies/test_base.py`: Verify `StrategyPhase.TRANSLATION` and `StrategyPhase.PROJECTION` exist. Verify `TranslationContext` fields serialize correctly. Verify `ProcessingContext` accepts `translation_context`.

---

### Plan 2: Formalize Strategy Gap Evidence with Rich Failure Context

Replace the minimal fixture format with a structured, classified gap evidence model.

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/registry.py`:

```python
# Replace/enhance StrategyGapEvidence:
@dataclass
class StrategyGapEvidence:
    """Evidence for a strategy gap -- no strategy could handle this failure mode.

    This is a FIRST-CLASS evidence type that triggers strategy evolution.
    """
    failure_mode: str              # Classified failure type
    failure_category: str          # "translation" | "projection" | "resolution" | "decomposition"
    fixture: dict[str, Any]        # Minimal failing fixture (rich format below)
    translation_context: TranslationContext | None = None  # If translation failure
    strategies_attempted: list[str] = field(default_factory=list)
    proposed_strategy: StrategyDefinition | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    gap_id: str = ""               # Unique ID for tracking (auto-generated)

    def __post_init__(self):
        if not self.gap_id:
            import hashlib
            content = f"{self.failure_mode}:{self.failure_category}:{self.timestamp.isoformat()}"
            self.gap_id = f"gap_{hashlib.sha256(content.encode()).hexdigest()[:12]}"

# Enhanced fixture format captured by capture_strategy_gap():
fixture = {
    "failure_mode": str,                   # e.g., "multi_concern_comment"
    "failure_category": str,               # e.g., "translation"
    "inputs": [                            # Failing inputs (up to 5)
        {"id": str, "content": str, "type": str}
    ],
    "context": {
        "phase": str,
        "patch_id": str | None,
        "comment_text": str | None,        # NEW
        "function_signature": str | None,   # NEW
        "surrounding_code": list[str],      # NEW
        "store_dependencies": list[str],    # NEW
    },
    "strategies_attempted": list[str],     # Names of strategies that were tried
    "error_details": str | None,           # Exception or failure description
}
```

Define failure mode taxonomy as constants:

```python
class FailureMode:
    """Classified failure modes that trigger strategy evolution."""
    MULTI_CONCERN_COMMENT = "multi_concern_comment"        # Comment describes multiple things
    VAGUE_ENTITY_REFERENCE = "vague_entity_reference"      # "the algorithm" without specifics
    INSUFFICIENT_DETAIL = "insufficient_detail"            # Not enough info to translate
    SHARED_STORE_ADJACENCY = "shared_store_adjacency"      # Missed connected algorithm
    STUB_WITH_CONTEXT = "stub_with_context"                # Stub has enough info to implement
    CONFLICTING_REQUIREMENTS = "conflicting_requirements"  # Contradictory spec elements
    UNKNOWN_PROJECTION_TYPE = "unknown_projection_type"    # No known projection pattern applies
```

Update `capture_strategy_gap()` to populate the enhanced format using `TranslationContext` when available.

**Tests:**
- Verify `StrategyGapEvidence` generates unique `gap_id`.
- Verify `FailureMode` constants are accessible.
- Verify `capture_strategy_gap()` populates `failure_category` and `translation_context` from context.

---

### Plan 3: Implement Strategy Proposal Pipeline (LLM + Template)

Replace the single `propose_strategy_via_llm()` with a two-tier proposal system: rule-based template matching for known failure modes, LLM proposal for unknown ones.

**Files to create:**

`scripts/spec_manager/spec_manager/strategies/evolution.py`:

```python
"""Strategy evolution pipeline: gap -> proposal -> registration -> promotion."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

from spec_manager.strategies.base import StrategyDefinition, ProcessingContext
from spec_manager.strategies.registry import StrategyGapEvidence, FailureMode, LLMClient


class StrategyProposer(Protocol):
    """Protocol for strategy proposers."""
    def propose(self, gap: StrategyGapEvidence) -> StrategyDefinition | None: ...


@dataclass
class TemplateStrategyProposer:
    """Proposes strategies from known failure mode templates.

    For each classified failure mode, we have a pre-built template
    that creates a StrategyDefinition with a real implementation_class.
    """

    templates: dict[str, StrategyDefinition] = field(default_factory=dict)

    def __post_init__(self):
        self._register_builtin_templates()

    def _register_builtin_templates(self) -> None:
        """Register templates for the five key paradigm strategies."""
        self.templates[FailureMode.MULTI_CONCERN_COMMENT] = StrategyDefinition(
            name="comment_decomposition",
            purpose="Split multi-concern pseudocode comments into separate single-concern comments",
            risk_addressed="Translation failure from comments that describe multiple things",
            version="1.0",
            phases=["translation"],
            when_conditions=["comment_text contains multiple verbs or conjunctions"],
            tools_used=["spacy_splitter"],
            implementation_class="spec_manager.strategies.implementations.comment_decomposition.CommentDecompositionStrategy",
            risk_category="compound_loss",
            metadata={"status": "experimental", "template_source": FailureMode.MULTI_CONCERN_COMMENT},
        )
        self.templates[FailureMode.VAGUE_ENTITY_REFERENCE] = StrategyDefinition(
            name="translation_entity_resolution",
            purpose="Resolve vague references in pseudocode comments to specific function names",
            risk_addressed="Translation failure from comments referencing 'the algorithm' without specifics",
            version="1.0",
            phases=["translation"],
            when_conditions=["comment contains vague references", "function context available"],
            tools_used=["reference_resolver", "call_graph_analyzer"],
            implementation_class="spec_manager.strategies.implementations.translation_entity_resolution.TranslationEntityResolutionStrategy",
            risk_category="vague_references",
            metadata={"status": "experimental", "template_source": FailureMode.VAGUE_ENTITY_REFERENCE},
        )
        self.templates[FailureMode.INSUFFICIENT_DETAIL] = StrategyDefinition(
            name="ambiguity_research",
            purpose="Search hollowed-out spec for details when comment has insufficient context",
            risk_addressed="Translation failure from insufficient detail in pseudocode comment",
            version="1.0",
            phases=["translation"],
            when_conditions=["hollowed_spec_path available", "comment is underspecified"],
            tools_used=["spec_researcher", "needle_searcher"],
            implementation_class="spec_manager.strategies.implementations.ambiguity_research.AmbiguityResearchStrategy",
            risk_category="information_loss",
            metadata={"status": "experimental", "template_source": FailureMode.INSUFFICIENT_DETAIL},
        )
        self.templates[FailureMode.SHARED_STORE_ADJACENCY] = StrategyDefinition(
            name="adjacency_detection",
            purpose="Detect and flag algorithms connected through shared stores",
            risk_addressed="Missed adjacency when translated code touches shared state",
            version="1.0",
            phases=["translation", "projection"],
            when_conditions=["store_dependencies present", "call_graph_neighbors available"],
            tools_used=["store_graph_analyzer"],
            implementation_class="spec_manager.strategies.implementations.adjacency_detection.AdjacencyDetectionStrategy",
            risk_category="content_loss",
            metadata={"status": "experimental", "template_source": FailureMode.SHARED_STORE_ADJACENCY},
        )
        self.templates[FailureMode.STUB_WITH_CONTEXT] = StrategyDefinition(
            name="stub_promotion",
            purpose="Promote stub functions with sufficient context into real implementations",
            risk_addressed="Stubs remain unimplemented despite having enough context to translate",
            version="1.0",
            phases=["translation"],
            when_conditions=["function is stub", "surrounding context provides implementation details"],
            tools_used=["stub_detector", "context_analyzer"],
            implementation_class="spec_manager.strategies.implementations.stub_promotion.StubPromotionStrategy",
            risk_category="information_loss",
            metadata={"status": "experimental", "template_source": FailureMode.STUB_WITH_CONTEXT},
        )

    def propose(self, gap: StrategyGapEvidence) -> StrategyDefinition | None:
        """Look up a template for the gap's failure mode."""
        return self.templates.get(gap.failure_mode)


@dataclass
class LLMStrategyProposer:
    """Proposes strategies via LLM for unknown failure modes."""

    llm_client: LLMClient | None = None

    def propose(self, gap: StrategyGapEvidence) -> StrategyDefinition | None:
        """Use LLM to propose a strategy for an unclassified failure mode."""
        # (Delegates to existing propose_strategy_via_llm logic with enhanced prompt)
        ...


@dataclass
class StrategyEvolutionPipeline:
    """Orchestrates: gap capture -> proposal -> experimental registration -> promotion.

    Public API for the strategy evolution system.
    """

    registry: StrategyRegistry
    template_proposer: TemplateStrategyProposer = field(default_factory=TemplateStrategyProposer)
    llm_proposer: LLMStrategyProposer = field(default_factory=LLMStrategyProposer)
    gap_log: list[StrategyGapEvidence] = field(default_factory=list)

    def on_translation_failure(
        self,
        context: ProcessingContext,
        failure_mode: str,
        error_details: str | None = None,
    ) -> StrategyDefinition | None:
        """Handle a translation/projection failure.

        1. Capture gap evidence
        2. Propose strategy (template first, then LLM)
        3. Register as experimental
        4. Return the strategy definition for immediate retry
        """
        ...

    def evaluate_experimental(self, strategy_name: str, results: list[StrategyResult]) -> dict[str, Any]:
        """Evaluate an experimental strategy's performance.

        Returns metrics: success_rate, failure_mode_reduction, fixture_pass_rate.
        """
        ...

    def promote_if_ready(self, strategy_name: str) -> bool:
        """Promote experimental strategy to stable if criteria are met.

        Criteria:
        - At least N successful applications (default: 3)
        - Failure mode reduction > threshold (default: 50%)
        - No regressions in other strategies
        """
        ...

    def get_evolution_report(self) -> dict[str, Any]:
        """Return a summary of all gaps, proposals, and promotions."""
        ...
```

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/registry.py`: Import and delegate to `StrategyEvolutionPipeline` from the `capture_strategy_gap`, `propose_strategy_via_llm`, and `register_experimental_from_gap` methods. Keep the registry methods as thin wrappers for backward compatibility.

`scripts/spec_manager/spec_manager/strategies/__init__.py`: Export `StrategyEvolutionPipeline`, `TemplateStrategyProposer`, `FailureMode`.

**Tests:**
- `test_evolution.py`: Verify template proposer returns correct definition for each `FailureMode`.
- Verify `on_translation_failure()` produces a registered experimental strategy.
- Verify LLM proposer is tried when template is not available.

---

### Plan 4: Implement Promotion Gate with Measurable Criteria

Replace the stub `promote_to_stable()` with real validation logic.

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/evolution.py` (add to `StrategyEvolutionPipeline`):

```python
@dataclass
class PromotionCriteria:
    """Criteria for promoting experimental strategy to stable."""
    min_successful_applications: int = 3         # Must succeed at least N times
    min_failure_mode_reduction: float = 0.5      # Must reduce failure mode by 50%
    max_regression_rate: float = 0.0             # No regressions allowed
    fixture_pass_rate: float = 1.0               # All test fixtures must pass

@dataclass
class StrategyPerformanceRecord:
    """Tracks performance of an experimental strategy."""
    strategy_name: str
    applications: list[dict[str, Any]] = field(default_factory=list)  # Each application result
    successes: int = 0
    failures: int = 0
    failure_mode_counts_before: dict[str, int] = field(default_factory=dict)
    failure_mode_counts_after: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 0.0

    def record_application(self, result: StrategyResult, success: bool) -> None:
        """Record an application of this strategy."""
        self.applications.append({
            "actions": result.actions_taken,
            "issues": result.issues,
            "metrics": result.metrics,
            "success": success,
        })
        if success:
            self.successes += 1
        else:
            self.failures += 1
```

`scripts/spec_manager/spec_manager/strategies/registry.py`: Update `promote_to_stable()` to accept `StrategyPerformanceRecord` and validate against `PromotionCriteria`:

```python
def promote_to_stable(self, name: str, performance: StrategyPerformanceRecord | None = None) -> bool:
    """Promote an experimental strategy to stable after validation.

    When performance record is provided, validates against PromotionCriteria.
    """
    if name not in self.definitions:
        return False
    definition = self.definitions[name]
    if definition.metadata.get("status") != "experimental":
        return False

    criteria = PromotionCriteria()

    if performance:
        if performance.successes < criteria.min_successful_applications:
            return False
        if performance.success_rate < (1.0 - criteria.max_regression_rate):
            return False

    definition.metadata["status"] = "stable"
    definition.metadata["promoted_at"] = datetime.now().isoformat()
    definition.metadata["promotion_evidence"] = {
        "successes": performance.successes if performance else 0,
        "success_rate": performance.success_rate if performance else 0.0,
    }
    return True
```

**Tests:**
- Verify promotion fails when successes < min threshold.
- Verify promotion fails when success rate is below threshold.
- Verify promotion succeeds with valid performance record.
- Verify metadata is updated with promotion evidence.

---

### Plan 5: Implement Five Paradigm-Specific Strategy Definitions and Stubs

Create YAML definitions and implementation class stubs for the five key strategies from the design document.

**Files to create (YAML definitions):**

`scripts/spec_manager/spec_manager/strategies/definitions/comment_decomposition.yaml`:
```yaml
name: comment_decomposition
version: "1.0"
purpose: "Split multi-concern pseudocode comments into separate single-concern comments"
risk_addressed: "Translation failure when a comment describes multiple things"
risk_category: compound_loss
phases:
  - translation
when_conditions:
  - "Comment contains multiple verbs"
  - "Comment has conjunctions connecting distinct actions"
  - "Comment has semicolons separating concerns"
tools_used:
  - spacy_splitter
implementation_class: "spec_manager.strategies.implementations.comment_decomposition.CommentDecompositionStrategy"
example:
  input: "# validate payment against fraud rules and send confirmation to customer"
  output: |
    - "# validate payment against fraud rules"
    - "# send confirmation to customer"
```

`scripts/spec_manager/spec_manager/strategies/definitions/ambiguity_research.yaml`:
```yaml
name: ambiguity_research
version: "1.0"
purpose: "Search hollowed-out spec for details when comment has insufficient context"
risk_addressed: "Translation failure from insufficient detail in pseudocode"
risk_category: information_loss
phases:
  - translation
when_conditions:
  - "Hollowed spec available"
  - "Comment contains underspecified terms"
  - "Previous translation attempt produced low-confidence result"
tools_used:
  - spec_researcher
  - needle_searcher
implementation_class: "spec_manager.strategies.implementations.ambiguity_research.AmbiguityResearchStrategy"
```

`scripts/spec_manager/spec_manager/strategies/definitions/adjacency_detection.yaml`:
```yaml
name: adjacency_detection
version: "1.0"
purpose: "Detect algorithms connected through shared stores during translation"
risk_addressed: "Missed adjacency when translated code touches shared state"
risk_category: content_loss
phases:
  - translation
  - projection
when_conditions:
  - "Function touches stores"
  - "Store is accessed by multiple functions"
  - "Call graph has disconnected subgraphs sharing stores"
tools_used:
  - store_graph_analyzer
implementation_class: "spec_manager.strategies.implementations.adjacency_detection.AdjacencyDetectionStrategy"
```

`scripts/spec_manager/spec_manager/strategies/definitions/stub_promotion.yaml`:
```yaml
name: stub_promotion
version: "1.0"
purpose: "Promote stub functions with enough context to real implementations"
risk_addressed: "Stubs remain unimplemented despite sufficient context"
risk_category: information_loss
phases:
  - translation
when_conditions:
  - "Function body is pass/raise NotImplementedError"
  - "Function has docstring or surrounding comments with implementation details"
  - "Adjacent translated functions provide sufficient context"
tools_used:
  - stub_detector
  - context_analyzer
implementation_class: "spec_manager.strategies.implementations.stub_promotion.StubPromotionStrategy"
```

`scripts/spec_manager/spec_manager/strategies/definitions/translation_entity_resolution.yaml`:
```yaml
name: translation_entity_resolution
version: "1.0"
purpose: "Resolve vague references in pseudocode comments to specific function names"
risk_addressed: "Translation failure from comments referencing 'the algorithm' without specifics"
risk_category: vague_references
phases:
  - translation
when_conditions:
  - "Comment contains vague references ('the algorithm', 'it', 'this')"
  - "Function call graph context available"
tools_used:
  - reference_resolver
  - call_graph_analyzer
implementation_class: "spec_manager.strategies.implementations.translation_entity_resolution.TranslationEntityResolutionStrategy"
```

**Files to create (implementation stubs):**

Each implementation follows the existing pattern from `SentenceDecompositionStrategy`:

`scripts/spec_manager/spec_manager/strategies/implementations/comment_decomposition.py`:
```python
class CommentDecompositionStrategy(Strategy):
    """Decomposes multi-concern pseudocode comments into single-concern comments.

    Adapted from SentenceDecompositionStrategy for the translation paradigm.
    Operates on pseudocode comments rather than prose TrackedUnits.
    """
    def __init__(self, definition=None, tools=None): ...
    @property
    def name(self) -> str: return "comment_decomposition"
    @property
    def purpose(self) -> str: ...
    @property
    def risk_addressed(self) -> str: ...
    @property
    def phases(self) -> list[StrategyPhase]: return [StrategyPhase.TRANSLATION]
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if translation_context has multi-concern comment."""
        ...
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Split the comment, create separate TrackedUnits per concern."""
        ...
```

`scripts/spec_manager/spec_manager/strategies/implementations/ambiguity_research.py`:
```python
class AmbiguityResearchStrategy(Strategy):
    """Searches hollowed-out spec for details when comment is underspecified.

    Uses needle-in-haystack search against the complete spec to find
    relevant details for translation.
    """
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if hollowed_spec_path is available and comment is underspecified."""
        ...
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Search spec, extract relevant details, augment translation context."""
        ...
```

`scripts/spec_manager/spec_manager/strategies/implementations/adjacency_detection.py`:
```python
class AdjacencyDetectionStrategy(Strategy):
    """Detects algorithms connected through shared stores.

    When translating/projecting, checks if the current function's store
    dependencies overlap with other functions, flagging potential adjacencies.
    """
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if store_dependencies are present in translation_context."""
        ...
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Analyze store graph, flag connected algorithms, add evidence records."""
        ...
```

`scripts/spec_manager/spec_manager/strategies/implementations/stub_promotion.py`:
```python
class StubPromotionStrategy(Strategy):
    """Promotes stub functions with enough context to real implementations.

    Checks if a stub (pass/raise NotImplementedError) has enough surrounding
    context (docstrings, comments, adjacent implementations) to attempt translation.
    """
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if function is a stub with surrounding context."""
        ...
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Gather context, produce translation-ready augmented context."""
        ...
```

`scripts/spec_manager/spec_manager/strategies/implementations/translation_entity_resolution.py`:
```python
class TranslationEntityResolutionStrategy(Strategy):
    """Resolves vague references in pseudocode comments during translation.

    Differs from the existing EntityResolutionStrategy in that it operates
    on pseudocode comments within code files rather than prose TrackedUnits,
    and uses the call graph and function signatures for resolution context.
    """
    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if comment contains vague references."""
        ...
    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Resolve references using call graph, function signatures, and spec."""
        ...
```

Update `scripts/spec_manager/spec_manager/strategies/implementations/__init__.py` to export all new classes.

**Tests:**
- Verify each new strategy can be loaded from YAML definition.
- Verify each new strategy's `applies_to()` correctly gates on `TranslationContext` presence.
- Verify the registry loads all definitions from the `definitions/` directory including the new ones.

---

### Plan 6: Wire Evolution Pipeline into Registry and Connect Triggers

Connect the evolution pipeline to the registry's existing trigger checks and make the end-to-end loop functional.

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/registry.py`:

Add `StrategyEvolutionPipeline` as an optional component of `StrategyRegistry`:

```python
class StrategyRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, StrategyDefinition] = {}
        self.strategies: dict[str, Strategy] = {}
        self.tools: dict[str, Tool] = {}
        self.evolution_pipeline: StrategyEvolutionPipeline | None = None  # NEW

    def enable_evolution(self, llm_client: LLMClient | None = None) -> None:
        """Enable the strategy evolution pipeline."""
        from spec_manager.strategies.evolution import (
            StrategyEvolutionPipeline,
            TemplateStrategyProposer,
            LLMStrategyProposer,
        )
        self.evolution_pipeline = StrategyEvolutionPipeline(
            registry=self,
            template_proposer=TemplateStrategyProposer(),
            llm_proposer=LLMStrategyProposer(llm_client=llm_client),
        )
```

Update `check_evolution_triggers()` to call `evolution_pipeline.on_translation_failure()` when triggers fire:

```python
def check_and_evolve(
    self,
    context: ProcessingContext,
    previous_context: ProcessingContext | None = None,
) -> list[StrategyDefinition]:
    """Check triggers and evolve strategies if needed.

    Returns list of newly registered experimental strategies.
    """
    if not self.evolution_pipeline:
        return []

    triggers = self.check_evolution_triggers(context, previous_context)
    new_strategies = []

    for trigger in triggers:
        failure_mode = self._classify_trigger(trigger)
        result = self.evolution_pipeline.on_translation_failure(
            context=context,
            failure_mode=failure_mode,
        )
        if result:
            new_strategies.append(result)

    return new_strategies
```

Update `scripts/spec_manager/spec_manager/strategies/__init__.py` to export all new public API.

**Tests:**
- End-to-end test: create registry, enable evolution, simulate a translation failure via `ProcessingContext` with `TranslationContext`, verify a new strategy is proposed and registered.
- Verify `check_and_evolve()` returns new strategy definitions when triggers fire.
- Verify evolution is a no-op when `enable_evolution()` has not been called.
- Verify backward compatibility: existing callers of `capture_strategy_gap()` still work.

---

### Plan 7: Add Persistence for Gap Evidence and Evolution State

Ensure gap evidence and evolution state survive across processing runs.

**Files to create:**

`scripts/spec_manager/spec_manager/strategies/persistence.py`:

```python
"""Persistence for strategy evolution state.

Stores gap evidence, experimental strategy records, and promotion history
to YAML files in the workspace.
"""

@dataclass
class EvolutionStateStore:
    """Persists evolution state to disk."""

    state_dir: Path

    def save_gap(self, gap: StrategyGapEvidence) -> Path:
        """Save gap evidence to {state_dir}/gaps/{gap_id}.yaml."""
        ...

    def save_performance(self, record: StrategyPerformanceRecord) -> Path:
        """Save performance record to {state_dir}/performance/{strategy_name}.yaml."""
        ...

    def load_gaps(self) -> list[StrategyGapEvidence]:
        """Load all gap evidence from {state_dir}/gaps/."""
        ...

    def load_performance(self, strategy_name: str) -> StrategyPerformanceRecord | None:
        """Load performance record for a strategy."""
        ...

    def save_experimental_definition(self, definition: StrategyDefinition) -> Path:
        """Save experimental strategy YAML to {state_dir}/experimental/."""
        ...
```

**Files to modify:**

`scripts/spec_manager/spec_manager/strategies/evolution.py`: Add `state_store: EvolutionStateStore | None` field to `StrategyEvolutionPipeline`. Persist gaps and performance records on capture/evaluate.

**Tests:**
- Verify gaps are written to and read from disk.
- Verify performance records survive round-trip serialization.
- Verify experimental strategy definitions are saved alongside stable ones.

## Execution Instructions

Execute plans in order (1 through 7). Each plan is independently implementable and testable.

- Plans 1-2 lay the data model foundation (no behavior change to existing code).
- Plan 3 builds the proposal pipeline (core new behavior).
- Plan 4 adds promotion validation (closes the loop).
- Plan 5 adds the five paradigm strategies (concrete deliverables).
- Plan 6 wires everything together (integration).
- Plan 7 adds persistence (operational requirement).

Run tests after each plan to verify no regressions. Use `uv run pytest scripts/spec_manager/ -p no:randomly` to avoid test ordering flakiness.

## Success Criteria

1. **StrategyPhase** includes `TRANSLATION` and `PROJECTION` values.
2. **ProcessingContext** accepts a `TranslationContext` with comment text, function signature, surrounding code, store dependencies, and hollowed-spec path.
3. **StrategyGapEvidence** captures classified failure modes with rich context including `failure_category`, `translation_context`, and `strategies_attempted`.
4. **TemplateStrategyProposer** returns a valid `StrategyDefinition` (with `implementation_class`) for each of the five classified failure modes: `MULTI_CONCERN_COMMENT`, `VAGUE_ENTITY_REFERENCE`, `INSUFFICIENT_DETAIL`, `SHARED_STORE_ADJACENCY`, `STUB_WITH_CONTEXT`.
5. **StrategyEvolutionPipeline.on_translation_failure()** captures a gap, proposes a strategy, and registers it as experimental in a single call.
6. **promote_to_stable()** validates against `PromotionCriteria` and rejects strategies that have not met the minimum success threshold.
7. **Five new YAML definitions** exist in `strategies/definitions/` and load without error via `registry.load_from_directory()`.
8. **Five new implementation class stubs** exist in `strategies/implementations/` and are importable.
9. **StrategyRegistry.enable_evolution()** activates the pipeline, and `check_and_evolve()` returns new strategies when triggers fire.
10. **Gap evidence persists** to disk and can be reloaded across runs.
11. All existing tests continue to pass (no regressions in strategies module).
