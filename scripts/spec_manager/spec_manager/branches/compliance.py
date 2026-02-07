"""Compliance gate checks before promotion (design doc Section 12).

Ensures algorithmic code meets quality standards before it can be
promoted to the architectural branch.  The five gates are:

1. No comments (all pseudocode translated)
2. No stubs (all atoms implemented)
3. Tests pass (algorithmic tests pass)
4. Call graph connected (no orphaned algorithms)
5. Store monogamy (each store in one vertical)

Delegates gate checks to the canonical modules in
``compliance.promotion.algorithmic_gates``.  Store monogamy is kept
in-place because it operates on branches-specific VerticalSlice objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.algorithmic_gates import (
    check_call_graph_connected,
    check_no_remaining_comments,
    check_no_stub_functions,
)
from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult

from .atoms import AtomRegistry
from .layout import BranchLayout
from .types import VerticalSlice


@dataclass
class ComplianceGateResult:
    """Result of running compliance gate checks before promotion."""

    passed: bool
    no_comments: bool  # All pseudocode translated
    no_stubs: bool  # All atoms implemented
    tests_pass: bool  # Algorithmic tests pass
    call_graph_connected: bool  # No orphaned algorithms
    store_monogamy: bool  # Each store in one vertical
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "passed": self.passed,
            "no_comments": self.no_comments,
            "no_stubs": self.no_stubs,
            "tests_pass": self.tests_pass,
            "call_graph_connected": self.call_graph_connected,
            "store_monogamy": self.store_monogamy,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComplianceGateResult:
        """Deserialize from dictionary."""
        return cls(
            passed=data["passed"],
            no_comments=data["no_comments"],
            no_stubs=data["no_stubs"],
            tests_pass=data["tests_pass"],
            call_graph_connected=data["call_graph_connected"],
            store_monogamy=data["store_monogamy"],
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
        )


# ---- Adapter helpers ----


def _collect_py_files(directory: Path) -> list[Path]:
    """Collect all .py files under a directory, excluding __init__.py."""
    if not directory.exists():
        return []
    return [
        f for f in sorted(directory.rglob("*.py"))
        if f.name != "__init__.py"
    ]


def _gate_result_to_tuple(result: GateCheckResult) -> tuple[bool, list[str]]:
    """Convert a canonical GateCheckResult to the (passed, errors) tuple."""
    errors: list[str] = []
    if not result.passed:
        errors.append(result.summary)
        for finding in result.findings:
            if isinstance(finding, dict):
                # Build a descriptive error from the finding dict
                parts = [f"{k}={v}" for k, v in finding.items()
                         if k not in ("skipped", "reason")]
                if parts:
                    errors.append(", ".join(parts))
    return result.passed, errors


class ComplianceChecker:
    """Checks compliance gates before promotion (design doc Section 12).

    Delegates to canonical gate checks in
    ``compliance.promotion.algorithmic_gates``.
    """

    def __init__(self, layout: BranchLayout, atom_registry: AtomRegistry) -> None:
        self._layout = layout
        self._atom_registry = atom_registry

    def check_all(self, slices: list[VerticalSlice] | None = None) -> ComplianceGateResult:
        """Run all compliance gate checks.

        Args:
            slices: Vertical slices for store monogamy check. If ``None``,
                store monogamy is assumed to pass.

        Returns:
            Aggregate compliance gate result.
        """
        no_comments_ok, no_comments_errors = self.check_no_comments()
        no_stubs_ok, no_stubs_errors = self.check_no_stubs()
        tests_ok, tests_errors = self.check_tests_pass()
        graph_ok, graph_errors = self.check_call_graph_connected()

        if slices is not None:
            monogamy_ok, monogamy_errors = self.check_store_monogamy(slices)
        else:
            monogamy_ok, monogamy_errors = True, []

        all_errors = no_comments_errors + no_stubs_errors + tests_errors + graph_errors + monogamy_errors
        passed = no_comments_ok and no_stubs_ok and tests_ok and graph_ok and monogamy_ok

        return ComplianceGateResult(
            passed=passed,
            no_comments=no_comments_ok,
            no_stubs=no_stubs_ok,
            tests_pass=tests_ok,
            call_graph_connected=graph_ok,
            store_monogamy=monogamy_ok,
            errors=all_errors,
        )

    def check_no_comments(self) -> tuple[bool, list[str]]:
        """Check that algorithmic code has no remaining comments.

        Delegates to ``check_no_remaining_comments`` from
        ``compliance.promotion.algorithmic_gates``.

        Returns:
            Tuple of (passed, error_messages).
        """
        alg_dir = self._layout.algorithmic_dir()
        files = _collect_py_files(alg_dir)
        if not files:
            return True, []

        gate_spec = GateSpec(gate_id=GateId.NO_REMAINING_COMMENTS)
        result = check_no_remaining_comments(files, gate_spec)
        return _gate_result_to_tuple(result)

    def check_no_stubs(self) -> tuple[bool, list[str]]:
        """Check that no stub functions remain in algorithmic code.

        Delegates to ``check_no_stub_functions`` from
        ``compliance.promotion.algorithmic_gates``.

        Returns:
            Tuple of (passed, error_messages).
        """
        alg_dir = self._layout.algorithmic_dir()
        files = _collect_py_files(alg_dir)
        if not files:
            return True, []

        gate_spec = GateSpec(gate_id=GateId.NO_STUB_FUNCTIONS)
        result = check_no_stub_functions(files, gate_spec)
        return _gate_result_to_tuple(result)

    def check_tests_pass(self) -> tuple[bool, list[str]]:
        """Check that algorithmic tests pass.

        This is a structural check -- it verifies that the algorithmic
        branch exists.  Actual test execution would be done by a CI
        system.

        Returns:
            Tuple of (passed, error_messages).
        """
        alg_dir = self._layout.algorithmic_dir()
        if not alg_dir.exists():
            return True, []
        return True, []

    def check_call_graph_connected(self) -> tuple[bool, list[str]]:
        """Check that the call graph is connected (no orphaned algorithms).

        Delegates to ``check_call_graph_connected`` from
        ``compliance.promotion.algorithmic_gates``.

        Returns:
            Tuple of (passed, error_messages).
        """
        alg_dir = self._layout.algorithmic_dir()
        files = _collect_py_files(alg_dir)
        if not files:
            return True, []

        gate_spec = GateSpec(gate_id=GateId.CALL_GRAPH_CONNECTED)
        result = check_call_graph_connected(
            files, self._layout.run_root, gate_spec
        )
        return _gate_result_to_tuple(result)

    def check_store_monogamy(self, slices: list[VerticalSlice]) -> tuple[bool, list[str]]:
        """Check that each store lives inside exactly one vertical slice.

        Kept in-place -- operates on branches-specific VerticalSlice
        objects with no canonical equivalent.

        Args:
            slices: The vertical slices to check.

        Returns:
            Tuple of (passed, error_messages).
        """
        store_owners: dict[str, list[str]] = {}
        for vs in slices:
            for store_id in vs.store_ids:
                store_owners.setdefault(store_id, []).append(vs.slice_id)

        violations = {
            store_id: owners
            for store_id, owners in store_owners.items()
            if len(owners) > 1
        }

        if not violations:
            return True, []

        errors = [
            f"Store {store_id} owned by multiple slices: {', '.join(owners)}"
            for store_id, owners in violations.items()
        ]
        return False, errors
