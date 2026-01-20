# Gaps and Proof Obligations

This file tracks unresolved gaps, ambiguities, and proof obligations.

## High Coupling

- ℹ️ Library 'algorithms_extra' is tightly coupled to 'data' (100% of refs)
  - Library: algorithms_extra
  - Coupling: 100%
  - Target Library: data
  - Suggestion: Consider merging 'algorithms_extra' and 'data' or refactoring shared concerns

## Invalid Library

- ⚠️ Library 'algorithms_extra' description suggests type-based organization
  - Library: algorithms_extra
  - Suggestion: Refactor into domain/subsystem libraries with clear system capabilities

- ⚠️ Library 'data' description suggests type-based organization
  - Library: data
  - Suggestion: Refactor into domain/subsystem libraries with clear system capabilities

- ⚠️ Library name 'goals' suggests type-based organization
  - Library: goals
  - Suggestion: Rename to describe the subsystem/domain capability, not the content type

## Low Cohesion

- ℹ️ Library 'algorithms_extra' has low internal cohesion (0%)
  - Library: algorithms_extra
  - Cohesion: 0%
  - Suggestion: Consider splitting library or reorganizing elements by their actual dependencies

## Misplaced Invariant

- ⚠️ Library 'goals' contains invariants/goals: G1, G2
  - Library: goals
  - Suggestion: Move invariants to root-level invariants.md file (not under libraries/)

## Missing Relation

- ℹ️ Algorithm 4 references Algorithm 1 but Algorithm 1 not in related
  - In: Algorithm 4
  - Target: Algorithm 1

- ℹ️ Algorithm 4 references Algorithm 2 but Algorithm 2 not in related
  - In: Algorithm 4
  - Target: Algorithm 2

- ℹ️ Algorithm 4 references Algorithm 3 but Algorithm 3 not in related
  - In: Algorithm 4
  - Target: Algorithm 3

- ℹ️ Algorithm 5 references Algorithm 3 but Algorithm 3 not in related
  - In: Algorithm 5
  - Target: Algorithm 3

- ℹ️ Algorithm 5 references D5 but D5 not in related
  - In: Algorithm 5
  - Target: D5

- ℹ️ Algorithm 1 references D1 but D1 not in related
  - In: Algorithm 1
  - Target: D1

- ℹ️ Algorithm 1 references D2 but D2 not in related
  - In: Algorithm 1
  - Target: D2

- ℹ️ Algorithm 2 references D3 but D3 not in related
  - In: Algorithm 2
  - Target: D3

- ℹ️ Algorithm 2 references D4 but D4 not in related
  - In: Algorithm 2
  - Target: D4

- ℹ️ Algorithm 3 references D4 but D4 not in related
  - In: Algorithm 3
  - Target: D4

- ℹ️ Algorithm 3 references D5 but D5 not in related
  - In: Algorithm 3
  - Target: D5

## Todo

- ⚠️ TODO in D5: decide if we need circuit breaker logic here.
  - In: D5
  - Marker: TODO

## Uncertain

- ℹ️ G1 contains 2 questions - needs clarification
  - ID: G1

- ℹ️ G2 contains 2 questions - needs clarification
  - ID: G2

## Unknown Function Call

- ℹ️ Unknown function call: validate_event
  - In: Algorithm 1
  - Name: validate_event

- ℹ️ Unknown function call: rule_store
  - In: Algorithm 2
  - Name: rule_store

- ℹ️ Unknown function call: audit_log
  - In: Algorithm 2
  - Name: audit_log

- ℹ️ Unknown function call: format_for_sink
  - In: Algorithm 3
  - Name: format_for_sink

- ℹ️ Unknown function call: sink_client
  - In: Algorithm 3
  - Name: sink_client

- ℹ️ Unknown function call: dead_letter_queue
  - In: Algorithm 3
  - Name: dead_letter_queue

## Unpinned Spec

- ℹ️ Spec element Algorithm 4 has no artifact pin
  - ID: Algorithm 4
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element Algorithm 5 has no artifact pin
  - ID: Algorithm 5
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element D1 has no artifact pin
  - ID: D1
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element D2 has no artifact pin
  - ID: D2
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element D3 has no artifact pin
  - ID: D3
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element D4 has no artifact pin
  - ID: D4
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element D5 has no artifact pin
  - ID: D5
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element Algorithm 1 has no artifact pin
  - ID: Algorithm 1
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element Algorithm 2 has no artifact pin
  - ID: Algorithm 2
  - Suggestion: Add (@pin path:symbol) to link to implementation

- ℹ️ Spec element Algorithm 3 has no artifact pin
  - ID: Algorithm 3
  - Suggestion: Add (@pin path:symbol) to link to implementation

## Unsatisfied Invariant

- ⚠️ Goal G1 has no elements that enforce it
  - ID: G1
  - Note: Consider migrating G# to I# (invariant)

- ⚠️ Goal G2 has no elements that enforce it
  - ID: G2
  - Note: Consider migrating G# to I# (invariant)
