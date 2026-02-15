"""Research tool adapter for the planner.

Wraps research backends and provides a unified, dimension-routed
research interface for the planner.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchQuery:
    """A research question from the planner."""

    question: str
    context: str = ""
    dimension: str = "auto"  # auto | local | layer | web | external
    layer: str = ""
    slice_id: str = ""
    hints: dict[str, Any] = field(default_factory=dict)
    max_results: int = 5


@dataclass
class ResearchFinding:
    """A single finding from research."""

    source: str  # evidence_store | constraints_store | steering | web_research | external_research
    text: str
    confidence: float = 0.0
    refs: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Aggregated research outcome."""

    findings: list[ResearchFinding] = field(default_factory=list)
    synthesis: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_answer(self) -> bool:
        return self.confidence > 0.0 and bool(self.synthesis)


class ResearchTool:
    """Planner-facing research adapter.

    Accepts optional injected dependencies:
    - evidence_searcher: local evidence-store lookup
    - constraints_tool: local constraints/decision lookup
    - research_coordinator: web-research coordinator
    - external_research_tool: optional adversarial/hypothesis tool
    - steering_script: predefined steering responses

    All dependencies are optional. Missing dependencies simply skip that
    stage and record the skip in metadata.
    """

    def __init__(
        self,
        evidence_searcher: Any = None,
        constraints_tool: Any = None,
        research_coordinator: Any = None,
        external_research_tool: Any = None,
        steering_script: Any = None,
        workspace: Path | None = None,
    ) -> None:
        self._evidence_searcher = evidence_searcher
        self._constraints_tool = constraints_tool
        self._coordinator = research_coordinator
        self._external_research_tool = external_research_tool
        self._steering = steering_script
        self._workspace = workspace

    def research(self, query: ResearchQuery) -> ResearchResult:
        """Execute a research query using an explicit dimension route."""
        requested_dimension = (query.dimension or "auto").strip().lower()
        dimension = self._resolve_dimension(query, requested_dimension)

        findings: list[ResearchFinding] = []
        metadata: dict[str, Any] = {
            "requested_dimension": requested_dimension,
            "resolved_dimension": dimension,
            "layer": str(query.layer or "").strip().lower(),
            "slice_id": str(query.slice_id or "").strip(),
            "stages": [],
        }

        def log_stage(stage: str, status: str, detail: str) -> None:
            metadata["stages"].append({"stage": stage, "status": status, "detail": detail})

        if dimension in {"local", "layer"}:
            self._run_steering_stage(query, findings, log_stage)
            self._run_evidence_stage(query, findings, log_stage)
            self._run_constraints_stage(query, findings, log_stage)
        elif dimension == "web":
            self._run_web_stage(query, findings, log_stage)
        elif dimension == "external":
            self._run_external_stage(query, findings, log_stage)
        else:
            log_stage("routing", "failed", f"unsupported dimension={dimension!r}")

        if findings:
            best = max(findings, key=lambda finding: finding.confidence)
            return ResearchResult(
                findings=findings,
                synthesis=best.text,
                confidence=best.confidence,
                metadata=metadata,
            )

        return ResearchResult(metadata=metadata)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9_./:-]+", text.lower()) if len(token) >= 3}

    def _resolve_dimension(self, query: ResearchQuery, requested_dimension: str) -> str:
        if requested_dimension in {"local", "layer", "web", "external"}:
            return requested_dimension

        parts = [
            str(query.question or ""),
            str(query.context or ""),
            str(query.layer or ""),
            " ".join(f"{key}:{value}" for key, value in (query.hints or {}).items()),
        ]
        blob = " ".join(parts).lower()

        external_tokens = (
            "adversarial",
            "hypothesis",
            "counterexample",
            "challenge assumptions",
            "red-team",
            "critique",
            "falsify",
        )
        if any(token in blob for token in external_tokens):
            if self._external_research_tool is not None:
                return "external"
            if self._coordinator is not None:
                return "web"
            return "layer" if str(query.layer).strip() else "local"

        web_tokens = (
            "latest",
            "today",
            "internet",
            "web",
            "external source",
            "rfc",
            "cve",
            "stackoverflow",
            "github issue",
            "docs.python.org",
        )
        if "http://" in blob or "https://" in blob or any(token in blob for token in web_tokens):
            if self._coordinator is not None:
                return "web"
            return "layer" if str(query.layer).strip() else "local"

        if str(query.layer or "").strip():
            return "layer"
        return "local"

    def _run_steering_stage(
        self,
        query: ResearchQuery,
        findings: list[ResearchFinding],
        log_stage: Any,
    ) -> None:
        if self._steering is None:
            log_stage("steering", "skipped", "steering script not configured")
            return

        try:
            match = self._steering.match(query.question)
            if match:
                findings.append(
                    ResearchFinding(
                        source="steering",
                        text=str(match),
                        confidence=0.9,
                    )
                )
                log_stage("steering", "hit", "steering script returned a match")
            else:
                log_stage("steering", "miss", "steering script returned no match")
        except Exception:
            logger.debug("Steering match failed for query: %s", query.question)
            log_stage("steering", "failed", "steering script raised")

    def _run_evidence_stage(
        self,
        query: ResearchQuery,
        findings: list[ResearchFinding],
        log_stage: Any,
    ) -> None:
        if self._evidence_searcher is None:
            log_stage("evidence_store", "skipped", "evidence searcher not configured")
            return

        try:
            results = self._evidence_searcher.search(
                query.question,
                max_results=query.max_results,
            )
            if results:
                for row in results:
                    findings.append(
                        ResearchFinding(
                            source="evidence_store",
                            text=getattr(row, "text", str(row)),
                            confidence=float(getattr(row, "score", 0.5) or 0.0),
                            refs=[
                                str(getattr(row, "lib_id", "") or ""),
                                str(getattr(row, "section_path", "") or ""),
                            ],
                        )
                    )
                log_stage("evidence_store", "hit", f"{len(results)} total matches")
            else:
                log_stage("evidence_store", "miss", "no matches")
        except Exception:
            logger.debug("Evidence search failed for query: %s", query.question)
            log_stage("evidence_store", "failed", "search raised")

    def _run_constraints_stage(
        self,
        query: ResearchQuery,
        findings: list[ResearchFinding],
        log_stage: Any,
    ) -> None:
        if self._constraints_tool is None:
            log_stage("constraints_store", "skipped", "constraints tool not configured")
            return

        rows = self._search_constraints(query)
        if not rows:
            log_stage("constraints_store", "miss", "no matching constraints/decisions")
            return

        for row in rows[: max(int(query.max_results), 1)]:
            findings.append(
                ResearchFinding(
                    source="constraints_store",
                    text=str(row.get("answer", "") or ""),
                    confidence=float(row.get("confidence", 0.75) or 0.75),
                    refs=[
                        str(row.get("constraint_id", "") or ""),
                        str(row.get("question", "") or ""),
                    ],
                )
            )
        log_stage("constraints_store", "hit", f"{len(rows)} matching constraints/decisions")

    def _search_constraints(self, query: ResearchQuery) -> list[dict[str, Any]]:
        question = str(query.question or "").strip()
        if not question:
            return []

        tool = self._constraints_tool
        slice_id = str(query.slice_id or "").strip() or "__system__"
        slice_ids = [slice_id]
        if slice_id != "__system__":
            slice_ids.append("__system__")

        question_tokens = self._tokenize(question)
        rows: list[dict[str, Any]] = []

        if hasattr(tool, "load_constraints"):
            for target_slice_id in slice_ids:
                try:
                    snapshot = tool.load_constraints(target_slice_id)
                except Exception:
                    logger.debug(
                        "Constraints load failed for slice=%s",
                        target_slice_id,
                        exc_info=True,
                    )
                    continue

                constraints = getattr(snapshot, "constraints", [])
                if not isinstance(constraints, list):
                    continue
                for record in constraints:
                    candidate_question = str(getattr(record, "question", "") or "")
                    candidate_answer = str(getattr(record, "answer", "") or "")
                    if not candidate_answer.strip():
                        continue
                    match_score = self._match_score(question, question_tokens, candidate_question)
                    if match_score <= 0.0:
                        continue
                    rows.append(
                        {
                            "constraint_id": str(getattr(record, "constraint_id", "") or ""),
                            "question": candidate_question,
                            "answer": candidate_answer,
                            "confidence": max(
                                float(getattr(record, "confidence", 0.0) or 0.0),
                                match_score,
                            ),
                        }
                    )

        elif hasattr(tool, "check_coverage"):
            for target_slice_id in slice_ids:
                try:
                    coverage = tool.check_coverage(target_slice_id, [question])
                except Exception:
                    logger.debug(
                        "Constraints coverage failed for slice=%s",
                        target_slice_id,
                        exc_info=True,
                    )
                    continue
                if not isinstance(coverage, dict):
                    continue

                record = coverage.get(question)
                if record is None:
                    continue
                answer = str(getattr(record, "answer", "") or "").strip()
                if not answer:
                    continue
                rows.append(
                    {
                        "constraint_id": str(getattr(record, "constraint_id", "") or ""),
                        "question": str(getattr(record, "question", question) or question),
                        "answer": answer,
                        "confidence": float(getattr(record, "confidence", 0.75) or 0.75),
                    }
                )

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in sorted(
            rows, key=lambda entry: float(entry.get("confidence", 0.0)), reverse=True
        ):
            marker = (
                str(row.get("constraint_id", "") or ""),
                str(row.get("answer", "") or ""),
            )
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(row)
        return deduped

    def _match_score(
        self, question: str, question_tokens: set[str], candidate_question: str
    ) -> float:
        candidate = str(candidate_question or "").strip()
        if not candidate:
            return 0.0
        if candidate.lower() == question.lower():
            return 1.0

        candidate_tokens = self._tokenize(candidate)
        if not question_tokens or not candidate_tokens:
            return 0.0

        overlap = question_tokens.intersection(candidate_tokens)
        if not overlap:
            return 0.0
        return len(overlap) / max(len(question_tokens), 1)

    def _run_web_stage(
        self,
        query: ResearchQuery,
        findings: list[ResearchFinding],
        log_stage: Any,
    ) -> None:
        if self._coordinator is None:
            log_stage("web_research", "skipped", "coordinator not configured")
            return

        try:
            from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

            ambiguity = Ambiguity(
                ambiguity_id=f"research-{query.question[:32]}",
                source_text=query.question,
                source_location=query.context or "",
                ambiguity_type="vague_integration",
                confidence=0.5,
                suggested_question=query.question,
            )
            response = self._coordinator.research(ambiguity, self._workspace)
            if response is not None:
                findings.append(
                    ResearchFinding(
                        source="web_research",
                        text=str(getattr(response, "response_text", "") or "").strip(),
                        confidence=0.7,
                    )
                )
                log_stage("web_research", "hit", "coordinator returned response")
                return
            log_stage("web_research", "miss", "coordinator returned no response")
        except Exception as exc:
            logger.warning("Web research failed: %s", exc)
            log_stage("web_research", "failed", str(exc))

    def _run_external_stage(
        self,
        query: ResearchQuery,
        findings: list[ResearchFinding],
        log_stage: Any,
    ) -> None:
        if self._external_research_tool is None:
            log_stage("external_research", "skipped", "external tool not configured")
            return

        payload = {
            "question": query.question,
            "context": query.context,
            "layer": query.layer,
            "slice_id": query.slice_id,
            "hints": dict(query.hints or {}),
            "max_results": int(query.max_results),
        }

        raw: Any = None
        tool = self._external_research_tool
        try:
            if callable(tool):
                for kwargs in (
                    {"question": query.question, "context": query.context, "payload": payload},
                    {"query": query.question, "context": query.context},
                    {"prompt": query.question, "context": query.context},
                ):
                    try:
                        raw = tool(**kwargs)
                        break
                    except TypeError:
                        continue
                if raw is None:
                    raw = tool(payload)
            elif hasattr(tool, "research"):
                raw = tool.research(payload)
            elif hasattr(tool, "run"):
                raw = tool.run(payload)
        except Exception as exc:
            logger.warning("External research failed: %s", exc)
            log_stage("external_research", "failed", str(exc))
            return

        text = self._coerce_external_text(raw)
        if not text:
            log_stage("external_research", "miss", "external tool returned no usable text")
            return

        findings.append(
            ResearchFinding(
                source="external_research",
                text=text,
                confidence=0.75,
            )
        )
        log_stage("external_research", "hit", "external tool returned response")

    @staticmethod
    def _coerce_external_text(raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            for key in ("response_text", "text", "answer", "synthesis", "critique"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return str(raw).strip()
        for attr in ("response_text", "text", "answer", "synthesis"):
            value = getattr(raw, attr, "")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(raw).strip()
