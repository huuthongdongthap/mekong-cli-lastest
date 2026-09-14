# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.
"""Real-time streaming renderer for agent TUI output.

Replaces batch-dump-on-completion with live streaming:
- Each agent event (step_started, step_output, step_completed, step_failed)
  is rendered immediately via Rich Live display.
- A progress panel shows overall pipeline progress.
- Cancel support via KeyboardInterrupt + event bus cancellation event.

Usage::

    bus = get_streaming_bus()
    renderer = StreamingRenderer(bus)
    renderer.start()
    # ... events flow through bus, renderer picks them up ...
    renderer.stop()
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from src.cli.tui.theme import get_theme
from src.core.event_bus import (
    EventType,
    StreamingEventBus,
    get_streaming_bus,
)


class RendererState(str, Enum):
    """Lifecycle states for the streaming renderer."""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    STOPPED = "stopped"


@dataclass(frozen=True)
class OutputLine:
    """A single line of streamed agent output."""

    text: str
    timestamp: float
    source: str = "agent"
    status: str = "running"  # running | success | warning | error


@dataclass(frozen=True)
class StepProgress:
    """Progress data for a single pipeline step."""

    order: int
    title: str
    status: str  # pending | running | success | error | skipped
    duration: float = 0.0
    timestamp: float = 0.0


# ── Color maps ──────────────────────────────────────────────────────────

_STATUS_COLORS = {
    "running": "yellow",
    "success": "green",
    "warning": "orange3",
    "error": "red",
    "skipped": "dim",
    "pending": "dim",
}

_STEP_ICONS = {
    "pending": "○",
    "running": "◉",
    "success": "✓",
    "error": "✗",
    "skipped": "−",
}

# Capped output line budget to prevent unbounded panel growth.
_MAX_OUTPUT_LINES = 500


# ── Progress Panel ──────────────────────────────────────────────────────


class ProgressPanel:
    """Progress panel showing overview of pipeline execution.

    Renders a Rich Progress bar plus per-step status list inside a Panel.
    Designed to be embedded as the top section of a Live layout.
    """

    def __init__(self, total_steps: int, console: Optional[Console] = None) -> None:
        self.total_steps = total_steps
        self.console = console or Console(theme=get_theme())
        self._progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[bold green]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
        )
        self._task_id: Optional[TaskID] = None
        self._steps: dict[int, StepProgress] = {}
        self._completed_count: int = 0

    def _ensure_task(self) -> TaskID:
        if self._task_id is None:
            self._task_id = self._progress.add_task(
                "Pipeline", total=self.total_steps, completed=0
            )
        return self._task_id

    def add_step(self, order: int, title: str) -> None:
        """Register a new step in the progress tracker."""
        self._steps[order] = StepProgress(order=order, title=title, status="pending")

    def start_step(self, order: int) -> None:
        """Mark a step as running."""
        if order in self._steps:
            self._steps[order] = dataclasses.replace(
                self._steps[order], status="running", timestamp=time.monotonic()
            )
            self._ensure_task()

    def complete_step(self, order: int, success: bool = True) -> None:
        """Mark a step as completed (success or error)."""
        if order not in self._steps:
            return
        step = self._steps[order]
        now = time.monotonic()
        duration = (now - step.timestamp) if step.timestamp else 0.0
        status = "success" if success else "error"
        if success:
            self._completed_count += 1
        self._steps[order] = dataclasses.replace(
            step, status=status, duration=duration, timestamp=now
        )
        task_id = self._ensure_task()
        delta = 1 if success else 0
        self._progress.update(task_id, advance=delta)

    def cancel_step(self, order: int) -> None:
        """Mark a step as skipped due to cancellation."""
        if order in self._steps:
            self._steps[order] = dataclasses.replace(
                self._steps[order], status="skipped", duration=0.0
            )

    def render(self) -> Panel:
        """Render the full progress panel."""
        step_lines: list[str] = []
        for order in sorted(self._steps):
            step = self._steps[order]
            icon = _STEP_ICONS.get(step.status, "?")
            color = _STATUS_COLORS.get(step.status, "white")
            dur = f" ({step.duration:.1f}s)" if step.duration > 0 else ""
            step_lines.append(
                f"[{color}]{icon}[/{color}] [{color}]Step {order}:[/{color}] "
                f"{step.title}{dur}"
            )
        if not step_lines:
            step_lines.append("[dim]No steps registered yet[/dim]")

        step_text = Text("\n".join(step_lines))

        # Use Rich's Group to combine Progress + Text vertically
        from rich.console import Group

        combined = Group(
            self._progress,
            Text(""),
            step_text,
        )

        return Panel(
            combined,
            title="[bold]Pipeline Progress[/bold]",
            border_style="blue",
            padding=(0, 1),
        )


# ── Streaming Renderer ─────────────────────────────────────────────────


class StreamingRenderer:
    """Real-time streaming renderer using Rich Live display.

    Subscribes to a :class:`StreamingEventBus` and re-renders the terminal
    on every agent event, replacing the old batch-dump-whole-output model.

    Features:
    - Live-updating output panel (agent stdout/stderr streamed line-by-line)
    - Progress panel with per-step status (pending/running/success/error)
    - Cancel via KeyboardInterrupt or explicit ``stop()`` call
    - Thread-safe: bus subscriptions are single-threaded (event bus is
      synchronous), Live rendering runs on the caller's thread.

    Parameters
    ----------
    bus:
        Optional ``StreamingEventBus`` instance. Defaults to the global
        ``get_streaming_bus()``.
    max_lines:
        Maximum output lines kept in the buffer (default 500, FIFO eviction).
    """

    def __init__(
        self,
        bus: Optional[StreamingEventBus] = None,
        max_lines: int = _MAX_OUTPUT_LINES,
        console: Optional[Console] = None,
    ) -> None:
        self.bus = bus or get_streaming_bus()
        self.max_lines = max_lines
        self.console = console or Console(theme=get_theme())
        self._output_lines: list[OutputLine] = []
        self._steps: dict[int, StepProgress] = {}
        self._total_steps: int = 0
        self._state = RendererState.IDLE
        self._live: Optional[Live] = None
        self._progress_panel: Optional[ProgressPanel] = None
        self._cancel_callback: Optional[Callable[[], None]] = None
        self._cancelled: bool = False
        self._start_time: float = 0.0
        self._subscribed_types: list[Any] = []

    # ── Public API ──────────────────────────────────────────────────────

    def set_total_steps(self, total: int) -> None:
        """Set the total step count (must be called before ``start()``)."""
        self._total_steps = total

    def register_step(self, order: int, title: str) -> None:
        """Register a step before it starts."""
        self._steps[order] = StepProgress(order=order, title=title, status="pending")

    def cancel(self) -> None:
        """Request cancellation from outside (alternative to Ctrl-C)."""
        self._handle_cancel()

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when cancellation occurs."""
        self._cancel_callback = callback

    def start(self) -> None:
        """Start the live streaming display.

        Subscribes to the event bus, opens the Rich Live context (blocking),
        and re-renders on every event. Returns when ``stop()`` is called or
        the pipeline finishes / is cancelled.
        """
        if self._state == RendererState.RUNNING:
            return

        self._state = RendererState.RUNNING
        self._cancelled = False
        self._start_time = time.monotonic()
        self._progress_panel = ProgressPanel(
            total_steps=self._total_steps, console=self.console
        )
        # Seed progress panel with registered steps
        for order in sorted(self._steps):
            sp = self._steps[order]
            self._progress_panel.add_step(order, sp.title)

        # Subscribe to relevant event types
        self._subscribed_types = [
            EventType.STEP_STARTED,
            EventType.STEP_COMPLETED,
            EventType.STEP_FAILED,
            EventType.STEP_HEALED,
            EventType.GOAL_STARTED,
            EventType.GOAL_COMPLETED,
            EventType.HALT_TRIGGERED,
        ]
        for event_type in self._subscribed_types:
            self.bus.subscribe(event_type, self._on_event)

        try:
            with Live(
                self._render(),
                console=self.console,
                refresh_per_second=10,
                screen=True,
            ) as live:
                self._live = live
                # Block until state changes from RUNNING
                while self._state == RendererState.RUNNING:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            self._handle_cancel()
        finally:
            self._cleanup()
            self.console.show_cursor()

    def stop(self) -> None:
        """Request the display to stop (called from outside)."""
        self._state = RendererState.STOPPED

    def add_output(self, text: str, source: str = "agent") -> None:
        """Manually inject an output line (alternative to event bus)."""
        self._output_lines.append(
            OutputLine(
                text=text,
                timestamp=time.monotonic(),
                source=source,
                status="running",
            )
        )
        self._evict_lines()

    def mark_output(self, index: int, status: str) -> None:
        """Update the status of a previously added output line."""
        if 0 <= index < len(self._output_lines):
            line = self._output_lines[index]
            self._output_lines[index] = dataclasses.replace(
                line, status=status
            )

    # ── Internal event handling ─────────────────────────────────────────

    def _on_event(self, event: Any) -> None:
        """Handle a single event from the bus (called synchronously)."""
        etype = event.type
        data = event.data or {}

        if etype == EventType.STEP_STARTED:
            order = int(data.get("step_order", data.get("step", 0)))
            title = data.get("title", f"Step {order}")
            self._handle_step_started(order, title)

        elif etype == EventType.STEP_COMPLETED:
            order = int(data.get("step_order", data.get("step", 0)))
            self._handle_step_completed(order, success=True)

        elif etype == EventType.STEP_FAILED:
            order = int(data.get("step_order", data.get("step", 0)))
            self._handle_step_completed(order, success=False)

        elif etype == EventType.STEP_HEALED:
            self._handle_step_healed(data)

        elif etype == EventType.GOAL_COMPLETED:
            self._handle_goal_completed(data)

        elif etype == EventType.HALT_TRIGGERED:
            self._handle_halt(data)

        # Inject output lines if the event carries stdout/stderr
        output = data.get("stdout", data.get("output", ""))
        if output:
            for line in output.splitlines():
                if line.strip():
                    self.add_output(line, source="agent")

    def _handle_step_started(self, order: int, title: str) -> None:
        self._steps.setdefault(
            order, StepProgress(order=order, title=title, status="pending")
        )
        self._steps[order] = dataclasses.replace(
            self._steps[order], status="running", timestamp=time.monotonic()
        )
        if self._progress_panel:
            self._progress_panel.add_step(order, title)
            self._progress_panel.start_step(order)
        self.add_output(f"[bold cyan]▶ Step {order}:[/bold cyan] {title}", source="renderer")

    def _handle_step_completed(self, order: int, success: bool) -> None:
        if order in self._steps:
            step = self._steps[order]
            now = time.monotonic()
            duration = (now - step.timestamp) if step.timestamp else 0.0
            status = "success" if success else "error"
            self._steps[order] = dataclasses.replace(
                step, status=status, duration=duration, timestamp=now
            )
        if self._progress_panel:
            self._progress_panel.complete_step(order, success=success)
        icon = "✓" if success else "✗"
        style = "green" if success else "red"
        self.add_output(
            f"[{style}]{icon} Step {order} {'done' if success else 'failed'}[/{style}]",
            source="renderer",
        )

    def _handle_step_healed(self, data: dict) -> None:
        order = data.get("step_order", data.get("step", "?"))
        self.add_output(
            f"[yellow]\U0001f527 Step {order} self-healed[/yellow]", source="renderer"
        )

    def _handle_goal_completed(self, data: dict) -> None:
        self._state = RendererState.STOPPED

    def _handle_halt(self, data: dict) -> None:
        reason = data.get("reason", "unknown")
        self.add_output(f"[bold red]⛔ HALT: {reason}[/bold red]", source="renderer")
        self._state = RendererState.STOPPED

    def _handle_cancel(self) -> None:
        """Handle user-initiated cancellation (Ctrl-C)."""
        self._cancelled = True
        self._state = RendererState.CANCELLING
        self.add_output(
            "[bold yellow]⚠ Cancellation requested — shutting down...[/bold yellow]",
            source="renderer",
        )
        if self._cancel_callback:
            try:
                self._cancel_callback()
            except Exception:
                pass
        # Emit halt event so other listeners know
        self.bus.emit(EventType.HALT_TRIGGERED, {"reason": "user_cancelled"})
        self._state = RendererState.STOPPED

    # ── Rendering ──────────────────────────────────────────────────────

    def _render(self) -> Layout:
        """Build the full terminal layout."""
        layout = Layout()
        output_panel = self._build_output_panel()
        progress = (
            self._progress_panel.render()
            if self._progress_panel
            else Panel(
                "[dim]Initializing...[/dim]", title="Progress", border_style="blue"
            )
        )
        layout.split_column(
            Layout(progress, name="progress", size=8),
            Layout(output_panel, name="output"),
        )
        return layout

    def _build_output_panel(self) -> Panel:
        lines = self._output_lines[-self.max_lines :]
        if not lines:
            body = Text("[dim]Waiting for agent output...[/dim]")
        else:
            parts: list[Text] = []
            for line in lines:
                color = _STATUS_COLORS.get(line.status, "white")
                parts.append(Text.from_markup(line.text, style=color))
            body = Text("\n").join(parts)
        return Panel(
            body,
            title="[bold]Agent Output[/bold]",
            border_style="gray",
            padding=(0, 1),
        )

    def _evict_lines(self) -> None:
        """Trim output buffer to max_lines (oldest first)."""
        while len(self._output_lines) > self.max_lines:
            self._output_lines.pop(0)

    def _cleanup(self) -> None:
        """Unsubscribe from event bus."""
        for event_type in self._subscribed_types:
            try:
                self.bus.unsubscribe(event_type, self._on_event)
            except Exception:
                pass
        self._live = None


# ── Context Manager ─────────────────────────────────────────────────────


class StreamingSession:
    """Convenience context manager for streaming renderer.

    Usage::

        bus = get_streaming_bus()
        with StreamingSession(bus, total_steps=5) as session:
            for step in steps:
                session.register_step(step.order, step.title)
                session.start_step(step.order)
                # execute step -- events flow through bus
    """

    def __init__(
        self,
        bus: Optional[StreamingEventBus] = None,
        total_steps: int = 0,
        console: Optional[Console] = None,
    ) -> None:
        self.renderer = StreamingRenderer(bus=bus, console=console)
        self.renderer.set_total_steps(total_steps)
        self._total = total_steps
        self._steps: dict[int, StepProgress] = {}

    def __enter__(self) -> "StreamingSession":
        import threading

        self._thread = threading.Thread(target=self.renderer.start, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.renderer.stop()
        if hasattr(self, "_thread"):
            self._thread.join(timeout=2.0)

    def register_step(self, order: int, title: str) -> None:
        self.renderer.register_step(order, title)

    def start_step(self, order: int) -> None:
        sp = self._steps.get(order) or StepProgress(
            order=order, title=f"Step {order}", status="pending"
        )
        self._steps[order] = sp
        self.renderer._handle_step_started(order, sp.title)

    def add_output(self, text: str, source: str = "agent") -> None:
        self.renderer.add_output(text, source=source)

    def set_total_steps(self, n: int) -> None:
        self._total = n
        self.renderer.set_total_steps(n)


