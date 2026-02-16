"""Tasks phase evaluator.

Evaluates the tasks phase by comparing generated tasks
against ground truth expectations.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    PhaseMetrics,
    score_detail_capture,
)
from spec_manager.refinement.workspace import WorkspaceManager


@dataclass
class TasksResult:
    """Result of tasks extraction.

    Attributes:
        tasks_generated: List of generated task descriptions.
        task_ids: List of task identifiers.
        dependencies_mapped: Number of task dependencies mapped.
        priorities_assigned: Number of tasks with priorities.
        file_count: Number of files processed.
    """

    tasks_generated: list[str]
    task_ids: list[str] = None
    dependencies_mapped: int = 0
    priorities_assigned: int = 0
    file_count: int = 0
    parse_failures: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.task_ids is None:
            self.task_ids = []


def extract_tasks_outputs(manager: WorkspaceManager) -> TasksResult:
    """Extract tasks outputs from workspace.

    Args:
        manager: WorkspaceManager for the run.

    Returns:
        TasksResult with generated tasks and counts.
    """
    tasks_dir = manager.structure.manifest_dir / "tasks"

    tasks_generated: list[str] = []
    task_ids: list[str] = []
    dependencies_mapped = 0
    priorities_assigned = 0
    file_count = 0
    parse_failures: list[str] = []

    # Read tasks from manifest
    if tasks_dir.exists():
        for tasks_file in tasks_dir.glob("*.tasks.json"):
            file_count += 1
            try:
                data = json.loads(tasks_file.read_text(encoding="utf-8"))

                for task in data.get("tasks", []):
                    # Extract task description
                    if isinstance(task, str):
                        tasks_generated.append(task)
                    elif isinstance(task, dict):
                        task_desc = task.get("description") or task.get("title") or task.get("name")
                        if task_desc:
                            tasks_generated.append(task_desc)

                        # Extract task ID
                        task_id = task.get("task_id") or task.get("id")
                        if task_id:
                            task_ids.append(task_id)

                        # Count dependencies
                        deps = task.get("dependencies", [])
                        if deps:
                            dependencies_mapped += len(deps)

                        # Count priorities
                        if task.get("priority") is not None:
                            priorities_assigned += 1

            except json.JSONDecodeError as exc:
                parse_failures.append(f"invalid_json:{tasks_file}:{exc}")
                continue
            except OSError as exc:
                parse_failures.append(f"unreadable:{tasks_file}:{exc}")
                continue

    # Also check for individual task files
    for task_file in tasks_dir.glob("*.task.json") if tasks_dir.exists() else []:
        file_count += 1
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))

            task_desc = data.get("description") or data.get("title") or data.get("name")
            if task_desc:
                tasks_generated.append(task_desc)

            task_id = data.get("task_id") or data.get("id")
            if task_id:
                task_ids.append(task_id)

        except json.JSONDecodeError as exc:
            parse_failures.append(f"invalid_json:{task_file}:{exc}")
            continue
        except OSError as exc:
            parse_failures.append(f"unreadable:{task_file}:{exc}")
            continue

    return TasksResult(
        tasks_generated=tasks_generated,
        task_ids=task_ids,
        dependencies_mapped=dependencies_mapped,
        priorities_assigned=priorities_assigned,
        file_count=file_count,
        parse_failures=parse_failures,
    )


def compute_tasks_state_hash(result: TasksResult) -> str:
    """Compute hash of tasks state for loop detection.

    Args:
        result: TasksResult to hash.

    Returns:
        16-character hex digest.
    """
    content = "|".join(
        [
            ",".join(sorted(result.tasks_generated)),
            ",".join(sorted(result.task_ids)),
            str(result.dependencies_mapped),
        ]
    )
    return LoopDetector.compute_hash(content)


def eval_tasks(
    manager: WorkspaceManager,
    ground_truth: PhaseGroundTruth,
    loop_detector: LoopDetector,
    fuzzy_threshold: float = 0.8,
    max_iterations: int = 5,
) -> PhaseMetrics:
    """Evaluate tasks phase against ground truth.

    Args:
        manager: WorkspaceManager for the run.
        ground_truth: Expected outputs for this phase.
        loop_detector: Loop detector for stagnation detection.
        fuzzy_threshold: Threshold for fuzzy string matching.
        max_iterations: Maximum iterations to attempt.

    Returns:
        PhaseMetrics for the tasks phase.
    """
    start_time = time.perf_counter()
    iterations = 0
    converged = False
    trajectory: list[float] = []

    expected_tasks = ground_truth.expected_tasks

    for iteration in range(1, max_iterations + 1):
        iterations = iteration

        # Extract current outputs
        result = extract_tasks_outputs(manager)

        # Score against ground truth
        score = score_detail_capture(
            expected_tasks,
            result.tasks_generated,
            fuzzy_threshold=fuzzy_threshold,
        )

        trajectory.append(score.recall)

        # Check for loop conditions
        state_hash = compute_tasks_state_hash(result)
        loop_status = loop_detector.update(state_hash)

        if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING, LoopStatus.MAX_ITERATIONS}:
            break

        # Check for convergence
        if score.recall >= 0.95:
            converged = True
            break

    # Final scoring
    final_result = extract_tasks_outputs(manager)
    final_score = score_detail_capture(
        expected_tasks,
        final_result.tasks_generated,
        fuzzy_threshold=fuzzy_threshold,
    )

    duration_ms = (time.perf_counter() - start_time) * 1000

    return PhaseMetrics(
        phase_name="tasks",
        detail_score=final_score,
        iterations=iterations,
        converged=converged,
        duration_ms=duration_ms,
        gaps_open=final_score.expected_count - final_score.matched_count,
        gaps_closed=final_score.matched_count,
        errors=final_result.parse_failures,
    )
