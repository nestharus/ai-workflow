"""Command-line interface for spec manager.

Usage:
    uv run spec <command> [options]

PDD orchestration (primary):
    run                 Run the full PDD pipeline (phases 0-10)
    phase               Run a specific PDD design phase (0-10)
    extract             Phase 0: extract input to PDD format

Module CLIs (standalone PDD modules):
    scan-source         Scan Python source for spec comments/stubs
    branches *          Branch lifecycle management
    pin *               Pin-function management
    plan-v2 *           Algorithmic planning operations
    generate-analysis   Generate analysis file
    adjacency           Run adjacency detection analysis
    coverage *          Entity coverage gap analysis
    eval *              Evaluation framework

Legacy:
    refine              Emit refinement questions and run the intent adapter loop
    ambiguities list    List detected ambiguities
    intent              Intent-agent queue adapters
    evidence-store *    Evidence store management
    phase-02            Run Phase 2 clean/compose/compliance workflow
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from spec_manager.core.project_root import resolve_from_root


def _resolve_spec_folder(raw_path: str) -> Path:
    """Resolve a spec folder path relative to the project root when not absolute."""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    return resolve_from_root(raw_path)


def _resolve_workspace(raw_path: str | None) -> Path:
    """Resolve a workspace path relative to the project root when not absolute."""
    if not raw_path:
        return Path.cwd()
    p = Path(raw_path)
    if p.is_absolute():
        return p
    return resolve_from_root(raw_path)


def _parse_model_profile(raw_profile: str) -> Any:
    """Parse CLI model profile string into a ModelProfile object.

    Expected format: ``name:model_id``. If ``model_id`` is omitted,
    the profile name is reused as the model id.
    """
    from spec_manager.evaluation.model_profile import ModelProfile

    parts = raw_profile.split(":", 1)
    name = parts[0].strip()
    model_id = parts[1].strip() if len(parts) > 1 and parts[1].strip() else name
    return ModelProfile(name=name, producer_model_id=model_id)


def _build_intent_agent(workspace: Path, run_id: str) -> Any:
    """Build a detached Intent Agent for question queue and answer handling."""

    run_dir = workspace / ".pdd_runs" / run_id
    from spec_manager.orchestration.intent_agent.agent import build_intent_agent_with_planner

    return build_intent_agent_with_planner(
        run_dir=run_dir,
        workspace_root=workspace,
        mode="interactive",
    )


def _intent_run_dir(workspace: Path, run_id: str) -> Path:
    """Return the lifecycle run directory for a run id."""
    return workspace / ".pdd_runs" / run_id


def _load_intent_queue(workspace: Path, run_id: str) -> Any:
    """Load the persisted intent queue for an active run."""
    run_dir = _intent_run_dir(workspace, run_id)
    try:
        from spec_manager.orchestration.intent_agent.queue import QuestionQueue

        return QuestionQueue.load(run_dir)
    except Exception:
        return None


def _intent_open_questions(workspace: Path, run_id: str) -> list[Any]:
    """Return open intent queue items from the persisted snapshot."""
    queue = _load_intent_queue(workspace, run_id)
    if queue is None or not hasattr(queue, "get_open_items"):
        return []

    try:
        return list(queue.get_open_items())
    except Exception:
        return []


def _build_intent_session(workspace: Path, run_id: str, *, create_if_missing: bool = False) -> Any:
    """Build and refresh an Intent Agent session for CLI ingress."""
    run_dir = _intent_run_dir(workspace, run_id)
    if not run_dir.exists():
        if create_if_missing:
            run_dir.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

    intent_agent = _build_intent_agent(workspace, run_id)
    intent_agent.resume()
    intent_agent.save_state()
    return intent_agent


def _intent_question_payload(item: object) -> dict[str, Any]:
    """Convert a queue question item to JSON-serializable CLI payload."""
    prompt = item.user_prompt
    answer_spec = prompt.answer_spec

    return {
        "question_id": item.question_id,
        "taxonomy_type": item.taxonomy_type,
        "status": item.status,
        "scope_kind": item.scope_kind,
        "severity": item.blockers.severity,
        "canonical_key": item.canonical_key,
        "text": prompt.text,
        "scenario": prompt.scenario,
        "answer_choices": answer_spec.choices,
        "answer_kind": answer_spec.kind,
        "value_type": answer_spec.value_type,
        "blocked_slices": item.blockers.blocked_slices,
        "blocked_layers": item.blockers.blocked_layers,
    }


def _taxonomy_hint_for_ambiguity(ambiguity_type: str) -> str:
    kind = str(ambiguity_type).strip().lower()
    if kind == "missing_condition":
        return "CONSTRAINT"
    if kind == "undefined_boundary":
        return "SCOPE"
    if kind == "vague_integration":
        return "IMPLEMENTATION"
    return "UNKNOWN"


def _slugify(raw: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "_" for ch in str(raw)]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "unknown"


def _resolve_refine_spec_path(workspace: Path, run_id: str) -> Path:
    candidates = [
        workspace / "spec.md",
        workspace / "runs" / run_id / "spec.md",
        workspace / ".pdd_runs" / run_id / "spec.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Spec not found. Looked for: {searched}")


def _emit_refine_signals(
    *,
    run_dir: Path,
    run_id: str,
    ambiguities: list[Any],
    spec_path: Path,
) -> tuple[int, int]:
    from spec_manager.orchestration.intent_agent.signals import (
        SignalBlocking,
        SignalContext,
        SignalQuestion,
        SignalSource,
        SpecRefItem,
        UserQuestionSignal,
        UserQuestionSignalStore,
    )

    store = UserQuestionSignalStore(run_dir)
    existing = store.read_all().signals
    known_signal_ids = {
        str(signal.source.signal_id).strip()
        for signal in existing
        if str(signal.source.signal_id).strip()
    }

    emitted = 0
    skipped = 0
    for ambiguity in ambiguities:
        ambiguity_id = _slugify(getattr(ambiguity, "ambiguity_id", ""))
        signal_id = f"refine:{run_id}:{ambiguity_id}"
        if signal_id in known_signal_ids:
            skipped += 1
            continue

        question_text = str(getattr(ambiguity, "suggested_question", "")).strip()
        if not question_text:
            question_text = str(getattr(ambiguity, "source_text", "")).strip()
        if not question_text:
            question_text = "Please clarify this ambiguous requirement."

        signal = UserQuestionSignal(
            run_id=run_id,
            source=SignalSource(
                kind="SLICE_AGENT",
                trace_id=str(getattr(ambiguity, "ambiguity_id", "")).strip(),
                slice_id="__system__",
                layer="l1",
                signal_id=signal_id,
            ),
            question=SignalQuestion(
                text=question_text,
                taxonomy_hint=_taxonomy_hint_for_ambiguity(
                    str(getattr(ambiguity, "ambiguity_type", ""))
                ),
                canonical_key_hint=f"refine.ambiguity.{ambiguity_id}",
                answer_spec_hint={
                    "preferred_kind": "choice_or_text",
                    "choices": [
                        {"id": "resolved_as_written", "label": "Requirement is already clear"},
                        {"id": "needs_clarification", "label": "Requirement needs clarification"},
                    ],
                },
            ),
            context=SignalContext(
                blocking=SignalBlocking(severity="BLOCKING", blocked_slices=["__system__"]),
                spec_refs=[
                    SpecRefItem(
                        spec_text=str(getattr(ambiguity, "source_text", "")).strip(),
                        source_file=str(spec_path),
                        source_line_hint=0,
                    )
                ],
            ),
            payload={
                "ambiguity_id": str(getattr(ambiguity, "ambiguity_id", "")).strip(),
                "ambiguity_type": str(getattr(ambiguity, "ambiguity_type", "")).strip(),
                "confidence": float(getattr(ambiguity, "confidence", 0.0)),
                "source_location": str(getattr(ambiguity, "source_location", "")).strip(),
                "source_text": str(getattr(ambiguity, "source_text", "")).strip(),
                "spec_path": str(spec_path),
            },
        )
        store.write(signal)
        known_signal_ids.add(signal_id)
        emitted += 1

    return emitted, skipped


def _print_intent_question(item: Any, *, turn: int, max_turns: int) -> None:
    payload = _intent_question_payload(item)
    print(
        f"\n[{turn}/{max_turns}] [{payload['severity']}] "
        f"{payload['question_id']} [{payload['taxonomy_type']}]"
    )
    print(f"  Text: {payload['text']}")
    if payload["scenario"]:
        print(f"  Scenario: {payload['scenario']}")
    if payload["answer_choices"]:
        print("  Choices:")
        for choice in payload["answer_choices"]:
            print(f"    {choice.get('id', '')}: {choice.get('label', '')}")


def _read_intent_answer(item: Any) -> tuple[str, str] | None:
    payload = _intent_question_payload(item)
    raw_choices = payload.get("answer_choices", [])
    choice_labels: dict[str, str] = {}
    for choice in raw_choices:
        choice_id = str(choice.get("id", "")).strip()
        label = str(choice.get("label", "")).strip()
        if not choice_id:
            continue
        choice_labels[choice_id] = label

    while True:
        try:
            raw = input("Answer (/quit to stop): ").strip()
        except EOFError:
            return None
        except KeyboardInterrupt:
            print()
            return None

        lowered = raw.lower()
        if lowered in {"/quit", "quit", "exit"}:
            return None
        if not raw:
            print("Answer text is required.")
            continue

        if raw in choice_labels:
            label = choice_labels.get(raw, "")
            return label or raw, raw

        matched_choice = ""
        for choice_id, label in choice_labels.items():
            if label and lowered == label.lower():
                matched_choice = choice_id
                break
        return raw, matched_choice


def _run_intent_loop(
    *,
    workspace: Path,
    run_id: str,
    max_turns: int,
    create_if_missing: bool = False,
) -> int:
    if max_turns <= 0:
        print("max_turns must be greater than 0.", file=sys.stderr)
        return 2

    try:
        intent_agent = _build_intent_session(
            workspace,
            run_id,
            create_if_missing=create_if_missing,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Failed to refresh intent state: {exc}", file=sys.stderr)
        return 1
    turn = 0

    while turn < max_turns:
        question = intent_agent.next_question()
        if question is None:
            print(f"No open intent questions for run_id={run_id}.")
            intent_agent.save_state()
            return 0

        turn += 1
        _print_intent_question(question, turn=turn, max_turns=max_turns)
        answer = _read_intent_answer(question)
        if answer is None:
            print("Intent loop paused by user.")
            intent_agent.save_state()
            return 0

        raw_text, choice_id = answer
        try:
            translation = intent_agent.handle_answer(
                question_id=question.question_id,
                raw_text=raw_text,
                selected_choice_id=choice_id,
            )
            intent_agent.save_state()
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            print(f"Failed to submit intent answer: {exc}", file=sys.stderr)
            return 1

        answer_id = getattr(translation, "answer_id", "")
        print(f"  Saved translation: {answer_id}")

    print(f"Stopped after {max_turns} answers. Re-run to continue.")
    intent_agent.save_state()
    return 2


def cmd_run(args: argparse.Namespace) -> int:
    """Run the full PDD pipeline (phases 0-10)."""
    from spec_manager.orchestration.pdd_orchestrator import PDD_PHASE_ORDER, PddOrchestrator
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    run_id = args.run_id
    input_folder = Path(args.input) if args.input else Path.cwd()

    print(f"PDD pipeline: run_id={run_id}")
    print(f"  Input: {input_folder}")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
    if not manager.is_initialized:
        manager.initialize()

    orchestrator = PddOrchestrator(manager)
    summary = orchestrator.run()

    completed = summary.get("completed", [])
    failed = summary.get("failed", [])
    skipped = summary.get("skipped", [])

    print(f"\nPDD pipeline finished for run {run_id}:")
    if completed:
        print(f"  Completed: {', '.join(completed)}")
    if skipped:
        print(f"  Skipped (already done): {', '.join(skipped)}")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
        return 1

    total = len(PDD_PHASE_ORDER)
    done = len(completed) + len(skipped)
    print(f"  Progress: {done}/{total} phases")
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    """Run the full PDD lifecycle (Build → QA → Architecture → Code Quality)."""
    from spec_manager.orchestration.pdd_lifecycle import PddLifecycle
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    run_id = args.run_id
    input_folder = Path(args.input) if args.input else Path.cwd()
    mode = args.mode
    use_research = args.research
    steering_path = Path(args.steering) if args.steering else None
    use_worktrees = getattr(args, "worktrees", False)
    model_profile = _parse_model_profile(args.model_profile) if args.model_profile else None

    print(f"PDD lifecycle: run_id={run_id}")
    print(f"  Input: {input_folder}")
    print(f"  Mode: {mode}")
    if use_research:
        print("  Research: enabled")
    if steering_path:
        print(f"  Steering: {steering_path}")
    if use_worktrees:
        print("  Worktrees: enabled")
    if model_profile is not None:
        print(f"  Model profile: {model_profile.name} ({model_profile.producer_model_id})")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
    if not manager.is_initialized:
        manager.initialize()

    # Setup worktree manager if requested
    worktree_manager = None
    if use_worktrees:
        from spec_manager.vcs.operations import GitVcs
        from spec_manager.vcs.worktree import WorktreeManager

        vcs = GitVcs(repo_root=input_folder)
        worktree_manager = WorktreeManager(
            vcs=vcs, workspace_root=input_folder, run_id=run_id or "default"
        )

    lifecycle = PddLifecycle(
        manager,
        mode=mode,
        use_research=use_research,
        steering_path=steering_path,
        worktree_manager=worktree_manager,
        model_profile=model_profile,
    )

    # Run specific phase or full lifecycle
    phase_name = getattr(args, "lifecycle_phase", None)
    if phase_name:
        runner = getattr(lifecycle, phase_name, None)
        if runner is None:
            print(f"Unknown lifecycle phase: {phase_name}", file=sys.stderr)
            return 1
        result = runner()
        print(f"\nLifecycle phase '{phase_name}' complete:")
    else:
        result = lifecycle.run()
        print("\nPDD lifecycle complete:")

    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_quality(args: argparse.Namespace) -> int:
    """Compute quality scorecard for a run."""
    from spec_manager.evaluation.digests import (
        build_architecture_digest,
        build_code_digest,
    )
    from spec_manager.evaluation.quality import QualityReporter

    workspace = Path.cwd()
    run_id = args.run_id
    run_dir = workspace / ".pdd_runs" / run_id
    snapshot_dir = run_dir / "snapshots" / "final_files"

    print(f"Computing quality scorecard for run: {run_id}")

    arch_digest = build_architecture_digest(
        workspace,
        run_id,
        git_sha="",
        producer_model_id="",
    )
    code_digest = build_code_digest(
        workspace,
        run_id,
        git_sha="",
        producer_model_id="",
    )
    producer_model_id = (
        (arch_digest.get("model") or {}).get("producer_model_id")
        or (code_digest.get("model") or {}).get("producer_model_id")
        or ""
    )

    arch_judge = None
    code_judge = None
    spec_judge = None

    if args.judges:
        print("  Running LLM judges...")
        from spec_manager.refinement.evals.judges.arch_quality import ArchitectureQualityJudge
        from spec_manager.refinement.evals.judges.code_quality import CodeQualityJudge
        from spec_manager.refinement.evals.judges.spec_fidelity import SpecFidelityJudge

        arch_j = ArchitectureQualityJudge(
            workspace=workspace,
            model_id=args.judge_model,
            producer_model_id=producer_model_id,
            allow_self_judge=args.allow_self_judge,
        )
        arch_result = arch_j.evaluate(arch_digest)
        arch_judge = arch_result.model_dump()

        code_j = CodeQualityJudge(
            workspace=workspace,
            model_id=args.judge_model,
            producer_model_id=producer_model_id,
            allow_self_judge=args.allow_self_judge,
        )
        code_result = code_j.evaluate(
            code_digest,
            snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
        )
        code_judge = code_result.model_dump()

        # Spec fidelity requires spec summary
        spec_summary_path = run_dir / "spec_summary.json"
        if spec_summary_path.exists():
            import json as _json

            spec_summary = _json.loads(spec_summary_path.read_text())
            spec_j = SpecFidelityJudge(
                workspace=workspace,
                model_id=args.judge_model,
                producer_model_id=producer_model_id,
                allow_self_judge=args.allow_self_judge,
            )
            spec_result = spec_j.evaluate(
                spec_summary,
                code_digest,
                snapshot_dir=snapshot_dir if snapshot_dir.exists() else None,
            )
            spec_judge = spec_result.model_dump()

    reporter = QualityReporter(workspace, run_id)
    scorecard = reporter.compute(
        arch_digest,
        code_digest,
        arch_judge_output=arch_judge,
        code_judge_output=code_judge,
        spec_judge_output=spec_judge,
    )
    json_path, md_path = reporter.write(scorecard)

    print("\nQuality scorecard written:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")
    print(f"  Status: {scorecard.overall_status}")
    print(f"  Arch: {scorecard.arch_quality_score:.3f}")
    print(f"  Code: {scorecard.code_quality_score:.3f}")
    print(f"  Spec: {scorecard.spec_fidelity_score:.3f}")
    return 0


def cmd_phase(args: argparse.Namespace) -> int:
    """Run a specific PDD design phase (0-10)."""
    from spec_manager.orchestration.pdd_orchestrator import PDD_PHASE_ORDER, PddOrchestrator
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    phase_number = args.phase_number
    if phase_number < 0 or phase_number > 10:
        print(f"Invalid phase number: {phase_number}. Must be 0-10.", file=sys.stderr)
        return 1

    phase = PDD_PHASE_ORDER[phase_number]
    run_id = args.run_id
    input_folder = Path(args.input) if args.input else Path.cwd()

    print(f"PDD phase {phase_number} ({phase.value}): run_id={run_id}")
    print(f"  Input: {input_folder}")

    manager = WorkspaceManager(run_id=run_id, input_folder=input_folder)
    if not manager.is_initialized:
        manager.initialize()

    orchestrator = PddOrchestrator(manager)
    try:
        outputs = orchestrator.run_phase(phase)
        print(f"\nPhase {phase_number} ({phase.value}) completed.")
        if outputs:
            for key, value in outputs.items():
                print(f"  {key}: {value}")
        return 0
    except NotImplementedError as exc:
        print(f"\nPhase {phase_number} ({phase.value}) not yet implemented: {exc}")
        return 1
    except Exception as exc:
        print(f"\nPhase {phase_number} ({phase.value}) failed: {exc}", file=sys.stderr)
        return 1


def cmd_extract(args: argparse.Namespace) -> int:
    """Phase 0: Route freeform prose into PDD format.

    Uses LLM-driven routing (summarize, discover libraries, route spans,
    check coverage, assemble verbatim output).
    """
    from spec_manager.intake import run_phase0

    input_path = Path(args.path) if args.path else Path.cwd()
    run_id = args.run_id
    output_dir = Path.cwd() / "runs" / run_id / "phase0_output"

    print(f"PDD routing (phase 0): run_id={run_id}")
    print(f"  Input: {input_path}")
    print(f"  Output: {output_dir}")

    try:
        outputs = run_phase0(input_path, output_dir)
        print("\nPhase 0 routing completed.")
        for key, value in outputs.items():
            print(f"  {key}: {value}")
        return 0
    except Exception as exc:
        print(f"\nPhase 0 routing failed: {exc}", file=sys.stderr)
        return 1


def cmd_refine(args: argparse.Namespace) -> int:
    """Emit refinement ambiguity signals and run the intent adapter loop."""
    from spec_manager.refinement.interactive.ambiguity_detector import AmbiguityDetector

    workspace = _resolve_workspace(args.workspace)
    run_id = args.run_id

    try:
        spec_path = _resolve_refine_spec_path(workspace, run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    run_dir = _intent_run_dir(workspace, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    spec_text = spec_path.read_text(encoding="utf-8")
    detector = AmbiguityDetector()
    ambiguities = detector.detect(spec_text, spec_path.parent)
    emitted, skipped = _emit_refine_signals(
        run_dir=run_dir,
        run_id=run_id,
        ambiguities=ambiguities,
        spec_path=spec_path,
    )

    print(f"Refinement ingest: run_id={run_id}")
    print(f"  Workspace: {workspace}")
    print(f"  Spec: {spec_path}")
    print(f"  Ambiguities detected: {len(ambiguities)}")
    print(f"  Signals emitted: {emitted}")
    if skipped:
        print(f"  Signals skipped (already emitted): {skipped}")

    if args.emit_only:
        return 0

    return _run_intent_loop(
        workspace=workspace,
        run_id=run_id,
        max_turns=args.max_turns,
        create_if_missing=True,
    )


def cmd_intent(args: argparse.Namespace) -> int:
    """Dispatch intent subcommands."""
    command = args.intent_command
    if command == "questions":
        return cmd_intent_questions(args)
    if command == "answer":
        return cmd_intent_answer(args)
    if command == "run":
        return cmd_intent_run(args)
    print(f"Unknown intent command: {command}", file=sys.stderr)
    return 1


def cmd_intent_questions(args: argparse.Namespace) -> int:
    """List open intent questions for a lifecycle run."""
    workspace = _resolve_workspace(args.workspace)
    run_id = args.run_id
    run_dir = _intent_run_dir(workspace, run_id)

    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    try:
        _build_intent_session(workspace, run_id)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Failed to refresh intent state: {exc}", file=sys.stderr)
        return 1

    open_items = _intent_open_questions(workspace, run_id)
    payload = [_intent_question_payload(item) for item in open_items]

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f"Open intent questions for run_id={run_id} (workspace={workspace})")
    if not payload:
        print("No open intent questions.")
        return 0

    for item in payload:
        print(f"\n[{item['severity']}] {item['question_id']} [{item['taxonomy_type']}]")
        print(f"  Text: {item['text']}")
        if item["scenario"]:
            print(f"  Scenario: {item['scenario']}")
        if item["answer_choices"]:
            print("  Choices:")
            for choice in item["answer_choices"]:
                print(f"    {choice.get('id', '')}: {choice.get('label', '')}")

    return 0


def cmd_intent_answer(args: argparse.Namespace) -> int:
    """Submit an answer for a queued intent question."""
    workspace = _resolve_workspace(args.workspace)
    run_id = args.run_id
    question_id = args.question_id
    answer = " ".join(args.answer).strip()
    if not answer:
        print("Answer text is required.", file=sys.stderr)
        return 1

    run_dir = _intent_run_dir(workspace, run_id)
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    intent_agent = _build_intent_session(workspace, run_id)
    try:
        translation = intent_agent.handle_answer(
            question_id=question_id,
            raw_text=answer,
            selected_choice_id=args.choice or "",
        )
        intent_agent.save_state()
    except Exception as exc:
        print(f"Failed to submit intent answer: {exc}", file=sys.stderr)
        return 1

    open_count = len(_intent_open_questions(workspace, run_id))

    if args.json:
        print(
            json.dumps(
                {
                    "question_id": question_id,
                    "answer_id": getattr(translation, "answer_id", ""),
                    "open_blocking_count": open_count,
                },
                indent=2,
            )
        )
        return 0

    print(f"Submitted answer for run_id={run_id}, question_id={question_id}")
    print(f"  Translation: {getattr(translation, 'answer_id', '')}")
    print(f"  Open question count: {open_count}")
    return 0


def cmd_intent_run(args: argparse.Namespace) -> int:
    """Run the terminal adapter loop for queued intent questions."""
    workspace = _resolve_workspace(args.workspace)
    run_id = args.run_id
    run_dir = _intent_run_dir(workspace, run_id)

    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    return _run_intent_loop(workspace=workspace, run_id=run_id, max_turns=args.max_turns)


def cmd_ambiguities_list(args: argparse.Namespace) -> int:
    """List detected ambiguities in a spec."""
    from spec_manager.refinement.interactive.ambiguity_detector import AmbiguityDetector

    workspace = Path(args.workspace) if args.workspace else Path.cwd() / "runs" / args.run_id
    if not workspace.exists():
        print(f"Workspace not found: {workspace}")
        return 1

    spec_path = workspace / "spec.md"
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        return 1

    spec_text = spec_path.read_text(encoding="utf-8")

    print(f"Detecting ambiguities: run_id={args.run_id}")
    print(f"  Workspace: {workspace}")

    detector = AmbiguityDetector()
    ambiguities = detector.detect(spec_text, workspace)

    if not ambiguities:
        print("\nNo ambiguities detected.")
        return 0

    print(f"\nFound {len(ambiguities)} ambiguities:\n")
    for amb in ambiguities:
        print(f"  [{amb.ambiguity_id}] ({amb.ambiguity_type}, confidence={amb.confidence:.0%})")
        print(f"    Location: {amb.source_location}")
        print(f"    Text: {amb.source_text[:120]}{'...' if len(amb.source_text) > 120 else ''}")
        print(f"    Question: {amb.suggested_question}")
        print()

    return 0


def cmd_evidence_store(args: argparse.Namespace) -> int:
    """Handle evidence-store subcommands."""
    evidence_store_commands = {
        "hollow": cmd_evidence_store_hollow,
        "rebuild-index": cmd_evidence_store_rebuild_index,
        "search": cmd_evidence_store_search,
        "status": cmd_evidence_store_status,
    }
    return evidence_store_commands[args.evidence_store_command](args)


def cmd_evidence_store_hollow(args: argparse.Namespace) -> int:
    """Manually trigger hollow-out for one or all libraries."""
    from spec_manager.refinement.hollowed_spec.hooks import on_spec_completed
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)

    if not manager.structure.libraries_dir.exists():
        print(f"Libraries directory not found: {manager.structure.libraries_dir}")
        return 1

    if args.lib_id:
        lib_ids = [args.lib_id]
    else:
        lib_ids = [d.name for d in sorted(manager.structure.libraries_dir.iterdir()) if d.is_dir()]

    if not lib_ids:
        print("No libraries found.")
        return 0

    hollowed_count = 0
    for lib_id in lib_ids:
        spec_path = manager.structure.libraries_dir / lib_id / "spec.md"
        if not spec_path.exists():
            print(f"  Skipping {lib_id}: no spec.md")
            continue
        print(f"  Hollowing {lib_id}...")
        on_spec_completed(lib_id, manager)
        hollowed_count += 1

    print(f"Hollowed {hollowed_count} library specs.")
    return 0


def cmd_evidence_store_rebuild_index(args: argparse.Namespace) -> int:
    """Rebuild the evidence index from scratch."""
    from spec_manager.refinement.hollowed_spec.hooks import rebuild_evidence_index
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    count = rebuild_evidence_index(manager)
    print(f"Rebuilt evidence index: {count} specs indexed.")
    return 0


def cmd_evidence_store_search(args: argparse.Namespace) -> int:
    """Interactive search for testing/debugging."""
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
    from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    index_path = manager.structure.evidence_index_path

    if not index_path.exists():
        print(f"Evidence index not found: {index_path}")
        print("Run 'evidence-store rebuild-index' first.")
        return 1

    index = EvidenceIndex.load(index_path)
    searcher = EvidenceSearcher(index)
    results = searcher.search(query=args.query, max_results=args.max_results)

    if not results:
        print("No results found.")
        return 0

    print(f"Found {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        print(f"  {i}. [{result.lib_id}] {result.section_path} (score={result.score:.2f})")
        text_preview = result.paragraph.text[:200]
        if len(result.paragraph.text) > 200:
            text_preview += "..."
        print(f"     {text_preview}")
        if result.matched_keywords:
            print(f"     Keywords: {', '.join(result.matched_keywords)}")
        if result.matched_entities:
            print(f"     Entities: {', '.join(result.matched_entities)}")
        print()

    return 0


def cmd_evidence_store_status(args: argparse.Namespace) -> int:
    """Show index stats."""
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager

    input_folder = Path(args.input_folder)
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)
    index_path = manager.structure.evidence_index_path

    if not index_path.exists():
        print(f"Evidence index not found: {index_path}")
        print("Run 'evidence-store rebuild-index' first.")
        return 1

    index = EvidenceIndex.load(index_path)

    print("Evidence Store Status:")
    print(f"  Indexed specs: {len(index.specs)}")
    print(f"  Total paragraphs: {index.total_paragraphs}")
    print(f"  Keyword count: {index.total_keywords}")
    print(f"  Entity count: {index.total_entities}")
    print()

    if index.specs:
        print("  Libraries:")
        for lib_id, spec in sorted(index.specs.items()):
            print(f"    {lib_id}: {len(spec.sections)} sections, {len(spec.paragraphs)} paragraphs")

    return 0


def cmd_adjacency(args: argparse.Namespace) -> int:
    """Run adjacency analysis from declared relationship facts."""
    from spec_manager.analysis.adjacency.runner import (
        AdjacencyAnalysisConfig,
        run_adjacency_analysis,
        save_report,
    )

    source_dirs = [Path(d) for d in args.source_dir] if args.source_dir else []
    spec_dirs = [Path(d) for d in args.spec_dir] if args.spec_dir else []
    relationship_fact_paths = (
        [Path(p) for p in args.relationship_facts] if args.relationship_facts else []
    )
    if args.pin_registry:
        relationship_fact_paths.extend(Path(p) for p in args.pin_registry)

    if not source_dirs and not spec_dirs and not relationship_fact_paths:
        print(
            "At least one --relationship-facts, --source-dir, or --spec-dir is required.",
        )
        return 1

    config = AdjacencyAnalysisConfig(
        source_dirs=source_dirs,
        spec_dirs=spec_dirs,
        relationship_fact_paths=relationship_fact_paths,
        output_format=args.format,
        output_path=Path(args.output) if args.output else None,
    )

    print("Running adjacency analysis...")
    if source_dirs:
        print(f"  Source dirs: {', '.join(str(d) for d in source_dirs)}")
    if spec_dirs:
        print(f"  Spec dirs: {', '.join(str(d) for d in spec_dirs)}")
    if relationship_fact_paths:
        print(f"  Relationship facts: {', '.join(str(p) for p in relationship_fact_paths)}")

    try:
        report = run_adjacency_analysis(config)
    except Exception as exc:
        print(f"Adjacency analysis failed: {exc}")
        return 1

    print("\nAdjacency Analysis Results:")
    print(f"  Total nodes: {report.total_nodes}")
    print(f"  Total edges: {report.total_edges}")
    print(f"  Connected components: {report.num_components}")

    if report.signal_type_counts:
        print("\n  Signal types:")
        for sig_type, count in sorted(report.signal_type_counts.items()):
            weight = report.signal_type_weights.get(sig_type, 0.0)
            print(f"    {sig_type}: {count} edges (weight: {weight:.2f})")

    if report.disconnected_warnings:
        print(f"\n  Warnings ({len(report.disconnected_warnings)}):")
        for warning in report.disconnected_warnings:
            print(f"    - {warning}")

    if args.output:
        output_path = save_report(report, config)
        print(f"\n  Report saved: {output_path}")
    elif args.json:
        print("\nJSON:")
        print(json.dumps(report.to_dict(), indent=2))

    return 0


def cmd_phase_02(args: argparse.Namespace) -> int:
    """Run Phase 2 clean/compose/compliance workflow."""
    run_id = args.run_id

    from spec_manager.refinement.workflows.phase_02_clean import run_phase_02_clean

    result = run_phase_02_clean(run_id)
    if result.get("success"):
        print(f"Phase 2 completed successfully for run {run_id}")
        return 0

    print(f"Phase 2 failed: {result.get('error')}", file=sys.stderr)
    return 1


def cmd_generate_analysis(args: argparse.Namespace) -> int:
    """Generate the analysis file (computed artifact)."""
    from spec_manager.analysis.generator import (
        generate_analysis_file,
        write_analysis_json,
    )
    from spec_manager.analysis.report_renderer import render_analysis_markdown

    spec_folder = _resolve_spec_folder(args.spec_folder)
    libraries_dir = spec_folder / "libraries"

    print(f"Generating analysis file for: {spec_folder}")
    print(f"  Algorithmic dir: {spec_folder}")
    print(f"  Architectural dir: {libraries_dir}")

    analysis = generate_analysis_file(
        algorithmic_dir=spec_folder,
        architectural_dir=libraries_dir,
        run_id="",
    )

    output_format = args.format if hasattr(args, "format") else "both"

    if output_format in ("json", "both"):
        json_dir = spec_folder / "analysis"
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / "analysis.json"
        write_analysis_json(analysis, json_path)
        print(f"  JSON: {json_path}")

    if output_format in ("markdown", "both"):
        reports_dir = spec_folder / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = reports_dir / "analysis.md"
        md_content = render_analysis_markdown(analysis)
        md_path.write_text(md_content, encoding="utf-8")
        print(f"  Markdown: {md_path}")

    if hasattr(args, "json") and args.json:
        print()
        print(json.dumps(analysis.model_dump(), indent=2, sort_keys=True))

    summary = analysis.summary
    print("\nAnalysis Summary:")
    print(f"  Total atoms: {summary.get('total_atoms', 0)}")
    print(f"  Implemented: {summary.get('implemented_atoms', 0)}")
    print(f"  Unimplemented: {summary.get('unimplemented_atoms', 0)}")
    print(f"  Orphaned architecture: {summary.get('orphaned_architecture', 0)}")
    print(f"  Lineage edges: {summary.get('total_lineage_edges', 0)}")

    return 0


def cmd_scan_source(args: argparse.Namespace) -> int:
    """Run edit-in-place source analysis on a Python file or directory.

    Produces a gap report showing all spec comments (gaps) and stub functions.
    """
    from spec_manager.core.edit_in_place import (
        ProjectTranslationState,
        analyze_file,
        analyze_project,
        format_gap_report,
    )

    target = Path(args.path)
    if not target.exists():
        print(f"Path not found: {target}")
        return 1

    exclude_patterns = args.exclude if args.exclude else None

    if target.is_file():
        file_state = analyze_file(str(target))
        # Wrap in ProjectTranslationState for uniform handling
        project_state = ProjectTranslationState(files={str(target): file_state})
    else:
        project_state = analyze_project(str(target), exclude=exclude_patterns)

    output_format = args.format if hasattr(args, "format") and args.format else "text"

    if output_format == "json":
        import dataclasses

        def _to_dict(obj: object) -> object:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_to_dict(i) for i in obj]
            if hasattr(obj, "value"):
                return obj.value  # type: ignore[union-attr]
            return obj

        result_dict = {
            "files": {path: _to_dict(state) for path, state in project_state.files.items()},
            "total_gaps": project_state.total_gaps,
            "total_functions": project_state.total_functions,
            "is_complete": project_state.is_complete,
        }
        output_text = json.dumps(result_dict, indent=2)
    else:
        output_text = format_gap_report(project_state)

    if hasattr(args, "output") and args.output:
        output_path = Path(args.output)
        output_path.write_text(output_text)
        print(f"Report written to: {output_path}")
    else:
        print(output_text)

    return 0


def cmd_branches(args: argparse.Namespace) -> int:
    """Handle branches subcommands."""
    branches_commands = {
        "init": cmd_branches_init,
        "gaps": cmd_branches_gaps,
        "promote": cmd_branches_promote,
        "analyze": cmd_branches_analyze,
        "status": cmd_branches_status,
        "run": cmd_branches_run,
    }
    return branches_commands[args.branches_command](args)


def cmd_branches_init(args: argparse.Namespace) -> int:
    """Initialize branch layout and optionally collapse codebase."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_init

    source_dir = Path(args.source_dir) if args.source_dir else None
    if args.from_scan:
        return cmd_branches_init_from_scan(args)

    result = run_branch_init(args.run_id, source_dir=source_dir)
    if not result.get("success"):
        print(f"Branch init failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Branch layout initialized for run {args.run_id}")
    print(f"  Atoms registered: {outputs.get('atom_count', 0)}")
    if outputs.get("atom_count_by_kind"):
        for kind, count in outputs["atom_count_by_kind"].items():
            print(f"    {kind}: {count}")
    if outputs.get("collapse_warnings"):
        print(f"  Warnings: {len(outputs['collapse_warnings'])}")
    return 0


def cmd_branches_init_from_scan(args: argparse.Namespace) -> int:
    """Initialize branches using edit-in-place scan."""
    from spec_manager.refinement.workflows.branch_lifecycle import (
        run_branch_init_from_edit_in_place,
    )

    source_dir = Path(args.from_scan)
    if not source_dir.exists():
        print(f"Source directory not found: {source_dir}", file=sys.stderr)
        return 1

    result = run_branch_init_from_edit_in_place(args.run_id, source_dir=source_dir)
    if not result.get("success"):
        print(f"Branch init from scan failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Branch layout initialized from scan for run {args.run_id}")
    print(f"  Atoms registered: {outputs.get('atom_count', 0)}")
    print(f"  EIP lineage mappings: {outputs.get('eip_lineage_count', 0)}")
    print(f"  EIP gaps found: {outputs.get('eip_gap_count', 0)}")
    return 0


def cmd_branches_gaps(args: argparse.Namespace) -> int:
    """Scan algorithmic branch for gaps."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_gaps

    result = run_branch_gaps(args.run_id)
    if not result.get("success"):
        print(f"Branch gaps scan failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Gap scan complete for run {args.run_id}")
    print(f"  Total gaps: {outputs.get('total_gaps', 0)}")
    if outputs.get("gaps_by_type"):
        for gap_type, count in outputs["gaps_by_type"].items():
            print(f"    {gap_type}: {count}")
    return 0


def cmd_branches_promote(args: argparse.Namespace) -> int:
    """Promote atoms to architectural branch."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_promote

    atom_ids = args.atom_ids if hasattr(args, "atom_ids") and args.atom_ids else None
    result = run_branch_promote(
        args.run_id,
        skip_compliance=args.skip_compliance,
        atom_ids=atom_ids,
    )
    if not result.get("success"):
        print(f"Branch promote failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Promotion complete for run {args.run_id}")
    print(f"  Promoted: {outputs.get('promoted_count', 0)}")
    print(f"  Skipped: {outputs.get('skipped_count', 0)}")
    print(f"  New pins: {len(outputs.get('new_pin_ids', []))}")
    compliance = outputs.get("compliance_passed")
    if compliance is not None:
        print(f"  Compliance passed: {compliance}")
    return 0


def cmd_branches_analyze(args: argparse.Namespace) -> int:
    """Regenerate analysis branch."""
    from spec_manager.refinement.workflows.branch_lifecycle import run_branch_analyze

    result = run_branch_analyze(args.run_id)
    if not result.get("success"):
        print(f"Branch analyze failed: {result.get('error')}", file=sys.stderr)
        return 1

    outputs = result.get("outputs", {})
    print(f"Analysis complete for run {args.run_id}")
    print(f"  Atoms analyzed: {outputs.get('atom_count', 0)}")
    print(f"  Orphaned: {outputs.get('orphaned_count', 0)}")
    print(f"  Subgraphs: {outputs.get('subgraph_count', 0)}")
    return 0


def cmd_branches_status(args: argparse.Namespace) -> int:
    """Show branch system status."""
    from spec_manager.refinement.workspace import WorkspaceManager as RefWorkspaceManager
    from spec_manager.refinement.workspace.state import Phase

    input_folder = Path(".")
    manager = RefWorkspaceManager(run_id=args.run_id, input_folder=input_folder)

    if not manager.is_initialized:
        print("Workspace not initialized.")
        return 0

    branch_initialized = manager.branches.is_initialized()
    print(f"Branch status for run {args.run_id}:")
    print(f"  Initialized: {branch_initialized}")

    if branch_initialized:
        import contextlib

        with contextlib.suppress(Exception):
            manager.branches.load()
        atoms = manager.branches.list_atoms()
        pins = manager.branches.pin_registry.list_all()
        slices = list(manager.branches.slice_navigator._slices.values())
        print(f"  Atoms: {len(atoms)}")
        print(f"  Pins: {len(pins)}")
        print(f"  Slices: {len(slices)}")

    # Show branch phase statuses
    branch_phases = [
        Phase.BRANCH_INIT,
        Phase.BRANCH_GAPS,
        Phase.BRANCH_PROMOTE,
        Phase.BRANCH_ANALYZE,
    ]
    print("  Phase status:")
    for phase in branch_phases:
        result = manager.state.phases[phase.value]
        print(f"    {phase.value}: {result.status.value}")

    return 0


def cmd_branches_run(args: argparse.Namespace) -> int:
    """Run all branch lifecycle phases in sequence."""
    from spec_manager.refinement.workflows.branch_lifecycle import (
        run_branch_analyze,
        run_branch_gaps,
        run_branch_init,
        run_branch_promote,
    )

    source_dir = Path(args.source_dir) if args.source_dir else None

    steps = [
        ("init", lambda: run_branch_init(args.run_id, source_dir=source_dir)),
        ("gaps", lambda: run_branch_gaps(args.run_id)),
        (
            "promote",
            lambda: run_branch_promote(args.run_id, skip_compliance=args.skip_compliance),
        ),
        ("analyze", lambda: run_branch_analyze(args.run_id)),
    ]

    for name, step_fn in steps:
        print(f"Running branch {name}...")
        result = step_fn()
        if not result.get("success"):
            print(f"Branch {name} failed: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"  Branch {name} completed.")

    print(f"All branch phases completed for run {args.run_id}.")
    return 0


def cmd_planner(args: argparse.Namespace) -> int:
    """Handle top-level planner trace commands."""
    from spec_manager.refinement.evals.cli import (
        cmd_planner_diff,
        cmd_planner_list,
        cmd_planner_replay,
        cmd_planner_show,
        cmd_planner_summarize_run,
        cmd_planner_timeline,
    )

    if args.planner_surface_command != "trace":
        print(f"Unknown planner command: {args.planner_surface_command}", file=sys.stderr)
        return 2

    commands = {
        "list": cmd_planner_list,
        "show": cmd_planner_show,
        "replay": cmd_planner_replay,
        "diff": cmd_planner_diff,
        "summarize-run": cmd_planner_summarize_run,
        "timeline": cmd_planner_timeline,
    }
    handler = commands.get(args.planner_trace_command)
    if handler is None:
        print(f"Unknown planner trace command: {args.planner_trace_command}", file=sys.stderr)
        return 2
    return handler(args)


def main() -> int:
    """Main entry point for the spec manager CLI.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    parser = argparse.ArgumentParser(
        description="Spec Manager - Manage specification libraries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── PDD orchestration commands ──────────────────────────────────

    # run - full PDD pipeline
    p_run = subparsers.add_parser(
        "run",
        help="Run the full PDD pipeline (phases 0-10)",
    )
    p_run.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )
    p_run.add_argument(
        "--input",
        help="Path to input spec folder",
    )

    # lifecycle - full PDD lifecycle (Build → QA → Architecture → Code Quality)
    p_lifecycle = subparsers.add_parser(
        "lifecycle",
        help="Run PDD lifecycle (Build → QA → Architecture → Code Quality)",
    )
    p_lifecycle.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )
    p_lifecycle.add_argument(
        "lifecycle_phase",
        nargs="?",
        default=None,
        choices=["build", "qa", "architecture", "code_quality"],
        help="Run a specific lifecycle phase (default: all)",
    )
    p_lifecycle.add_argument(
        "--input",
        help="Path to input spec folder",
    )
    p_lifecycle.add_argument(
        "--mode",
        choices=["auto", "interactive", "steering"],
        default="interactive",
        help="Ambiguity resolution mode (default: interactive)",
    )
    p_lifecycle.add_argument(
        "--research",
        action="store_true",
        help="Enable web research for ambiguity resolution",
    )
    p_lifecycle.add_argument(
        "--steering",
        help="Path to steering script JSON (for eval mode)",
    )
    p_lifecycle.add_argument(
        "--worktrees",
        action="store_true",
        help="Enable per-library git worktrees for parallel implementation",
    )
    p_lifecycle.add_argument(
        "--model-profile",
        help="Model profile name for multi-model comparison",
    )

    # quality - compute quality scorecard for a run
    p_quality = subparsers.add_parser(
        "quality",
        help="Compute quality scorecard for a PDD run",
    )
    p_quality.add_argument(
        "run_id",
        help="Run identifier",
    )
    p_quality.add_argument(
        "--judges",
        action="store_true",
        help="Run LLM judges (arch, code, spec fidelity)",
    )
    p_quality.add_argument(
        "--judge-model",
        default="",
        help="Model ID for quality judges",
    )
    p_quality.add_argument(
        "--allow-self-judge",
        action="store_true",
        help="Allow judge model to equal producer model",
    )

    # phase - run a specific PDD phase
    p_phase = subparsers.add_parser(
        "phase",
        help="Run a specific PDD design phase (0-10)",
    )
    p_phase.add_argument(
        "phase_number",
        type=int,
        help="Phase number (0-10)",
    )
    p_phase.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )
    p_phase.add_argument(
        "--input",
        help="Path to input spec folder",
    )

    # extract - alias for phase 0
    p_extract = subparsers.add_parser(
        "extract",
        help="Phase 0: extract input to PDD format",
    )
    p_extract.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to input spec (default: current directory)",
    )
    p_extract.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Run identifier (auto-generated if omitted)",
    )

    # ── Legacy / module commands ────────────────────────────────────

    # phase-02
    p_phase_02 = subparsers.add_parser(
        "phase-02",
        help="Run Phase 2 clean/compose/compliance workflow",
    )
    p_phase_02.add_argument("run_id", help="Run identifier")

    # refine (intent-backed ambiguity ingestion + terminal loop)
    p_refine = subparsers.add_parser("refine", help="Emit refinement questions and run intent loop")
    p_refine.add_argument("run_id", help="Run identifier")
    p_refine.add_argument("--workspace", help="Workspace root")
    p_refine.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Maximum questions to answer in one run (default: 50)",
    )
    p_refine.add_argument(
        "--emit-only",
        action="store_true",
        help="Emit refinement signals only (do not start interactive intent loop)",
    )

    # ambiguities (sub-group with "list" subcommand)
    p_ambiguities = subparsers.add_parser("ambiguities", help="Ambiguity detection commands")
    ambiguities_sub = p_ambiguities.add_subparsers(dest="ambiguities_command", required=True)
    p_amb_list = ambiguities_sub.add_parser("list", help="List detected ambiguities")
    p_amb_list.add_argument("run_id", help="Run identifier")
    p_amb_list.add_argument("--workspace", help="Workspace directory")

    # intent adapter commands (question queue + answer bridge)
    p_intent = subparsers.add_parser("intent", help="Intent adapter commands")
    intent_sub = p_intent.add_subparsers(dest="intent_command", required=True)

    p_intent_questions = intent_sub.add_parser(
        "questions",
        help="List open intent questions for a run",
    )
    p_intent_questions.add_argument("run_id", help="Run identifier")
    p_intent_questions.add_argument("--workspace", help="Workspace directory")
    p_intent_questions.add_argument(
        "--json",
        action="store_true",
        help="Print JSON payload",
    )

    p_intent_answer = intent_sub.add_parser(
        "answer",
        help="Submit an answer to an intent question",
    )
    p_intent_answer.add_argument("run_id", help="Run identifier")
    p_intent_answer.add_argument("question_id", help="Question identifier")
    p_intent_answer.add_argument(
        "answer",
        nargs="+",
        help="Answer text to submit",
    )
    p_intent_answer.add_argument(
        "--choice",
        help="Choice identifier when answering choice questions",
    )
    p_intent_answer.add_argument("--workspace", help="Workspace directory")
    p_intent_answer.add_argument(
        "--json",
        action="store_true",
        help="Print JSON payload",
    )

    p_intent_run = intent_sub.add_parser(
        "run",
        help="Run interactive queue loop (ask next question, submit answer, repeat)",
    )
    p_intent_run.add_argument("run_id", help="Run identifier")
    p_intent_run.add_argument("--workspace", help="Workspace directory")
    p_intent_run.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Maximum questions to answer in one run (default: 50)",
    )

    # evidence-store
    p_evidence_store = subparsers.add_parser(
        "evidence-store", help="Evidence store management commands"
    )
    evidence_store_sub = p_evidence_store.add_subparsers(
        dest="evidence_store_command", required=True
    )

    p_es_hollow = evidence_store_sub.add_parser("hollow", help="Hollow out specs for a run")
    p_es_hollow.add_argument("run_id", help="Run identifier")
    p_es_hollow.add_argument("--lib-id", help="Specific library ID to hollow (default: all)")
    p_es_hollow.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_rebuild = evidence_store_sub.add_parser("rebuild-index", help="Rebuild evidence index")
    p_es_rebuild.add_argument("run_id", help="Run identifier")
    p_es_rebuild.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_search = evidence_store_sub.add_parser("search", help="Search evidence store")
    p_es_search.add_argument("run_id", help="Run identifier")
    p_es_search.add_argument("--query", required=True, help="Search query text")
    p_es_search.add_argument(
        "--max-results", type=int, default=5, help="Maximum results (default: 5)"
    )
    p_es_search.add_argument("--input-folder", help="Input folder path", default=".")

    p_es_status = evidence_store_sub.add_parser("status", help="Show evidence store status")
    p_es_status.add_argument("run_id", help="Run identifier")
    p_es_status.add_argument("--input-folder", help="Input folder path", default=".")

    # generate-analysis
    p_gen_analysis = subparsers.add_parser(
        "generate-analysis",
        help="Generate analysis file (algorithmic-to-architectural mapping)",
    )
    p_gen_analysis.add_argument("spec_folder", help="Path to spec folder")
    p_gen_analysis.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    p_gen_analysis.add_argument("--json", action="store_true", help="Print JSON to stdout")

    # adjacency
    p_adjacency = subparsers.add_parser("adjacency", help="Run adjacency detection analysis")
    p_adjacency.add_argument(
        "--source-dir",
        action="append",
        help="Root directory used to discover relationship fact artifacts (repeatable)",
    )
    p_adjacency.add_argument(
        "--spec-dir",
        action="append",
        help="Root directory used to discover relationship fact artifacts (repeatable)",
    )
    p_adjacency.add_argument(
        "--relationship-facts",
        action="append",
        help="Path to RelationshipFacts JSON artifact (repeatable)",
    )
    p_adjacency.add_argument(
        "--pin-registry",
        action="append",
        help="Path to pin_registry.json artifact (repeatable)",
    )
    p_adjacency.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    p_adjacency.add_argument(
        "--output",
        help="Output file path",
    )
    p_adjacency.add_argument("--json", action="store_true", help="Print JSON to stdout")

    # scan-source (edit-in-place engine)
    p_scan_source = subparsers.add_parser(
        "scan-source",
        help="Scan Python source for spec comments and stubs (edit-in-place engine)",
    )
    p_scan_source.add_argument("path", help="Path to a Python file or directory")
    p_scan_source.add_argument(
        "--exclude",
        nargs="*",
        help="Glob patterns to exclude (default: test_*, __pycache__)",
    )
    p_scan_source.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p_scan_source.add_argument(
        "--output",
        help="Write output to file instead of stdout",
    )

    # branches - branch lifecycle management commands
    p_branches = subparsers.add_parser("branches", help="Branch lifecycle management commands")
    branches_sub = p_branches.add_subparsers(dest="branches_command", required=True)

    p_br_init = branches_sub.add_parser("init", help="Initialize branch layout")
    p_br_init.add_argument("run_id", help="Run identifier")
    p_br_init.add_argument("--source-dir", help="Source directory to collapse")
    p_br_init.add_argument("--from-scan", help="Run edit-in-place scan on this directory first")
    p_br_init.add_argument("--force", action="store_true", help="Force re-initialization")

    p_br_gaps = branches_sub.add_parser("gaps", help="Scan algorithmic branch for gaps")
    p_br_gaps.add_argument("run_id", help="Run identifier")

    p_br_promote = branches_sub.add_parser("promote", help="Promote atoms to architectural branch")
    p_br_promote.add_argument("run_id", help="Run identifier")
    p_br_promote.add_argument("--skip-compliance", action="store_true", help="Skip compliance gate")
    p_br_promote.add_argument("--atom-ids", nargs="+", help="Specific atom IDs to promote")

    p_br_analyze = branches_sub.add_parser("analyze", help="Regenerate analysis branch")
    p_br_analyze.add_argument("run_id", help="Run identifier")

    p_br_status = branches_sub.add_parser("status", help="Show branch system status")
    p_br_status.add_argument("run_id", help="Run identifier")

    p_br_run = branches_sub.add_parser("run", help="Run all branch lifecycle phases")
    p_br_run.add_argument("run_id", help="Run identifier")
    p_br_run.add_argument("--source-dir", help="Source directory to collapse")
    p_br_run.add_argument("--skip-compliance", action="store_true", help="Skip compliance gate")

    # pin - pin-function management commands
    from spec_manager.pin_functions.cli import setup_pin_parser

    setup_pin_parser(subparsers)

    # eval - add subcommand group for evaluation
    from spec_manager.refinement.evals.cli import setup_eval_parser

    setup_eval_parser(subparsers)

    # planner - trace tooling surface (parallel to eval planner ...)
    p_planner_surface = subparsers.add_parser(
        "planner",
        help="Planner operational tooling",
    )
    planner_surface_sub = p_planner_surface.add_subparsers(
        dest="planner_surface_command",
        required=True,
    )
    p_trace = planner_surface_sub.add_parser("trace", help="Planner trace commands")
    planner_trace_sub = p_trace.add_subparsers(dest="planner_trace_command", required=True)

    p_trace_list = planner_trace_sub.add_parser("list", help="List planner traces")
    p_trace_list.add_argument("--run-id", default="", help="Filter by run ID")
    p_trace_list.add_argument("--slice", default="", help="Filter by slice ID")
    p_trace_list.add_argument("--capability", default="", help="Filter by capability")
    p_trace_list.add_argument("--layer", default="", help="Filter by layer")
    p_trace_list.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    p_trace_show = planner_trace_sub.add_parser("show", help="Show a specific trace")
    p_trace_show.add_argument("trace_id", help="Trace ID to show")
    p_trace_show.add_argument("--calls", action="store_true", help="Include model/tool calls")
    p_trace_show.add_argument("--artifacts", action="store_true", help="Include artifacts")
    p_trace_show.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    p_trace_replay = planner_trace_sub.add_parser("replay", help="Replay a planner decision")
    p_trace_replay.add_argument("trace_id", help="Trace ID to replay")
    p_trace_replay.add_argument(
        "--model-config",
        default="",
        help="Model configuration override for replayed planner call",
    )
    p_trace_replay.add_argument(
        "--override",
        help="Path to override YAML/JSON (mapping with optional inputs/outputs keys)",
    )
    p_trace_replay.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    p_trace_diff = planner_trace_sub.add_parser("diff", help="Diff two traces")
    p_trace_diff.add_argument("trace_a", help="First trace ID")
    p_trace_diff.add_argument("trace_b", help="Second trace ID")
    p_trace_diff.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    p_trace_summary = planner_trace_sub.add_parser(
        "summarize-run",
        help="Summarize traces for a run",
    )
    p_trace_summary.add_argument("--run-id", required=True, help="Run ID to summarize")
    p_trace_summary.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    p_trace_timeline = planner_trace_sub.add_parser(
        "timeline",
        help="Generate planner timeline HTML",
    )
    p_trace_timeline.add_argument("--run-id", required=True, help="Run ID to visualize")
    p_trace_timeline.add_argument(
        "--workspace", default=".", help="Workspace root (where traces are stored)"
    )

    # plan-v2 - algorithmic planning subcommand group
    from spec_manager.comment_planning.algo_cli import setup_plan_v2_parser

    setup_plan_v2_parser(subparsers)

    # coverage - entity coverage gap analysis
    from spec_manager.compliance.coverage.cli import setup_coverage_parser

    setup_coverage_parser(subparsers)

    args = parser.parse_args()

    # Auto-generate run_id for PDD commands when not provided
    if (
        args.command in ("run", "phase", "extract", "lifecycle")
        and getattr(args, "run_id", None) is None
    ):
        from datetime import datetime

        args.run_id = datetime.now().strftime("pdd-%Y%m%d-%H%M%S")

    commands = {
        "run": cmd_run,
        "lifecycle": cmd_lifecycle,
        "quality": cmd_quality,
        "phase": cmd_phase,
        "extract": cmd_extract,
        "phase-02": cmd_phase_02,
        "refine": cmd_refine,
        "adjacency": cmd_adjacency,
        "generate-analysis": cmd_generate_analysis,
        "scan-source": cmd_scan_source,
    }

    # Handle eval command separately
    if args.command == "eval":
        from spec_manager.refinement.evals.cli import handle_eval_command

        return handle_eval_command(args)

    # Handle planner trace tooling
    if args.command == "planner":
        return cmd_planner(args)

    # Handle pin sub-group
    if args.command == "pin":
        from spec_manager.pin_functions.cli import handle_pin_command

        return handle_pin_command(args)

    # Handle evidence-store sub-group
    if args.command == "evidence-store":
        return cmd_evidence_store(args)

    # Handle plan-v2 sub-group
    if args.command == "plan-v2":
        from spec_manager.comment_planning.algo_cli import handle_plan_v2_command

        return handle_plan_v2_command(args)

    # Handle coverage sub-group
    if args.command == "coverage":
        from spec_manager.compliance.coverage.cli import handle_coverage_command

        return handle_coverage_command(args)

    # Handle branches sub-group
    if args.command == "branches":
        return cmd_branches(args)

    # Handle ambiguities sub-group
    if args.command == "ambiguities":
        ambiguities_commands = {
            "list": cmd_ambiguities_list,
        }
        return ambiguities_commands[args.ambiguities_command](args)

    # Handle intent adapter sub-group
    if args.command == "intent":
        return cmd_intent(args)

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
