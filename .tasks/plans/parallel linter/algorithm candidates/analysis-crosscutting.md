# Cross-Cutting Concerns Analysis

## Executive Summary

This analysis identifies **7 major cross-cutting concerns** in the parallel linter algorithm that span multiple subgraphs and complicate the control flow. Each concern appears in 3-6 different locations, making the algorithm difficult to reason about and maintain.

---

## 1. Staleness Checking & Hash/Fingerprint Tracking

### Description
The algorithm constantly verifies that file content and project configuration haven't changed since various checkpoints (investigation start, agent run start, etc.) to prevent race conditions and ensure data consistency.

### Nodes/Decisions Involved

1. **InvCheck Subgraph**
   - Line 29: `J0` - "Still safe to apply? (current hash/fingerprint == investigation start)"
   - Line 30: `JDROP` - Discard stale results, update seen_hashes
   - Line 41: `NOOP0` - "Still safe to trust? (current hash/fingerprint == investigation start)"
   - Line 51: `FAIL0` - "Still safe to trust? (current hash/fingerprint == investigation start)"
   - Line 32: `J1` - "Any actual diff? (new hash/fingerprint != investigation start)"
   - Line 37: `K` - Record new hash/fingerprint in seen_hashes

2. **AgentPhase Subgraph**
   - Line 101: `R` - Snapshot agent_input_files BEFORE agent (hash files) + project fingerprint
   - Line 102: `R1` - Update seen_hashes for agent_input_files hashes + project fingerprint
   - Line 104: `S` - CAS-protected writes (verify hashes/fingerprint from R immediately before write)
   - Line 105: `S0` - "Pre-write check passed? (hash/fingerprint unchanged since R)"
   - Line 108: `T` - Snapshot agent_input_files AFTER agent
   - Line 109: `U` - Detect changes via diff (changed_files + project_changed)
   - Line 110: `U1` - Update seen_hashes for changed_files hashes + project fingerprint (post-agent)

3. **UpdateState Subgraph**
   - Line 166: `BG3A` - Snapshot investigation start hashes/fingerprint NOW
   - Line 167: `BG4` - Track start hashes/fingerprint per target in investigation_futures

4. **ErrorCheck Subgraph**
   - Line 77: `O4B` - Snapshot start hashes/fingerprint NOW before investigation dispatch
   - Line 89: `EXT` - Clear seen_hashes for changed_files on external change

5. **Key Concepts**
   - Concept #15: Investigator staleness protection
   - Concept #16: Investigator cycle protections (MODIFIED but no diff)

### Why It's Cross-Cutting

Staleness checking is not a discrete step but a **continuous verification concern** that:
- Appears at every async boundary (agent writes, investigation results, external changes)
- Requires maintaining state (`seen_hashes`) that's accessed and modified across all subgraphs
- Mixes two distinct dimensions: file content hashing and project fingerprinting
- Creates complex decision trees in multiple locations with identical logic patterns

The concern is **temporally distributed** - each checkpoint must remember what the state was at multiple prior points in time (investigation start, agent pre-write, agent post-write).

### Isolation Strategies

#### Strategy 1: Aspect-Oriented Programming (AOP)
```python
@verify_staleness(checkpoint="investigation_start", on_stale=discard_and_refresh)
def apply_investigation_result(result, target):
    # Business logic without staleness checks
    ...

@verify_staleness(checkpoint="agent_pre_write", on_stale=trigger_external_change)
def agent_write_files(files):
    # Write logic without manual CAS checks
    ...
```

**Benefits:**
- Centralizes staleness logic in decorators/aspects
- Makes business logic cleaner and more testable
- Enforces consistent handling across all checkpoints

**Drawbacks:**
- Python's limited AOP support (requires decorators or metaclasses)
- Hidden control flow (jumps to on_stale handlers)
- Debugging becomes harder (stack traces obscured)

#### Strategy 2: Version Vector / Logical Clock Abstraction
```python
class VersionedState:
    """Encapsulates all hash/fingerprint tracking with versioning"""

    def __init__(self):
        self._version = 0
        self._file_hashes = {}
        self._project_fingerprint = None
        self._checkpoints = {}  # name -> version snapshot

    def checkpoint(self, name: str) -> int:
        """Create named checkpoint, return version"""
        self._checkpoints[name] = self._version
        return self._version

    def is_stale(self, checkpoint_name: str) -> bool:
        """Check if state changed since checkpoint"""
        return self._version != self._checkpoints.get(checkpoint_name)

    def update_files(self, file_hashes: dict):
        """Update file hashes, increment version"""
        if self._file_hashes != file_hashes:
            self._file_hashes = file_hashes
            self._version += 1

    def update_project(self, fingerprint):
        """Update project fingerprint, increment version"""
        if self._project_fingerprint != fingerprint:
            self._project_fingerprint = fingerprint
            self._version += 1
```

**Benefits:**
- Single source of truth for staleness
- Explicit version tracking makes temporal reasoning easier
- Can add debugging/logging at version boundaries
- Testable in isolation

**Drawbacks:**
- Doesn't reduce number of staleness checks, just centralizes state
- Still need to sprinkle `.is_stale()` calls throughout
- Version increment logic could get complex with partial updates

#### Strategy 3: Event Sourcing + Validator Chain
```python
class StateChangeEvent:
    """Base class for all state mutations"""
    pass

class FileModifiedEvent(StateChangeEvent):
    def __init__(self, files, new_hashes):
        self.files = files
        self.new_hashes = new_hashes

class InvestigationCompletedEvent(StateChangeEvent):
    def __init__(self, target, result, checkpoint_version):
        self.target = target
        self.result = result
        self.checkpoint_version = checkpoint_version

class StaleValidator:
    """Intercepts events and rejects stale ones"""

    def __init__(self, versioned_state):
        self.state = versioned_state

    def validate(self, event):
        if isinstance(event, InvestigationCompletedEvent):
            if event.checkpoint_version != self.state.current_version:
                raise StaleEventError("Investigation result is stale")
        return event

# Event pipeline
def process_event(event):
    event = StaleValidator(state).validate(event)
    event_handler.handle(event)
```

**Benefits:**
- Complete decoupling of staleness validation from business logic
- All state changes go through single pipeline
- Easy to add logging, replay, debugging
- Natural fit for async event processing

**Drawbacks:**
- Requires rewriting entire algorithm as event-driven
- Large architectural change
- May introduce latency (event queue overhead)

---

## 2. Target Normalization

### Description
The algorithm must normalize file paths and target identifiers (like `<PROJECT>`) before all set operations to ensure consistent matching across different representations.

### Nodes/Decisions Involved

1. **Implicit in all set operations**
   - Line 30: `JDROP` - seen_hashes -= changed_files
   - Line 69: `O3` - unlintable = keys(unlintable_targets)
   - Line 70: `O3A` - pending = keys(pending_investigation_targets)
   - Line 75: `O4` - actionable_targets = all_error_targets - inv_files - pending
   - Line 80: `O6` - actionable_targets = actionable_targets - {<PROJECT>}
   - Line 82: `O8` - actionable_files = actionable_targets - {<PROJECT>}
   - Line 89: `EXT` - pending_investigation_targets -= changed_files
   - Line 111: `V` - candidate_stalled_files = actionable_files - changed_files
   - Line 112: `V2` - candidate_stalled_targets = candidate_stalled_files ∪ ({<PROJECT>} if ...)
   - Line 129: `AI3` - files_that_passed = (changed_files ∪ candidate_stalled_files) - files_with_errors
   - Line 138: `AM1` - files_to_check = ALL_TRACKED_FILES - inv_files - unlintable - {<PROJECT>}
   - Line 139: `AM2` - files_to_check = (changed_files ∪ candidate_stalled_files) - inv_files - unlintable - {<PROJECT>}
   - Line 145: `AO3` - files_that_passed = files_to_check - files_with_errors
   - Line 158: `BG1` - confirmed_stalled_targets = candidate_stalled_targets ∩ verified_error_targets

2. **Explicit warnings**
   - Line 95: `Q4` - "likely path normalization / set logic bug"
   - Key Concept #24: "Target normalization - Normalize file paths/target identifiers before all set operations (case, separators, relative vs absolute) to preserve invariants and avoid Q4"

### Why It's Cross-Cutting

Target normalization is a **data quality concern** that:
- Must be applied at every set operation boundary (15+ locations)
- Affects multiple data types (file paths, pseudo-targets like `<PROJECT>`)
- Has platform-specific requirements (Windows: case-insensitive, backslash vs forward slash)
- Violations lead to silent bugs (invariant violations, infinite loops)
- No single enforcement point - relies on discipline across all code paths

The algorithm explicitly calls out this concern in Concept #24 and warns that violations lead to the "invariant violation" abort path (Q4).

### Isolation Strategies

#### Strategy 1: Type System + NewType Wrapper
```python
from typing import NewType, Set
from pathlib import Path

class NormalizedPath:
    """Wrapper that guarantees normalization"""

    def __init__(self, path: str | Path):
        # Normalize: resolve, absolute, lowercase on Windows
        self._path = Path(path).resolve()
        if sys.platform == "win32":
            self._normalized = str(self._path).lower()
        else:
            self._normalized = str(self._path)

    def __hash__(self):
        return hash(self._normalized)

    def __eq__(self, other):
        if isinstance(other, NormalizedPath):
            return self._normalized == other._normalized
        return False

    def __str__(self):
        return self._normalized

class Target:
    """Union type for file paths and pseudo-targets"""

    @staticmethod
    def from_path(path: str | Path) -> 'Target':
        return FileTarget(NormalizedPath(path))

    @staticmethod
    def project() -> 'Target':
        return PseudoTarget("<PROJECT>")

# Type safety at API boundaries
def compute_actionable(
    all_errors: Set[Target],
    inv_files: Set[Target],
    pending: Set[Target]
) -> Set[Target]:
    return all_errors - inv_files - pending
```

**Benefits:**
- Type system enforces normalization at construction
- Impossible to mix normalized and non-normalized paths
- IDE autocomplete helps developers use correct types
- Can add validation/assertions in constructor

**Drawbacks:**
- Requires wrapping all path strings throughout codebase
- Performance overhead (normalization on every construction)
- Interop with external libraries that expect strings
- Still possible to bypass with manual string operations

#### Strategy 2: Smart Set Collections
```python
class NormalizedSet:
    """Set that auto-normalizes all elements"""

    def __init__(self, items=None):
        self._normalize = self._get_normalizer()
        self._items = set()
        if items:
            self.update(items)

    def _get_normalizer(self):
        """Platform-specific normalization function"""
        if sys.platform == "win32":
            return lambda p: str(Path(p).resolve()).lower()
        else:
            return lambda p: str(Path(p).resolve())

    def add(self, item):
        if item == "<PROJECT>":
            self._items.add(item)
        else:
            self._items.add(self._normalize(item))

    def update(self, items):
        for item in items:
            self.add(item)

    def __sub__(self, other):
        result = NormalizedSet()
        result._items = self._items - other._items
        return result

    # Implement full Set interface...

# Usage
actionable_targets = NormalizedSet(all_error_targets)
actionable_targets -= NormalizedSet(inv_files)
actionable_targets -= NormalizedSet(pending)
```

**Benefits:**
- Transparent normalization at collection level
- No changes to business logic (still uses set operators)
- Centralized normalization logic
- Easy to add debug logging/validation

**Drawbacks:**
- Normalization overhead on every add/remove
- Can't prevent mixing NormalizedSet with regular sets
- Hidden behavior (not obvious that normalization happens)
- Doesn't help with dict keys or other collections

#### Strategy 3: Repository Pattern + Canonical Key Store
```python
class TargetRepository:
    """Central registry that owns all target identifiers"""

    def __init__(self):
        self._canonical_paths = {}  # normalized -> canonical
        self._project_target = "<PROJECT>"

    def register_file(self, path: str | Path) -> str:
        """Register a file, return canonical ID"""
        normalized = self._normalize(path)
        if normalized not in self._canonical_paths:
            self._canonical_paths[normalized] = f"file://{normalized}"
        return self._canonical_paths[normalized]

    def register_project(self) -> str:
        """Return project target ID"""
        return self._project_target

    def resolve_many(self, paths: Iterable) -> Set[str]:
        """Batch normalize paths to canonical IDs"""
        return {self.register_file(p) for p in paths}

    def _normalize(self, path):
        p = Path(path).resolve()
        return str(p).lower() if sys.platform == "win32" else str(p)

# Usage
repo = TargetRepository()
all_error_ids = repo.resolve_many(all_error_targets)
inv_file_ids = repo.resolve_many(inv_files)
actionable_ids = all_error_ids - inv_file_ids
```

**Benefits:**
- Single source of truth for normalization
- Can track all targets in one place (debugging)
- Easy to swap normalization strategy
- Can add caching, validation, metrics

**Drawbacks:**
- Requires passing repository instance everywhere
- ID indirection (harder to debug raw values)
- Doesn't prevent bypassing repository
- Extra lookup overhead

---

## 3. Investigation Lifecycle Management

### Description
The algorithm must carefully coordinate investigation futures across their entire lifecycle: creation, dispatch, completion, staleness validation, result application, and cleanup.

### Nodes/Decisions Involved

1. **Init Subgraph**
   - Line 9: `F` - Initialize investigation_futures = empty
   - Line 10: `F1` - Initialize pending_investigation_targets = empty

2. **InvCheck Subgraph**
   - Line 20: `H` - "Any investigations completed?"
   - Line 21: `I` - Get completed investigation result
   - Line 22: `I2` - Remove current future from investigation_futures
   - Lines 29-59: Investigation result processing (MODIFIED/NO_OP/FAILURE with staleness checks)

3. **ErrorCheck Subgraph**
   - Line 68: `O2` - inv_files = keys(investigation_futures)
   - Line 77: `O4B` - Reserve pending in investigation_futures, dispatch async
   - Line 79: `O5` - "inv_files empty?"
   - Line 80: `O6` - Block <PROJECT> fixes if inv_files not empty
   - Line 86: `Q` - "Pending investigations?"
   - Line 86: `WAIT2` - Non-blocking wait on futures

4. **UpdateState Subgraph**
   - Line 157: `BG0A` - Filter pending_investigation_targets to verified errors
   - Line 159: `BG1A` - stalled_targets_ready includes pending keys
   - Line 162: `BG2B` - Upsert pending_investigation_targets for deferred targets
   - Line 165: `BG3` - Build per-target investigation context (use pending snapshot)
   - Line 167: `BG4` - Add to investigation_futures
   - Line 168: `BG4A` - Dispatch targets_to_submit async
   - Line 169: `BG5` - Remove from pending_investigation_targets after dispatch

5. **Multiple places**
   - Line 38: `K3` - pending_investigation_targets -= changed_files (on investigator MODIFIED)
   - Line 89: `EXT` - pending_investigation_targets -= changed_files (on external change)
   - Line 172: `BH` - "investigation_futures empty?" (termination check)

### Why It's Cross-Cutting

Investigation lifecycle is a **state machine concern** that:
- Spans the entire algorithm (initialization → main loop → cleanup)
- Has two parallel tracking structures (investigation_futures for active, pending_investigation_targets for deferred)
- Requires synchronization across async boundaries (futures completion)
- Affects termination logic, locking logic, and staleness validation
- Mixes concerns: locking (prevent concurrent edits), context preservation (snapshots), deferral logic (granular gating)

The lifecycle has **4 distinct states** but they're scattered across different data structures:
1. **Not started**: Not in investigation_futures or pending
2. **Deferred**: In pending_investigation_targets (waiting for stale linter refresh)
3. **Active**: In investigation_futures (async execution)
4. **Completed**: Result processed, removed from investigation_futures

### Isolation Strategies

#### Strategy 1: State Machine with Explicit Transitions
```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class InvestigationState(Enum):
    NOT_STARTED = "not_started"
    DEFERRED = "deferred"
    ACTIVE = "active"
    COMPLETED = "completed"
    STALE = "stale"

@dataclass
class Investigation:
    target: str
    state: InvestigationState
    error_snapshot: dict
    agent_output_snapshot: str
    start_checkpoint: Optional[int] = None
    future: Optional[asyncio.Future] = None

    def defer(self):
        """Transition to deferred state"""
        assert self.state == InvestigationState.NOT_STARTED
        self.state = InvestigationState.DEFERRED

    def activate(self, future, checkpoint):
        """Transition to active state"""
        assert self.state in (InvestigationState.NOT_STARTED, InvestigationState.DEFERRED)
        self.state = InvestigationState.ACTIVE
        self.future = future
        self.start_checkpoint = checkpoint

    def complete(self):
        """Transition to completed state"""
        assert self.state == InvestigationState.ACTIVE
        self.state = InvestigationState.COMPLETED

    def mark_stale(self):
        """Mark as stale (can happen from any state)"""
        self.state = InvestigationState.STALE

class InvestigationTracker:
    """Manages all investigation lifecycle"""

    def __init__(self):
        self._investigations = {}  # target -> Investigation

    def get_active_targets(self) -> Set[str]:
        return {t for t, inv in self._investigations.items()
                if inv.state == InvestigationState.ACTIVE}

    def get_deferred_targets(self) -> Set[str]:
        return {t for t, inv in self._investigations.items()
                if inv.state == InvestigationState.DEFERRED}

    def get_all_locked_targets(self) -> Set[str]:
        return {t for t, inv in self._investigations.items()
                if inv.state in (InvestigationState.ACTIVE, InvestigationState.DEFERRED)}
```

**Benefits:**
- Single source of truth for investigation state
- Explicit state transitions with assertions
- Easy to visualize/debug lifecycle
- Can add logging at transition boundaries

**Drawbacks:**
- Doesn't reduce number of state checks, just centralizes them
- Still need to query state throughout algorithm
- Memory overhead (Investigation objects)

#### Strategy 2: Observer Pattern + Event Callbacks
```python
class InvestigationManager:
    """Observable investigation lifecycle manager"""

    def __init__(self):
        self._observers = []
        self._active = {}
        self._deferred = {}

    def attach_observer(self, observer):
        self._observers.append(observer)

    def _notify(self, event, target, data=None):
        for obs in self._observers:
            obs.on_investigation_event(event, target, data)

    def defer_investigation(self, target, context):
        self._deferred[target] = context
        self._notify("investigation_deferred", target, context)

    def dispatch_investigation(self, target, future, checkpoint):
        context = self._deferred.pop(target, None)
        self._active[target] = {
            'future': future,
            'checkpoint': checkpoint,
            'context': context
        }
        self._notify("investigation_dispatched", target, checkpoint)

    def complete_investigation(self, target, result):
        inv = self._active.pop(target)
        self._notify("investigation_completed", target, result)
        return inv

# Observers handle side effects
class StaleLinterObserver:
    def on_investigation_event(self, event, target, data):
        if event == "investigation_completed":
            # Update blocked_by sets
            self._update_blocked_linters(target)

class TerminationObserver:
    def on_investigation_event(self, event, target, data):
        if event == "investigation_completed":
            # Check if we can terminate
            self._check_termination_condition()
```

**Benefits:**
- Decouples investigation lifecycle from side effects
- Easy to add new behaviors without modifying core logic
- Natural fit for async event handling
- Testable observers in isolation

**Drawbacks:**
- Hidden control flow (observers fire implicitly)
- Debugging harder (who handled this event?)
- Order dependencies between observers
- May need event queue for async consistency

#### Strategy 3: Monadic Workflow (Functional Approach)
```python
from typing import TypeVar, Generic, Callable

T = TypeVar('T')

class InvestigationWorkflow(Generic[T]):
    """Monad for investigation lifecycle with explicit dependencies"""

    def __init__(self, target: str):
        self.target = target
        self._pipeline = []

    def with_context(self, errors, agent_output):
        """Attach investigation context"""
        self._pipeline.append(('context', errors, agent_output))
        return self

    def defer_if(self, predicate: Callable):
        """Conditionally defer investigation"""
        self._pipeline.append(('defer_if', predicate))
        return self

    def dispatch(self, executor):
        """Dispatch to investigator"""
        self._pipeline.append(('dispatch', executor))
        return self

    def validate_staleness(self, versioned_state):
        """Add staleness validation step"""
        self._pipeline.append(('validate', versioned_state))
        return self

    def apply_result(self, handler):
        """Apply investigation result"""
        self._pipeline.append(('apply', handler))
        return self

    async def execute(self):
        """Execute the pipeline"""
        context = None
        for step in self._pipeline:
            if step[0] == 'context':
                context = {'errors': step[1], 'output': step[2]}
            elif step[0] == 'defer_if':
                if step[1]():  # predicate
                    return InvestigationDeferred(self.target, context)
            # ... handle other steps
        return InvestigationComplete(self.target)

# Usage
investigation = (InvestigationWorkflow(target)
    .with_context(errors, agent_output)
    .defer_if(lambda: has_stale_linter(target))
    .dispatch(investigator)
    .validate_staleness(state)
    .apply_result(apply_handler))

result = await investigation.execute()
```

**Benefits:**
- Explicit dependency chain
- Composable workflow steps
- Easy to test individual steps
- Declarative style (what, not how)

**Drawbacks:**
- Unfamiliar paradigm for Python developers
- Requires entire algorithm rewrite
- May obscure imperative control flow
- Error handling complexity

---

## 4. Stale Linter Tracking & Wake-up Logic

### Description
The algorithm must track linters that are temporarily suspended because they can't run (PROJECT-scoped linters blocked by locked files), remember why they're blocked, wake them up when blocks clear, and force a refresh-only tick before their diagnostics become actionable again.

### Nodes/Decisions Involved

1. **Init Subgraph**
   - Line 12: `F2` - Initialize stale_linters = empty (linter → STALE/SUSPENDED + blocked_by)

2. **InvCheck Subgraph**
   - Line 23: `I2A` - Update stale_linters blocked_by (remove completed target)
   - Line 24: `I2B` - "Any stale linter unblocked? (blocked_by empty)"
   - Line 25: `I2C` - Mark unblocked stale_linters as PENDING_REFRESH; keep excluded until refreshed

3. **ErrorCheck Subgraph**
   - Line 65: `NREF` - "Any stale linter PENDING_REFRESH?"
   - Line 66: `NREF0` - Refresh-only tick (set changed_files = empty, etc.)
   - Line 73: `O0` - actionable_errors_by_linter excludes stale_linters
   - Line 74: `O` - Get all_error_targets from actionable_errors (excludes stale diagnostics)
   - Line 91: `Q2` - "actionable_errors_by_linter empty AND stale_linters empty?" (termination)
   - Line 93: `Q3` - "stale_linters non-empty OR ..." (keep looping)

4. **ProcessLinters Subgraph**
   - Line 127: `AI0A` - Clear stale_linters entry for this linter (wake-up is post-refresh)
   - Line 133: `AG2` - Skip project run; mark diagnostics as STALE/SUSPENDED
   - Line 134: `AG2A` - Upsert stale_linters entry (blocked_by = blocking_files)

5. **UpdateState Subgraph**
   - Line 156: `BG0` - Extract targets from errors_by_linter excluding stale_linters
   - Line 161: `BG2A` - Granular gating: check if target's required_linter is in stale_linters
   - Line 172: `BH` - "errors_by_linter empty AND stale_linters empty..." (termination)

6. **Key Concepts**
   - Concept #11: Project-scoped lint safety
   - Concept #12: Stale linter refresh gating
   - Concept #13: Granular stale-linter gating

### Why It's Cross-Cutting

Stale linter tracking is a **coordination concern** that:
- Affects almost every subgraph (InvCheck, ErrorCheck, ProcessLinters, UpdateState)
- Creates complex dependencies: investigations affect linter state, linter state affects investigations
- Requires a 3-state lifecycle (STALE → PENDING_REFRESH → active)
- Interacts with multiple other concerns (investigation locks, actionable error computation, termination)
- Maintains bidirectional mappings (linter → blocked_by files, target → required_linter)

The concern is **temporally complex**: a linter can become stale at any investigation completion (I2A), must wait for wake-up (I2B), forces a refresh-only tick (NREF), then becomes actionable after refresh (AI0A).

### Isolation Strategies

#### Strategy 1: Linter Coordinator (Mediator Pattern)
```python
class LinterState(Enum):
    ACTIVE = "active"
    STALE = "stale"
    PENDING_REFRESH = "pending_refresh"

class LinterCoordinator:
    """Centralized mediator for linter state transitions"""

    def __init__(self):
        self._linter_states = {}  # linter -> LinterState
        self._blocked_by = {}     # linter -> Set[target]
        self._required_by = {}    # target -> linter (reverse index)

    def mark_linter_stale(self, linter: str, blocked_by: Set[str]):
        """Block a linter when it can't run"""
        self._linter_states[linter] = LinterState.STALE
        self._blocked_by[linter] = blocked_by.copy()
        for target in blocked_by:
            self._required_by[target] = linter

    def on_investigation_completed(self, target: str):
        """Update blocked_by sets when investigation completes"""
        newly_unblocked = []
        for linter, blocked in self._blocked_by.items():
            if target in blocked:
                blocked.discard(target)
                if not blocked:
                    newly_unblocked.append(linter)

        # Transition unblocked linters to PENDING_REFRESH
        for linter in newly_unblocked:
            self._linter_states[linter] = LinterState.PENDING_REFRESH

        return newly_unblocked

    def get_pending_refresh_linters(self) -> List[str]:
        """Get linters that need refresh-only tick"""
        return [l for l, state in self._linter_states.items()
                if state == LinterState.PENDING_REFRESH]

    def refresh_completed(self, linter: str):
        """Mark linter as active after refresh"""
        self._linter_states[linter] = LinterState.ACTIVE
        self._blocked_by.pop(linter, None)

    def is_actionable(self, linter: str) -> bool:
        """Check if linter diagnostics are actionable"""
        return self._linter_states.get(linter, LinterState.ACTIVE) == LinterState.ACTIVE

    def should_defer_target(self, target: str) -> bool:
        """Check if target should be deferred due to stale linter"""
        if target not in self._required_by:
            return False
        linter = self._required_by[target]
        return self._linter_states.get(linter) != LinterState.ACTIVE
```

**Benefits:**
- Single source of truth for linter state
- Centralized state transition logic
- Reverse index (target → required_linter) maintained automatically
- Easy to add logging, metrics, debugging

**Drawbacks:**
- Still requires calling coordinator from multiple places
- Doesn't eliminate wake-up complexity
- State mutations scattered across algorithm
- Coordinator becomes a god object

#### Strategy 2: Reactive Streams (Publish/Subscribe)
```python
import asyncio
from typing import AsyncIterator

class LinterStateStream:
    """Reactive stream of linter state changes"""

    def __init__(self):
        self._subscribers = []
        self._state_queue = asyncio.Queue()

    async def publish(self, event):
        """Publish linter state change event"""
        await self._state_queue.put(event)

    async def subscribe(self) -> AsyncIterator:
        """Subscribe to linter state changes"""
        while True:
            event = await self._state_queue.get()
            yield event

class LinterStateManager:
    """Manages linter state via event stream"""

    def __init__(self, stream: LinterStateStream):
        self._stream = stream
        self._states = {}

    async def handle_events(self):
        """Process linter state events"""
        async for event in self._stream.subscribe():
            if event.type == "investigation_completed":
                unblocked = self._update_blocked_by(event.target)
                for linter in unblocked:
                    await self._stream.publish(
                        LinterUnblockedEvent(linter)
                    )
            elif event.type == "linter_unblocked":
                self._states[event.linter] = LinterState.PENDING_REFRESH
                await self._stream.publish(
                    RefreshRequiredEvent(event.linter)
                )
            elif event.type == "refresh_completed":
                self._states[event.linter] = LinterState.ACTIVE

# Usage
stream = LinterStateStream()
manager = LinterStateManager(stream)
asyncio.create_task(manager.handle_events())

# Elsewhere in code
await stream.publish(InvestigationCompletedEvent(target))
```

**Benefits:**
- Fully decoupled state transitions
- Easy to add new handlers for state changes
- Natural fit for async architecture
- Observable state changes (debugging, logging)

**Drawbacks:**
- Requires full async rewrite
- Event ordering guarantees needed
- Complex error handling across stream
- Performance overhead (queue operations)

#### Strategy 3: Finite State Machine with Guards
```python
from transitions import Machine

class LinterFSM:
    """Finite state machine for individual linter lifecycle"""

    states = ['active', 'stale', 'pending_refresh']

    def __init__(self, name):
        self.name = name
        self.blocked_by = set()

        self.machine = Machine(
            model=self,
            states=LinterFSM.states,
            initial='active'
        )

        # Define transitions with guards
        self.machine.add_transition(
            trigger='block',
            source='active',
            dest='stale',
            before='record_blockers'
        )

        self.machine.add_transition(
            trigger='unblock',
            source='stale',
            dest='pending_refresh',
            conditions=['has_no_blockers']
        )

        self.machine.add_transition(
            trigger='refresh',
            source='pending_refresh',
            dest='active',
            after='clear_blockers'
        )

    def record_blockers(self, blocked_by):
        self.blocked_by = blocked_by.copy()

    def has_no_blockers(self):
        return len(self.blocked_by) == 0

    def clear_blockers(self):
        self.blocked_by.clear()

    def remove_blocker(self, target):
        self.blocked_by.discard(target)
        if not self.blocked_by:
            self.unblock()  # Auto-transition

# Usage
linter_fsm = LinterFSM('eslint')
linter_fsm.block(blocked_by={'file1.js', 'file2.js'})
linter_fsm.remove_blocker('file1.js')
linter_fsm.remove_blocker('file2.js')  # Auto-transitions to pending_refresh
linter_fsm.refresh()  # Transitions to active
```

**Benefits:**
- Explicit state machine prevents invalid transitions
- Guards ensure preconditions met
- Hooks for side effects (before/after)
- Well-tested FSM library

**Drawbacks:**
- External dependency (transitions library)
- Still need to manage collection of FSMs
- Doesn't reduce number of state checks
- Wake-up logic still complex

---

## 5. Candidate Stall Debouncing & Cleared State Management

### Description
The algorithm must track which targets are "candidate stalled" (agent ran but errors persist), prevent re-submission spam when agent phase is skipped due to locks, and clear candidate state when targets are deferred, submitted, or externally modified.

### Nodes/Decisions Involved

1. **AgentPhase Subgraph**
   - Line 111: `V` - candidate_stalled_files = actionable_files - changed_files
   - Line 112: `V2` - candidate_stalled_targets = candidate_stalled_files ∪ ({<PROJECT>} if ...)

2. **UpdateState Subgraph**
   - Line 158: `BG1` - confirmed_stalled_targets = candidate_stalled_targets ∩ verified_error_targets
   - Line 162: `BG2B` - clear candidate_stalled_targets for targets_to_defer
   - Line 169: `BG5` - clear candidate_stalled_targets for targets_to_submit

3. **InvCheck Subgraph**
   - Line 30: `JDROP` - clear candidate_stalled_* (on stale investigation result)
   - Line 38: `K3` - clear candidate_stalled_* (on investigator MODIFIED)

4. **ErrorCheck Subgraph**
   - Line 66: `NREF0` - candidate_stalled_files = empty (refresh-only tick)
   - Line 89: `EXT` - clear candidate_stalled_* (on external change)

5. **ProcessLinters Subgraph**
   - Line 129: `AI3` - files_that_passed = (changed_files ∪ candidate_stalled_files) - files_with_errors
   - Line 145: `AO3` - files_that_passed = files_to_check - files_with_errors (uses candidate_stalled_files indirectly)

6. **Key Concepts**
   - Concept #22: Candidate stall debouncing

### Why It's Cross-Cutting

Candidate stall tracking is a **transient state concern** that:
- Computed in one place (AgentPhase: V, V2)
- Read in another place (UpdateState: BG1)
- Cleared in 5 different places (JDROP, K3, NREF0, EXT, BG2B, BG5)
- Interacts with multiple concerns: agent changes, linter results, investigations, external changes
- Has unclear ownership (is it part of agent phase or investigation triggering?)

The concern is **synchronization-heavy**: candidate state must be cleared whenever targets move to a different workflow stage (investigation dispatch, external modification, stale result discard) to prevent "re-submission spam."

### Isolation Strategies

#### Strategy 1: Target Lifecycle Tracker
```python
class TargetLifecycle(Enum):
    FRESH = "fresh"                    # Just processed by agent
    CANDIDATE_STALLED = "candidate"    # Agent ran but errors persist
    CONFIRMED_STALLED = "confirmed"    # Post-lint verified stall
    INVESTIGATING = "investigating"    # Investigation in progress
    RESOLVED = "resolved"              # No errors

class TargetTracker:
    """Tracks target lifecycle to prevent state leakage"""

    def __init__(self):
        self._targets = {}  # target -> TargetLifecycle

    def mark_candidate_stalled(self, targets: Set[str]):
        """Mark targets as candidate stalled after agent"""
        for target in targets:
            self._targets[target] = TargetLifecycle.CANDIDATE_STALLED

    def confirm_stalled(self, targets: Set[str]):
        """Confirm stalled after post-lint verification"""
        for target in targets:
            if self._targets.get(target) == TargetLifecycle.CANDIDATE_STALLED:
                self._targets[target] = TargetLifecycle.CONFIRMED_STALLED

    def mark_investigating(self, targets: Set[str]):
        """Transition to investigating (auto-clears candidate state)"""
        for target in targets:
            self._targets[target] = TargetLifecycle.INVESTIGATING

    def mark_resolved(self, targets: Set[str]):
        """Mark as resolved (auto-clears candidate state)"""
        for target in targets:
            self._targets[target] = TargetLifecycle.RESOLVED

    def mark_fresh(self, targets: Set[str]):
        """Mark as fresh (auto-clears candidate state)"""
        for target in targets:
            self._targets[target] = TargetLifecycle.FRESH

    def get_candidates(self) -> Set[str]:
        """Get current candidate stalled targets"""
        return {t for t, state in self._targets.items()
                if state == TargetLifecycle.CANDIDATE_STALLED}

    def get_confirmed(self) -> Set[str]:
        """Get confirmed stalled targets"""
        return {t for t, state in self._targets.items()
                if state == TargetLifecycle.CONFIRMED_STALLED}
```

**Benefits:**
- Centralized lifecycle state
- Automatic clearing via state transitions
- No manual clear() calls scattered around
- Easy to debug (can dump all target states)

**Drawbacks:**
- Adds memory overhead (track all targets)
- Still need to call mark_* methods from multiple places
- Doesn't prevent forgetting to update state
- State transitions can be called in wrong order

#### Strategy 2: Functional Immutable Collections
```python
from dataclasses import dataclass, replace
from typing import FrozenSet

@dataclass(frozen=True)
class WorkflowState:
    """Immutable snapshot of workflow state"""
    candidate_stalled: FrozenSet[str]
    confirmed_stalled: FrozenSet[str]
    investigating: FrozenSet[str]

    def with_candidates(self, targets: Set[str]) -> 'WorkflowState':
        """Return new state with updated candidates"""
        return replace(self, candidate_stalled=frozenset(targets))

    def with_investigation_started(self, targets: Set[str]) -> 'WorkflowState':
        """Return new state with targets moved to investigating"""
        new_candidates = self.candidate_stalled - targets
        new_investigating = self.investigating | targets
        return replace(
            self,
            candidate_stalled=new_candidates,
            investigating=frozenset(new_investigating)
        )

    def clear_candidates(self) -> 'WorkflowState':
        """Return new state with cleared candidates"""
        return replace(self, candidate_stalled=frozenset())

# Usage (pure functional style)
state = WorkflowState(
    candidate_stalled=frozenset(),
    confirmed_stalled=frozenset(),
    investigating=frozenset()
)

# After agent
state = state.with_candidates({'file1.js', 'file2.js'})

# On investigation dispatch
state = state.with_investigation_started({'file1.js'})

# External change
state = state.clear_candidates()
```

**Benefits:**
- Impossible to forget to clear (new state returned)
- Thread-safe (immutable)
- Easy to test (pure functions)
- Can implement undo/redo (keep state history)

**Drawbacks:**
- Requires full functional rewrite
- Performance overhead (copy on every update)
- Unfamiliar paradigm for Python
- Still need discipline to use new state

#### Strategy 3: Aspect-Oriented Auto-Clearing
```python
def auto_clear_candidates(method):
    """Decorator that auto-clears candidates on state transitions"""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        # Identify targets being transitioned
        targets = _extract_targets_from_args(args, kwargs)

        # Execute the transition
        result = method(self, *args, **kwargs)

        # Auto-clear candidates for transitioned targets
        self.candidate_stalled_targets -= targets

        return result
    return wrapper

class WorkflowManager:
    def __init__(self):
        self.candidate_stalled_targets = set()
        self.investigating = set()

    @auto_clear_candidates
    def start_investigation(self, targets: Set[str]):
        """Dispatch investigation (auto-clears candidates)"""
        self.investigating.update(targets)

    @auto_clear_candidates
    def handle_external_change(self, changed_files: Set[str]):
        """Handle external modification (auto-clears candidates)"""
        # Business logic...
        pass
```

**Benefits:**
- DRY (clear logic in one place)
- Automatic (can't forget)
- Easy to add to existing code

**Drawbacks:**
- Hidden behavior (not obvious from method signature)
- Target extraction logic fragile
- Doesn't work if targets not in args
- Debugging harder (stack traces)

---

## 6. Unlintable Target Management

### Description
The algorithm must track targets that can't be fixed (investigator NO_OP/FAILURE), preserve their state, exclude them from processing, abort if <PROJECT> is unlintable, and clean up unlintable state when files are externally modified.

### Nodes/Decisions Involved

1. **Init Subgraph**
   - Line 11: `F1` - Initialize unlintable_targets = empty (target, reason)

2. **InvCheck Subgraph**
   - Line 33: `LIE1` - Mark targets as UNLINTABLE (investigator MODIFIED but no diff)
   - Line 34: `LIEP` - "target == <PROJECT>?"
   - Line 35: `ABORT` - Abort: <PROJECT> unrecoverable (UNLINTABLE)
   - Line 44: `NOOPPROJ` - Mark <PROJECT> as UNLINTABLE (investigator NO_OP)
   - Line 46: `NOOP1` - Mark target as UNLINTABLE (investigator NO_OP)
   - Line 47: `NOOP2` - Remove target diagnostics from errors_by_linter
   - Line 48: `NOOP3` - Clear passed_linters for target
   - Line 54: `FAILPROJ` - Mark <PROJECT> as UNLINTABLE (investigator FAILURE)
   - Line 56: `FAIL1` - Mark target as UNLINTABLE (investigator FAILURE)
   - Line 57: `FAIL2` - Remove target diagnostics from errors_by_linter
   - Line 58: `FAIL3` - Clear passed_linters for target

3. **ErrorCheck Subgraph**
   - Line 69: `O3` - unlintable = keys(unlintable_targets)
   - Line 71: `O3P` - "<PROJECT> in unlintable_targets?"
   - Line 72: `ABORT` (same as line 35)
   - Line 73: `O0` - actionable_errors_by_linter excludes unlintable
   - Line 75: `O4` - actionable_targets = all_error_targets - ... - unlintable
   - Line 89: `EXT` - unlintable_targets -= changed_files (external change cleanup)

4. **ProcessLinters Subgraph**
   - Line 126: `AI0` - Filter out diagnostics for ... + unlintable
   - Line 138: `AM1` - files_to_check = ALL_TRACKED_FILES - ... - unlintable
   - Line 139: `AM2` - files_to_check = ... - unlintable
   - Line 143: `AO` - preserve ... + unlintable

5. **Cleanup Subgraph**
   - Line 182: `BK` - Print final report (include unlintable_targets + reasons)

6. **Key Concepts**
   - Concept #8: UNLINTABLE targets are first-class
   - Concept #20: <PROJECT> UNLINTABLE implication

### Why It's Cross-Cutting

Unlintable management is a **terminal state concern** that:
- Spans the entire algorithm (InvCheck sets it, ErrorCheck checks it, ProcessLinters excludes it, Cleanup reports it)
- Has dual semantics: regular files (remove from workflow) vs <PROJECT> (abort entire workflow)
- Requires cleanup on external changes (files might be fixed externally)
- Affects multiple data structures (errors_by_linter, passed_linters, actionable_targets)
- Mixes error reporting (reason tracking) with state management (exclusion logic)

The concern is **semantically overloaded**: "unlintable" means different things depending on reason (NO_OP = unfixable, FAILURE = tool error, MODIFIED but no diff = investigator lie).

### Isolation Strategies

#### Strategy 1: Exception Hierarchy with Recovery
```python
class UnlintableError(Exception):
    """Base exception for unlintable targets"""
    def __init__(self, target, reason):
        self.target = target
        self.reason = reason
        super().__init__(f"Target {target} is unlintable: {reason}")

class FileUnlintableError(UnlintableError):
    """Recoverable: exclude file from workflow"""
    pass

class ProjectUnlintableError(UnlintableError):
    """Fatal: abort entire workflow"""
    pass

class UnlintableRecoveryManager:
    """Centralized unlintable handling"""

    def __init__(self):
        self.unlintable_files = {}  # target -> reason

    def handle_unlintable(self, error: UnlintableError):
        """Handle unlintable error based on type"""
        if isinstance(error, ProjectUnlintableError):
            raise error  # Propagate to top level (abort)
        elif isinstance(error, FileUnlintableError):
            self.unlintable_files[error.target] = error.reason
            # Remove from workflow state
            self._cleanup_unlintable_file(error.target)

    def _cleanup_unlintable_file(self, target):
        """Remove target from all workflow state"""
        # errors_by_linter cleanup
        # passed_linters cleanup
        # etc.

    def recover_from_external_change(self, changed_files):
        """Re-enable unlintable files if externally fixed"""
        for file in changed_files:
            if file in self.unlintable_files:
                del self.unlintable_files[file]

# Usage
try:
    if investigator.result == "NO_OP":
        if target == "<PROJECT>":
            raise ProjectUnlintableError(target, "Investigator NO_OP")
        else:
            raise FileUnlintableError(target, "Investigator NO_OP")
except UnlintableError as e:
    recovery_manager.handle_unlintable(e)
```

**Benefits:**
- Type-safe distinction between file and project unlintable
- Centralized cleanup logic
- Exception propagation enforces abort semantics
- Easy to add new unlintable reasons

**Drawbacks:**
- Exception-based control flow (anti-pattern in some contexts)
- Harder to reason about (non-local jumps)
- May obscure normal error handling
- Cleanup still needs access to workflow state

#### Strategy 2: Discriminated Union (Result Type)
```python
from dataclasses import dataclass
from typing import Union, Generic, TypeVar
from enum import Enum

T = TypeVar('T')

class UnlintableReason(Enum):
    INVESTIGATOR_NOOP = "investigator_noop"
    INVESTIGATOR_FAILURE = "investigator_failure"
    NO_DIFF_BUT_MODIFIED = "no_diff_but_modified"

@dataclass
class Lintable:
    """Target is lintable"""
    target: str

@dataclass
class UnlintableFile:
    """File target is unlintable"""
    target: str
    reason: UnlintableReason

@dataclass
class UnlintableProject:
    """Project is unlintable (fatal)"""
    reason: UnlintableReason

TargetStatus = Union[Lintable, UnlintableFile, UnlintableProject]

def process_investigation_result(result, target) -> TargetStatus:
    """Return discriminated union based on investigation"""
    if result == "NO_OP":
        if target == "<PROJECT>":
            return UnlintableProject(UnlintableReason.INVESTIGATOR_NOOP)
        else:
            return UnlintableFile(target, UnlintableReason.INVESTIGATOR_NOOP)
    # ... other cases
    return Lintable(target)

def handle_target_status(status: TargetStatus, workflow_state):
    """Pattern match on status and update state"""
    match status:
        case UnlintableProject(reason):
            abort_workflow(reason)
        case UnlintableFile(target, reason):
            workflow_state.unlintable_files[target] = reason
            workflow_state.cleanup_target(target)
        case Lintable(target):
            # Continue processing
            pass
```

**Benefits:**
- Type-safe (exhaustiveness checking with match)
- No exceptions for control flow
- Clear intent (explicit union type)
- Easy to extend with new statuses

**Drawbacks:**
- Requires Python 3.10+ (match statement)
- Verbose (need to handle all cases)
- Doesn't reduce number of status checks
- Still need cleanup logic elsewhere

#### Strategy 3: Target Filter Chain
```python
class TargetFilter:
    """Base class for target filtering"""
    def filter(self, targets: Set[str]) -> Set[str]:
        raise NotImplementedError

class UnlintableFilter(TargetFilter):
    """Filter out unlintable targets"""

    def __init__(self):
        self.unlintable = {}  # target -> reason

    def mark_unlintable(self, target: str, reason: str):
        if target == "<PROJECT>":
            raise ProjectAbortError(reason)
        self.unlintable[target] = reason

    def filter(self, targets: Set[str]) -> Set[str]:
        return targets - self.unlintable.keys()

    def recover(self, changed_files: Set[str]):
        for file in changed_files:
            self.unlintable.pop(file, None)

class InvestigationFilter(TargetFilter):
    """Filter out targets under investigation"""

    def __init__(self, investigation_futures):
        self.futures = investigation_futures

    def filter(self, targets: Set[str]) -> Set[str]:
        return targets - self.futures.keys()

class TargetFilterChain:
    """Compose multiple filters"""

    def __init__(self, filters: List[TargetFilter]):
        self.filters = filters

    def filter(self, targets: Set[str]) -> Set[str]:
        result = targets
        for f in self.filters:
            result = f.filter(result)
        return result

# Usage
unlintable_filter = UnlintableFilter()
investigation_filter = InvestigationFilter(investigation_futures)
chain = TargetFilterChain([unlintable_filter, investigation_filter])

actionable_targets = chain.filter(all_error_targets)
```

**Benefits:**
- Single responsibility (each filter does one thing)
- Composable (easy to add new filters)
- Centralized filtering logic
- DRY (filter chain used everywhere)

**Drawbacks:**
- Doesn't reduce number of filter calls
- Still need to manage filter instances
- Abort semantics awkward (exception in filter)
- Filter order dependencies

---

## 7. passed_linters Tracking & Invalidation

### Description
The algorithm maintains a set of linters that have successfully passed for each file, clears this state when files change or project config changes, and uses it to determine which files have errors after linting.

### Nodes/Decisions Involved

1. **Init Subgraph**
   - Line 8: `E` - Initialize passed_linters = empty

2. **InvCheck Subgraph**
   - Line 48: `NOOP3` - Clear passed_linters for target (investigator NO_OP)
   - Line 58: `FAIL3` - Clear passed_linters for target (investigator FAILURE)

3. **ProcessLinters Subgraph**
   - Line 116: `AC` - Clear passed_linters for changed_files; if project_changed then clear all passed_linters
   - Line 131: `AJ` - Record this linter in passed_linters for files_that_passed
   - Line 146: `AP` - Record this linter in passed_linters for files_that_passed

4. **UpdateState Subgraph**
   - Line 169: `BG5` - clear passed_linters for targets_to_submit; if <PROJECT> in targets_to_submit then clear all passed_linters

5. **Key Concepts**
   - Concept #2: passed_linters tracking

### Why It's Cross-Cutting

passed_linters tracking is a **incremental state concern** that:
- Affects ProcessLinters (recording), InvCheck (invalidation), UpdateState (invalidation)
- Has dual invalidation semantics: file-level (clear for changed files) vs project-level (clear ALL on project change)
- Mixed read/write pattern: cleared before linting, written during linting, cleared after investigation dispatch
- Interaction with multiple invalidation triggers: file changes, project changes, investigation dispatch, investigator failures

The concern is **optimization-focused** but leaks into correctness: if invalidation is missed, stale "pass" state could prevent error detection.

### Isolation Strategies

#### Strategy 1: Cache Invalidation Service
```python
class LinterPassCache:
    """Manages incremental linter pass state with smart invalidation"""

    def __init__(self):
        self._pass_cache = {}  # file -> Set[linter]
        self._cache_version = 0
        self._file_versions = {}  # file -> version

    def mark_passed(self, file: str, linter: str):
        """Record linter pass for file"""
        if file not in self._pass_cache:
            self._pass_cache[file] = set()
            self._file_versions[file] = self._cache_version
        self._pass_cache[file].add(linter)

    def has_passed(self, file: str, linter: str) -> bool:
        """Check if file has passed linter"""
        return linter in self._pass_cache.get(file, set())

    def invalidate_files(self, files: Set[str]):
        """Clear cache for specific files"""
        for file in files:
            self._pass_cache.pop(file, None)
            self._file_versions.pop(file, None)

    def invalidate_all(self):
        """Clear entire cache (project-level change)"""
        self._pass_cache.clear()
        self._file_versions.clear()
        self._cache_version += 1

    def get_files_with_errors(
        self,
        candidates: Set[str],
        linter: str,
        linter_errors: Set[str]
    ) -> Set[str]:
        """Compute which candidates have errors"""
        # Files that passed = candidates - errors - previously_passed
        previously_passed = {
            f for f in candidates
            if self.has_passed(f, linter)
        }
        return linter_errors | previously_passed

# Usage
cache = LinterPassCache()

# After agent
cache.invalidate_files(changed_files)
if project_changed:
    cache.invalidate_all()

# After linting
for file in files_that_passed:
    cache.mark_passed(file, linter_name)

# After investigation dispatch
cache.invalidate_files(targets_to_submit)
if "<PROJECT>" in targets_to_submit:
    cache.invalidate_all()
```

**Benefits:**
- Centralized cache invalidation logic
- Explicit invalidation API (invalidate_files vs invalidate_all)
- Can add versioning, TTL, metrics
- Testable in isolation

**Drawbacks:**
- Still need to call invalidation from multiple places
- Easy to forget invalidation call
- Doesn't prevent misuse
- Performance overhead (set operations)

#### Strategy 2: Reactive Invalidation (Observer Pattern)
```python
class PassCacheInvalidator:
    """Observer that auto-invalidates cache on state changes"""

    def __init__(self, cache: LinterPassCache):
        self.cache = cache

    def on_state_change(self, event):
        """Auto-invalidate based on event type"""
        if event.type == "files_changed":
            self.cache.invalidate_files(event.files)
        elif event.type == "project_changed":
            self.cache.invalidate_all()
        elif event.type == "investigation_dispatched":
            self.cache.invalidate_files(event.targets)
            if "<PROJECT>" in event.targets:
                self.cache.invalidate_all()
        elif event.type == "investigator_failed":
            self.cache.invalidate_files({event.target})

class WorkflowEventBus:
    """Publishes workflow state changes"""

    def __init__(self):
        self.observers = []

    def attach(self, observer):
        self.observers.append(observer)

    def publish(self, event):
        for obs in self.observers:
            obs.on_state_change(event)

# Setup
cache = LinterPassCache()
invalidator = PassCacheInvalidator(cache)
event_bus = WorkflowEventBus()
event_bus.attach(invalidator)

# Usage
event_bus.publish(FilesChangedEvent(changed_files))
event_bus.publish(ProjectChangedEvent())
```

**Benefits:**
- Automatic invalidation (can't forget)
- Decoupled from business logic
- Easy to add new invalidation rules
- Single source of truth for invalidation

**Drawbacks:**
- Hidden control flow
- Event ordering dependencies
- Debugging harder (who invalidated?)
- Requires event bus infrastructure

#### Strategy 3: Versioned Immutable Cache
```python
from dataclasses import dataclass, replace
from typing import FrozenSet, Dict

@dataclass(frozen=True)
class PassCacheSnapshot:
    """Immutable snapshot of pass state"""
    passes: Dict[str, FrozenSet[str]]  # file -> frozenset(linters)
    version: int

    def with_pass(self, file: str, linter: str) -> 'PassCacheSnapshot':
        """Return new snapshot with added pass"""
        current = set(self.passes.get(file, frozenset()))
        current.add(linter)
        new_passes = {**self.passes, file: frozenset(current)}
        return replace(self, passes=new_passes)

    def without_files(self, files: Set[str]) -> 'PassCacheSnapshot':
        """Return new snapshot with files removed"""
        new_passes = {
            f: linters for f, linters in self.passes.items()
            if f not in files
        }
        return replace(self, passes=new_passes)

    def clear(self) -> 'PassCacheSnapshot':
        """Return new snapshot with everything cleared"""
        return PassCacheSnapshot(passes={}, version=self.version + 1)

# Usage (functional style)
cache = PassCacheSnapshot(passes={}, version=0)

# After linting
for file in files_that_passed:
    cache = cache.with_pass(file, linter_name)

# After agent
cache = cache.without_files(changed_files)
if project_changed:
    cache = cache.clear()
```

**Benefits:**
- Impossible to forget invalidation (new snapshot required)
- Thread-safe (immutable)
- Can implement time-travel debugging
- Pure functions (easy to test)

**Drawbacks:**
- Performance overhead (copy on write)
- Requires functional discipline
- Unfamiliar paradigm
- Still need to propagate new snapshot

---

## Summary of Recommendations

### High-Impact Isolations (Recommended)

1. **Staleness Checking**: Implement **Version Vector Abstraction (Strategy 2)** combined with **Event Sourcing Validator (Strategy 3)**
   - Creates single source of truth for version tracking
   - Validates staleness at event boundaries (clean separation)
   - Moderate refactoring effort with high clarity gains

2. **Target Normalization**: Implement **Type System + NewType Wrapper (Strategy 1)**
   - Prevents normalization bugs at compile time
   - Low refactoring effort (gradual migration possible)
   - High correctness impact (eliminates Q4 invariant violations)

3. **Investigation Lifecycle**: Implement **State Machine with Explicit Transitions (Strategy 1)**
   - Centralizes complex state tracking
   - Makes investigation flow explicit and debuggable
   - Moderate effort with high maintainability gains

### Medium-Impact Isolations (Consider)

4. **Stale Linter Tracking**: Implement **Linter Coordinator (Mediator Pattern, Strategy 1)**
   - Centralizes complex wake-up logic
   - Maintains reverse indexes automatically
   - Can be introduced incrementally

5. **Unlintable Management**: Implement **Discriminated Union (Result Type, Strategy 2)**
   - Type-safe distinction between file and project unlintable
   - No exception-based control flow
   - Requires Python 3.10+ but provides exhaustiveness checking

### Low-Impact Isolations (Optional)

6. **Candidate Stall Debouncing**: Implement **Target Lifecycle Tracker (Strategy 1)**
   - Relatively isolated concern (fewer touch points than others)
   - Current manual clear() calls workable with discipline
   - Consider if other lifecycle tracking implemented

7. **passed_linters Tracking**: Implement **Cache Invalidation Service (Strategy 1)**
   - Primarily optimization concern
   - Current approach acceptable if invalidation discipline maintained
   - Add if cache bugs become frequent

### Architectural Shift (Long-term)

Consider migrating to an **Event-Driven Architecture** where:
- All state changes are events
- Validators/observers handle cross-cutting concerns at event boundaries
- Clear separation of business logic and synchronization logic
- Requires significant rewrite but dramatically improves modularity

This would address multiple concerns simultaneously (staleness, invalidation, lifecycle) through a unified event pipeline.
