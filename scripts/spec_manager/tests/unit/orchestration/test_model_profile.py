"""Tests for model profile configuration."""

from spec_manager.evaluation.model_profile import ModelProfile


class TestModelProfile:
    def test_construction(self):
        profile = ModelProfile(
            name="opus",
            producer_model_id="claude-opus-4",
            role_models={"planner": "claude-opus-4", "judge": "gpt-4.1"},
        )
        assert profile.name == "opus"
        assert profile.producer_model_id == "claude-opus-4"
        assert profile.role_models["judge"] == "gpt-4.1"

    def test_get_model_for_role_explicit(self):
        profile = ModelProfile(
            name="mixed",
            producer_model_id="default-model",
            role_models={"planner": "planner-model", "judge": "judge-model"},
        )
        assert profile.get_model_for_role("planner") == "planner-model"
        assert profile.get_model_for_role("judge") == "judge-model"

    def test_get_model_for_role_fallback(self):
        profile = ModelProfile(
            name="simple",
            producer_model_id="default-model",
        )
        assert profile.get_model_for_role("planner") == "default-model"
        assert profile.get_model_for_role("refinement") == "default-model"
        assert profile.get_model_for_role("judge") == "default-model"

    def test_to_dict(self):
        profile = ModelProfile(
            name="opus",
            producer_model_id="claude-opus-4",
            role_models={"planner": "fast-model"},
        )
        d = profile.to_dict()
        assert d["name"] == "opus"
        assert d["producer_model_id"] == "claude-opus-4"
        assert d["role_models"]["planner"] == "fast-model"

    def test_from_dict(self):
        data = {
            "name": "gpt5",
            "producer_model_id": "gpt-5.3",
            "role_models": {"review": "gpt-4.1"},
        }
        profile = ModelProfile.from_dict(data)
        assert profile.name == "gpt5"
        assert profile.producer_model_id == "gpt-5.3"
        assert profile.get_model_for_role("review") == "gpt-4.1"

    def test_roundtrip(self):
        original = ModelProfile(
            name="test",
            producer_model_id="model-x",
            role_models={"a": "b", "c": "d"},
        )
        restored = ModelProfile.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.producer_model_id == original.producer_model_id
        assert restored.role_models == original.role_models

    def test_empty_role_models(self):
        profile = ModelProfile(name="minimal", producer_model_id="the-model")
        assert profile.role_models == {}
        assert profile.get_model_for_role("anything") == "the-model"

    def test_from_dict_missing_fields(self):
        profile = ModelProfile.from_dict({})
        assert profile.name == ""
        assert profile.producer_model_id == ""
        assert profile.role_models == {}
