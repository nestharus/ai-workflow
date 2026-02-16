"""Research tool adapter for the planner.

Wraps research backends and provides a unified, dimension-routed
research interface for the planner.
"""

from __future__ import annotations

import hashlib
import inspect
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
    run_id: str = ""
    iteration: int = 0
    capability: str = "research"
    event_id: str = ""
    hints: dict[str, Any] = field(default_factory=dict)
    max_results: int = 5


@dataclass
class ResearchFinding:
    """A single finding from research."""

    source: str  # evidence_store | constraints_store | steering | web_research | external_research
    text: str
    confidence: float = 0.0
    refs: list[str] = field(default_factory=list)
    verified: bool = True


@dataclass
class ConstraintLookupResult:
    """Outcome of constraints lookup with explicit error visibility."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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
        trace_contract = self._build_trace_contract(query)
        operator_modes = self._select_operator_modes(query, dimension)

        findings: list[ResearchFinding] = []
        metadata: dict[str, Any] = {
            "requested_dimension": requested_dimension,
            "resolved_dimension": dimension,
            "layer": str(query.layer or "").strip().lower(),
            "slice_id": str(trace_contract["slice_id"]),
            "run_id": str(trace_contract["run_id"]),
            "iteration": int(trace_contract["iteration"]),
            "capability": str(trace_contract["capability"]),
            "event_id": str(trace_contract["event_id"]),
            "trace_id": str(trace_contract["trace_id"]),
            "operator_modes": [self._operator_label(mode) for mode in operator_modes],
            "stages": [],
        }

        def log_stage(stage: str, status: str, detail: str) -> None:
            metadata["stages"].append({"stage": stage, "status": status, "detail": detail})

        if dimension in {"local", "layer"}:
            self._run_steering_stage(query, findings, log_stage)
            self._run_evidence_stage(query, findings, log_stage)
            self._run_constraints_stage(query, findings, log_stage)
        elif dimension == "web":
            self._run_web_stage(
                query,
                findings,
                log_stage,
                trace_contract=trace_contract,
                operator_modes=operator_modes,
            )
        elif dimension == "external":
            self._run_external_stage(
                query,
                findings,
                log_stage,
                trace_contract=trace_contract,
                operator_modes=operator_modes,
            )
        else:
            log_stage("routing", "failed", f"unsupported dimension={dimension!r}")

        return self._finalize_result(findings=findings, metadata=metadata)

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

        if self._should_route_external(query, blob):
            return "external"

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

    def _should_route_external(self, query: ResearchQuery, blob: str) -> bool:
        if self._external_research_tool is None:
            return False
        hints = query.hints if isinstance(query.hints, dict) else {}

        research_mode = str(hints.get("research_mode", "") or "").strip().lower()
        problem_kind = str(hints.get("problem_kind", "") or "").strip().lower()
        explicit_opt_in = any(
            (
                self._is_truthy(hints.get("external_research")),
                self._is_truthy(hints.get("requires_external_research")),
                self._is_truthy(hints.get("research_problem")),
                research_mode in {"external", "adversarial", "hypothesis_test", "brennerbot"},
                problem_kind in {"research", "open_research", "hypothesis_test", "investigation"},
            )
        )
        if not explicit_opt_in:
            return False

        if self._is_truthy(hints.get("force_external")):
            return True

        research_tokens = (
            "adversarial",
            "hypothesis",
            "counterexample",
            "challenge assumptions",
            "red-team",
            "critique",
            "falsify",
            "disconfirm",
        )
        open_inquiry_tokens = (
            "unknown",
            "uncertain",
            "investigate",
            "tradeoff",
            "compare",
            "evaluate",
            "open question",
            "what if",
        )
        has_research_vocab = any(token in blob for token in research_tokens)
        has_open_inquiry_signal = any(token in blob for token in open_inquiry_tokens) or (
            "?" in str(query.question or "")
        )
        return has_research_vocab and has_open_inquiry_signal

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y"}
        return False

    def _build_trace_contract(self, query: ResearchQuery) -> dict[str, Any]:
        hints = query.hints if isinstance(query.hints, dict) else {}
        context = str(query.context or "")

        run_id = self._first_non_empty(
            query.run_id,
            hints.get("run_id"),
            self._extract_context_value(context, "run_id"),
            default="__unknown_run__",
        )
        slice_id = self._first_non_empty(
            query.slice_id,
            hints.get("slice_id"),
            self._extract_context_value(context, "slice_id"),
            default="__system__",
        )
        capability = self._first_non_empty(
            query.capability,
            hints.get("capability"),
            hints.get("hint"),
            self._extract_context_value(context, "capability"),
            default="research",
        )
        iteration = self._coerce_iteration(
            query.iteration,
            hints.get("iteration"),
            self._extract_context_value(context, "iteration"),
        )
        event_id = self._first_non_empty(
            query.event_id,
            hints.get("event_id"),
            self._extract_context_value(context, "event_id"),
            default="",
        )
        if not event_id:
            event_id = self._derived_event_id(
                question=str(query.question or ""),
                context=context,
                capability=capability,
            )

        trace_id = f"{run_id}/{slice_id}/{iteration}/{capability}/{event_id}"
        return {
            "run_id": run_id,
            "slice_id": slice_id,
            "iteration": iteration,
            "capability": capability,
            "event_id": event_id,
            "trace_id": trace_id,
        }

    @staticmethod
    def _first_non_empty(*values: Any, default: str = "") -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return default

    @staticmethod
    def _extract_context_value(context: str, key: str) -> str:
        if not context:
            return ""
        match = re.search(rf"(?:^|\s){re.escape(key)}=([^\s]+)", context)
        if not match:
            return ""
        return str(match.group(1) or "").strip()

    @staticmethod
    def _coerce_iteration(*candidates: Any) -> int:
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            return max(value, 0)
        return 0

    @staticmethod
    def _derived_event_id(*, question: str, context: str, capability: str) -> str:
        seed = f"{question}|{context}|{capability}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"research-{digest}"

    def _select_operator_modes(self, query: ResearchQuery, resolved_dimension: str) -> list[str]:
        hints = query.hints if isinstance(query.hints, dict) else {}
        explicit = hints.get("operators", hints.get("operator_modes"))

        requested_modes: list[str] = []
        if isinstance(explicit, str):
            requested_modes.extend(token.strip() for token in explicit.split(","))
        elif isinstance(explicit, (list, tuple, set)):
            requested_modes.extend(str(token or "").strip() for token in explicit)

        inferred_blob = " ".join(
            (
                str(query.question or ""),
                str(query.context or ""),
                " ".join(f"{k}:{v}" for k, v in hints.items()),
            )
        ).lower()
        if any(
            token in inferred_blob for token in ("spec", "implementation", "integration", "layer")
        ):
            requested_modes.append("level_split")
        if any(
            token in inferred_blob
            for token in (
                "correct",
                "valid",
                "safe",
                "assumption",
                "falsify",
                "counterexample",
                "critique",
                "risk",
            )
        ):
            requested_modes.append("exclusion_test")
        if any(
            token in inferred_blob
            for token in ("alternative", "entrypoint", "wiring", "transpose", "architecture")
        ):
            requested_modes.append("object_transpose")
        if any(
            token in inferred_blob
            for token in ("blast radius", "complexity", "scope", "impact", "scale")
        ):
            requested_modes.append("scale_check")

        normalized: list[str] = []
        for mode in requested_modes:
            canonical = self._normalize_operator_mode(mode)
            if canonical and canonical not in normalized:
                normalized.append(canonical)

        if not normalized and resolved_dimension in {"web", "external"}:
            return ["level_split", "exclusion_test"]
        return normalized

    @staticmethod
    def _normalize_operator_mode(mode: str) -> str:
        token = str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "level_split": "level_split",
            "levelsplit": "level_split",
            "exclusion_test": "exclusion_test",
            "exclusiontest": "exclusion_test",
            "object_transpose": "object_transpose",
            "objecttranspose": "object_transpose",
            "scale_check": "scale_check",
            "scalecheck": "scale_check",
        }
        return alias_map.get(token, "")

    @staticmethod
    def _operator_label(mode: str) -> str:
        labels = {
            "level_split": "Level-Split",
            "exclusion_test": "Exclusion-Test",
            "object_transpose": "Object-Transpose",
            "scale_check": "Scale-Check",
        }
        return labels.get(mode, mode)

    def _operator_instructions(self, operator_modes: list[str]) -> list[str]:
        instructions = {
            "level_split": (
                "Level-Split: separate answers into spec intent, implementation mechanics, "
                "and integration implications."
            ),
            "exclusion_test": (
                "Exclusion-Test: identify evidence that would falsify the proposed answer."
            ),
            "object_transpose": (
                "Object-Transpose: include at least one alternative wiring or entrypoint approach."
            ),
            "scale_check": ("Scale-Check: evaluate blast radius, complexity, and rollout risk."),
        }
        return [instructions[mode] for mode in operator_modes if mode in instructions]

    def _apply_operator_framing(
        self, query: ResearchQuery, operator_modes: list[str]
    ) -> tuple[str, str]:
        question = str(query.question or "").strip()
        context = str(query.context or "").strip()
        operator_instructions = self._operator_instructions(operator_modes)
        if not operator_instructions:
            return question, context

        framed_question_lines = [
            question,
            "",
            "Apply these planning operators while answering:",
        ]
        for index, instruction in enumerate(operator_instructions, start=1):
            framed_question_lines.append(f"{index}. {instruction}")
        framed_question = "\n".join(framed_question_lines).strip()

        framed_context = context
        mode_summary = ",".join(self._operator_label(mode) for mode in operator_modes)
        operator_context = f"operator_modes={mode_summary}"
        if framed_context:
            framed_context = f"{framed_context}\n{operator_context}"
        else:
            framed_context = operator_context
        return framed_question, framed_context

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

        lookup = self._search_constraints(query)
        if lookup.errors and not lookup.rows:
            log_stage(
                "constraints_store",
                "failed",
                "; ".join(lookup.errors),
            )
            return

        rows = lookup.rows
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
        if lookup.errors:
            log_stage(
                "constraints_store",
                "partial",
                f"{len(rows)} matches with {len(lookup.errors)} lookup failures",
            )
            return
        log_stage("constraints_store", "hit", f"{len(rows)} matching constraints/decisions")

    def _search_constraints(self, query: ResearchQuery) -> ConstraintLookupResult:
        question = str(query.question or "").strip()
        if not question:
            return ConstraintLookupResult()

        tool = self._constraints_tool
        slice_id = str(query.slice_id or "").strip() or "__system__"
        slice_ids = [slice_id]
        if slice_id != "__system__":
            slice_ids.append("__system__")

        question_tokens = self._tokenize(question)
        rows: list[dict[str, Any]] = []
        errors: list[str] = []

        if hasattr(tool, "load_constraints"):
            for target_slice_id in slice_ids:
                try:
                    snapshot = tool.load_constraints(target_slice_id)
                except Exception as exc:
                    logger.warning(
                        "Constraints load failed for slice=%s",
                        target_slice_id,
                        exc_info=True,
                    )
                    errors.append(
                        f"load_constraints failed for slice '{target_slice_id}': "
                        f"{str(exc).strip() or exc.__class__.__name__}"
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
                except Exception as exc:
                    logger.warning(
                        "Constraints coverage failed for slice=%s",
                        target_slice_id,
                        exc_info=True,
                    )
                    errors.append(
                        f"check_coverage failed for slice '{target_slice_id}': "
                        f"{str(exc).strip() or exc.__class__.__name__}"
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
        return ConstraintLookupResult(rows=deduped, errors=errors)

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
        *,
        trace_contract: dict[str, Any],
        operator_modes: list[str],
    ) -> None:
        if self._coordinator is None:
            log_stage("web_research", "skipped", "coordinator not configured")
            return

        try:
            from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

            framed_question, framed_context = self._apply_operator_framing(query, operator_modes)
            event_id = str(trace_contract.get("event_id", "") or "").strip()
            ambiguity_id = event_id if event_id.startswith("research-") else f"research-{event_id}"
            ambiguity = Ambiguity(
                ambiguity_id=ambiguity_id,
                source_text=query.question,
                source_location=framed_context or "",
                ambiguity_type="vague_integration",
                confidence=0.5,
                suggested_question=framed_question,
            )
            response = self._coordinator.research(ambiguity, self._workspace)
            if response is not None:
                refs = self._collect_finding_refs(
                    response,
                    trace_contract=trace_contract,
                    fallback_ids=[ambiguity.ambiguity_id],
                )
                findings.append(
                    ResearchFinding(
                        source="web_research",
                        text=str(getattr(response, "response_text", "") or "").strip(),
                        confidence=0.7,
                        refs=refs,
                        verified=False,
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
        *,
        trace_contract: dict[str, Any],
        operator_modes: list[str],
    ) -> None:
        if self._external_research_tool is None:
            log_stage("external_research", "skipped", "external tool not configured")
            return

        framed_question, framed_context = self._apply_operator_framing(query, operator_modes)
        payload = {
            "question": framed_question,
            "original_question": query.question,
            "context": framed_context,
            "original_context": query.context,
            "layer": query.layer,
            "run_id": trace_contract["run_id"],
            "slice_id": trace_contract["slice_id"],
            "iteration": trace_contract["iteration"],
            "capability": trace_contract["capability"],
            "event_id": trace_contract["event_id"],
            "trace_id": trace_contract["trace_id"],
            "operator_modes": [self._operator_label(mode) for mode in operator_modes],
            "hints": dict(query.hints or {}),
            "max_results": int(query.max_results),
        }

        raw: Any = None
        tool = self._external_research_tool
        try:
            if callable(tool):
                raw = self._invoke_external_callable(tool, payload)
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
                refs=self._collect_finding_refs(
                    raw,
                    trace_contract=trace_contract,
                    fallback_ids=[str(trace_contract.get("event_id", "") or "")],
                ),
                verified=False,
            )
        )
        log_stage("external_research", "hit", "external tool returned response")

    def _invoke_external_callable(self, tool: Any, payload: dict[str, Any]) -> Any:
        signature = self._resolve_callable_signature(tool)
        keyword_candidates = (
            {
                "question": payload["question"],
                "context": payload["context"],
                "trace_id": payload["trace_id"],
                "payload": payload,
            },
            {
                "question": payload["question"],
            },
            {
                "query": payload["question"],
                "context": payload["context"],
                "trace_id": payload["trace_id"],
            },
            {
                "query": payload["question"],
            },
            {
                "prompt": payload["question"],
                "context": payload["context"],
                "trace_id": payload["trace_id"],
            },
            {
                "prompt": payload["question"],
            },
            {
                "payload": payload,
            },
        )
        if signature is None:
            return tool(payload)

        for kwargs in keyword_candidates:
            if self._signature_accepts_kwargs(signature, kwargs):
                return tool(**kwargs)

        if self._signature_accepts_payload(signature, payload):
            return tool(payload)

        raise TypeError(
            "External research callable does not accept supported payload format "
            "(question/query/prompt kwargs or single payload argument)"
        )

    @staticmethod
    def _resolve_callable_signature(tool: Any) -> inspect.Signature | None:
        try:
            return inspect.signature(tool)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _signature_accepts_kwargs(signature: inspect.Signature, kwargs: dict[str, Any]) -> bool:
        try:
            signature.bind_partial(**kwargs)
        except TypeError:
            return False
        return True

    @staticmethod
    def _signature_accepts_payload(signature: inspect.Signature, payload: dict[str, Any]) -> bool:
        try:
            signature.bind_partial(payload)
        except TypeError:
            return False
        return True

    def _finalize_result(
        self,
        *,
        findings: list[ResearchFinding],
        metadata: dict[str, Any],
    ) -> ResearchResult:
        metadata["finding_count"] = len(findings)
        metadata["verified_finding_count"] = sum(1 for finding in findings if finding.verified)
        metadata["unverified_finding_count"] = len(findings) - int(
            metadata["verified_finding_count"]
        )

        if not findings:
            metadata["synthesis_status"] = "none"
            return ResearchResult(metadata=metadata)

        verified_findings = [finding for finding in findings if finding.verified]
        if verified_findings:
            best = max(verified_findings, key=lambda finding: finding.confidence)
            metadata["synthesis_status"] = "verified"
            metadata["synthesis_source"] = best.source
            return ResearchResult(
                findings=findings,
                synthesis=best.text,
                confidence=best.confidence,
                metadata=metadata,
            )

        best_unverified = max(findings, key=lambda finding: finding.confidence)
        metadata["synthesis_status"] = "blocked_unverified"
        metadata["synthesis_source"] = best_unverified.source
        metadata["blocked_unverified_synthesis"] = best_unverified.text
        return ResearchResult(
            findings=findings,
            synthesis="",
            confidence=0.0,
            metadata=metadata,
        )

    def _collect_finding_refs(
        self,
        payload: Any,
        *,
        trace_contract: dict[str, Any],
        fallback_ids: list[str] | None = None,
    ) -> list[str]:
        refs: list[str] = []
        refs.extend(self._extract_refs(payload))
        for fallback in fallback_ids or []:
            fallback_text = str(fallback or "").strip()
            if fallback_text:
                refs.append(f"id:{fallback_text}")
        trace_id = str(trace_contract.get("trace_id", "") or "").strip()
        if trace_id:
            refs.append(f"trace:{trace_id}")
        return self._dedupe_values(refs)

    def _extract_refs(self, payload: Any) -> list[str]:
        if payload is None:
            return []

        refs: list[str] = []
        scalar_keys = (
            "id",
            "ref",
            "url",
            "uri",
            "link",
            "source_id",
            "source_url",
            "reference_id",
            "trace_id",
            "ambiguity_id",
        )
        list_keys = ("refs", "references", "urls", "source_urls", "links", "sources")

        if isinstance(payload, dict):
            for key in scalar_keys:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append(value.strip())
            for key in list_keys:
                values = payload.get(key)
                if isinstance(values, list):
                    refs.extend(self._extract_refs(values))
            return self._dedupe_values(refs)

        if isinstance(payload, list):
            for item in payload:
                refs.extend(self._extract_refs(item))
            return self._dedupe_values(refs)

        for key in scalar_keys:
            value = getattr(payload, key, "")
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
        for key in list_keys:
            values = getattr(payload, key, None)
            if isinstance(values, list):
                refs.extend(self._extract_refs(values))
        return self._dedupe_values(refs)

    @staticmethod
    def _dedupe_values(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

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
