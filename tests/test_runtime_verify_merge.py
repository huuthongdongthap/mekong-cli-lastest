# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for Gap #4 (SC8) Phase 1 — merge RecipeVerifier into core runtime verify().

The core ``MekongCoreRuntimeImpl.verify()`` now delegates to ``RecipeVerifier``
via the adapter helpers ``_criteria_to_verification_dict`` and
``_report_to_verification``. These tests prove:

1. Core CheckSpec kinds map to the correct verifier verdicts.
2. The verifier is actually invoked (wiring test, not reimplementation).
3. Empty criteria falls back to the legacy no-error-means-pass behavior.
4. ``VerificationReport.errors`` surface as ``Verification.failures``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.runtime_adapter import (
    CheckSpec,
    Criteria,
    MekongCoreRuntimeImpl,
    Observation,
    Result,
    Verification,
    _ExecResultLike,
    _criteria_to_verifier_dict,
    _report_to_verification,
)
from src.core.verifier import (
    RecipeVerifier,
    VerificationCheck,
    VerificationReport,
    VerificationStatus,
)


class _FakeDispatcher:
    def dispatch(self, task, agent=None):  # noqa: ANN001, ANN202
        return {"status": "noop", "task_id": task.id}


def _make_runtime(*, verifier=None) -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=_FakeDispatcher(),
        tool_registry=None,
        memory_store=None,
        billing=None,
        telemetry=None,
        llm_router=None,
        capability_bus=None,
        agent_id="test",
        verifier=verifier,
    )


def _observation(*, output=None, error=None, metadata=None) -> Observation:
    return Observation(
        result=Result(task_id="t-1", output=output, error=error, metadata=metadata or {}),
    )


# ---------------------------------------------------------------------------
# 1. exit_code pass/fail
# ---------------------------------------------------------------------------


class TestVerifyExitCode:
    def test_exit_code_pass(self):
        """exit_code expected=0, observation with no error → passed."""
        rt = _make_runtime()
        criteria = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        obs = _observation(output="ok", error=None)
        v = rt.verify(obs, criteria)
        assert isinstance(v, Verification)
        assert v.passed is True
        assert len(v.checks) == 1
        assert v.checks[0].check.kind == "exit_code"
        assert v.checks[0].passed is True

    def test_exit_code_fail(self):
        """observation with error=boom → passed=False, failure mentions exit code mismatch."""
        rt = _make_runtime()
        criteria = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        obs = _observation(error="boom")
        v = rt.verify(obs, criteria)
        assert v.passed is False
        assert len(v.checks) == 1
        assert v.checks[0].check.kind == "exit_code"
        assert v.checks[0].passed is False
        assert v.failures
        # Verifier emits "Exit code mismatch: expected 0, got 1".
        assert "Exit code mismatch" in v.failures[0]


# ---------------------------------------------------------------------------
# 2. output_pattern
# ---------------------------------------------------------------------------


class TestVerifyOutputPattern:
    def test_output_pattern_matching_passes(self):
        rt = _make_runtime()
        criteria = Criteria(checks=[CheckSpec(kind="output_pattern", params={"pattern": "OK"})])
        obs = _observation(output="OK done")
        v = rt.verify(obs, criteria)
        assert v.passed is True
        assert v.checks[0].passed is True

    def test_output_pattern_not_matching_fails(self):
        rt = _make_runtime()
        criteria = Criteria(checks=[CheckSpec(kind="output_pattern", params={"pattern": "OK"})])
        obs = _observation(output="no")
        v = rt.verify(obs, criteria)
        assert v.passed is False
        assert v.checks[0].passed is False


# ---------------------------------------------------------------------------
# 3. empty criteria fallback
# ---------------------------------------------------------------------------


class TestVerifyEmptyCriteriaFallback:
    def test_empty_criteria_no_error_passes(self):
        """Empty Criteria → passed iff no error (legacy parity)."""
        rt = _make_runtime()
        criteria = Criteria(checks=[])
        obs = _observation(output="anything", error=None)
        v = rt.verify(obs, criteria)
        assert v.passed is True

    def test_empty_criteria_with_error_fails(self):
        rt = _make_runtime()
        criteria = Criteria(checks=[])
        obs = _observation(error="broken")
        v = rt.verify(obs, criteria)
        assert v.passed is False


# ---------------------------------------------------------------------------
# 4. wiring — mock verifier proves delegation
# ---------------------------------------------------------------------------


class TestVerifyUsesRecipeVerifier:
    def test_verify_calls_injected_verifier(self):
        """mock_verifier.verify is called with an object whose exit_code matches."""
        mock_verifier = MagicMock(spec=RecipeVerifier)
        mock_verifier.verify.return_value = VerificationReport(
            passed=True,
            checks=[
                VerificationCheck(
                    name="exit_code",
                    status=VerificationStatus.PASSED,
                    message="ok",
                )
            ],
        )
        rt = _make_runtime(verifier=mock_verifier)
        criteria = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        obs = _observation(output="x", error=None)
        v = rt.verify(obs, criteria)
        assert v.passed is True
        mock_verifier.verify.assert_called_once()
        args, _kwargs = mock_verifier.verify.call_args
        exec_result_like = args[0]
        assert isinstance(exec_result_like, _ExecResultLike)
        # No error → exit_code 0.
        assert exec_result_like.exit_code == 0
        assert exec_result_like.stdout == "x"

    def test_verify_routes_error_to_exit_code_1(self):
        """error present → exec_result.exit_code == 1 (failed dispatch convention)."""
        mock_verifier = MagicMock(spec=RecipeVerifier)
        mock_verifier.verify.return_value = VerificationReport(
            passed=False,
            checks=[
                VerificationCheck(
                    name="exit_code",
                    status=VerificationStatus.FAILED,
                    message="boom",
                )
            ],
            errors=["boom"],
        )
        rt = _make_runtime(verifier=mock_verifier)
        criteria = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        obs = _observation(error="boom")
        rt.verify(obs, criteria)
        args, _kwargs = mock_verifier.verify.call_args
        exec_result_like = args[0]
        assert exec_result_like.exit_code == 1
        assert exec_result_like.stderr == "boom"


# ---------------------------------------------------------------------------
# 5. report errors surface as Verification.failures
# ---------------------------------------------------------------------------


class TestVerifyReportErrorsSurface:
    def test_report_errors_propagate_to_failures(self):
        """VerificationReport with errors=["x"] → Verification.failures == ["x"]."""
        mock_verifier = MagicMock(spec=RecipeVerifier)
        mock_verifier.verify.return_value = VerificationReport(
            passed=False,
            checks=[
                VerificationCheck(
                    name="exit_code",
                    status=VerificationStatus.FAILED,
                    message="msg",
                )
            ],
            errors=["x"],
        )
        rt = _make_runtime(verifier=mock_verifier)
        criteria = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        obs = _observation(error="bad")
        v = rt.verify(obs, criteria)
        assert v.failures == ["x"]


# ---------------------------------------------------------------------------
# 6. adapter unit tests (helpers in isolation)
# ---------------------------------------------------------------------------


class TestCriteriaToVerifierDict:
    def test_exit_code_maps_to_scalar(self):
        d = _criteria_to_verifier_dict(
            Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
        )
        assert d == {"exit_code": 0}

    def test_output_pattern_maps_to_output_contains_list(self):
        d = _criteria_to_verifier_dict(
            Criteria(checks=[CheckSpec(kind="output_pattern", params={"pattern": "OK"})])
        )
        assert d == {"output_contains": ["OK"]}

    def test_file_exists_and_not_exists_mapping(self):
        d = _criteria_to_verifier_dict(
            Criteria(checks=[
                CheckSpec(kind="file_exists", params={"path": "/tmp/a.txt"}),
                CheckSpec(kind="file_not_exists", params={"filepath": "/tmp/b.txt"}),
                CheckSpec(kind="output_not_contains", params={"pattern": "ERROR"}),
            ])
        )
        assert d == {
            "file_exists": ["/tmp/a.txt"],
            "file_not_exists": ["/tmp/b.txt"],
            "output_not_contains": ["ERROR"],
        }

    def test_unknown_kind_skipped(self):
        d = _criteria_to_verifier_dict(
            Criteria(checks=[CheckSpec(kind="unknown_kind", params={"a": 1})])
        )
        assert d == {}


class TestReportToVerification:
    def test_passed_report_maps_clean(self):
        report = VerificationReport(
            passed=True,
            checks=[
                VerificationCheck(
                    name="exit_code",
                    status=VerificationStatus.PASSED,
                    message="ok",
                )
            ],
        )
        v = _report_to_verification(report)
        assert v.passed is True
        assert len(v.checks) == 1
        assert v.checks[0].check.kind == "exit_code"
        assert v.checks[0].passed is True
        assert v.failures == []

    def test_errors_become_failures(self):
        report = VerificationReport(passed=False, errors=["x", "y"])
        v = _report_to_verification(report)
        assert v.passed is False
        assert v.failures == ["x", "y"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
