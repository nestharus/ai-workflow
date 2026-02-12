# Strategies

**Classification**: Business (reasoning strategies)
**Package**: `spec_manager/strategies/`
**Files**: 16
**Role**: Strategy framework for reasoning layer. Strategies know purpose, when to apply, what tools to use, risks mitigated.

---

## System

### Strategy Framework
**Modules**: `base.py`, `registry.py`, `entity_resolution.py`, `evolution.py`, `definitions/`, `implementations/`
**Purpose**: Defines reusable reasoning strategies that can be loaded from YAML definitions and executed in context.
**Surface API**:
- `StrategyRegistry.load_from_directory() -> StrategyRegistry`
- `StrategyRegistry.get_applicable(context) -> list[Strategy]`
- `Strategy.execute(context) -> StrategyResult`
- `EntityResolver.resolve(references) -> ResolutionResult`
- `StrategyEvolutionPipeline.evolve(strategies) -> EvolutionReport`
**Dependencies**: `schemas.tasks`, strategy definition files
**Consumers**: Interactive steering, research coordination

**Note**: This is the *reasoning strategy* framework (Design #1 lineage), distinct from `planner/strategies/` which is the *planning session pipeline* (Design #3).
