# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Mekong CLI - Recipe Executor

Executes recipes parsed from Markdown files.
Returns ExecutionResult for orchestrator integration.
"""

import shlex
import subprocess
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.core.circuit_breaker import get_circuit_breaker
from src.core.crash_detector import CrashPatternDetector
from src.core.retry import ExponentialBackoff, call_with_retry

from src.core.command_sanitizer import CommandSanitizer
from .parser import Recipe, RecipeStep
from src.harness.pev.checkpoint import CheckpointStore, PipelineCheckpoint, _utc_now  # noqa: F401
from src.core.verifier import ExecutionResult


class RecipeExecutor:
    """Executes a Recipe step by step, returning structured results."""

    # Agentic reliability: global execution caps prevent infinite loops.
    MAX_RETRIES_PER_STEP = 5
    MAX_TOTAL_ITERATIONS = 20

    def __init__(
        self,
        recipe: Recipe,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        """Initialize RecipeExecutor with a parsed recipe.

        Args:
            recipe: The Recipe object containing steps to execute.
            checkpoint_store: Optional store for checkpoint/resume support.
        """
        self.recipe = recipe
        self.console = Console()
        self._total_iterations: int = 0
        self._checkpoint_store = checkpoint_store
        # C3 self-healing: exponential backoff, circuit breakers, crash detector.
        self._backoff: ExponentialBackoff = ExponentialBackoff(
            initial=1.0, max_delay=30.0, factor=2.0,
        )
        self._llm_breaker = get_circuit_breaker(
            "pev-llm", failure_threshold=3, recovery_timeout=30.0,
        )
        self._api_breaker = get_circuit_breaker(
            "pev-api", failure_threshold=3, recovery_timeout=30.0,
        )
        self._browse_breaker = get_circuit_breaker(
            "pev-browse", failure_threshold=3, recovery_timeout=30.0,
        )
        self._crash_detector: CrashPatternDetector | None = CrashPatternDetector()

    def execute_step(self, step: RecipeStep) -> ExecutionResult:
        """
        Execute a single step.
        Supports multiple execution modes: shell, llm, api, tool, browse

        Returns:
            ExecutionResult with exit_code, stdout, stderr for verification
        """
        # Bounded iteration guard: prevent runaway pipelines.
        self._total_iterations += 1
        if self._total_iterations > self.MAX_TOTAL_ITERATIONS:
            msg = (
                f"Global iteration cap reached ({self.MAX_TOTAL_ITERATIONS}). "
                "Pipeline aborted to prevent runaway execution."
            )
            self.console.print(f"[bold red]ITERATION CAP:[/bold red] {msg}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=msg,
                metadata={
                    "iteration_cap_hit": True,
                    "total_iterations": self._total_iterations,
                },
            )

        self.console.print(
            f"\n[bold blue]Step {step.order}:[/bold blue] {step.title}"
        )

        # Determine execution mode from step params or description
        step_type = (
            step.params.get("type", "shell") if step.params else "shell"
        )

        # Handle different execution types
        if step_type == "llm":
            result = self._execute_llm_step(step)
        elif step_type == "api":
            result = self._execute_api_step(step)
        elif step_type == "tool":
            result = self._execute_tool_step(step)
        elif step_type == "browse":
            result = self._execute_browse_step(step)
        else:
            result = self._execute_shell_step(step)

        # C3 crash-pattern detection hook: annotate result with crash signals.
        if self._crash_detector is not None:
            signals = self._crash_detector.inspect_step(result)
            if signals:
                result.metadata["crash_signals"] = signals
                self.console.print(
                    "[bold red][crash-detected][/bold red] Signals: "
                    + ", ".join(
                        f"{s['category']}:{s['signal']}" for s in signals
                    )
                )

        # Checkpoint/resume: persist completed step so pipeline can resume on failure.
        if (
            result.exit_code == 0
            and self._checkpoint_store is not None
        ):
            pipeline_id = self.recipe.name
            existing = self._checkpoint_store.load(pipeline_id)
            completed = (
                list(existing.completed_steps) if existing else []
            )
            if step.order not in completed:
                completed.append(step.order)
            checkpoint = PipelineCheckpoint(
                pipeline_id=pipeline_id,
                completed_steps=completed,
                last_step_order=step.order,
                status="running",
                created_at=(
                    existing.created_at if existing else _utc_now()
                ),
                updated_at=_utc_now(),
            )
            self._checkpoint_store.save(checkpoint)

        return result

    def _execute_llm_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute LLM generation step via Antigravity Proxy or OpenAI."""
        from src.providers.llm.client import get_client

        self.console.print(
            f"[cyan][LLM] Generating:[/cyan] {step.description}"
        )

        client = get_client()
        if not client.is_available:
            self.console.print(
                "[yellow]LLM offline — skipping step[/yellow]"
            )
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] LLM offline",
                stderr="",
                metadata={"mode": "llm", "skipped": True},
            )

        try:
            prompt = step.description
            system_prompt = (
                step.params.get("system", "")
                if step.params
                else ""
            )

            messages = []
            if system_prompt:
                messages.append(
                    {"role": "system", "content": system_prompt}
                )
            messages.append({"role": "user", "content": prompt})

            def _call_llm():
                return client.chat(messages)

            def _llm_fallback():
                # Called when circuit is OPEN — skipped result.
                self.console.print(
                    "[yellow]LLM circuit open — step skipped "
                    "(fallback)[/yellow]"
                )
                from src.core.verifier import ExecutionResult as ER
                return ER(
                    exit_code=0,
                    stdout="[SKIPPED] Circuit open",
                    stderr="",
                    metadata={
                        "mode": "llm",
                        "circuit_open": True,
                    },
                )

            response = self._llm_breaker.call(
                _call_llm, fallback=_llm_fallback
            )
            # The fallback returns a ready-to-use ExecutionResult (circuit
            # open); only the normal LLM path returns a chat response object.
            if isinstance(response, ExecutionResult):
                return response
            output = response.content[:2000]
            self.console.print(
                Panel(
                    output,
                    title=f"LLM Output ({response.model})",
                    border_style="cyan",
                    expand=False,
                )
            )
            return ExecutionResult(
                exit_code=0,
                stdout=response.content,
                stderr="",
                metadata={
                    "mode": "llm",
                    "model": response.model,
                },
            )

        except Exception as e:
            self.console.print(
                f"[bold red]LLM Error:[/bold red] {str(e)}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "llm"},
            )

    def _execute_api_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute API call step."""
        import requests as req

        url = (
            step.params.get("url", "")
            if step.params
            else ""
        )
        method = (
            (step.params.get("method", "GET") if step.params else "GET")
        ).upper()
        body = (
            step.params.get("body", None) if step.params else None
        )
        headers = (
            step.params.get("headers", {}) if step.params else {}
        )

        if not url:
            self.console.print(
                "[yellow]No URL specified — skipping API step[/yellow]"
            )
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] No URL",
                stderr="",
                metadata={"mode": "api", "skipped": True},
            )

        self.console.print(f"[cyan][API] {method}:[/cyan] {url}")

        def _call_api():
            return req.request(
                method, url, json=body, headers=headers, timeout=30
            )

        def _api_fallback():
            self.console.print(
                "[yellow]API circuit open — step skipped "
                "(fallback)[/yellow]"
            )
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] Circuit open",
                stderr="",
                metadata={
                    "mode": "api",
                    "circuit_open": True,
                    "url": url,
                },
            )

        try:
            response = self._api_breaker.call(
                _call_api, fallback=_api_fallback
            )
            status_color = "green" if response.ok else "red"
            self.console.print(
                f"[{status_color}]Status: "
                f"{response.status_code}[/{status_color}]"
            )

            preview = (
                response.text[:1000] if response.text else ""
            )
            if preview:
                self.console.print(
                    Panel(
                        preview,
                        title="Response",
                        border_style="dim",
                        expand=False,
                    )
                )

            return ExecutionResult(
                exit_code=0 if response.ok else 1,
                stdout=response.text or "",
                stderr=(
                    ""
                    if response.ok
                    else f"HTTP {response.status_code}"
                ),
                metadata={
                    "mode": "api",
                    "status_code": response.status_code,
                    "url": url,
                },
            )

        except req.exceptions.RequestException as e:
            self.console.print(
                f"[bold red]API Error:[/bold red] {str(e)}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "api", "url": url},
            )

    def _execute_tool_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute step via AGI v2 ToolRegistry."""
        tool_name = (
            step.params.get("tool_name", "") if step.params else ""
        )
        tool_args = (
            step.params.get("tool_args", {}) if step.params else {}
        )

        if not tool_name:
            # Try to infer tool from step description
            tool_name = step.description.strip()

        self.console.print(
            f"[cyan][Tool] Executing:[/cyan] {tool_name}"
        )

        try:
            from src.core.tool_registry import ToolRegistry

            registry = ToolRegistry()
            result = registry.execute(tool_name, tool_args)

            output = result.get("output", "")
            success = result.get("success", False)
            duration = result.get("duration_ms", 0)

            status_color = "green" if success else "red"
            self.console.print(
                f"[{status_color}]Tool "
                f"{'succeeded' if success else 'failed'} "
                f"({duration:.0f}ms)[/{status_color}]"
            )

            if output:
                self.console.print(
                    Panel(
                        str(output)[:1000],
                        title=f"Tool: {tool_name}",
                        border_style=status_color,
                        expand=False,
                    )
                )

            return ExecutionResult(
                exit_code=0 if success else 1,
                stdout=str(output),
                stderr=result.get("error", ""),
                metadata={
                    "mode": "tool",
                    "tool_name": tool_name,
                    "duration_ms": duration,
                },
            )

        except Exception as e:
            self.console.print(
                f"[bold red]Tool Error:[/bold red] {str(e)}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={
                    "mode": "tool",
                    "tool_name": tool_name,
                },
            )

    def _execute_browse_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute step via AGI v2 BrowserAgent."""
        url = (
            step.params.get("url", "")
            if step.params
            else ""
        )
        browse_action = (
            step.params.get("action", "analyze")
            if step.params
            else "analyze"
        )

        if not url:
            url = step.description.strip()

        self.console.print(
            f"[cyan][Browse] {browse_action}:[/cyan] {url}"
        )

        def _call_browse():
            from src.core.browser_agent import BrowserAgent
            agent = BrowserAgent()
            if browse_action == "check":
                return agent.check_status(url)
            elif browse_action == "links":
                return agent.get_links(url)
            else:  # analyze
                return agent.analyze_page(url)

        def _browse_fallback():
            self.console.print(
                "[yellow]Browse circuit open — step skipped "
                "(fallback)[/yellow]"
            )
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] Circuit open",
                stderr="",
                metadata={
                    "mode": "browse",
                    "circuit_open": True,
                    "url": url,
                },
            )

        try:
            result = self._browse_breaker.call(
                _call_browse, fallback=_browse_fallback,
            )
            if browse_action == "check":
                _status_color = (
                    "green"
                    if getattr(result, "success", False)
                    else "red"
                )
                output = (
                    f"HTTP {getattr(result, 'status_code', 0)} "
                    f"({getattr(result, 'duration_ms', 0):.0f}ms)"
                )
            elif browse_action == "links":
                _links = getattr(result, "links", [])
                output = (
                    f"Found {len(_links)} links:\n"
                    + "\n".join(_links[:10])
                )
            else:  # analyze
                output = (
                    f"Title: {getattr(result, 'title', '')}\n"
                    f"Status: {getattr(result, 'status_code', 0)}\n"
                    f"Links: {len(getattr(result, 'links', []))}\n"
                    f"Load Time: "
                    f"{getattr(result, 'load_time_ms', 0):.0f}ms\n\n"
                    f"{getattr(result, 'text_content', '')[:500]}"
                )
            _status_color = (
                "green"
                if getattr(result, "status_code", 0) < 400
                else "red"
            )

            self.console.print(
                Panel(
                    output[:1000],
                    title=f"Browse: {url[:60]}",
                    border_style="cyan",
                    expand=False,
                )
            )

            return ExecutionResult(
                exit_code=(
                    0
                    if getattr(result, "success", False)
                    else 1
                ),
                stdout=output,
                stderr="",
                metadata={
                    "mode": "browse",
                    "url": url,
                    "action": browse_action,
                },
            )

        except Exception as e:
            self.console.print(
                f"[bold red]Browse Error:[/bold red] {str(e)}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "browse", "url": url},
            )

    def _execute_shell_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute shell command step with automatic retry on failure."""
        command = step.description.strip()
        import re

        # Extract embedded command if present
        backtick_matches = re.findall(r"`([^`]+)`", command)
        if backtick_matches:
            if len(backtick_matches) == 1:
                command = backtick_matches[0].strip()
            else:
                command = backtick_matches[-1].strip()
        else:
            if "command to execute is:" in command.lower():
                parts = re.split(
                    r"(?i)command to execute is:\s*", command
                )
                if len(parts) > 1:
                    command = parts[-1].strip()
            elif "command is:" in command.lower():
                parts = re.split(r"(?i)command is:\s*", command)
                if len(parts) > 1:
                    command = parts[-1].strip()
            elif "command:" in command.lower():
                parts = re.split(r"(?i)command:\s*", command)
                if len(parts) > 1:
                    command = parts[-1].strip()

        command = command.strip()
        if command.startswith("`") and command.endswith("`") and len(command) >= 2:
            command = command[1:-1].strip()
        elif (command.startswith('"') and command.endswith('"')) or (
            command.startswith("'") and command.endswith("'")
        ):
            command = command[1:-1].strip()

        if not command:
            self.console.print("[yellow]Skipping empty step[/yellow]")
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] Empty command",
                stderr="",
                metadata={"mode": "shell", "skipped": True},
            )

        # Sanitize command before execution
        sanitizer = CommandSanitizer()
        if not sanitizer.is_safe_command(command):
            res = sanitizer.sanitize(command)
            self.console.print(
                f"[red]BLOCKED:[/red] Unsafe command: {command}. "
                f"Reason: {res.blocked_reason}. "
                f"Patterns: {res.blocked_patterns}. "
                f"Warnings: {res.warnings}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=(
                    f"Command blocked by sanitizer: {command}. "
                    f"Reason: {res.blocked_reason}"
                ),
                metadata={"mode": "shell", "blocked": True},
            )

        # C3: use exponential backoff via call_with_retry().
        def _run_shell() -> ExecutionResult:
            cmd_args = (
                shlex.split(command)
                if isinstance(command, str)
                else command
            )
            process = subprocess.run(
                cmd_args,
                shell=False,
                check=True,
                text=True,
                capture_output=True,
            )
            if process.stdout:
                self.console.print(
                    Panel(
                        process.stdout.strip(),
                        title="Output",
                        border_style="green",
                        expand=False,
                    )
                )
            if process.stderr:
                self.console.print(
                    Panel(
                        process.stderr.strip(),
                        title="Stderr",
                        border_style="yellow",
                        expand=False,
                    )
                )
            return ExecutionResult(
                exit_code=process.returncode or 0,
                stdout=process.stdout or "",
                stderr=process.stderr or "",
                metadata={
                    "mode": "shell",
                    "command": command,
                },
            )

        def _on_shell_retry(
            attempt: int, delay: float
        ) -> None:
            self.console.print(
                f"[yellow]Retry {attempt} after "
                f"{delay:.1f}s...[/yellow]"
            )

        raw_attempts = (
            (step.params.get("retry", 1) + 1)
            if step.params
            else 2
        )
        max_attempts = min(
            raw_attempts, self.MAX_RETRIES_PER_STEP + 1
        )

        success, result_or_err, stats = call_with_retry(
            _run_shell,
            max_attempts=max_attempts,
            backoff=self._backoff,
            retryable=(subprocess.CalledProcessError,),
            on_retry=_on_shell_retry,
        )

        if success:
            result = result_or_err
            result.metadata["attempt"] = stats.attempts
            result.metadata["delays"] = stats.delays
            return result
        else:
            e = result_or_err
            self.console.print(
                f"[bold red]Error executing step "
                f"{step.order}[/bold red]"
                f" (failed after {stats.attempts} attempts)"
            )
            err_code = getattr(e, "returncode", 1)
            err_out = getattr(e, "stdout", "") or ""
            err_err = getattr(e, "stderr", "") or ""
            if err_out:
                self.console.print(
                    Panel(
                        err_out.strip(),
                        title="Output (Partial)",
                        border_style="yellow",
                        expand=False,
                    )
                )
            if err_err:
                self.console.print(
                    Panel(
                        err_err.strip(),
                        title="Error Output",
                        border_style="red",
                        expand=False,
                    )
                )
            return ExecutionResult(
                exit_code=err_code,
                stdout=err_out,
                stderr=err_err or str(e),
                error=e,
                metadata={
                    "mode": "shell",
                    "command": command,
                    "attempt": stats.attempts,
                    "delays": stats.delays,
                },
            )

    def run(self) -> bool:
        """Run the full recipe (legacy mode, returns bool)."""
        self.console.print(
            Panel(
                Text(
                    self.recipe.title or self.recipe.name, style="italic"
                ),
                title=f"Running: {self.recipe.name}",
                border_style="cyan",
            )
        )

        for step in self.recipe.steps:
            result = self.execute_step(step)
            if result.exit_code != 0:
                self.console.print(
                    "\n[bold red]Recipe execution failed.[/bold red]"
                )
                return False

        self.console.print(
            f"\n[bold green]Recipe '{self.recipe.name}' "
            "completed successfully![/bold green]"
        )
        return True
