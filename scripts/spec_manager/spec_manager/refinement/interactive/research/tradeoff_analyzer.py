"""Tradeoff analysis for low-confidence research results.

When the research coordinator's synthesizer returns confidence < 0.5, the
tradeoff analyzer generates a structured analysis of the available options
so that auto-mode can pick the best one or manual-mode can present choices
to the user.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TradeoffOption:
    """A single option in a tradeoff analysis.

    Attributes:
        option_id: Unique identifier within the analysis.
        description: What this option proposes.
        pros: Advantages of choosing this option.
        cons: Disadvantages of choosing this option.
        confidence: How confident we are this option is correct (0.0-1.0).
        source: Where this option came from.
    """

    option_id: str
    description: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "inference"  # "evidence_store" | "web_research" | "inference"

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "description": self.description,
            "pros": self.pros,
            "cons": self.cons,
            "confidence": self.confidence,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeoffOption:
        return cls(
            option_id=data.get("option_id", ""),
            description=data.get("description", ""),
            pros=data.get("pros", []),
            cons=data.get("cons", []),
            confidence=float(data.get("confidence", 0.0)),
            source=data.get("source", "inference"),
        )


@dataclass
class TradeoffAnalysis:
    """Structured analysis of a tradeoff when research is inconclusive.

    Attributes:
        ambiguity_id: The ambiguity this analysis addresses.
        question: The question being analyzed.
        options: Available options with pros/cons.
        recommendation: Human-readable recommendation text.
        recommendation_reasoning: Why this recommendation was chosen.
        chosen_option_id: The option selected (None if manual decision needed).
    """

    ambiguity_id: str
    question: str
    options: list[TradeoffOption] = field(default_factory=list)
    recommendation: str = ""
    recommendation_reasoning: str = ""
    chosen_option_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "question": self.question,
            "options": [opt.to_dict() for opt in self.options],
            "recommendation": self.recommendation,
            "recommendation_reasoning": self.recommendation_reasoning,
            "chosen_option_id": self.chosen_option_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeoffAnalysis:
        return cls(
            ambiguity_id=data.get("ambiguity_id", ""),
            question=data.get("question", ""),
            options=[TradeoffOption.from_dict(o) for o in data.get("options", [])],
            recommendation=data.get("recommendation", ""),
            recommendation_reasoning=data.get("recommendation_reasoning", ""),
            chosen_option_id=data.get("chosen_option_id"),
        )

    def best_option(self) -> TradeoffOption | None:
        """Return the option with the highest confidence, or ``None``."""
        if not self.options:
            return None
        return max(self.options, key=lambda o: o.confidence)


class TradeoffAnalyzer:
    """Builds tradeoff analyses from low-confidence research results."""

    def analyze(
        self,
        ambiguity_id: str,
        question: str,
        decision_json: str,
        findings_json: str | None = None,
    ) -> TradeoffAnalysis:
        """Build a ``TradeoffAnalysis`` from research outputs.

        Parses the decision and findings JSON produced by the research
        coordinator and structures them into options with pros/cons.

        Args:
            ambiguity_id: ID of the ambiguity being analyzed.
            question: The question under investigation.
            decision_json: JSON string from the synthesizer agent.
            findings_json: Optional JSON string from the web researcher.

        Returns:
            A populated ``TradeoffAnalysis``.
        """
        options: list[TradeoffOption] = []

        # Parse decision
        decision_data = self._safe_parse(decision_json)
        decision_text = ""
        decision_confidence = 0.0
        if isinstance(decision_data, dict):
            decision_text = decision_data.get("decision", "")
            decision_confidence = float(decision_data.get("confidence", 0.0))
            reasoning = decision_data.get("reasoning", "")

            if decision_text:
                options.append(TradeoffOption(
                    option_id="OPT-SYNTH",
                    description=decision_text,
                    pros=[reasoning] if reasoning else ["Synthesized from research findings"],
                    cons=["Low confidence from research synthesis"],
                    confidence=decision_confidence,
                    source="web_research",
                ))

        # Parse findings for alternative options
        if findings_json:
            findings_data = self._safe_parse(findings_json)
            if isinstance(findings_data, dict):
                for i, finding in enumerate(findings_data.get("findings", [])):
                    if not isinstance(finding, dict):
                        continue
                    summary = finding.get("summary", "")
                    if summary and summary != decision_text:
                        source = finding.get("source", "web_research")
                        relevance = finding.get("relevance", "")
                        options.append(TradeoffOption(
                            option_id=f"OPT-FIND-{i + 1:02d}",
                            description=summary,
                            pros=[relevance] if relevance else [],
                            cons=["Individual finding; not synthesized"],
                            confidence=max(0.1, decision_confidence - 0.1),
                            source="web_research" if "http" in source else "inference",
                        ))

        # Fallback: if no options were extracted, create a generic one
        if not options:
            options.append(TradeoffOption(
                option_id="OPT-DEFAULT",
                description="Insufficient evidence to determine answer",
                pros=[],
                cons=["No research findings available"],
                confidence=0.0,
                source="inference",
            ))

        # Pick the best
        best = max(options, key=lambda o: o.confidence)

        return TradeoffAnalysis(
            ambiguity_id=ambiguity_id,
            question=question,
            options=options,
            recommendation=best.description,
            recommendation_reasoning=(
                f"Highest confidence option ({best.confidence:.0%}) "
                f"from {best.source}"
            ),
            chosen_option_id=best.option_id,
        )

    def save(self, analysis: TradeoffAnalysis, output_path: Path) -> None:
        """Persist a tradeoff analysis to disk."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(analysis.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.info("Tradeoff analysis saved: %s", output_path)

    @staticmethod
    def _safe_parse(text: str) -> dict | list | None:
        """Best-effort JSON parse, returning ``None`` on failure."""
        try:
            from spec_manager.refinement.formats import extract_json_from_llm_output

            return extract_json_from_llm_output(
                text, allow_object=True, allow_array=True, location="tradeoff_analyzer"
            )
        except (ValueError, TypeError):
            pass

        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
