"""Promotion gate orchestrator.

Wires all gate checks into a single orchestrator and integrates with
the existing compliance module.
"""

from __future__ import annotations

import time
from pathlib import Path

# Conditional imports for entity coverage gate
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.algorithmic_gates import (
    check_all_tests_pass,
    check_call_graph_connected,
    check_no_remaining_comments,
    check_no_stub_functions,
    check_store_monogamy,
)
from spec_manager.compliance.promotion.architectural_quality import (
    check_function_recomposition,
    check_no_inlined_atom_logic,
)
from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.introduction_checker import (
    check_introduced_algorithm_specs,
)
from spec_manager.compliance.promotion.pin_coverage import (
    build_pin_coverage_report,
    check_pin_coverage,
)
from spec_manager.compliance.promotion.provenance import (
    ProvenanceRegistry,
    check_provenance_complete,
)
from spec_manager.compliance.promotion.result import (
    GateCheckResult,
    PromotionReport,
)
from spec_manager.compliance.promotion.test_pin_gate import (
    check_test_pin_alignment_gate,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry

if TYPE_CHECKING:
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.schemas.entities import EntitiesArtifact


class LayerPromotionGate:
    """Orchestrates all promotion gate checks.

    Usage:
        config = PromotionGateConfig.default()
        gate = LayerPromotionGate(config, pin_registry)
        report = gate.run_all_checks()
        if report.passed:
            # Safe to promote to architectural branch
            ...
        else:
            for blocker in report.blockers:
                print(f"BLOCKED: {blocker.gate_id}: {blocker.summary}")
    """

    def __init__(
        self,
        config: PromotionGateConfig,
        pin_registry: PinFunctionRegistry | None = None,
        provenance_registry_path: Path | None = None,
        evidence_index: EvidenceIndex | None = None,
        entities_artifact: EntitiesArtifact | None = None,
    ) -> None:
        """Initialize the promotion gate.

        Args:
            config: Gate configuration.
            pin_registry: PinFunctionRegistry for pin coverage checks.
                If None, pin-related gates are skipped with a warning.
            provenance_registry_path: Path to the provenance registry JSON.
                If None, provenance gate is skipped with a warning.
            evidence_index: EvidenceIndex for entity coverage checks.
                If None, entity coverage gate is skipped with a warning.
            entities_artifact: EntitiesArtifact for explicit entity-atom linkage.
                Optional even when evidence_index is provided.
        """
        self._config = config
        self._pin_registry = pin_registry
        self._provenance_registry_path = provenance_registry_path
        self._evidence_index = evidence_index
        self._entities_artifact = entities_artifact
        self._project_root = Path(config.project_root)

    def run_all_checks(self) -> PromotionReport:
        """Run all enabled gate checks and produce a promotion report.

        Gate execution order:
        1. Algorithmic layer gates (comments, stubs, tests, call graph, stores)
        2. Pin coverage check
        3. Introduced algorithm spec check
        4. Provenance completeness check
        5. Architectural quality checks (inlined logic, recomposition)

        Returns:
            PromotionReport with all gate results.
        """
        start = time.monotonic()
        results: list[GateCheckResult] = []

        # 1. Algorithmic layer gates
        algorithmic_files = self._resolve_files(self._config.algorithmic_roots)

        for gate_id, runner in [
            (GateId.NO_REMAINING_COMMENTS, lambda: self._run_comments(algorithmic_files)),
            (GateId.NO_STUB_FUNCTIONS, lambda: self._run_stubs(algorithmic_files)),
            (GateId.ALL_TESTS_PASS, lambda: self._run_tests()),
            (GateId.CALL_GRAPH_CONNECTED, lambda: self._run_call_graph(algorithmic_files)),
            (GateId.STORE_MONOGAMY, lambda: self._run_store_monogamy(algorithmic_files)),
        ]:
            gate_spec = self._config.get_gate(gate_id)
            if gate_spec.enabled:
                results.append(runner())

        # 2. Pin coverage check
        architectural_files = self._resolve_files(self._config.architectural_roots)
        pin_coverage_report = None

        gate_spec = self._config.get_gate(GateId.PIN_COVERAGE)
        if gate_spec.enabled:
            if self._pin_registry is not None:
                result = check_pin_coverage(self._pin_registry, architectural_files, gate_spec)
                results.append(result)
                pin_coverage_report = build_pin_coverage_report(
                    self._pin_registry, architectural_files
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.PIN_COVERAGE, gate_spec, "PinFunctionRegistry not provided"
                    )
                )

        # 3. Introduced algorithm spec check
        gate_spec = self._config.get_gate(GateId.INTRODUCED_ALGORITHM_SPECS)
        if gate_spec.enabled:
            if self._pin_registry is not None and pin_coverage_report is not None:
                results.append(
                    check_introduced_algorithm_specs(
                        pin_coverage_report, architectural_files, gate_spec
                    )
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.INTRODUCED_ALGORITHM_SPECS,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    )
                )

        # 4. Provenance completeness check
        gate_spec = self._config.get_gate(GateId.PROVENANCE_COMPLETE)
        if gate_spec.enabled:
            if self._pin_registry is not None:
                provenance_registry = self._load_provenance()
                results.append(
                    check_provenance_complete(self._pin_registry, provenance_registry, gate_spec)
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.PROVENANCE_COMPLETE, gate_spec, "PinFunctionRegistry not provided"
                    )
                )

        # 5. Architectural quality checks
        gate_spec = self._config.get_gate(GateId.NO_INLINED_ATOM_LOGIC)
        if gate_spec.enabled:
            if self._pin_registry is not None:
                results.append(
                    check_no_inlined_atom_logic(
                        self._pin_registry, architectural_files, algorithmic_files, gate_spec
                    )
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.NO_INLINED_ATOM_LOGIC, gate_spec, "PinFunctionRegistry not provided"
                    )
                )

        gate_spec = self._config.get_gate(GateId.FUNCTION_RECOMPOSITION)
        if gate_spec.enabled:
            if self._pin_registry is not None:
                results.append(
                    check_function_recomposition(self._pin_registry, architectural_files, gate_spec)
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.FUNCTION_RECOMPOSITION, gate_spec, "PinFunctionRegistry not provided"
                    )
                )

        # 6. Test-pin alignment check
        gate_spec = self._config.get_gate(GateId.TEST_PIN_ALIGNMENT)
        if gate_spec.enabled:
            if self._pin_registry is not None:
                test_roots = [
                    self._project_root / r for r in gate_spec.params.get("test_roots", ["tests/"])
                ]
                baseline_path = self._project_root / ".spec" / "test_pin_baselines.json"
                results.append(
                    check_test_pin_alignment_gate(
                        self._pin_registry, test_roots, baseline_path, gate_spec
                    )
                )
            else:
                results.append(
                    self._skip_gate(
                        GateId.TEST_PIN_ALIGNMENT, gate_spec, "PinFunctionRegistry not provided"
                    )
                )

        # 7. Entity coverage check
        gate_spec = self._config.get_gate(GateId.ENTITY_COVERAGE)
        if gate_spec.enabled:
            if self._evidence_index is not None:
                from spec_manager.compliance.coverage.gate import check_entity_coverage

                results.append(
                    check_entity_coverage(
                        self._evidence_index,
                        self._atom_registry_for_coverage(),
                        gate_spec,
                        self._entities_artifact,
                    )
                )
            else:
                results.append(
                    self._skip_gate(GateId.ENTITY_COVERAGE, gate_spec, "EvidenceIndex not provided")
                )

        total_duration = (time.monotonic() - start) * 1000
        return self._build_report(results, total_duration)

    def run_single_check(self, gate_id: GateId) -> GateCheckResult:
        """Run a single gate check by ID.

        Args:
            gate_id: Which gate to run.

        Returns:
            GateCheckResult for the specified gate.
        """
        gate_spec = self._config.get_gate(gate_id)
        algorithmic_files = self._resolve_files(self._config.algorithmic_roots)
        architectural_files = self._resolve_files(self._config.architectural_roots)

        runners: dict[GateId, Any] = {
            GateId.NO_REMAINING_COMMENTS: lambda: check_no_remaining_comments(
                algorithmic_files, gate_spec
            ),
            GateId.NO_STUB_FUNCTIONS: lambda: check_no_stub_functions(algorithmic_files, gate_spec),
            GateId.ALL_TESTS_PASS: lambda: check_all_tests_pass(
                self._config.test_command, self._project_root, gate_spec
            ),
            GateId.CALL_GRAPH_CONNECTED: lambda: check_call_graph_connected(
                algorithmic_files, self._project_root, gate_spec
            ),
            GateId.STORE_MONOGAMY: lambda: check_store_monogamy(
                algorithmic_files, self._project_root, gate_spec
            ),
            GateId.PIN_COVERAGE: lambda: check_pin_coverage(
                self._pin_registry, architectural_files, gate_spec
            )
            if self._pin_registry
            else self._skip_gate(
                GateId.PIN_COVERAGE, gate_spec, "PinFunctionRegistry not provided"
            ),
            GateId.INTRODUCED_ALGORITHM_SPECS: lambda: self._run_introduction_check(
                architectural_files, gate_spec
            ),
            GateId.NO_INLINED_ATOM_LOGIC: lambda: check_no_inlined_atom_logic(
                self._pin_registry, architectural_files, algorithmic_files, gate_spec
            )
            if self._pin_registry
            else self._skip_gate(
                GateId.NO_INLINED_ATOM_LOGIC, gate_spec, "PinFunctionRegistry not provided"
            ),
            GateId.FUNCTION_RECOMPOSITION: lambda: check_function_recomposition(
                self._pin_registry, architectural_files, gate_spec
            )
            if self._pin_registry
            else self._skip_gate(
                GateId.FUNCTION_RECOMPOSITION, gate_spec, "PinFunctionRegistry not provided"
            ),
            GateId.PROVENANCE_COMPLETE: lambda: check_provenance_complete(
                self._pin_registry, self._load_provenance(), gate_spec
            )
            if self._pin_registry
            else self._skip_gate(
                GateId.PROVENANCE_COMPLETE, gate_spec, "PinFunctionRegistry not provided"
            ),
            GateId.ENTITY_COVERAGE: lambda: self._run_entity_coverage(gate_spec),
            GateId.TEST_PIN_ALIGNMENT: lambda: self._run_test_pin_alignment(gate_spec),
        }

        return runners[gate_id]()

    def _run_comments(self, algorithmic_files: list[Path]) -> GateCheckResult:
        gate_spec = self._config.get_gate(GateId.NO_REMAINING_COMMENTS)
        return check_no_remaining_comments(algorithmic_files, gate_spec)

    def _run_stubs(self, algorithmic_files: list[Path]) -> GateCheckResult:
        gate_spec = self._config.get_gate(GateId.NO_STUB_FUNCTIONS)
        return check_no_stub_functions(algorithmic_files, gate_spec)

    def _run_tests(self) -> GateCheckResult:
        gate_spec = self._config.get_gate(GateId.ALL_TESTS_PASS)
        return check_all_tests_pass(self._config.test_command, self._project_root, gate_spec)

    def _run_call_graph(self, algorithmic_files: list[Path]) -> GateCheckResult:
        gate_spec = self._config.get_gate(GateId.CALL_GRAPH_CONNECTED)
        return check_call_graph_connected(algorithmic_files, self._project_root, gate_spec)

    def _run_store_monogamy(self, algorithmic_files: list[Path]) -> GateCheckResult:
        gate_spec = self._config.get_gate(GateId.STORE_MONOGAMY)
        return check_store_monogamy(algorithmic_files, self._project_root, gate_spec)

    def _run_introduction_check(
        self,
        architectural_files: list[Path],
        gate_spec: GateSpec,
    ) -> GateCheckResult:
        if self._pin_registry is None:
            return self._skip_gate(
                GateId.INTRODUCED_ALGORITHM_SPECS, gate_spec, "PinFunctionRegistry not provided"
            )
        pin_coverage = build_pin_coverage_report(self._pin_registry, architectural_files)
        return check_introduced_algorithm_specs(pin_coverage, architectural_files, gate_spec)

    def _run_test_pin_alignment(self, gate_spec: GateSpec) -> GateCheckResult:
        """Run test-pin alignment gate check."""
        if self._pin_registry is None:
            return self._skip_gate(
                GateId.TEST_PIN_ALIGNMENT, gate_spec, "PinFunctionRegistry not provided"
            )
        test_roots = [
            self._project_root / r for r in gate_spec.params.get("test_roots", ["tests/"])
        ]
        baseline_path = self._project_root / ".spec" / "test_pin_baselines.json"
        return check_test_pin_alignment_gate(
            self._pin_registry, test_roots, baseline_path, gate_spec
        )

    def _run_entity_coverage(self, gate_spec: GateSpec) -> GateCheckResult:
        """Run entity coverage gate check."""
        if self._evidence_index is None:
            return self._skip_gate(GateId.ENTITY_COVERAGE, gate_spec, "EvidenceIndex not provided")
        from spec_manager.compliance.coverage.gate import check_entity_coverage

        return check_entity_coverage(
            self._evidence_index,
            self._atom_registry_for_coverage(),
            gate_spec,
            self._entities_artifact,
        )

    def _atom_registry_for_coverage(self) -> AtomRegistry:
        """Build a minimal AtomRegistry for entity coverage checks.

        Returns an empty registry. The caller should provide a real
        ``AtomRegistry`` via dependency injection if atom data is available.
        """
        from spec_manager.branches.atoms import AtomRegistry as _AtomRegistry
        from spec_manager.branches.layout import BranchLayout

        layout = BranchLayout(run_root=self._project_root)
        return _AtomRegistry(layout)

    def _load_provenance(self) -> ProvenanceRegistry:
        if self._provenance_registry_path:
            return ProvenanceRegistry.load(self._provenance_registry_path)
        return ProvenanceRegistry()

    def _resolve_files(self, roots: list[str]) -> list[Path]:
        """Resolve directory roots to Python file lists.

        Args:
            roots: Directory paths relative to project root.

        Returns:
            List of .py files found in the directories.
        """
        files: list[Path] = []
        for root in roots:
            root_path = self._project_root / root
            if root_path.exists():
                files.extend(sorted(root_path.rglob("*.py")))
        return files

    @staticmethod
    def _skip_gate(
        gate_id: GateId,
        gate_spec: GateSpec,
        reason: str,
    ) -> GateCheckResult:
        """Create a skipped gate result with an advisory warning."""
        return GateCheckResult(
            gate_id=gate_id.value,
            passed=True,
            mode=GateMode.ADVISORY.value,
            score=0.0,
            findings=[{"skipped": True, "reason": reason}],
            summary=f"Gate skipped: {reason}",
            duration_ms=0.0,
        )

    @staticmethod
    def _build_report(
        results: list[GateCheckResult],
        total_duration_ms: float,
    ) -> PromotionReport:
        """Build the final report from individual results.

        Separates blockers (REQUIRED mode + failed) from warnings
        (ADVISORY mode + failed). Sets passed=True only if zero blockers.

        Args:
            results: All gate check results.
            total_duration_ms: Total wall-clock time.

        Returns:
            PromotionReport.
        """
        blockers: list[GateCheckResult] = []
        warnings: list[GateCheckResult] = []

        for result in results:
            if not result.passed:
                if result.mode == GateMode.REQUIRED.value:
                    blockers.append(result)
                else:
                    warnings.append(result)

        return PromotionReport(
            passed=len(blockers) == 0,
            gate_results=results,
            blockers=blockers,
            warnings=warnings,
            total_duration_ms=total_duration_ms,
        )
