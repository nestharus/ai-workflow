"""Builds comprehensive prompts for model runners.

Includes the dense spec, all labyrinth source code, and instructions
for the model to write a labyrinth_setup.py module.
"""

from __future__ import annotations

from pathlib import Path

# Labyrinth package root (installed package source)
_LABYRINTH_PKG = Path(__file__).resolve().parents[3] / "labyrinth"


def build_prompt(spec_text: str, codebase_path: Path) -> str:
    """Build a comprehensive prompt with spec + source code + instructions.

    Args:
        spec_text: The dense specification markdown.
        codebase_path: Path to the workspace codebase directory.

    Returns:
        Full prompt string for the model.
    """
    source_listing = _collect_source_files()
    return _FORMAT.format(
        spec_text=spec_text,
        source_listing=source_listing,
    )


def _collect_source_files() -> str:
    """Collect all .py files from the labyrinth package."""
    parts: list[str] = []

    if not _LABYRINTH_PKG.exists():
        return "(labyrinth source not found)"

    for py_file in sorted(_LABYRINTH_PKG.rglob("*.py")):
        # Skip __pycache__ and test files
        if "__pycache__" in str(py_file):
            continue
        if py_file.parent.name == "tests":
            continue

        rel = py_file.relative_to(_LABYRINTH_PKG.parent)
        content = py_file.read_text(encoding="utf-8", errors="replace")
        parts.append(f"### {rel}\n```python\n{content}\n```")

    return "\n\n".join(parts)


_FORMAT = """\
# Task: Implement Labyrinth Integration

You are given a specification for a brownfield Python event-driven data processing system.
Your job is to write a `labyrinth_setup.py` file that sets up the pipeline according to the spec.

## What You Must Do

1. Read the specification below carefully
2. Study the source code of the labyrinth framework below
3. Write a file called `labyrinth_setup.py` in the current directory
4. The file must define a function `setup_labyrinth(pipeline)` that:
   - Creates `Rule` objects with the correct conditions and transforms
   - Registers rules in the `pipeline.rule_registry`
   - Creates `IntegrationPoint` objects and adds them to `pipeline.integration_points`
   - Registers required rules at each integration point
   - Creates `SideEffectChain` objects and adds them via `pipeline.wiring.add_chain()`

## Important Details

- The `pipeline` parameter is a `Pipeline` instance from `spec_manager.labyrinth.integration.pipeline`
- Rules need `ConditionGroup` with `Condition` objects for their conditions
- Each rule needs a transform function: `def transform(record: InputRecord) -> dict[str, Any]`
- Integration points need their `required_rules` registered via `ip.register_rule(rule_id)`
- Side-effect chains connect topics to services (audit, notification, metrics)
- The tests use `pipeline.process_sync(record)` which runs all rules and triggers side effects

## Key Imports

```python
from spec_manager.labyrinth.engine.conditions import (
    Condition, ConditionGroup, ConditionOperator, LogicOperator,
)
from spec_manager.labyrinth.engine.rule import Rule, CompositeRule, CompositionMode
from spec_manager.labyrinth.core.record import InputRecord
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain
```

---

## Specification

{spec_text}

---

## Labyrinth Source Code

{source_listing}

---

## Output

Write ONLY the `labyrinth_setup.py` file. Do not modify any other files.
The file must contain a `setup_labyrinth(pipeline)` function as described above.
"""
