# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for BuzzAdapter — v0.1 Buzz+Mekong autonomous runtime integration."""

import pytest

from src.core.buzz_adapter import BuzzAdapter, BuzzConfigError, BuzzPayload


class TestBuzzPayloadDataclass:
    def test_default_values(self):
        bp = BuzzPayload(goal_text="hello")
        assert bp.goal_text == "hello"
        assert bp.context == {}
        assert bp.callback_url is None
        assert bp.mission_id is None

    def test_full_construction(self):
        bp = BuzzPayload(
            goal_text="deploy",
            context={"env": "staging"},
            callback_url="https://buzz.test/cb",
            mission_id="m-123",
        )
        assert bp.goal_text == "deploy"
        assert bp.context == {"env": "staging"}
        assert bp.callback_url == "https://buzz.test/cb"
        assert bp.mission_id == "m-123"


class TestReceiveGoal:
    def test_parses_goal_field(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({"goal": "analyze sales"})
        assert result["text"] == "analyze sales"
        assert result["context"] == {}
        assert result["mission_id"] is None
        assert result["callback_url"] is None

    def test_parses_text_field_as_fallback(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({"text": "fallback goal"})
        assert result["text"] == "fallback goal"

    def test_goal_field_takes_priority(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({"goal": "primary", "text": "secondary"})
        assert result["text"] == "primary"

    def test_raises_on_missing_goal(self):
        adapter = BuzzAdapter()
        with pytest.raises(ValueError, match="missing 'goal' field"):
            adapter.receive_goal({})

    def test_raises_on_empty_goal(self):
        adapter = BuzzAdapter()
        with pytest.raises(ValueError, match="missing 'goal' field"):
            adapter.receive_goal({"goal": ""})

    def test_with_callback_url(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({
            "goal": "task",
            "callback_url": "https://buzz.test/update",
        })
        assert result["callback_url"] == "https://buzz.test/update"

    def test_with_mission_id(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({
            "goal": "task",
            "mission_id": "mission-42",
        })
        assert result["mission_id"] == "mission-42"

    def test_with_context(self):
        adapter = BuzzAdapter()
        result = adapter.receive_goal({
            "goal": "task",
            "context": {"priority": "high", "source": "buzz"},
        })
        assert result["context"] == {"priority": "high", "source": "buzz"}


class TestSendUpdate:
    def test_returns_status_dict(self):
        adapter = BuzzAdapter()
        result = adapter.send_update("running", {"progress": 50})
        assert result == {"status": "running", "data": {"progress": 50}}

    def test_completed_status(self):
        adapter = BuzzAdapter()
        result = adapter.send_update("completed", {"output": "done"})
        assert result["status"] == "completed"
        assert result["data"]["output"] == "done"


class TestNoTransportFailsLoud:
    """Adapter with no transport must refuse delivery, not silently no-op."""

    def test_send_update_raises_buzz_config_error(self):
        adapter = BuzzAdapter.without_transport()
        with pytest.raises(BuzzConfigError, match="no transport wired"):
            adapter.send_update("running", {"x": 1}, callback_url="https://buzz.test/cb")

    def test_send_update_no_callback_url_is_noop(self):
        adapter = BuzzAdapter.without_transport()
        result = adapter.send_update("running", {"x": 1})
        assert result == {"status": "running", "data": {"x": 1}}

    def test_default_adapter_delivers_via_urllib(self):
        adapter = BuzzAdapter(transport=lambda url, payload: 200)
        result = adapter.send_update("completed", {"ok": True}, callback_url="https://buzz.test/cb")
        assert result["status"] == "completed"


class TestReceiveFeedback:
    def test_returns_feedback_dict(self):
        adapter = BuzzAdapter()
        fb = {"rating": 5, "comment": "great"}
        result = adapter.receive_feedback(fb)
        assert result == fb
        assert result["rating"] == 5

    def test_empty_feedback(self):
        adapter = BuzzAdapter()
        result = adapter.receive_feedback({})
        assert result == {}


class TestRuntimeProperty:
    def test_default_runtime_is_none(self):
        adapter = BuzzAdapter()
        assert adapter.runtime is None

    def test_runtime_assignment_via_property(self):
        adapter = BuzzAdapter()
        sentinel = object()
        adapter.runtime = sentinel
        assert adapter.runtime is sentinel

    def test_runtime_set_via_init(self):
        sentinel = object()
        adapter = BuzzAdapter(runtime=sentinel)
        assert adapter.runtime is sentinel
