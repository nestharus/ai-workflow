# TODO(single-layer): KEEP/EXTEND — Pattern library concept aligns with proposal's
#   contract pattern templates (Section 7.2). The existing core rule catalog + strategy
#   packs MUST extend to include shape contract patterns (EVENT_FLOW, DI_BINDING,
#   MIDDLEWARE_ORDERING) as a concrete mechanism, not optional. The pattern library
#   already stores language-agnostic review rules; shape patterns are structural review
#   rules. Section 7 presents this as a minimal required library.
# ALGORITHM(single-layer):
#   References: response3 Section 7.2; evaluation modification #4.
#   Data structures:
#     - Extend Pattern.dimension enum set with CONTRACT_EVENT_FLOW, CONTRACT_DI_BINDING, CONTRACT_MIDDLEWARE_ORDERING.
#     - ContractPatternTemplate: {template_id: str, kind: Literal['EVENT_FLOW','DI_BINDING','MIDDLEWARE_ORDERING'], required_fields: list[str], verifier_requirement: str, example_block: str, enabled: bool}.
#     - PatternLibrary adds project_scope_id: str and contract_templates: list[ContractPatternTemplate].
#   Interface contracts:
#     - def ensure_contract_templates(self) -> None
#     - def validate_contract_pattern_coverage(self, shape_index: ShapePackIndex) -> list[dict[str, Any]]  # missing verifier test findings
#   Control flow:
#     1. Initialize built-in contract templates as non-optional defaults.
#     2. Scope templates per project/run and allow repository-specific overrides.
#     3. Validate pattern activation by checking referenced verifier tests exist.
#   Error handling:
#     - Missing verifier test for template usage returns actionable finding.
#   Integration points:
#     - Called by Architecture phase and matcher when creating contract-related work items.
# IMPL(single-layer): Architecture-phase reviewers and matcher-generated contract work
# items should consume the same contract template vocabulary (`EVENT_FLOW`,
# `DI_BINDING`, `MIDDLEWARE_ORDERING`) from this module to avoid split rule sources.
#   Test requirements:
#     - Default template presence.
#     - Project-scoped override behavior.
#     - Validation detects missing verifier tests.

"""Pattern library for language-agnostic code review.

Provides a core rule catalog of principles, optional strategy packs
for language/framework-specific detection cues, and an evolution
mechanism that collects StrategyCandidate instances from repeated
human approvals.

Core reviewers always run with core principles.  Strategy packs are
optional overlays scoped by language, framework, or repository.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.routing.shapes import ShapePackIndex

logger = logging.getLogger(__name__)

_CONTRACT_TEMPLATE_KINDS = {"EVENT_FLOW", "DI_BINDING", "MIDDLEWARE_ORDERING"}
_DIMENSION_TO_KIND = {
    "CONTRACT_EVENT_FLOW": "EVENT_FLOW",
    "CONTRACT_DI_BINDING": "DI_BINDING",
    "CONTRACT_MIDDLEWARE_ORDERING": "MIDDLEWARE_ORDERING",
}
_KIND_TO_DIMENSION = {
    "EVENT_FLOW": "CONTRACT_EVENT_FLOW",
    "DI_BINDING": "CONTRACT_DI_BINDING",
    "MIDDLEWARE_ORDERING": "CONTRACT_MIDDLEWARE_ORDERING",
}
DEFAULT_CONTRACT_SCOPE_PHASE: PhaseId = "architecture"


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class Pattern:
    """A single review pattern/rule.

    Attributes:
        pattern_id: Unique identifier.
        principle: Core language-agnostic statement of what must be true.
        signals: Optional language/framework-specific detection cues.
        fix_guidance: Minimal remediation suggestions.
        dimension: Which review dimension this pattern serves
            (ARCH_BOUNDARY, TOPOLOGY, PIN_COVERAGE, CLARITY, etc.).
        enabled: Whether this pattern is active.
    """

    pattern_id: str = ""
    principle: str = ""
    signals: list[dict[str, str]] = field(default_factory=list)
    fix_guidance: str = ""
    dimension: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pattern:
        """Reconstruct from a dict, ignoring unknown keys."""
        import dataclasses as _dc

        known = {f.name for f in _dc.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ContractPatternTemplate:
    """Contract-specific rule template for Architecture contracts."""

    template_id: str = ""
    kind: str = ""
    required_fields: list[str] = field(default_factory=list)
    verifier_requirement: str = ""
    example_block: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        project_scope_id: str = "",
    ) -> ContractPatternTemplate:
        """Reconstruct a template, applying optional scope-prefix filtering."""
        raw_template_id = str(data.get("template_id", "")).strip()
        if not raw_template_id:
            raise ValueError("contract template is missing template_id")

        if ":" in raw_template_id:
            scope_id, _, template_id = raw_template_id.partition(":")
            if scope_id and scope_id != project_scope_id:
                raise ValueError(f"contract template scoped to {scope_id}, not {project_scope_id}")
            raw_template_id = template_id

        if not raw_template_id:
            raise ValueError("contract template_id is empty after scope prefix parse")

        kind = str(data.get("kind", "")).strip()
        if kind not in _CONTRACT_TEMPLATE_KINDS:
            raise ValueError(f"unsupported contract template kind: {kind}")

        required_fields = data.get("required_fields", [])
        if not isinstance(required_fields, list) or not all(isinstance(item, str) for item in required_fields):
            raise ValueError("contract template required_fields must be list[str]")
        if not required_fields:
            raise ValueError("contract template required_fields cannot be empty")

        verifier_requirement = str(data.get("verifier_requirement", "")).strip()
        if not verifier_requirement:
            raise ValueError("contract template verifier_requirement cannot be empty")

        return cls(
            template_id=raw_template_id,
            kind=kind,
            required_fields=required_fields,
            verifier_requirement=verifier_requirement,
            example_block=str(data.get("example_block", "")).strip(),
            enabled=bool(data.get("enabled", True)),
        )


# IMPL(single-layer): `Pattern.dimension` remains the shared routing key consumed by
# reviewers; extend dimension values with `CONTRACT_EVENT_FLOW`,
# `CONTRACT_DI_BINDING`, and `CONTRACT_MIDDLEWARE_ORDERING` when contract templates
# are introduced so Architecture/Quality prompt generation can select them directly.


@dataclass
class StrategyPack:
    """Optional overlay of language/framework-specific signals.

    Attributes:
        pack_id: Unique identifier (e.g., "python", "fastapi").
        language: Target language (empty = language-agnostic).
        framework: Target framework (empty = framework-agnostic).
        scope: Scope qualifier (e.g., repository name).
        patterns: Patterns in this pack.
    """

    pack_id: str = ""
    language: str = ""
    framework: str = ""
    scope: str = ""
    patterns: list[Pattern] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "pack_id": self.pack_id,
            "language": self.language,
            "framework": self.framework,
            "scope": self.scope,
            "patterns": [p.to_dict() for p in self.patterns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyPack:
        """Reconstruct from a dict."""
        import dataclasses as _dc

        raw_patterns = data.get("patterns", []) if isinstance(data.get("patterns"), list) else []
        patterns = [Pattern.from_dict(p) for p in raw_patterns]
        known = {f.name for f in _dc.fields(cls)} - {"patterns"}
        return cls(patterns=patterns, **{k: v for k, v in data.items() if k in known})


@dataclass
class StrategyCandidate:
    """Candidate for evolution into a strategy pattern.

    Created when a human approves a fix or a recurring finding is detected.

    Attributes:
        signal_patterns: Code patterns observed in the codebase.
        approved_remediation: The fix that was approved.
        exceptions: Known false positives.
        occurrences: How many times this was seen.
        source_dimension: Which review dimension generated this.
    """

    signal_patterns: list[str] = field(default_factory=list)
    approved_remediation: str = ""
    exceptions: list[str] = field(default_factory=list)
    occurrences: int = 1
    source_dimension: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return asdict(self)


# ------------------------------------------------------------------
# Default core patterns
# ------------------------------------------------------------------


def _default_core_patterns() -> list[Pattern]:
    """Return built-in core patterns covering all review dimensions."""
    # IMPL(single-layer): Keep base core principles here, and layer in non-optional
    # contract templates via PatternLibrary initialization (Section 7.2) rather than
    # making contract coverage dependent on optional strategy packs.
    return [
        # ---- ARCH_BOUNDARY (4 patterns) ----
        Pattern(
            pattern_id="AB-001",
            principle="Each component must have a single, clearly defined responsibility.",
            dimension="ARCH_BOUNDARY",
            fix_guidance="Split the component so each piece owns exactly one concern.",
        ),
        Pattern(
            pattern_id="AB-002",
            principle=(
                "Dependencies must flow in one direction: higher layers depend on "
                "lower layers, never the reverse."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance="Invert the dependency or introduce an abstraction at the boundary.",
        ),
        Pattern(
            pattern_id="AB-003",
            principle=(
                "Cross-cutting concerns must not leak implementation details across "
                "component boundaries."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance=(
                "Route cross-cutting behavior through a dedicated mechanism rather than "
                "direct coupling."
            ),
        ),
        Pattern(
            pattern_id="AB-004",
            principle=(
                "Public interfaces of a component must be the only way other "
                "components interact with it."
            ),
            dimension="ARCH_BOUNDARY",
            fix_guidance=(
                "Remove internal-detail references and route through the declared public interface."
            ),
        ),
        # ---- TOPOLOGY (4 patterns) ----
        Pattern(
            pattern_id="TP-001",
            principle="Every declared component must be reachable from at least one entrypoint.",
            dimension="TOPOLOGY",
            fix_guidance="Wire the orphan component into an existing handler chain or remove it.",
        ),
        Pattern(
            pattern_id="TP-002",
            principle=(
                "Handler chains must be complete: every event that is emitted must have a consumer."
            ),
            dimension="TOPOLOGY",
            fix_guidance="Add a handler for the unconsumed event or remove the emission.",
        ),
        Pattern(
            pattern_id="TP-003",
            principle="All declared entrypoints must be reachable and functional.",
            dimension="TOPOLOGY",
            fix_guidance="Connect the entrypoint to the component graph or remove the declaration.",
        ),
        Pattern(
            pattern_id="TP-004",
            principle=(
                "Data flow paths must form complete pipelines from source to sink "
                "with no dead ends."
            ),
            dimension="TOPOLOGY",
            fix_guidance="Extend the pipeline to a terminal consumer or prune the dead-end branch.",
        ),
        # ---- PIN_COVERAGE (3 patterns) ----
        Pattern(
            pattern_id="PC-001",
            principle="Every promoted pin must be consumed by at least one downstream component.",
            dimension="PIN_COVERAGE",
            fix_guidance="Add a consumer for the orphan pin or revoke the promotion.",
        ),
        Pattern(
            pattern_id="PC-002",
            principle="No edge in the component graph may reference a pin that does not exist.",
            dimension="PIN_COVERAGE",
            fix_guidance="Create the missing pin or correct the edge reference.",
        ),
        Pattern(
            pattern_id="PC-003",
            principle=(
                "Every edge declared in the architecture must be realized in the implementation."
            ),
            dimension="PIN_COVERAGE",
            fix_guidance="Implement the declared edge or remove it from the architecture manifest.",
        ),
        # ---- ARCH_DRIFT (3 patterns) ----
        Pattern(
            pattern_id="AD-001",
            principle="The implementation must conform to the declared architecture manifest.",
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Update the implementation to match the manifest, or amend the "
                "manifest through the promotion process."
            ),
        ),
        Pattern(
            pattern_id="AD-002",
            principle=(
                "No component may exist in the implementation without a corresponding declaration."
            ),
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Declare the component in the manifest or remove it from the implementation."
            ),
        ),
        Pattern(
            pattern_id="AD-003",
            principle=(
                "Configuration and environment values must be externalized, not "
                "embedded in component logic."
            ),
            dimension="ARCH_DRIFT",
            fix_guidance=(
                "Move the embedded value to a configuration source and reference it indirectly."
            ),
        ),
        # ---- GOVERNANCE (3 patterns) ----
        Pattern(
            pattern_id="GV-001",
            principle="Every promotion decision must have a recorded receipt with rationale.",
            dimension="GOVERNANCE",
            fix_guidance="Generate a decision receipt before allowing the promotion to proceed.",
        ),
        Pattern(
            pattern_id="GV-002",
            principle=(
                "No artifact may be modified without an authorized promotion or demotion ticket."
            ),
            dimension="GOVERNANCE",
            fix_guidance="Route the change through the promotion loop or create a demotion ticket.",
        ),
        Pattern(
            pattern_id="GV-003",
            principle=(
                "Evidence bundles must contain all required references before a gate can pass."
            ),
            dimension="GOVERNANCE",
            fix_guidance="Populate the missing evidence references in the bundle.",
        ),
        # ---- CLARITY (2 patterns) ----
        Pattern(
            pattern_id="CL-001",
            principle=(
                "Code structure and naming must convey intent without requiring "
                "external documentation."
            ),
            dimension="CLARITY",
            fix_guidance="Rename symbols to express their purpose and restructure for readability.",
        ),
        Pattern(
            pattern_id="CL-002",
            principle=(
                "Function and type names must accurately describe what they do, not how they do it."
            ),
            dimension="CLARITY",
            fix_guidance=(
                "Rename to reflect the behavioral contract rather than the "
                "implementation mechanism."
            ),
        ),
        # ---- CONSISTENCY (2 patterns) ----
        Pattern(
            pattern_id="CN-001",
            principle=(
                "Public APIs within the same component must follow uniform conventions "
                "for signatures, return types, and error handling."
            ),
            dimension="CONSISTENCY",
            fix_guidance=(
                "Align the inconsistent API to match the established convention in the component."
            ),
        ),
        Pattern(
            pattern_id="CN-002",
            principle=(
                "Naming, formatting, and structural conventions must be uniform "
                "within a codebase scope."
            ),
            dimension="CONSISTENCY",
            fix_guidance="Apply the dominant convention consistently across the scope.",
        ),
        # ---- MAINTAINABILITY (2 patterns) ----
        Pattern(
            pattern_id="MT-001",
            principle=(
                "No single function or method should exceed a complexity threshold "
                "that impairs understanding."
            ),
            dimension="MAINTAINABILITY",
            fix_guidance="Extract sub-routines or simplify control flow to reduce complexity.",
        ),
        Pattern(
            pattern_id="MT-002",
            principle="Duplicated logic must be consolidated into a single authoritative location.",
            dimension="MAINTAINABILITY",
            fix_guidance="Extract the duplicated logic into a shared function or module.",
        ),
        # ---- CORRECTNESS (2 patterns) ----
        Pattern(
            pattern_id="CR-001",
            principle=(
                "All boundary conditions and edge cases identified in the spec must "
                "have corresponding handling."
            ),
            dimension="CORRECTNESS",
            fix_guidance="Add explicit handling for the missing edge case.",
        ),
        Pattern(
            pattern_id="CR-002",
            principle=(
                "Every error path must terminate in a defined recovery or propagation action."
            ),
            dimension="CORRECTNESS",
            fix_guidance="Add error handling that either recovers or propagates with context.",
        ),
        # ---- DRIFT (2 patterns) ----
        Pattern(
            pattern_id="DR-001",
            principle=(
                "Implementation must not introduce capabilities beyond what the "
                "current plan specifies."
            ),
            dimension="DRIFT",
            fix_guidance=(
                "Remove the unplanned capability or create a plan amendment through "
                "the promotion loop."
            ),
        ),
        Pattern(
            pattern_id="DR-002",
            principle="Each iteration's changes must be traceable to a gap or plan item.",
            dimension="DRIFT",
            fix_guidance="Link the change to an existing plan item or file a new gap.",
        ),
        # ---- DIFF_IMPACT (2 patterns) ----
        Pattern(
            pattern_id="DI-001",
            principle=(
                "A refactor-only change must preserve observable behavior at all declared "
                "interfaces and side-effect boundaries."
            ),
            dimension="DIFF_IMPACT",
            fix_guidance=(
                "Rework the patch to preserve behavior, or reclassify and route it as a "
                "behavior_change."
            ),
        ),
        Pattern(
            pattern_id="DI-002",
            principle=(
                "Any detected behavior change must be explicitly classified and demoted to "
                "the authoritative layer before promotion can continue."
            ),
            dimension="DIFF_IMPACT",
            fix_guidance=(
                "Emit a behavior_change finding with evidence and route the change through "
                "the appropriate lower-layer workflow."
            ),
        ),
    ]


def _default_contract_templates() -> list[ContractPatternTemplate]:
    """Return built-in contract templates for structural contract checks."""
    return [
        ContractPatternTemplate(
            template_id="CONTRACT-EVENT-FLOW",
            kind="EVENT_FLOW",
            required_fields=["producer_shape_id", "consumer_shape_ids", "payload_schema_ref"],
            verifier_requirement="all_declared_verifiers",
            example_block=(
                "EVENT_FLOW contracts define producer/consumer communication."
            ),
        ),
        ContractPatternTemplate(
            template_id="CONTRACT-DI-BINDING",
            kind="DI_BINDING",
            required_fields=["producer_shape_id", "consumer_shape_ids", "metadata"],
            verifier_requirement="all_declared_verifiers",
            example_block="DI_BINDING contracts assert injected binding edges.",
        ),
        ContractPatternTemplate(
            template_id="CONTRACT-MIDDLEWARE-ORDERING",
            kind="MIDDLEWARE_ORDERING",
            required_fields=[
                "producer_shape_id",
                "consumer_shape_ids",
                "payload_schema_ref",
                "metadata",
            ],
            verifier_requirement="all_declared_verifiers",
            example_block=(
                "MIDDLEWARE_ORDERING contracts capture middleware chain and "
                "interceptor order constraints."
            ),
        ),
    ]


def _coerce_contract_fields(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    fields: list[str] = []
    for item in raw:
        value = str(item).strip()
        if value:
            fields.append(value)
    return fields


# ------------------------------------------------------------------
# PatternLibrary
# ------------------------------------------------------------------


class PatternLibrary:
    """Manages core patterns and strategy packs.

    The library is loaded from a JSON file and provides patterns
    to reviewers.  Core patterns are language-agnostic principles.
    Strategy packs add optional detection cues.
    """

    def __init__(self, library_path: Path | None = None) -> None:
        self._core_patterns: list[Pattern] = []
        self._strategy_packs: list[StrategyPack] = []
        self._candidates: list[StrategyCandidate] = []
        self._project_scope_id = self._infer_project_scope_id(library_path)
        self._contract_templates: list[ContractPatternTemplate] = []
        # IMPL(single-layer): Add run/project scoping fields here
        # (`project_scope_id`, `contract_templates`) so per-run overrides can be loaded
        # before review prompts and matcher work-item generation execute.
        self._library_path = library_path
        if library_path and library_path.exists():
            self._load(library_path)
        else:
            self._load_defaults()
        self.ensure_contract_templates()

    # -- persistence -------------------------------------------------

    def _load_defaults(self) -> None:
        """Load built-in core patterns."""
        self._core_patterns = _default_core_patterns()
        self._contract_templates = _default_contract_templates()

    def _infer_project_scope_id(self, library_path: Path | None) -> str:
        """Infer a project/run scope identifier from path metadata."""
        if library_path is None:
            return ""
        resolved = library_path.resolve()
        parts = list(resolved.parts)
        if ".pdd_runs" in parts:
            idx = parts.index(".pdd_runs")
            if idx + 1 < len(parts):
                scope = parts[idx + 1]
                if scope != resolved.name:
                    return scope
            if idx > 0:
                return parts[idx - 1]
        return resolved.parent.name if resolved.parent != resolved else ""

    def _load(self, path: Path) -> None:
        """Load patterns from JSON file."""
        # IMPL(single-layer): Loading should fail closed for malformed
        # `contract_templates` entries that omit required verifier metadata, because
        # Section 7.2 treats verifier-backed contracts as required, not advisory.
        data = json.loads(path.read_text(encoding="utf-8"))
        self._core_patterns = [Pattern.from_dict(p) for p in data.get("core_patterns", [])]
        self._strategy_packs = [StrategyPack.from_dict(sp) for sp in data.get("strategy_packs", [])]
        self._candidates = [StrategyCandidate(**c) for c in data.get("candidates", [])]
        override_scope = str(data.get("project_scope_id", "")).strip()
        if override_scope:
            self._project_scope_id = override_scope

        raw_templates = data.get("contract_templates", [])
        if isinstance(raw_templates, list):
            parsed: list[ContractPatternTemplate] = []
            for raw_template in raw_templates:
                if not isinstance(raw_template, dict):
                    raise ValueError("contract_templates entries must be dict objects")
                try:
                    parsed.append(
                        ContractPatternTemplate.from_dict(
                            raw_template,
                            project_scope_id=self._project_scope_id,
                        )
                    )
                except ValueError as exc:
                    logger.debug("Skipping scoped or invalid template %r: %s", raw_template, exc)
                    if ":" in str(raw_template.get("template_id", "")):
                        continue
                    raise
            self._contract_templates = parsed
        elif not raw_templates:
            self._contract_templates = []
        else:
            raise ValueError("contract_templates must be a list")

    def save(self, path: Path | None = None) -> Path:
        """Persist the library to disk."""
        target = path or self._library_path or Path("pattern_library.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        # IMPL(single-layer): Persist `project_scope_id` and `contract_templates` in the
        # same artifact as core patterns so lifecycle/promotion loops read one coherent
        # rule bundle per run.
        data = {
            "core_patterns": [p.to_dict() for p in self._core_patterns],
            "strategy_packs": [sp.to_dict() for sp in self._strategy_packs],
            "candidates": [c.to_dict() for c in self._candidates],
            "project_scope_id": self._project_scope_id,
            "contract_templates": [template.to_dict() for template in self._contract_templates],
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return target

    # -- query -------------------------------------------------------

    def ensure_contract_templates(self) -> None:
        """Apply defaults and merge with per-scope overrides."""
        defaults = _default_contract_templates()
        by_id: dict[str, int] = {template.template_id: idx for idx, template in enumerate(defaults)}
        merged = defaults
        for template in self._contract_templates:
            if template.template_id in by_id:
                merged[by_id[template.template_id]] = template
            elif template.template_id not in by_id:
                merged.append(template)
        self._contract_templates = merged

    def _normalize_verifier_requirement(self, requirement: str) -> str:
        """Normalize requirement policy labels."""
        normalized = str(requirement or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"all", "all_declared", "all_declared_verifiers"}:
            return "all_declared"
        if normalized in {"any", "at_least_one", "at_least_one_verifier", "one_of"}:
            return "at_least_one"
        return normalized or "all_declared"

    def _template_dimension(self, kind: str) -> str:
        return _KIND_TO_DIMENSION.get(kind, "")

    def _template_to_pattern(self, template: ContractPatternTemplate) -> Pattern:
        signals: list[dict[str, str]] = []
        if template.required_fields:
            signals.append(
                {
                    "language": "contract",
                    "cue": "required_fields=" + ",".join(template.required_fields),
                }
            )
        if template.verifier_requirement:
            signals.append(
                {
                    "language": "contract",
                    "cue": "verifier_requirement=" + template.verifier_requirement,
                }
            )
        guidance_lines = [line.strip() for line in template.example_block.splitlines() if line.strip()]
        if guidance_lines:
            fix_guidance = " ".join(guidance_lines)
        else:
            fix_guidance = "Apply contract template requirements and verifier evidence checks."
        return Pattern(
            pattern_id=template.template_id,
            principle=f"{template.kind} contracts must satisfy deterministic validator requirements.",
            signals=signals,
            fix_guidance=fix_guidance,
            dimension=self._template_dimension(template.kind),
            enabled=template.enabled,
        )

    def get_patterns_for_dimension(
        self,
        dimension: str,
        *,
        language: str = "",
        framework: str = "",
    ) -> list[Pattern]:
        """Get all active patterns for a review dimension.

        Includes core patterns plus any matching strategy pack overlays
        filtered by language and framework.
        """
        # IMPL(single-layer): Contract dimensions must be resolvable through this same
        # selector so callers (`promotion_loop`, `pdd_lifecycle`) do not need a separate
        # contract-pattern query path.
        patterns = [p for p in self._core_patterns if p.dimension == dimension and p.enabled]
        for sp in self._strategy_packs:
            if language and sp.language and sp.language != language:
                continue
            if framework and sp.framework and sp.framework != framework:
                continue
            patterns.extend(p for p in sp.patterns if p.dimension == dimension and p.enabled)

        template_kind = _DIMENSION_TO_KIND.get(dimension, "")
        if template_kind:
            patterns.extend(
                self._template_to_pattern(template)
                for template in self._contract_templates
                if template.enabled and template.kind == template_kind
            )
        return patterns

    def get_review_prompt_section(self, dimension: str, **kwargs: Any) -> str:
        """Generate a prompt section with patterns for a given dimension.

        Returns a markdown-formatted block suitable for inclusion in
        an LLM review prompt.  Returns empty string if no patterns match.
        """
        # IMPL(single-layer): Contract template prompts should include verifier
        # requirements/required fields so review output can directly map to
        # deterministic verifier-backed work items.
        patterns = self.get_patterns_for_dimension(dimension, **kwargs)
        if not patterns:
            return ""
        lines: list[str] = ["## Review Patterns", ""]
        for p in patterns:
            lines.append(f"### {p.pattern_id}: {p.principle}")
            if p.signals:
                lines.append("Signals:")
                for sig in p.signals:
                    lang = sig.get("language", "any")
                    cue = sig.get("cue", "")
                    lines.append(f"  - [{lang}] {cue}")
            if p.fix_guidance:
                lines.append(f"Fix: {p.fix_guidance}")
            lines.append("")
        return "\n".join(lines)

    def validate_contract_pattern_coverage(
        self,
        shape_index: ShapePackIndex,
    ) -> list[dict[str, Any]]:
        """Detect missing contract verifier coverage in shape contracts."""
        findings: list[dict[str, Any]] = []
        templates = {
            template.kind: template
            for template in self._contract_templates
            if template.enabled and template.kind in _CONTRACT_TEMPLATE_KINDS
        }

        for shape in shape_index.shapes.values():
            available_verifiers = {str(verifier.verifier_id).strip() for verifier in shape.verifiers}
            for contract in shape.contracts:
                template = templates.get(str(contract.kind).strip())
                if not template:
                    continue

                contract_as_dict = asdict(contract)
                missing_fields = [
                    field_name
                    for field_name in template.required_fields
                    if not self._has_required_metadata(contract_as_dict, field_name)
                ]
                if missing_fields:
                    findings.append(
                        {
                            "shape_id": str(shape.shape_id),
                            "phase": DEFAULT_CONTRACT_SCOPE_PHASE,
                            "contract_id": str(contract.contract_id),
                            "contract_kind": str(contract.kind),
                            "template_id": template.template_id,
                            "finding": "missing_required_fields",
                            "required_fields": template.required_fields,
                            "missing_fields": missing_fields,
                            "severity": "BLOCKER",
                            "message": (
                                f"Contract {contract.contract_id} on shape {shape.shape_id} "
                                f"missing required fields: {', '.join(missing_fields)}"
                            ),
                            "evidence_refs": [
                                f"contract:{contract.contract_id}:required-field:{field_name}"
                                for field_name in missing_fields
                            ],
                            "required_change_type": "spec_change",
                        }
                    )

                required_verifiers = [
                    str(item).strip() for item in contract.verifier_ids if str(item).strip()
                ]
                requirement_mode = self._normalize_verifier_requirement(template.verifier_requirement)
                missing_verifiers: list[str] = []
                if requirement_mode == "at_least_one":
                    if not required_verifiers or not any(
                        verifier_id in available_verifiers for verifier_id in required_verifiers
                    ):
                        missing_verifiers = required_verifiers or ["<missing-verifier>"]
                else:
                    missing_verifiers = [
                        verifier_id
                        for verifier_id in required_verifiers
                        if verifier_id not in available_verifiers
                    ]
                    if not required_verifiers:
                        missing_verifiers = ["<missing-verifier>"]

                if missing_verifiers:
                    findings.append(
                        {
                            "shape_id": str(shape.shape_id),
                            "phase": DEFAULT_CONTRACT_SCOPE_PHASE,
                            "contract_id": str(contract.contract_id),
                            "contract_kind": str(contract.kind),
                            "template_id": template.template_id,
                            "finding": "missing_contract_verifiers",
                            "required_verifiers": required_verifiers,
                            "missing_verifiers": missing_verifiers,
                            "severity": "BLOCKER",
                            "message": (
                                f"Contract {contract.contract_id} on shape {shape.shape_id} "
                                "references verifier IDs that are not declared for the shape"
                            ),
                            "evidence_refs": [
                                f"contract:{contract.contract_id}:missing-verifier:{verifier_id}"
                                for verifier_id in missing_verifiers
                            ],
                            "required_change_type": "spec_change",
                        }
                    )
        return findings

    @staticmethod
    def _has_required_metadata(data: dict[str, Any], path: str) -> bool:
        """Return true when a dotted field path exists and has non-empty value."""
        cursor: Any = data
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return False
            cursor = cursor[part]
        if isinstance(cursor, (list, tuple, dict)):
            return bool(cursor)
        return str(cursor).strip() != ""

    # -- evolution ---------------------------------------------------

    def record_candidate(self, candidate: StrategyCandidate) -> None:
        """Record a strategy candidate from a repeated finding or human approval.

        If a candidate with overlapping signal patterns and the same
        source dimension already exists, the occurrence count is merged
        and signal patterns are unioned.
        """
        for existing in self._candidates:
            if existing.source_dimension == candidate.source_dimension and set(
                existing.signal_patterns
            ) & set(candidate.signal_patterns):
                existing.occurrences += candidate.occurrences
                existing.signal_patterns = list(
                    set(existing.signal_patterns) | set(candidate.signal_patterns)
                )
                return
        self._candidates.append(candidate)

    # -- properties --------------------------------------------------

    @property
    def candidates(self) -> list[StrategyCandidate]:
        """All recorded strategy candidates."""
        return list(self._candidates)

    @property
    def core_patterns(self) -> list[Pattern]:
        """All core patterns (read-only copy)."""
        return list(self._core_patterns)

    @property
    def strategy_packs(self) -> list[StrategyPack]:
        """All strategy packs (read-only copy)."""
        return list(self._strategy_packs)

    @property
    def project_scope_id(self) -> str:
        """Current run/project scope."""
        return self._project_scope_id

    @property
    def contract_templates(self) -> list[ContractPatternTemplate]:
        """Contract templates (read-only copy)."""
        return list(self._contract_templates)
