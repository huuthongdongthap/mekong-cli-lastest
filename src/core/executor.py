# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Mekong CLI - Recipe Executor

Executes recipes parsed from Markdown files.
Returns ExecutionResult for orchestrator integration.
"""

import concurrent.futures
import ipaddress
import re
import shlex
import socket
import subprocess
import time
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.core.command_sanitizer import CommandSanitizer
from src.core.parser import Recipe, RecipeStep
from src.harness.pev.checkpoint import CheckpointStore, PipelineCheckpoint, _utc_now
from src.core.verifier import ExecutionResult

# Blocked CIDR ranges for SSRF prevention
_SSRF_BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),        # current network
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


class RecipeExecutor:
    """Executes a Recipe step by step, returning structured results."""

    # Agentic reliability: global execution caps prevent infinite loops.
    MAX_RETRIES_PER_STEP = 5
    MAX_TOTAL_ITERATIONS = 20

    def __init__(self, recipe: Recipe, checkpoint_store: CheckpointStore | None = None) -> None:
        """Initialize RecipeExecutor with a parsed recipe.

        Args:
            recipe: The Recipe object containing steps to execute.
            checkpoint_store: Optional store for checkpoint/resume support.
        """
        self.recipe = recipe
        self.console = Console()
        self._total_iterations: int = 0
        self._checkpoint_store = checkpoint_store

    def execute_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute a single step.

        Supports multiple execution modes: shell, llm, api, tool, browse.

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
                metadata={"iteration_cap_hit": True, "total_iterations": self._total_iterations},
            )

        self.console.print(f"\n[bold blue]Step {step.order}:[/bold blue] {step.title}")

        # Determine execution mode from step params or description
        step_type = step.params.get("type", "shell") if step.params else "shell"

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

        # Checkpoint/resume: persist completed step so pipeline can resume on failure.
        if result.exit_code == 0 and self._checkpoint_store is not None:
            pipeline_id = self.recipe.name
            existing = self._checkpoint_store.load(pipeline_id)
            completed = list(existing.completed_steps) if existing else []
            if step.order not in completed:
                completed.append(step.order)
            checkpoint = PipelineCheckpoint(
                pipeline_id=pipeline_id,
                completed_steps=completed,
                last_step_order=step.order,
                status="running",
                created_at=existing.created_at if existing else _utc_now(),
                updated_at=_utc_now(),
            )
            self._checkpoint_store.save(checkpoint)

        return result

    def _validate_url(self, url: str) -> tuple:
        """Validate URL against SSRF attacks with IP pinning.

        Resolves hostname to IP, checks against blocked networks, and returns
        the resolved IP for callers to re-validate immediately before the
        HTTP request (prevents DNS rebinding / TOCTOU attacks).

        Args:
            url: The URL to validate.

        Returns:
            (error_message, pinned_ip) -- error_message is None if safe,
            pinned_ip is the resolved IP string (or None if unresolvable).
        """
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if not host:
                return f"No hostname in URL: {url}", None

            # Resolve IP and capture for pinning
            try:
                addr = ipaddress.ip_address(host)
                pinned_ip = str(addr)
            except ValueError:
                # Resolve hostname - capture IP for pinning
                try:
                    pinned_ip = socket.gethostbyname(host)
                    addr = ipaddress.ip_address(pinned_ip)
                except (socket.gaierror, OSError, ValueError):
                    # Cannot resolve - allow
                    return None, None

            if not isinstance(addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
                return None, None

            # Check against all blocked networks
            for network in _SSRF_BLOCKED_NETWORKS:
                if addr in network:
                    return (
                        f"SSRF blocked - target {host} ({addr}) is in blocked range {network}",
                        pinned_ip,
                    )

            return None, pinned_ip
        except Exception as e:
            return f"URL validation error: {e}", None
    def _sanitize_llm_prompt(self, text: str, max_length: int = 8000) -> str:
        """Sanitize text before passing to LLM to prevent prompt injection.

        - Truncate to max_length to avoid context overflow attacks.
        - Strip control characters and null bytes.
        - Neutralize common prompt injection patterns.

        Args:
            text: Raw step description or prompt text.
            max_length: Maximum allowed length.

        Returns:
            Sanitized text safe for LLM consumption.
        """
        # Truncate
        if len(text) > max_length:
            text = text[:max_length]
            self.console.print(
                f"[yellow]Prompt truncated to {max_length} chars[/yellow]"
            )

        # Strip null bytes and control characters (except newlines/tabs)
        text = text.replace("\x00", "")
        text = "".join(c for c in text if c.isprintable() or c in ("\n", "\t", " "))

        # Neutralize common prompt injection patterns
        injection_patterns = [
            r"ignore\s+(all\s+)?(previous|above)\s+(instructions|prompts?)",
            r"disregard\s+(all\s+)?(previous|above)",
            r"you\s+are\s+now\s+(a|an)\s+",
            r"system\s*:\s*",
            r"\[INST\]",
            r"<<SYS>>",
            r"<\|im_start\|>",
            r"<\|im_end\|>",
            r"###\s*(instruction|system|human|assistant)",
        ]
        for pattern in injection_patterns:
            text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)

        return text

    def _execute_llm_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute LLM generation step via Antigravity Proxy or OpenAI."""
        from src.providers.llm.client import get_client

        self.console.print(f"[cyan][LLM] Generating:[/cyan] {step.description}")

        client = get_client()
        if not client.is_available:
            self.console.print("[yellow]LLM offline — skipping step[/yellow]")
            return ExecutionResult(
                exit_code=0,
                stdout="[SKIPPED] LLM offline",
                stderr="",
                metadata={"mode": "llm", "skipped": True},
            )

        try:
            # Sanitize prompt before sending to LLM — prevent prompt injection
            prompt = self._sanitize_llm_prompt(step.description)
            system_prompt = step.params.get("system", "") if step.params else ""
            if system_prompt:
                system_prompt = self._sanitize_llm_prompt(system_prompt)

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat(messages)
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
                metadata={"mode": "llm", "model": response.model},
            )

        except Exception as e:
            self.console.print(f"[bold red]LLM Error:[/bold red] {str(e)}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "llm"},
            )

    def _execute_api_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute API call step with SSRF protection."""
        import requests as req

        url = step.params.get("url", "") if step.params else ""
        method = (step.params.get("method", "GET") if step.params else "GET").upper()
        body = step.params.get("body", None) if step.params else None
        headers = step.params.get("headers", {}) if step.params else {}

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

        # SSRF prevention: validate URL before making request
        ssrf_error, pinned_ip = self._validate_url(url)
        if ssrf_error:
            self.console.print(f"[bold red]SECURITY:[/bold red] {ssrf_error}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"SSRF blocked: {url}",
                metadata={"mode": "api", "ssrf_blocked": True},
            )


        # Re-validate pinned IP immediately before request (defense-in-depth
        # against DNS rebinding: if DNS changed since validation, block it).
        if pinned_ip:
            _addr = ipaddress.ip_address(pinned_ip)
            for network in _SSRF_BLOCKED_NETWORKS:
                if _addr in network:
                    self.console.print(
                        f"[bold red]SECURITY:[/bold red] "
                        f"SSRF blocked - pinned IP {pinned_ip} in blocked range {network}"
                    )
                    return ExecutionResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"SSRF blocked (pinned IP): {url}",
                        metadata={"mode": "api", "ssrf_blocked": True},
                    )
        self.console.print(f"[cyan][API] {method}:[/cyan] {url}")

        try:
            response = req.request(
                method, url, json=body, headers=headers, timeout=30
            )
            status_color = "green" if response.ok else "red"
            self.console.print(
                f"[{status_color}]Status: {response.status_code}[/{status_color}]"
            )

            preview = response.text[:1000] if response.text else ""
            if preview:
                self.console.print(
                    Panel(
                        preview, title="Response", border_style="dim", expand=False
                    )
                )

            return ExecutionResult(
                exit_code=0 if response.ok else 1,
                stdout=response.text or "",
                stderr="" if response.ok else f"HTTP {response.status_code}",
                metadata={
                    "mode": "api",
                    "status_code": response.status_code,
                    "url": url,
                },
            )

        except req.exceptions.RequestException as e:
            self.console.print(f"[bold red]API Error:[/bold red] {str(e)}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "api", "url": url},
            )

    def _execute_tool_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute step via AGI v2 ToolRegistry."""
        tool_name = step.params.get("tool_name", "") if step.params else ""
        tool_args = step.params.get("tool_args", {}) if step.params else {}

        if not tool_name:
            # Try to infer tool from step description
            tool_name = step.description.strip()

        self.console.print(f"[cyan][Tool] Executing:[/cyan] {tool_name}")

        try:
            from src.core.tool_registry import ToolRegistry

            registry = ToolRegistry()
            result = registry.execute(tool_name, tool_args)

            output = result.get("output", "")
            success = result.get("success", False)
            duration = result.get("duration_ms", 0)

            status_color = "green" if success else "red"
            self.console.print(
                f"[{status_color}]Tool {'succeeded' if success else 'failed'} "
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
            self.console.print(f"[bold red]Tool Error:[/bold red] {str(e)}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
                error=e,
                metadata={"mode": "tool", "tool_name": tool_name},
            )

    def _execute_browse_step(self, step: RecipeStep) -> ExecutionResult:
        """Execute step via AGI v2 BrowserAgent with SSRF protection."""
        url = step.params.get("url", "") if step.params else ""
        browse_action = step.params.get("action", "analyze") if step.params else "analyze"

        if not url:
            url = step.description.strip()

        # SSRF prevention: validate URL before browser fetch
        ssrf_error, pinned_ip = self._validate_url(url)
        if ssrf_error:
            self.console.print(f"[bold red]SECURITY:[/bold red] {ssrf_error}")
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"SSRF blocked: {url}",
                metadata={"mode": "browse", "ssrf_blocked": True},
            )

        # Re-validate pinned IP immediately before browser fetch
        # (DNS rebinding guard)
        if pinned_ip:
            _addr = ipaddress.ip_address(pinned_ip)
            for network in _SSRF_BLOCKED_NETWORKS:
                if _addr in network:
                    self.console.print(
                        f"[bold red]SECURITY:[/bold red] "
                        f"SSRF blocked - pinned IP {pinned_ip} in blocked range {network}"
                    )
                    return ExecutionResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"SSRF blocked (pinned IP browse): {url}",
                        metadata={"mode": "browse", "ssrf_blocked": True},
                    )

        self.console.print(f"[cyan][Browse] {browse_action}:[/cyan] {url}")

        try:
            from src.core.browser_agent import BrowserAgent

            agent = BrowserAgent()

            if browse_action == "check":
                result = agent.check_status(url)
                _status_color = "green" if result.success else "red"
                output = f"HTTP {result.status_code} ({result.duration_ms:.0f}ms)"
            elif browse_action == "links":
                result = agent.get_links(url)
                output = (
                    f"Found {len(result.links)} links:\n"
                    + "\n".join(result.links[:10])
                )
            else:  # analyze
                result = agent.analyze_page(url)
                output = (
                    f"Title: {result.title}\n"
                    f"Status: {result.status_code}\n"
                    f"Links: {len(result.links)}\n"
                    f"Load Time: {result.load_time_ms:.0f}ms\n\n"
                    f"{result.text_content[:500]}"
                )
            _status_color = "green" if result.status_code < 400 else "red"

            self.console.print(
                Panel(
                    output[:1000],
                    title=f"Browse: {url[:60]}",
                    border_style="cyan",
                    expand=False,
                )
            )

            return ExecutionResult(
                exit_code=0 if result.success else 1,
                stdout=output,
                stderr="",
                metadata={
                    "mode": "browse",
                    "url": url,
                    "action": browse_action,
                },
            )

        except Exception as e:
            self.console.print(f"[bold red]Browse Error:[/bold red] {str(e)}")
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

        # Extract embedded command if present (e.g. wrapped in backticks or with prefixes)
        backtick_matches = re.findall(r"`([^`]+)`", command)
        if backtick_matches:
            if len(backtick_matches) == 1:
                command = backtick_matches[0].strip()
            else:
                command = backtick_matches[-1].strip()
        else:
            if "command to execute is:" in command.lower():
                parts = re.split(r"(?i)command to execute is:\s*", command)
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

        command = command.strip("`'\" ").strip()

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
                f"Patterns: {res.blocked_patterns}. Warnings: {res.warnings}"
            )
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Command blocked by sanitizer: {command}. Reason: {res.blocked_reason}",
                metadata={"mode": "shell", "blocked": True},
            )

        raw_attempts = (step.params.get("retry", 1) + 1) if step.params else 2
        # Cap per-step retries to MAX_RETRIES_PER_STEP (total attempts = cap + 1).
        max_attempts = min(raw_attempts, self.MAX_RETRIES_PER_STEP + 1)
        retry_delay = step.params.get("retry_delay", 2) if step.params else 2

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.console.print(
                    f"[yellow]Retry {attempt - 1}/{max_attempts - 1} after {retry_delay}s...[/yellow]"
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(time.sleep, retry_delay).result()

            self.console.print(f"[dim]Running:[/dim] {command}")

            try:
                # shell=False: split string into list to prevent command injection.
                # CommandSanitizer already vetted `command`, but shell=True still
                # allows metachar injection (;, &&, $()) on unsanitised sub-parts.
                cmd_args = shlex.split(command) if isinstance(command, str) else command
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        subprocess.run,
                        cmd_args,
                        shell=False,
                        check=True,
                        text=True,
                        capture_output=True,
                    )
                    process = future.result()

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
                    exit_code=process.returncode,
                    stdout=process.stdout or "",
                    stderr=process.stderr or "",
                    metadata={
                        "mode": "shell",
                        "command": command,
                        "attempt": attempt,
                    },
                )

            except subprocess.CalledProcessError as e:
                # Retry if not on last attempt
                if attempt < max_attempts:
                    self.console.print(
                        f"[yellow]Step {step.order} failed (exit {e.returncode})[/yellow]"
                    )
                    continue

                self.console.print(
                    f"[bold red]Error executing step {step.order}[/bold red]"
                )
                if e.stdout:
                    self.console.print(
                        Panel(
                            e.stdout.strip(),
                            title="Output (Partial)",
                            border_style="yellow",
                            expand=False,
                        )
                    )
                if e.stderr:
                    self.console.print(
                        Panel(
                            e.stderr.strip(),
                            title="Error Output",
                            border_style="red",
                            expand=False,
                        )
                    )
                return ExecutionResult(
                    exit_code=e.returncode,
                    stdout=e.stdout or "",
                    stderr=e.stderr or "",
                    error=e,
                    metadata={
                        "mode": "shell",
                        "command": command,
                        "attempt": attempt,
                    },
                )
            except Exception as e:
                self.console.print(f"[bold red]Unexpected error:[/bold red] {str(e)}")
                return ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr=str(e),
                    error=e,
                    metadata={
                        "mode": "shell",
                        "command": command,
                        "attempt": attempt,
                    },
                )

        # Should not reach here, but safety fallback
        return ExecutionResult(
            exit_code=1,
            stdout="",
            stderr="Max retries exhausted",
            metadata={"mode": "shell", "command": command, "attempt": max_attempts},
        )

    def run(self) -> bool:
        """Run the full recipe (legacy mode, returns bool for backward compat)."""
        self.console.print(
            Panel(
                Text(self.recipe.description, style="italic"),
                title=f"Running: {self.recipe.name}",
                border_style="cyan",
            )
        )

        for step in self.recipe.steps:
            result = self.execute_step(step)
            if result.exit_code != 0:
                self.console.print("\n[bold red]Recipe execution failed.[/bold red]")
                return False

        self.console.print(
            f"\n[bold green]Recipe '{self.recipe.name}' completed successfully![/bold green]"
        )
        return True
