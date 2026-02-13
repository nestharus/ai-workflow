"""Intent Agent — single user-facing interface for the spec manager pipeline.

Implements the intent ingest system from Research Prompt 6 (response2.md).
The Intent Agent mediates ALL user interaction. The Planner is the single
constraint and decision authority. The Intent Agent translates between
user language and system language, enforces question quality, and manages
a prioritized question queue.

Modules:
    agent — IntentAgentOrchestrator (deterministic event loop)
    state — IntentSessionState persistence and schemas
    queue — QuestionItem lifecycle, dedup, priority, reassessment
    quality_gate — QualityValidatorStrategy + QuestionRepairStrategy
    taxonomy — Question type classification and reframing
    signals — UserQuestionSignal read/write store
    answer_translation — AnswerTranslation artifact production
    skeleton — Pre-decomposition skeleton renderer
"""

from spec_manager.orchestration.intent_agent.agent import IntentAgentOrchestrator
from spec_manager.orchestration.intent_agent.answer_translation import (
    AnswerTranslation,
    AnswerTranslateStrategy,
)
from spec_manager.orchestration.intent_agent.quality_gate import (
    QualityCheckRecord,
    QualityValidatorStrategy,
    QuestionRepairStrategy,
)
from spec_manager.orchestration.intent_agent.queue import QuestionItem, QuestionQueue
from spec_manager.orchestration.intent_agent.signals import UserQuestionSignal
from spec_manager.orchestration.intent_agent.state import IntentSessionState
from spec_manager.orchestration.intent_agent.taxonomy import (
    QuestionTaxonomy,
    classify_question,
    reframe_to_user_valid,
)

__all__ = [
    "AnswerTranslation",
    "AnswerTranslateStrategy",
    "IntentAgentOrchestrator",
    "IntentSessionState",
    "QualityCheckRecord",
    "QualityValidatorStrategy",
    "QuestionItem",
    "QuestionQueue",
    "QuestionRepairStrategy",
    "QuestionTaxonomy",
    "UserQuestionSignal",
    "classify_question",
    "reframe_to_user_valid",
]
