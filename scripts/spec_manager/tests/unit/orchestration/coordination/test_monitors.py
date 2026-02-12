"""Tests for orchestration.coordination.monitors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.orchestration.coordination.monitors import (
    CompoundCondition,
    ConstraintPresentCondition,
    GitSymbolExistsCondition,
    MonitorCondition,
    MonitorExecution,
    MonitorRegistry,
    MonitorSpec,
    MonitorStatus,
    MonitorTimeout,
    MonitorWake,
    SliceInfo,
    SliceMergedCondition,
    WorkItemDoneCondition,
    condition_from_dict,
)


# ------------------------------------------------------------------
# condition_from_dict
# ------------------------------------------------------------------


class TestConditionFromDict:
    def test_git_symbol_exists(self) -> None:
        d = {
            "type": "git_symbol_exists",
            "ref": "pdd/run_001/l1/dirty",
            "file_glob": "libraries/**.py",
            "symbol_fqn": "RiskEngine.check_exposure",
        }
        cond = condition_from_dict(d)
        assert isinstance(cond, GitSymbolExistsCondition)
        assert cond.ref == "pdd/run_001/l1/dirty"
        assert cond.file_glob == "libraries/**.py"
        assert cond.symbol_fqn == "RiskEngine.check_exposure"
        assert cond.signature_regex == ""

    def test_work_item_done(self) -> None:
        d = {"type": "work_item_done", "work_item_id": "wi_123", "required_status": "DONE"}
        cond = condition_from_dict(d)
        assert isinstance(cond, WorkItemDoneCondition)
        assert cond.work_item_id == "wi_123"
        assert cond.required_status == "DONE"

    def test_constraint_present(self) -> None:
        d = {"type": "constraint_present", "constraint_key": "no_orm"}
        cond = condition_from_dict(d)
        assert isinstance(cond, ConstraintPresentCondition)
        assert cond.constraint_key == "no_orm"
        assert cond.constraint_dir == "analysis/constraints"

    def test_slice_merged(self) -> None:
        d = {"type": "slice_merged", "provider_slice_id": "auth-lib", "layer": "L1"}
        cond = condition_from_dict(d)
        assert isinstance(cond, SliceMergedCondition)
        assert cond.provider_slice_id == "auth-lib"
        assert cond.layer == "L1"

    def test_compound(self) -> None:
        d = {
            "type": "compound",
            "operator": "AND",
            "conditions": [
                {"type": "work_item_done", "work_item_id": "a"},
                {"type": "work_item_done", "work_item_id": "b"},
            ],
        }
        cond = condition_from_dict(d)
        assert isinstance(cond, CompoundCondition)
        assert cond.operator == "AND"
        assert len(cond.conditions) == 2

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown condition type"):
            condition_from_dict({"type": "time_travel"})

    def test_defaults_for_work_item_done(self) -> None:
        d = {"type": "work_item_done", "work_item_id": "x"}
        cond = condition_from_dict(d)
        assert isinstance(cond, WorkItemDoneCondition)
        assert cond.required_status == "MERGED"


# ------------------------------------------------------------------
# MonitorSpec serialization
# ------------------------------------------------------------------


class TestMonitorSpecSerialization:
    def test_round_trip(self) -> None:
        spec = MonitorSpec(
            monitor_id="mon_001",
            run_id="run_42",
            waiting_slice=SliceInfo(layer="L1", slice_id="risk-engine"),
            signal_id="sig_abc",
            condition={
                "type": "work_item_done",
                "work_item_id": "wi_123",
                "required_status": "MERGED",
            },
            execution=MonitorExecution(
                mode="hybrid",
                poll_interval_sec=30,
                event_triggers=["SLICE_MERGED"],
            ),
            timeout=MonitorTimeout(timeout_sec=3600, on_timeout="FAIL"),
            wake=MonitorWake(payload={"resume_step": "IMPLEMENT"}),
            status=MonitorStatus(
                state="ACTIVE",
                created_at="2026-01-01T00:00:00+00:00",
            ),
        )
        d = spec.to_dict()
        restored = MonitorSpec.from_dict(d)

        assert restored.monitor_id == "mon_001"
        assert restored.run_id == "run_42"
        assert restored.waiting_slice.layer == "L1"
        assert restored.waiting_slice.slice_id == "risk-engine"
        assert restored.signal_id == "sig_abc"
        assert restored.condition["type"] == "work_item_done"
        assert restored.execution.mode == "hybrid"
        assert restored.execution.poll_interval_sec == 30
        assert restored.execution.event_triggers == ["SLICE_MERGED"]
        assert restored.timeout.timeout_sec == 3600
        assert restored.timeout.on_timeout == "FAIL"
        assert restored.wake.payload == {"resume_step": "IMPLEMENT"}
        assert restored.status.state == "ACTIVE"
        assert restored.status.created_at == "2026-01-01T00:00:00+00:00"

    def test_round_trip_via_json(self) -> None:
        spec = MonitorSpec(
            monitor_id="mon_json",
            run_id="r1",
            condition={"type": "constraint_present", "constraint_key": "k"},
        )
        text = json.dumps(spec.to_dict())
        restored = MonitorSpec.from_dict(json.loads(text))
        assert restored.monitor_id == "mon_json"
        assert restored.condition["constraint_key"] == "k"

    def test_auto_generated_id(self) -> None:
        spec = MonitorSpec(run_id="r1")
        assert spec.monitor_id != ""
        assert len(spec.monitor_id) == 16  # hex of 8 bytes

    def test_auto_generated_created_at(self) -> None:
        spec = MonitorSpec(run_id="r1")
        assert spec.status.created_at != ""

    def test_save_and_load(self, tmp_path: Path) -> None:
        spec = MonitorSpec(
            monitor_id="mon_file",
            run_id="r1",
            condition={"type": "slice_merged", "provider_slice_id": "p1", "layer": "L2"},
        )
        monitors_dir = tmp_path / "monitors"
        spec.save(monitors_dir)

        path = monitors_dir / "mon_file.json"
        assert path.exists()

        loaded = MonitorSpec.load(path)
        assert loaded.monitor_id == "mon_file"
        assert loaded.condition["type"] == "slice_merged"


# ------------------------------------------------------------------
# MonitorRegistry
# ------------------------------------------------------------------


class TestMonitorRegistry:
    def _make_spec(self, **kwargs: object) -> MonitorSpec:
        defaults = {
            "run_id": "run_1",
            "condition": {"type": "work_item_done", "work_item_id": "wi_1"},
        }
        defaults.update(kwargs)
        return MonitorSpec(**defaults)  # type: ignore[arg-type]

    def test_register_and_get(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        spec = self._make_spec(monitor_id="m1")
        reg.register(spec)

        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.monitor_id == "m1"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_get_active(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(self._make_spec(monitor_id="active_1"))
        reg.register(self._make_spec(monitor_id="active_2"))

        fired_spec = self._make_spec(monitor_id="fired_1")
        fired_spec.status.state = "FIRED"
        reg.register(fired_spec)

        active = reg.get_active()
        assert len(active) == 2
        assert {s.monitor_id for s in active} == {"active_1", "active_2"}

    def test_get_for_slice(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(
            self._make_spec(
                monitor_id="m1",
                waiting_slice=SliceInfo(layer="L1", slice_id="risk"),
            )
        )
        reg.register(
            self._make_spec(
                monitor_id="m2",
                waiting_slice=SliceInfo(layer="L1", slice_id="auth"),
            )
        )
        reg.register(
            self._make_spec(
                monitor_id="m3",
                waiting_slice=SliceInfo(layer="L2", slice_id="risk"),
            )
        )

        risk_monitors = reg.get_for_slice("risk")
        assert len(risk_monitors) == 2
        assert {s.monitor_id for s in risk_monitors} == {"m1", "m3"}

    def test_get_for_signal(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(self._make_spec(monitor_id="m1", signal_id="sig_a"))
        reg.register(self._make_spec(monitor_id="m2", signal_id="sig_b"))

        found = reg.get_for_signal("sig_a")
        assert found is not None
        assert found.monitor_id == "m1"

        assert reg.get_for_signal("sig_missing") is None

    def test_fire(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(self._make_spec(monitor_id="m1"))
        reg.fire("m1")

        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.status.state == "FIRED"

    def test_cancel_for_signal(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(self._make_spec(monitor_id="m1", signal_id="sig_x"))
        reg.cancel_for_signal("sig_x")

        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.status.state == "CANCELLED"

    def test_cancel_for_slice(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(
            self._make_spec(
                monitor_id="m1",
                waiting_slice=SliceInfo(layer="L1", slice_id="risk"),
            )
        )
        reg.register(
            self._make_spec(
                monitor_id="m2",
                waiting_slice=SliceInfo(layer="L1", slice_id="risk"),
            )
        )
        fired = self._make_spec(
            monitor_id="m3",
            waiting_slice=SliceInfo(layer="L1", slice_id="risk"),
        )
        fired.status.state = "FIRED"
        reg.register(fired)

        reg.cancel_for_slice("risk")

        m1 = reg.get("m1")
        m2 = reg.get("m2")
        m3 = reg.get("m3")
        assert m1 is not None and m1.status.state == "CANCELLED"
        assert m2 is not None and m2.status.state == "CANCELLED"
        # Already FIRED — should not be cancelled
        assert m3 is not None and m3.status.state == "FIRED"

    def test_update_status_with_extra_fields(self, tmp_path: Path) -> None:
        reg = MonitorRegistry(tmp_path)
        reg.register(self._make_spec(monitor_id="m1"))
        reg.update_status("m1", "ACTIVE", check_count=5, failures=2)

        loaded = reg.get("m1")
        assert loaded is not None
        assert loaded.status.check_count == 5
        assert loaded.status.failures == 2
