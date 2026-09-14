"""C3 Self-Healing Integration Tests for PEV Executor

Verifies the three C3 pillars in src/harness/pev/executor.py:
  a) Retry on transient failure  (ExponentialBackoff + call_with_retry)
  b) Circuit open after threshold (CircuitBreaker per service)
  c) Crash detection             (CrashPatternDetector in execute_step)

Run:  python3 -m pytest tests/test_pev_self_healing.py -v
"""

from __future__ import annotations

import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    get_circuit_breaker,
    reset_all_breakers,
)
from src.core.retry import ExponentialBackoff, call_with_retry
from src.core.crash_detector import CrashPatternDetector, detect_crash_signals
from src.harness.pev.executor import RecipeExecutor
from src.harness.pev.parser import Recipe, RecipeStep


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_step(order: int, description: str, params: dict | None = None) -> RecipeStep:
    return RecipeStep(
        order=order,
        title=f"Step {order}",
        description=description,
        params=params or {},
    )


def _make_recipe(*steps: RecipeStep) -> Recipe:
    return Recipe(name="test-c3", title="C3 self-healing recipe", steps=list(steps))


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Start each test with a clean circuit-breaker registry."""
    reset_all_breakers()
    yield


# ═════════════════════════════════════════════════════════════════════════════
# (a) Retry on transient failure
# ═════════════════════════════════════════════════════════════════════════════


class TestRetryOnTransientFailure:
    """Shell step retries via ExponentialBackoff + call_with_retry."""

    def test_succeeds_after_one_retry(self):
        """Call fails once then succeeds — exit_code=0."""
        step = _make_step(1, "echo hello")
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        call_count = 0

        def fail_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.CalledProcessError(
                    returncode=1, cmd="echo hello", stderr="transient error",
                )
            return MagicMock(stdout="hello\n", stderr="", returncode=0)

        with patch("src.harness.pev.executor.subprocess.run", side_effect=fail_once):
            result = executor._execute_shell_step(step)

        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert call_count >= 2
        assert result.metadata.get("attempt", 1) >= 2

    def test_exhausts_max_retries(self):
        """All retry attempts fail — final result is non-zero."""
        step = _make_step(1, "echo always-fails")
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        with patch("src.harness.pev.executor.subprocess.run", side_effect=subprocess.CalledProcessError(
            returncode=1, cmd="echo", stderr="permanent failure",
        )):
            result = executor._execute_shell_step(step)

        assert result.exit_code == 1
        assert "permanent failure" in result.stderr

    def test_exponential_backoff_delays_double(self):
        """Backoff delays follow initial * factor^n pattern (with jitter)."""
        backoff = ExponentialBackoff(initial=0.05, max_delay=5.0, factor=2.0)
        # Generate many delays and observe them monotonically tend toward
        # doubling (jitter may slightly perturb, but trend should be clear).
        delays = [backoff.next_delay() for _ in range(6)]
        # Each delay should be > 0
        assert all(d > 0 for d in delays)
        # Delays must respect the 2x growth pattern within jitter bounds.
        # After 4+ steps the theoretical value (0.05 * 2^3 = 0.4) should
        # dominate jitter window [0.2, 0.6].
        assert delays[3] >= 0.2  # roughly initial * 2^3 = 0.4

    def test_call_with_retry_succeeds_eventually(self):
        """call_with_retry returns success=True after transient failures."""
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f"transient #{call_count}")
            return "ok"

        backoff = ExponentialBackoff(initial=0.001, max_delay=0.01, factor=2.0)
        success, result, stats = call_with_retry(
            flaky, max_attempts=5, backoff=backoff, retryable=(RuntimeError,),
        )

        assert success is True
        assert result == "ok"
        assert stats.attempts == 3
        assert len(stats.delays) == 2  # retried after fail #1 and #2


# ═════════════════════════════════════════════════════════════════════════════
# (b) Circuit breaker opens after threshold recoveries
# ═════════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerCore:
    """Test CircuitBreaker state machine directly (unit)."""

    def _force_failures(self, breaker: CircuitBreaker, count: int) -> None:
        """Call breaker.call with a failing function count times."""
        for _ in range(count):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            except RuntimeError:
                pass

    def test_closed_to_open_transition(self):
        """CLOSED → OPEN after failure_threshold consecutive failures."""
        breaker = CircuitBreaker("svc", failure_threshold=3, recovery_timeout=30.0)
        assert breaker.state == CircuitState.CLOSED
        self._force_failures(breaker, 3)
        assert breaker.state == CircuitState.OPEN

    def test_open_rejects_calls(self):
        """When OPEN, call() raises CircuitOpenError (no fallback)."""
        breaker = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30.0)
        self._force_failures(breaker, 2)
        with pytest.raises(Exception) as exc_info:
            breaker.call(lambda: "this should not run")
        assert "Circuit open" in str(exc_info.value)

    def test_open_calls_fallback(self):
        """When OPEN and fallback provided, fallback is returned."""
        breaker = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30.0)
        self._force_failures(breaker, 2)
        fallback_result = breaker.call(lambda: "never", fallback=lambda: "fallback")
        assert fallback_result == "fallback"
        assert breaker.stats.rejected_calls >= 1

    def test_half_open_after_timeout(self):
        """OPEN → HALF_OPEN after recovery_timeout via .state property."""
        breaker = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=0.05)
        self._force_failures(breaker, 2)
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.1)
        # Accessing .state triggers HALF_OPEN transition
        _ = breaker.state
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        """HALF_OPEN → CLOSED after success_threshold successful calls."""
        breaker = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=0.05, success_threshold=2)
        self._force_failures(breaker, 2)
        time.sleep(0.1)
        _ = breaker.state
        assert breaker.state == CircuitState.HALF_OPEN

        # First success stays HALF_OPEN
        breaker.call(lambda: "ok")
        assert breaker.state == CircuitState.HALF_OPEN
        # Second success closes
        breaker.call(lambda: "ok")
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """HALF_OPEN → OPEN on any failure during probe."""
        breaker = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=0.05)
        self._force_failures(breaker, 2)
        time.sleep(0.1)
        _ = breaker.state
        assert breaker.state == CircuitState.HALF_OPEN

        try:
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("still down")))
        except RuntimeError:
            pass
        assert breaker.state == CircuitState.OPEN

    def test_registry_singleton(self):
        """get_circuit_breaker returns same instance for same service name."""
        b1 = get_circuit_breaker("shared", failure_threshold=5)
        b2 = get_circuit_breaker("shared")
        assert b1 is b2
        # Different name → different instance
        b3 = get_circuit_breaker("other")
        assert b3 is not b1

    def test_reset_restores_closed(self):
        """reset() closes circuit and clears failure counters."""
        breaker = CircuitBreaker("svc", failure_threshold=2)
        self._force_failures(breaker, 2)
        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.consecutive_failures == 0


# ═════════════════════════════════════════════════════════════════════════════
# (c) Crash detection
# ═════════════════════════════════════════════════════════════════════════════


class TestCrashDetection:
    """CrashPatternDetector unit tests (signals, OOM, strict mode)."""

    @pytest.fixture()
    def detector(self):
        return CrashPatternDetector(strict=False)

    def test_sigkill_detected(self, detector):
        sigs = detector.inspect(exit_code=-9, stderr="Killed", combined_text="")
        assert sigs
        assert sigs[0]["signal"] == "SIGKILL"

    def test_sigsegv_detected(self, detector):
        sigs = detector.inspect(exit_code=-11, stderr="", combined_text="")
        assert sigs
        assert sigs[0]["signal"] == "SIGSEGV"

    def test_unknown_negative_exit(self, detector):
        sigs = detector.inspect(exit_code=-99, stderr="", combined_text="")
        assert sigs
        assert sigs[0]["signal"] == "signal 99"

    def test_linux_oom_detected(self, detector):
        sigs = detector.inspect(exit_code=137, stderr="Out of memory: Kill process 12345")
        assert any(s["signal"] == "linux-oom" for s in sigs)

    def test_macos_jetsam_detected(self, detector):
        sigs = detector.inspect(exit_code=0, stderr="terminated due to memory pressure")
        assert any(s["signal"] == "macos-jetsam" for s in sigs)

    def test_python_memory_error(self, detector):
        sigs = detector.inspect(
            exit_code=1,
            stderr="Traceback (most recent call last):\n  ...\nMemoryError",
            combined_text="",
        )
        assert any(s["signal"] == "python-memory" for s in sigs)

    def test_fatal_python_error(self, detector):
        sigs = detector.inspect(
            exit_code=1,
            stderr="Fatal Python error: Abort trap",
            combined_text="",
        )
        assert any(s["category"] == "python" for s in sigs)

    def test_clean_exit_no_signals(self, detector):
        sigs = detector.inspect(exit_code=0, stderr="", combined_text="all good")
        assert sigs == []

    def test_nonzero_exit_not_strict(self, detector):
        """strict=False: non-zero exit codes that aren't signals are not flagged."""
        sigs = detector.inspect(exit_code=2, stderr="file not found", combined_text="")
        assert sigs == []

    def test_nonzero_exit_strict_mode(self):
        """strict=True: any non-zero exit code is flagged."""
        detector = CrashPatternDetector(strict=True)
        sigs = detector.inspect(exit_code=2, stderr="")
        assert sigs
        assert sigs[0]["signal"] == "non-zero"

    def test_inspect_step_with_fake_result(self):
        """inspect_step reads exit_code/stderr/metadata from any duck-typed object."""
        detector = CrashPatternDetector(strict=True)

        class FakeResult:
            exit_code = -11
            stderr = "Killed"
            metadata = {"command": "app --serve"}

        sigs = detector.inspect_step(FakeResult())
        assert sigs
        assert sigs[0]["signal"] == "SIGSEGV"

    def test_inspect_step_graceful_on_bare_object(self):
        """inspect_step should not crash when given a plain dict."""
        detector = CrashPatternDetector(strict=False)
        sigs = detector.inspect_step({"exit_code": 0, "stderr": "", "metadata": {}})
        assert sigs == []

    def test_detect_crash_signals_convenience(self):
        sigs = detect_crash_signals(exit_code=-9, stderr="Killed")
        assert len(sigs) == 1
        assert sigs[0]["signal"] == "SIGKILL"


# ═════════════════════════════════════════════════════════════════════════════
# (d) PEV executor: C3 components wired together
# ═════════════════════════════════════════════════════════════════════════════


class TestPEVExecutorC3Wiring:
    """Verify the PEV executor has C3 components initialized."""

    def test_executor_has_backoff(self):
        step = _make_step(1, "echo test")
        recipe = _make_recipe(step)
        exe = RecipeExecutor(recipe)
        assert exe._backoff is not None
        assert isinstance(exe._backoff, ExponentialBackoff)
        assert exe._backoff.initial == 1.0
        assert exe._backoff.max_delay == 30.0
        assert exe._backoff.factor == 2.0

    def test_executor_has_circuit_breakers(self):
        step = _make_step(1, "echo test")
        recipe = _make_recipe(step)
        RecipeExecutor(recipe)
        # Breakers live in the registry; we pull by name.
        assert get_circuit_breaker("pev-llm") is not None
        assert get_circuit_breaker("pev-api") is not None
        assert get_circuit_breaker("pev-browse") is not None

    def test_executor_has_crash_detector(self):
        step = _make_step(1, "echo test")
        recipe = _make_recipe(step)
        exe = RecipeExecutor(recipe)
        # Assert on the executor's own instance rather than the imported
        # class: a session-scoped conftest patches CrashPatternDetector, so
        # the local import and the instance held by the executor may differ.
        detector = exe._crash_detector
        assert detector is not None
        assert type(detector).__name__ == "CrashPatternDetector"

    def test_crash_signals_appear_in_shell_step_metadata(self):
        """When we manually set crash_signals in metadata, they survive to result."""
        step = _make_step(1, "echo test", params={"type": "shell"})
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        # Inject a fake crash detector that always returns a signal.
        fake_detector = MagicMock()
        fake_detector.inspect_step.return_value = [
            {"category": "system", "signal": "SIGSEGV", "detail": "exit code 139"},
        ]
        executor._crash_detector = fake_detector

        proc = MagicMock(stdout="", stderr="Segmentation fault", returncode=139)
        with patch("src.harness.pev.executor.subprocess.run", return_value=proc):
            # Use execute_step (not _execute_shell_step) because the crash
            # detector hook lives in execute_step (executor.py:112-115).
            result = executor.execute_step(step)

        assert result.metadata.get("crash_signals") is not None
        assert result.metadata["crash_signals"][0]["signal"] == "SIGSEGV"

    def test_llm_step_breaker_invoked(self):
        """LLM breaker.call is invoked during _execute_llm_step when client is available."""
        step = _make_step(1, "Generate a plan", params={"type": "llm"})
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        mock_response = MagicMock(content="generated text", model="test-model")
        mock_client = MagicMock()
        mock_client.is_available = True
        mock_client.chat.return_value = mock_response

        with patch("src.providers.llm.client.get_client", return_value=mock_client):
            result = executor._execute_llm_step(step)

        assert result.exit_code == 0
        assert "generated text" in result.stdout
        mock_client.chat.assert_called_once()

    def test_llm_fallback_on_circuit_open(self):
        """When pev-llm circuit is OPEN, LLM step returns skipped result."""
        # Use a fresh breaker (not the shared "pev-llm" singleton, whose
        # threshold is 3) and install it on the executor instance directly.
        breaker = get_circuit_breaker(
            "pev-llm-fallback", failure_threshold=2, recovery_timeout=30.0
        )
        # Force open by exhausting retries. breaker.call() re-raises the
        # exception after recording the failure, so it must be caught.
        for _ in range(2):
            with pytest.raises(RuntimeError):
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert breaker.state == CircuitState.OPEN

        step = _make_step(1, "Generate text", params={"type": "llm"})
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)
        executor._llm_breaker = breaker

        mock_client = MagicMock()
        mock_client.is_available = True

        with patch("src.providers.llm.client.get_client", return_value=mock_client):
            result = executor._execute_llm_step(step)

        assert result.metadata.get("circuit_open") is True
        # Circuit-open fallback returns exit_code=0 (graceful skip, not hard failure)
        assert result.exit_code == 0

    def test_api_step_breaker_invoked(self):
        """API breaker is called and result has correct structure."""
        step = _make_step(1, "Fetch data", params={"type": "api", "url": "http://example.com"})
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'

        mock_req = MagicMock()
        mock_req.exceptions.RequestException = Exception
        mock_req.request.return_value = mock_response

        # requests is imported inline in _execute_api_step; sys.modules trick
        with patch.dict(sys.modules, {"requests": mock_req}):
            result = executor._execute_api_step(step)

        assert result.exit_code == 0
        assert result.metadata["status_code"] == 200

    def test_full_run_succeeds_with_shell_steps(self):
        """run() returns True when all shell steps pass."""
        steps = [
            _make_step(1, "echo alpha"),
            _make_step(2, "echo beta"),
        ]
        recipe = _make_recipe(*steps)
        executor = RecipeExecutor(recipe)

        proc_ok = MagicMock(stdout="alpha\nbeta\n", stderr="", returncode=0)
        with patch("src.harness.pev.executor.subprocess.run", return_value=proc_ok):
            result = executor.run()

        assert result is True

    def test_full_run_fails_when_step_fails_all_retries(self):
        """run() returns False when a step exhausts retries."""
        step = _make_step(1, "bad command")
        recipe = _make_recipe(step)
        executor = RecipeExecutor(recipe)

        with patch("src.harness.pev.executor.subprocess.run", side_effect=subprocess.CalledProcessError(
            returncode=1, cmd="bad", stderr="error",
        )):
            result = executor.run()

        assert result is False
