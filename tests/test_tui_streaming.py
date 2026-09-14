"""Tests for TUI Streaming Renderer (Phase C2).

Tests cover:
- OutputLine / StepProgress dataclasses
- ProgressPanel lifecycle (add/start/complete/cancel steps)
- StreamingRenderer event handling (step events, halt, cancel, output)
- Line eviction (max_lines cap)
- Event bus subscription/unsubscription
- StreamingSession context manager

Run: python3 -m pytest tests/test_tui_streaming.py -v
"""
from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/Users/macbook/mekong-cli")

from src.cli.tui.streaming import (
    OutputLine,
    ProgressPanel,
    RendererState,
    StepProgress,
    StreamingRenderer,
    StreamingSession,
    _MAX_OUTPUT_LINES,
)
from src.core.event_bus import (
    Event,
    EventType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_renderer(bus=None, max_lines=50):
    """Create a StreamingRenderer with a mocked console and throwaway bus."""
    console = MagicMock()
    if bus is None:
        bus = MagicMock()
        bus.subscribe = MagicMock()
        bus.unsubscribe = MagicMock()
        bus.emit = MagicMock()
    r = StreamingRenderer(bus=bus, max_lines=max_lines, console=console)
    return r, bus


def make_event(event_type, **data):
    return Event(type=event_type, data=data)


def step_event(event_type, step_order=1, title="Test step", **extra):
    data = {"step_order": step_order, "title": title}
    data.update(extra)
    return Event(type=event_type, data=data)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestOutputLine:
    def test_default_fields(self):
        line = OutputLine(text="hello", timestamp=time.monotonic())
        assert line.text == "hello"
        assert line.source == "agent"
        assert line.status == "running"

    def test_custom_fields(self):
        line = OutputLine(
            text="err", source="stderr", status="error", timestamp=42.0
        )
        assert line.source == "stderr"
        assert line.status == "error"
        assert line.timestamp == 42.0

    def test_frozen(self):
        line = OutputLine(text="x", timestamp=0.0)
        with pytest.raises(Exception):
            line.text = "y"


class TestStepProgress:
    def test_default(self):
        sp = StepProgress(order=1, title="Build", status="pending", timestamp=0.0)
        assert sp.status == "pending"
        assert sp.duration == 0.0
        assert sp.order == 1

    def test_custom_status(self):
        sp = StepProgress(
            order=2, title="Deploy", status="success",
            duration=1.5, timestamp=0.0
        )
        assert sp.status == "success"
        assert sp.duration == 1.5


# ---------------------------------------------------------------------------
# ProgressPanel tests
# ---------------------------------------------------------------------------


class TestProgressPanel:
    def test_render_without_steps(self):
        panel = ProgressPanel(total_steps=3)
        rendered = panel.render()
        assert rendered is not None

    def test_add_and_start_step(self):
        panel = ProgressPanel(total_steps=2)
        panel.add_step(1, "First")
        panel.add_step(2, "Second")
        panel.start_step(1)
        assert panel._steps[1].status == "running"

    def test_complete_step_success(self):
        panel = ProgressPanel(total_steps=2)
        panel.add_step(1, "Build")
        panel.start_step(1)
        # Back-date timestamp to produce measurable duration
        step = panel._steps[1]
        panel._steps[1] = StepProgress(
            step.order, step.title, step.status, step.duration,
            time.monotonic() - 1.0
        )
        panel.complete_step(1, success=True)
        assert panel._steps[1].status == "success"
        assert panel._completed_count == 1
        assert panel._steps[1].duration >= 0.9

    def test_complete_step_failure(self):
        panel = ProgressPanel(total_steps=2)
        panel.add_step(1, "Test")
        panel.complete_step(1, success=False)
        assert panel._steps[1].status == "error"
        assert panel._completed_count == 0

    def test_cancel_step(self):
        panel = ProgressPanel(total_steps=2)
        panel.add_step(1, "Skip me")
        panel.cancel_step(1)
        assert panel._steps[1].status == "skipped"

    def test_render_contains_step_info(self):
        panel = ProgressPanel(total_steps=1)
        panel.add_step(1, "Hello")
        panel.complete_step(1, success=True)
        rendered = panel.render()
        # The Panel wraps a Group; the step title is in the step list
        body = rendered.renderable
        # Access the Group's children (Progress + Text + step_text)
        children = list(body._renderables) if hasattr(body, "_renderables") else []
        child_str = " ".join(str(c) for c in children)
        assert "Hello" in child_str

    def test_complete_nonexistent_step_no_crash(self):
        panel = ProgressPanel(total_steps=1)
        panel.complete_step(99, success=True)  # Should not raise


# ---------------------------------------------------------------------------
# StreamingRenderer — event handling
# ---------------------------------------------------------------------------


class TestStreamingRendererEvents:
    def test_emits_output_on_step_started(self):
        renderer, bus = make_renderer()
        renderer.set_total_steps(3)
        renderer._on_event(step_event(EventType.STEP_STARTED, step_order=1, title="Init"))
        assert len(renderer._output_lines) == 1
        assert "Step 1" in renderer._output_lines[0].text

    def test_emits_output_on_step_completed_success(self):
        renderer, bus = make_renderer()
        renderer._steps[1] = StepProgress(
            order=1, title="T", status="running",
            timestamp=time.monotonic() - 0.5
        )
        renderer._progress_panel = MagicMock()
        renderer._on_event(step_event(EventType.STEP_COMPLETED, step_order=1))
        assert renderer._steps[1].status == "success"
        assert "done" in renderer._output_lines[-1].text

    def test_emits_output_on_step_completed_failure(self):
        renderer, bus = make_renderer()
        renderer._steps[1] = StepProgress(
            order=1, title="T", status="running",
            timestamp=time.monotonic() - 0.5
        )
        renderer._progress_panel = MagicMock()
        renderer._on_event(step_event(EventType.STEP_FAILED, step_order=1))
        assert renderer._steps[1].status == "error"
        assert "failed" in renderer._output_lines[-1].text

    def test_self_healed_event(self):
        renderer, bus = make_renderer()
        renderer._on_event(step_event(EventType.STEP_HEALED, step_order=2))
        assert any("healed" in ln.text.lower() for ln in renderer._output_lines)

    def test_goal_completed_stops_renderer(self):
        renderer, bus = make_renderer()
        renderer._state = RendererState.RUNNING
        renderer._on_event(step_event(EventType.GOAL_COMPLETED))
        assert renderer._state == RendererState.STOPPED

    def test_halt_event_stops_with_message(self):
        renderer, bus = make_renderer()
        renderer._state = RendererState.RUNNING
        renderer._on_event(make_event(EventType.HALT_TRIGGERED, reason="budget_exhausted"))
        assert renderer._state == RendererState.STOPPED
        assert any("HALT" in ln.text for ln in renderer._output_lines)

    def test_stdout_in_event_data_is_injected(self):
        renderer, bus = make_renderer()
        renderer._on_event(make_event(
            EventType.STEP_COMPLETED, step_order=1, stdout="line1\nline2\n"
        ))
        texts = [ln.text for ln in renderer._output_lines]
        assert any("line1" in t for t in texts)
        assert any("line2" in t for t in texts)

    def test_empty_stdout_adds_only_status_line(self):
        renderer, bus = make_renderer()
        base_count = len(renderer._output_lines)
        renderer._on_event(
            make_event(EventType.STEP_COMPLETED, step_order=1, stdout="   \n")
        )
        # One line added (step_completed status), none from empty stdout
        assert len(renderer._output_lines) == base_count + 1


# ---------------------------------------------------------------------------
# StreamingRenderer — output management
# ---------------------------------------------------------------------------


class TestStreamingRendererOutput:
    def test_add_output_appends_line(self):
        renderer, _ = make_renderer()
        renderer.add_output("hello world")
        assert len(renderer._output_lines) == 1
        assert renderer._output_lines[0].text == "hello world"

    def test_multiple_outputs(self):
        renderer, _ = make_renderer()
        for i in range(5):
            renderer.add_output(f"line {i}")
        assert len(renderer._output_lines) == 5

    def test_eviction_enforces_max_lines(self):
        renderer, _ = make_renderer(max_lines=10)
        for i in range(30):
            renderer.add_output(f"line {i}")
        assert len(renderer._output_lines) <= 10

    def test_eviction_drops_oldest(self):
        renderer, _ = make_renderer(max_lines=5)
        for i in range(10):
            renderer.add_output(f"line {i}")
        texts = [ln.text for ln in renderer._output_lines]
        assert "line 0" not in texts
        assert "line 9" in texts

    def test_mark_output_changes_status(self):
        renderer, _ = make_renderer()
        renderer.add_output("some text")
        renderer.mark_output(0, "success")
        assert renderer._output_lines[0].status == "success"

    def test_mark_output_out_of_range_safe(self):
        renderer, _ = make_renderer()
        renderer.mark_output(999, "error")  # Should not raise

    def test_default_max_lines_constant(self):
        assert _MAX_OUTPUT_LINES == 500


# ---------------------------------------------------------------------------
# StreamingRenderer — lifecycle
# ---------------------------------------------------------------------------


class TestStreamingRendererLifecycle:
    def test_initial_state(self):
        renderer, _ = make_renderer()
        assert renderer._state == RendererState.IDLE

    def test_set_total_steps(self):
        renderer, _ = make_renderer()
        renderer.set_total_steps(7)
        assert renderer._total_steps == 7

    def test_register_step(self):
        renderer, _ = make_renderer()
        renderer.register_step(1, "Init")
        renderer.register_step(2, "Build")
        assert 1 in renderer._steps
        assert renderer._steps[1].title == "Init"
        assert renderer._steps[1].status == "pending"

    def test_on_cancel_registers_callback(self):
        renderer, _ = make_renderer()
        cb = MagicMock()
        renderer.on_cancel(cb)
        assert renderer._cancel_callback is cb

    def test_handle_cancel_invokes_callback(self):
        renderer, _ = make_renderer()
        cb = MagicMock()
        renderer.on_cancel(cb)
        renderer._handle_cancel()
        cb.assert_called_once()
        assert renderer._cancelled is True
        assert renderer._state == RendererState.STOPPED

    def test_handle_cancel_emits_halt_event(self):
        renderer, mock_bus = make_renderer()
        renderer._handle_cancel()
        mock_bus.emit.assert_called_once()
        call_args = mock_bus.emit.call_args
        assert call_args[0][0] == EventType.HALT_TRIGGERED
        assert call_args[0][1]["reason"] == "user_cancelled"

    def test_cancel_public_method(self):
        renderer, mock_bus = make_renderer()
        renderer.cancel()
        mock_bus.emit.assert_called_once()
        assert renderer._cancelled is True


# ---------------------------------------------------------------------------
# StreamingRenderer — cleanup
# ---------------------------------------------------------------------------


class TestStreamingRendererCleanup:
    def test_cleanup_unsubscribes(self):
        renderer, bus = make_renderer()
        renderer._subscribed_types = [EventType.STEP_STARTED, EventType.STEP_FAILED]
        renderer._cleanup()
        assert bus.unsubscribe.call_count == 2

    def test_cleanup_no_subscribed_types(self):
        renderer, bus = make_renderer()
        renderer._subscribed_types = []
        renderer._cleanup()
        bus.unsubscribe.assert_not_called()

    def test_cleanup_sets_live_none(self):
        renderer, _ = make_renderer()
        renderer._live = object()
        renderer._cleanup()
        assert renderer._live is None


# ---------------------------------------------------------------------------
# _render layout
# ---------------------------------------------------------------------------


class TestStreamingRendererRender:
    def test_render_returns_layout(self):
        renderer, _ = make_renderer()
        renderer.set_total_steps(2)
        layout = renderer._render()
        from rich.layout import Layout
        assert isinstance(layout, Layout)

    def test_render_includes_progress_and_output_panels(self):
        renderer, _ = make_renderer()
        renderer.set_total_steps(2)
        layout = renderer._render()
        names = [c.name for c in layout.children]
        assert "progress" in names
        assert "output" in names


# ---------------------------------------------------------------------------
# StreamingSession
# ---------------------------------------------------------------------------


class TestStreamingSession:
    def test_context_manager_enters(self):
        bus = MagicMock()
        bus.subscribe = MagicMock()
        bus.unsubscribe = MagicMock()
        bus.emit = MagicMock()
        session = StreamingSession(bus=bus, total_steps=2)
        with session:
            assert session.renderer is not None
        assert session.renderer._state == RendererState.STOPPED

    def test_register_step_propagates(self):
        session = StreamingSession.__new__(StreamingSession)
        session.renderer = MagicMock()
        session.renderer.register_step = MagicMock()
        session.register_step(1, "Build")
        session.renderer.register_step.assert_called_once_with(1, "Build")

    def test_add_output_propagates(self):
        session = StreamingSession.__new__(StreamingSession)
        session.renderer = MagicMock()
        session.renderer.add_output = MagicMock()
        session.add_output("test line")
        session.renderer.add_output.assert_called_once_with("test line", source="agent")

    def test_set_total_steps_propagates(self):
        session = StreamingSession.__new__(StreamingSession)
        session.renderer = MagicMock()
        session.renderer.set_total_steps = MagicMock()
        session.set_total_steps(10)
        session.renderer.set_total_steps.assert_called_once_with(10)
