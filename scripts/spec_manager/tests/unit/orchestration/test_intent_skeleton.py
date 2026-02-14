"""Tests for intent-agent skeleton rendering and metadata propagation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone

from spec_manager.orchestration.intent_agent.queue import (
    QUESTION_QUEUE_SNAPSHOT_RELATIVE_PATH,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    UserPrompt,
)
from spec_manager.orchestration.intent_agent.skeleton import (
    EntityStub,
    InterfaceStub,
    SkeletonSpec,
    SkeletonSynthesisStrategy,
    WorkflowStub,
    render_intent_snapshot,
    render_skeleton,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_sample_spec() -> SkeletonSpec:
    return SkeletonSpec(
        problem_frame={
            "current_restatement": "Create a claims workflow",
            "goals": ["deliver claims"],
            "non_goals": [],
            "scope": {"in": ["core"], "out": []},
            "success_metrics": [],
        },
        concept_map={},
        open_question_ids=["Q-1", "Q-2"],
        constraint_refs=["C-1"],
        workflows=[
            WorkflowStub(
                name="resolve_claim",
                description="Resolve a claim",
                open_question_ids=["Q-1", "Q-2"],
                canonical_keys=["auth.claims", "billing.policy"],
                scenarios=["A user submits a claim", "A bill is rejected"],
            )
        ],
        entities=[
            EntityStub(
                name="Claim",
                description="Core claim record",
                fields=["id", "status"],
                open_question_ids=["Q-1"],
                canonical_keys=["auth.claims"],
                scenarios=["A user submits a claim"],
            )
        ],
        interfaces=[
            InterfaceStub(
                name="LedgerService",
                description="External ledger",
                direction="outbound",
                open_question_ids=["Q-2"],
                canonical_keys=["billing.policy"],
                scenarios=["A bill is rejected"],
            )
        ],
    )


def test_render_skeleton_emits_todos_with_canonical_key_and_scenario(tmp_path):
    """Workflow/entity/interface stubs include TODO metadata and remain non-operational."""
    spec = _build_sample_spec()
    output_dir = tmp_path / "intent" / "skeleton"

    created = render_skeleton(spec, output_dir)

    wf_path = output_dir / "system" / "workflows" / "resolve_claim.py"
    ent_path = output_dir / "system" / "entities" / "Claim.py"
    iface_path = output_dir / "system" / "interfaces" / "LedgerService.py"

    assert wf_path in created
    assert ent_path in created
    assert iface_path in created

    workflow_text = wf_path.read_text(encoding="utf-8")
    assert "# Q:Q-1 (canonical_key: auth.claims)" in workflow_text
    assert "# Scenario: A user submits a claim" in workflow_text
    assert "# TODO: finalize resolve_claim based on user answer to Q:Q-1." in workflow_text
    assert "raise NotImplementedError" in workflow_text

    entity_text = ent_path.read_text(encoding="utf-8")
    assert "# Q:Q-1 (canonical_key: auth.claims)" in entity_text
    assert "class Claim:" in entity_text

    interface_text = iface_path.read_text(encoding="utf-8")
    assert "# Q:Q-2 (canonical_key: billing.policy)" in interface_text
    assert "class LedgerService:" in interface_text


def test_synthesis_propagates_canonical_keys_and_scenarios_from_llm_output():
    """LLM workflow stubs preserve canonical keys and scenarios in stub metadata."""
    strategy = SkeletonSynthesisStrategy()

    def run_agent(_: str) -> str:
        return json.dumps(
            {
                "workflows": [
                    {
                        "name": "resolve_claim",
                        "description": "Resolve a claim",
                        "open_questions": [
                            {
                                "question_id": "Q-1",
                                "canonical_key": "auth.claims",
                                "scenario": "Claim is submitted by user.",
                            }
                        ],
                    },
                ],
                "entities": [
                    {
                        "name": "Claim",
                        "description": "Core claim record",
                        "fields": ["id", "status"],
                        "open_questions": [
                            {
                                "question_id": "Q-2",
                                "canonical_key": "billing.policy",
                                "scenario": "Billing policy conflict.",
                            }
                        ],
                    }
                ],
                "interfaces": [],
            }
        )

    spec = strategy.synthesize(
        problem_frame={
            "current_restatement": "Create a claims workflow",
            "goals": ["deliver claims"],
            "non_goals": [],
            "scope": {"in": ["core"], "out": []},
        },
        concept_map={},
        open_question_ids=["Q-1", "Q-2"],
        open_questions=[
            {
                "question_id": "Q-1",
                "canonical_key": "auth.claims",
                "scenario": "Claim is submitted by user.",
            },
            {
                "question_id": "Q-2",
                "canonical_key": "billing.policy",
                "scenario": "Billing policy conflict.",
            },
        ],
        constraint_refs=["C-1"],
        run_agent=run_agent,
    )

    assert len(spec.workflows) == 1
    assert spec.workflows[0].open_question_ids == ["Q-1"]
    assert spec.workflows[0].canonical_keys == ["auth.claims"]
    assert spec.workflows[0].scenarios == ["Claim is submitted by user."]

    assert len(spec.entities) == 1
    assert spec.entities[0].open_question_ids == ["Q-2"]
    assert spec.entities[0].canonical_keys == ["billing.policy"]
    assert spec.entities[0].scenarios == ["Billing policy conflict."]


def test_render_intent_snapshot_records_canonical_key_and_scenario(tmp_path):
    """Intent snapshot records canonical keys and scenarios for open questions."""
    output_dir = tmp_path / "intent" / "skeleton"

    path = render_intent_snapshot(
        problem_frame={},
        concept_map={},
        open_questions=[
            {
                "question_id": "Q-1",
                "canonical_key": "auth.claims",
                "scenario": "Claim is submitted.",
            },
            {
                "question_id": "Q-2",
                "canonical_key": "billing.policy",
                "scenario": "Policy rejected.",
            },
        ],
        constraint_refs=["C-1"],
        output_dir=output_dir,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert path == output_dir / "analysis" / "intent" / "intent_snapshot.json"
    assert data["open_questions"] == [
        {"question_id": "Q-1", "canonical_key": "auth.claims", "scenario": "Claim is submitted."},
        {"question_id": "Q-2", "canonical_key": "billing.policy", "scenario": "Policy rejected."},
    ]


def test_question_queue_snapshot_path_is_analysis_intent(tmp_path):
    """Question queue snapshot moves to analysis/intent under the skeleton artifact area."""
    queue = QuestionQueue()
    item = QuestionItem(
        question_id="Q-1",
        canonical_key="auth.claims",
        user_prompt=UserPrompt(scenario="Claim is submitted by user"),
        origins=[
            QuestionOrigin(
                source_kind="PLANNER",
                trace_id="trace-q1",
                created_at=_now_iso(),
            ),
        ],
    )
    item.quality_gate.status = "PASS"
    queue.enqueue(item)

    out_path = queue.save(tmp_path)
    assert out_path == tmp_path / QUESTION_QUEUE_SNAPSHOT_RELATIVE_PATH
    assert out_path.exists()

    loaded = QuestionQueue.load(tmp_path)
    loaded_item = loaded.get_item("Q-1")
    assert loaded_item is not None
    assert loaded_item.canonical_key == "auth.claims"
