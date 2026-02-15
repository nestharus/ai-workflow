"""Test tier dispatch for PDD pipeline CI.

Implements the 4-tier test strategy from the E2E pipeline research response:

- Tier 0 (Smoke): ``python -m compileall`` + import graph smoke
- Tier 1 (Unit): fast unit tests, per-library/slice selection
- Tier 2 (Integration): component wiring tests, cross-library
- Tier 3 (Full regression): entire suite + slow e2e

Layer-specific dispatch:

- L1 dirty->clean: Tier 0 + Tier 1 + minimal Tier 2
- L2 dirty->clean: Tier 0 + Tier 1 + Tier 2 (wiring/topology)
- L3 dirty->clean: Tier 0 + Tier 1 + Tier 2 + Tier 3 + diff-impact
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class TierResult:
    """Result from running a single test tier.

    Attributes:
        tier: Tier number (0-3).
        passed: Whether the tier passed.
        output: Captured stdout (truncated to 2000 chars in serialization).
        error: Captured stderr (truncated to 1000 chars in serialization).
        duration_ms: Wall-clock duration in milliseconds.
    """

    tier: int = 0
    passed: bool = True
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict with truncated output."""
        return {
            "tier": self.tier,
            "passed": self.passed,
            "output": self.output[:2000],
            "error": self.error[:1000],
            "duration_ms": self.duration_ms,
        }


_TIER0_UNSET: str = "__unset__"
_TIER2_L1_UNSET: str = "__inherit_tier2__"


@dataclass
class TierConfig:
    """Configuration for test tier dispatch.

    Each tier has a shell command and a timeout in seconds.
    Commands must be explicitly configured for every tier that runs for
    a layer promotion. Missing commands fail the tier so the promotion
    gate cannot silently pass without executing tests.

    Attributes:
        tier0_command: Smoke test command (default from language module).
            Pass ``""`` explicitly to disable.
        tier1_command: Unit test command.
        tier2_command: Integration test command.
        tier2_l1_command: L1-specific minimal integration sanity command.
            Defaults to ``tier2_command`` when not set.
        tier3_command: Full regression test command.
        tier0_timeout: Timeout in seconds for tier 0.
        tier1_timeout: Timeout in seconds for tier 1.
        tier2_timeout: Timeout in seconds for tier 2.
        tier3_timeout: Timeout in seconds for tier 3.
    """

    tier0_command: str = _TIER0_UNSET
    tier1_command: str = ""
    tier2_command: str = ""
    tier2_l1_command: str = _TIER2_L1_UNSET
    tier3_command: str = ""
    tier0_timeout: int = 60
    tier1_timeout: int = 300
    tier2_timeout: int = 600
    tier3_timeout: int = 1200

    def __post_init__(self) -> None:
        if self.tier0_command == _TIER0_UNSET:
            from spec_manager.core.language import DEFAULT_SMOKE_COMMAND

            self.tier0_command = DEFAULT_SMOKE_COMMAND
        if self.tier2_l1_command == _TIER2_L1_UNSET:
            self.tier2_l1_command = self.tier2_command

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TierConfig:
        """Build a TierConfig from a plain dict payload."""
        return cls(
            tier0_command=str(payload.get("tier0_command", _TIER0_UNSET)),
            tier1_command=str(payload.get("tier1_command", "")),
            tier2_command=str(payload.get("tier2_command", "")),
            tier2_l1_command=str(payload.get("tier2_l1_command", _TIER2_L1_UNSET)),
            tier3_command=str(payload.get("tier3_command", "")),
            tier0_timeout=int(payload.get("tier0_timeout", 60)),
            tier1_timeout=int(payload.get("tier1_timeout", 300)),
            tier2_timeout=int(payload.get("tier2_timeout", 600)),
            tier3_timeout=int(payload.get("tier3_timeout", 1200)),
        )


# ------------------------------------------------------------------
# Layer -> tier mapping
# ------------------------------------------------------------------

# Map layer -> which tiers to run at dirty->clean promotion
_LAYER_TIERS: dict[str, list[int]] = {
    "l1": [0, 1, 2],  # L1: smoke + unit + minimal integration sanity
    "l2": [0, 1, 2],  # L2: smoke + unit + integration (wiring/topology)
    "l3": [0, 1, 2, 3],  # L3: all tiers
}


# ------------------------------------------------------------------
# TierRunner
# ------------------------------------------------------------------


class TierRunner:
    """Runs test tiers appropriate for a given layer.

    Usage::

        runner = TierRunner(config=TierConfig(
            tier1_command="pytest tests/unit -x",
            tier2_command="pytest tests/integration -x",
        ))
        results = runner.run_for_layer("l2")
        if all(r.passed for r in results):
            print("All tiers passed")
    """

    def __init__(
        self,
        config: TierConfig | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.config = config or TierConfig()
        self.cwd = cwd

    def run_for_layer(self, layer: str) -> list[TierResult]:
        """Run all tiers appropriate for the given layer.

        Stops on first failure (fail-fast).  Returns the list of
        results for tiers that were actually executed.
        """
        tiers = _LAYER_TIERS.get(layer, [0])
        return self.run_for_tiers(layer, tiers)

    def run_for_tiers(self, layer: str, tiers: list[int]) -> list[TierResult]:
        """Run an explicit tier list for a layer context."""
        results: list[TierResult] = []
        for tier in tiers:
            result = self._run_tier(tier, layer=layer)
            results.append(result)
            if not result.passed:
                logger.warning("Tier %d failed for layer %s, stopping", tier, layer)
                break
        return results

    def _run_tier(self, tier: int, *, layer: str) -> TierResult:
        """Run a single test tier."""
        command = self._get_command(tier, layer=layer)
        if not command:
            return TierResult(
                tier=tier,
                passed=False,
                error=f"Tier {tier} command is not configured for layer {layer}",
            )

        timeout = self._get_timeout(tier)
        start = time.monotonic()

        try:
            result = subprocess.run(  # noqa: S602
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.cwd) if self.cwd else None,
            )
            duration = (time.monotonic() - start) * 1000
            return TierResult(
                tier=tier,
                passed=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            duration = (time.monotonic() - start) * 1000
            return TierResult(
                tier=tier,
                passed=False,
                error=f"Tier {tier} timed out after {timeout}s",
                duration_ms=duration,
            )
        except Exception as exc:
            return TierResult(
                tier=tier,
                passed=False,
                error=str(exc),
            )

    def _get_command(self, tier: int, *, layer: str) -> str:
        """Get the shell command for a tier."""
        tier2_command = self.config.tier2_l1_command if layer == "l1" else self.config.tier2_command
        commands = {
            0: self.config.tier0_command,
            1: self.config.tier1_command,
            2: tier2_command,
            3: self.config.tier3_command,
        }
        return commands.get(tier, "")

    def _get_timeout(self, tier: int) -> int:
        """Get the timeout in seconds for a tier."""
        timeouts = {
            0: self.config.tier0_timeout,
            1: self.config.tier1_timeout,
            2: self.config.tier2_timeout,
            3: self.config.tier3_timeout,
        }
        return timeouts.get(tier, 300)
