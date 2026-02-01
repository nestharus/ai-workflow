from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class PhaseMetrics:
    name: str
    latency_seconds: float
    agent_calls: int
    token_usage: int
    cost_estimate: float


@dataclass
class PerformanceBenchmark:
    token_per_call: int = 800
    cost_per_token: float = 1e-6
    phases: dict[str, PhaseMetrics] = field(default_factory=dict)

    def record_phase(
        self,
        name: str,
        latency_seconds: float,
        agent_calls: int,
    ) -> None:
        token_usage = agent_calls * self.token_per_call
        cost_estimate = token_usage * self.cost_per_token
        self.phases[name] = PhaseMetrics(
            name=name,
            latency_seconds=latency_seconds,
            agent_calls=agent_calls,
            token_usage=token_usage,
            cost_estimate=cost_estimate,
        )

    @contextmanager
    def benchmark_phase(
        self,
        name: str,
        call_counter: Callable[[], int] | None = None,
    ):
        start_calls = call_counter() if call_counter else 0
        start = perf_counter()
        yield
        duration = perf_counter() - start
        end_calls = call_counter() if call_counter else start_calls
        self.record_phase(name, duration, max(end_calls - start_calls, 0))

    def total_latency(self) -> float:
        return sum(metric.latency_seconds for metric in self.phases.values())

    def total_tokens(self) -> int:
        return sum(metric.token_usage for metric in self.phases.values())

    def total_cost(self) -> float:
        return sum(metric.cost_estimate for metric in self.phases.values())


def benchmark_phase(
    phase_name: str,
    tracker: PerformanceBenchmark,
    call_counter: Callable[[], int] | None = None,
):
    return tracker.benchmark_phase(phase_name, call_counter)


def generate_performance_report(tracker: PerformanceBenchmark) -> str:
    lines = [
        "# Performance Report",
        "",
        "| Phase | Latency (s) | Calls | Tokens | Cost ($) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, metric in tracker.phases.items():
        lines.append(
            f"| {name} | {metric.latency_seconds:.2f} | {metric.agent_calls} | {metric.token_usage} | {metric.cost_estimate:.4f} |"
        )
    lines.extend(
        [
            "",
            f"**Total Latency**: {tracker.total_latency():.2f}s",
            f"**Total Tokens**: {tracker.total_tokens()}",
            f"**Total Cost**: ${tracker.total_cost():.4f}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
