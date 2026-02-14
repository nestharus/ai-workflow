"""Quality-gate BAD/GOOD examples from intent section 5.6."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from spec_manager.orchestration.intent_agent.quality_gate import QualityValidatorStrategy


@dataclass(frozen=True)
class QualityExamplePair:
    case_id: str
    bad_text: str
    good_text: str
    good_scenario: str


QUALITY_EXAMPLE_PAIRS = [
    QualityExamplePair(
        case_id="consistency_wording",
        bad_text="For transaction records, do you require strong consistency or eventual consistency?",
        good_text=(
            "After a settlement is recorded, do users need to see it reflected everywhere immediately, "
            "or is a short delay acceptable?"
        ),
        good_scenario="After a settlement is recorded, different screens may update at different times.",
    ),
    QualityExamplePair(
        case_id="processing_mode",
        bad_text="Should this run event-driven, batch, or synchronous?",
        good_text=(
            "Should settlements be processed as they arrive throughout the day, or collected and "
            "processed at scheduled times?"
        ),
        good_scenario="Some organizations process settlements as they arrive, others in scheduled runs.",
    ),
    QualityExamplePair(
        case_id="minimum_behavior",
        bad_text="What is the minimum acceptable behavior for this flow?",
        good_text=(
            "If a settlement completes internally but the confirmation to the counterparty fails, "
            "what should happen next?"
        ),
        good_scenario="Sometimes a settlement completes internally but confirmation to the counterparty fails.",
    ),
    QualityExamplePair(
        case_id="integration_extensibility",
        bad_text="Should external integrations be plug-in points or hardwired?",
        good_text=(
            "If this system connects to an external provider, do you expect that provider to stay fixed "
            "long-term or possibly change?"
        ),
        good_scenario="Some systems must be able to switch providers later.",
    ),
    QualityExamplePair(
        case_id="realtime_updates",
        bad_text="Should we use WebSockets or polling for real-time updates?",
        good_text=(
            "When a settlement status changes, how quickly do users need to see the update?"
        ),
        good_scenario="Users may need near-real-time status updates.",
    ),
    QualityExamplePair(
        case_id="database_choice",
        bad_text="Which database should we use for the ledger?",
        good_text=(
            "Are there vendor or platform restrictions that limit which storage technologies are allowed, "
            "or is this open?"
        ),
        good_scenario="Some organizations restrict what vendors can be used.",
    ),
    QualityExamplePair(
        case_id="caching_wording",
        bad_text="Should we use caching to improve performance?",
        good_text=(
            "For user-visible balances, is it acceptable if the displayed value is briefly out of date "
            "to keep the system responsive?"
        ),
        good_scenario="Some values can be slightly delayed if it keeps the system responsive.",
    ),
]


def _extract_candidate_text(prompt: str) -> str:
    prefix = "CANDIDATE TEXT: "
    suffix = "\nSCENARIO:"
    start = prompt.index(prefix) + len(prefix)
    end = prompt.index(suffix, start)
    return prompt[start:end].strip()


def _quality_gate_llm_stub(good_questions: set[str]):
    def run_agent(prompt: str) -> str:
        candidate_text = _extract_candidate_text(prompt)
        if candidate_text in good_questions:
            return json.dumps(
                {
                    "domain_language_only": True,
                    "bounded_answerability": True,
                    "specific_behavior": True,
                    "scenario_grounded": True,
                    "single_question": True,
                    "reason": "Scenario-grounded and business-answerable.",
                }
            )

        return json.dumps(
            {
                "domain_language_only": False,
                "bounded_answerability": True,
                "specific_behavior": False,
                "scenario_grounded": True,
                "single_question": True,
                "reason": "Uses internal technical framing instead of user-facing behavior.",
            }
        )

    return run_agent


@pytest.mark.parametrize(
    "pair", QUALITY_EXAMPLE_PAIRS, ids=[p.case_id for p in QUALITY_EXAMPLE_PAIRS]
)
def test_section_5_6_bad_examples_fail_quality_gate(pair: QualityExamplePair) -> None:
    validator = QualityValidatorStrategy()
    run_agent = _quality_gate_llm_stub({p.good_text for p in QUALITY_EXAMPLE_PAIRS})

    record = validator.run(
        candidate_text=pair.bad_text,
        scenario=pair.good_scenario,
        answer_spec_kind="choice",
        taxonomy_type="CONSTRAINT",
        run_agent=run_agent,
    )

    assert record.result == "FAIL"
    assert record.checks.bounded_answerability is True
    assert record.checks.scenario_grounded is True
    assert record.checks.domain_language_only is False or record.checks.specific_behavior is False


@pytest.mark.parametrize(
    "pair", QUALITY_EXAMPLE_PAIRS, ids=[p.case_id for p in QUALITY_EXAMPLE_PAIRS]
)
def test_section_5_6_good_examples_pass_quality_gate(pair: QualityExamplePair) -> None:
    validator = QualityValidatorStrategy()
    run_agent = _quality_gate_llm_stub({p.good_text for p in QUALITY_EXAMPLE_PAIRS})

    record = validator.run(
        candidate_text=pair.good_text,
        scenario=pair.good_scenario,
        answer_spec_kind="choice",
        taxonomy_type="CONSTRAINT",
        run_agent=run_agent,
    )

    assert record.result == "PASS"
    assert record.checks.all_pass is True
