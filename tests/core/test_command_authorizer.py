"""Tests for src/core/command_authorizer.py"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Env vars that `has_contribution_evidence()` reads. GitHub Actions sets
# GITHUB_EVENT_NAME=pull_request on PR runs, which would make the Core DNA
# gate pass when it must block. Clear them for the whole test.
_CONTRIBUTION_ENV_VARS = (
    "GITHUB_EVENT_NAME",
    "GITHUB_REF",
    "MEKONG_CONTRIBUTION_PR",
    "MEKONG_CONTRIBUTION_ISSUE",
)


@pytest.fixture(autouse=True)
def _clear_contribution_env():
    """Remove CI contribution-evidence env vars for deterministic gate tests."""
    snapshot = {k: os.environ.pop(k, None) for k in _CONTRIBUTION_ENV_VARS}
    yield
    for k, v in snapshot.items():
        if v is not None:
            os.environ[k] = v


def _make_authorizer(
    license_valid: bool = True,
    license_expired: bool = False,
    gateway_status: int = 200,
    gateway_data: dict | None = None,
    kv_state: str | None = None,
    license_key_env: str | None = "mk_test_key",
):
    """Build a CommandAuthorizer with all external deps mocked."""
    from src.core.command_authorizer import CommandAuthorizer

    # --- gateway client mock ---
    gateway = MagicMock()
    response = MagicMock()
    response.status_code = gateway_status
    response.data = gateway_data or {"tenant_id": "t1", "tier": "pro"}
    response.rate_limit_remaining = 999
    response.headers = {}
    gateway.get.return_value = response

    # --- auth client mock ---
    auth_client = MagicMock()

    # --- license manager mock ---
    license_manager = MagicMock()
    license_manager.is_valid.return_value = license_valid
    if license_valid:
        license_data = MagicMock()
        license_data.is_expired = license_expired
        license_data.expires_at = "2030-01-01T00:00:00+00:00" if not license_expired else "2020-01-01T00:00:00+00:00"
        license_data.license_key = "mk_test_key"
        license_manager.get_license.return_value = license_data
    else:
        license_manager.get_license.return_value = None

    # --- kv client mock ---
    kv_client = MagicMock()
    kv_client.get.return_value = kv_state
    kv_client.set.return_value = None

    env_patch = {"RAAS_LICENSE_KEY": license_key_env} if license_key_env else {}
    with (
        patch("src.core.command_authorizer.get_gateway_client", return_value=gateway),
        patch("src.core.command_authorizer.get_auth_client", return_value=auth_client),
        patch("src.core.command_authorizer.get_license_manager", return_value=license_manager),
        patch("src.core.command_authorizer.get_kv_client", return_value=kv_client),
        patch.dict("os.environ", env_patch, clear=False),
    ):
        authorizer = CommandAuthorizer(gateway_client=gateway)
        authorizer.auth_client = auth_client
        authorizer.license_manager = license_manager
        authorizer.kv_client = kv_client
        return authorizer, gateway, kv_client


# ---------------------------------------------------------------------------
# CommandTier / is_free_command / get_command_tier
# ---------------------------------------------------------------------------


class TestCommandTierMapping:
    def test_known_free_commands(self):
        authorizer, _, _ = _make_authorizer()
        for cmd in ["cook", "plan", "status", "health", "help", "version"]:
            assert authorizer.is_free_command(cmd), f"{cmd} should be FREE"

    def test_known_pro_commands(self):
        authorizer, _, _ = _make_authorizer()
        for cmd in ["deploy", "monitor", "review", "debug", "scout"]:
            assert not authorizer.is_free_command(cmd), f"{cmd} should not be FREE"

    def test_unknown_command_defaults_to_pro(self):
        authorizer, _, _ = _make_authorizer()
        from src.core.command_authorizer import CommandTier
        tier = authorizer.get_command_tier("totally-unknown-command-xyz")
        assert tier == CommandTier.PRO

    def test_enterprise_commands(self):
        authorizer, _, _ = _make_authorizer()
        from src.core.command_authorizer import CommandTier
        for cmd in ["license-admin", "tier-admin", "raas-maintenance"]:
            assert authorizer.get_command_tier(cmd) == CommandTier.ENTERPRISE


class TestCoreDnaGate:
    def test_unknown_local_command_blocked_before_license(self):
        authorizer, gateway, _ = _make_authorizer(license_valid=True)
        from src.core.command_authorizer import AuthorizationReason

        result = authorizer.authorize_command("private-local-updater")

        assert result.allowed is False
        assert result.reason == AuthorizationReason.CORE_DNA_BLOCKED
        assert "Core DNA" in result.message
        gateway.get.assert_not_called()

    def test_unknown_command_allowed_with_contribution_evidence(self):
        authorizer, gateway, _ = _make_authorizer(license_valid=True)

        with patch.dict("os.environ", {"MEKONG_CONTRIBUTION_PR": "123"}, clear=False):
            result = authorizer.authorize_command("community-feature")

        assert result.allowed is True
        assert result.tier == "pro"
        gateway.get.assert_called_once()


# ---------------------------------------------------------------------------
# authorize_command — FREE path
# ---------------------------------------------------------------------------


class TestAuthorizeFreeCommands:
    def test_free_command_allowed_without_license(self):
        authorizer, _, _ = _make_authorizer(license_valid=False)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("cook")
        assert result.allowed is True
        assert result.reason == AuthorizationReason.FREE_COMMAND

    def test_free_command_never_hits_gateway(self):
        authorizer, gateway, _ = _make_authorizer()
        authorizer.authorize_command("status")
        gateway.get.assert_not_called()

    def test_free_command_message_mentions_command(self):
        authorizer, _, _ = _make_authorizer()
        result = authorizer.authorize_command("help")
        assert "help" in result.message


# ---------------------------------------------------------------------------
# authorize_command — invalid license
# ---------------------------------------------------------------------------


class TestAuthorizeInvalidLicense:
    def test_blocked_when_no_valid_license_and_no_grace(self):
        authorizer, _, _ = _make_authorizer(license_valid=False, kv_state=None)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is False
        assert result.reason == AuthorizationReason.INVALID_LICENSE

    def test_grace_period_allows_when_invalid_license(self):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        state = json.dumps({"grace_until": future.isoformat()})
        authorizer, _, _ = _make_authorizer(license_valid=False, kv_state=state)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is True
        assert result.reason == AuthorizationReason.GRACE_PERIOD

    def test_enters_grace_period_on_invalid_license(self):
        authorizer, _, kv = _make_authorizer(license_valid=False, kv_state=None)
        authorizer.authorize_command("deploy")
        kv.set.assert_called_once_with("auth_grace_state", kv.set.call_args[0][1])


# ---------------------------------------------------------------------------
# authorize_command — gateway validation
# ---------------------------------------------------------------------------


class TestAuthorizeGatewayValidation:
    def test_allowed_when_gateway_200(self):
        authorizer, _, _ = _make_authorizer(gateway_status=200)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is True
        assert result.reason == AuthorizationReason.LICENSE_VALID

    def test_blocked_when_gateway_401(self):
        authorizer, _, _ = _make_authorizer(gateway_status=401)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is False
        assert result.reason == AuthorizationReason.INVALID_LICENSE

    def test_blocked_when_gateway_403(self):
        authorizer, _, _ = _make_authorizer(gateway_status=403)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is False
        assert result.reason == AuthorizationReason.EXPIRED_LICENSE

    def test_rate_limited_when_gateway_429(self):
        authorizer, _, _ = _make_authorizer(gateway_status=429)
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")
        assert result.allowed is False
        assert result.reason == AuthorizationReason.QUOTA_EXCEEDED

    def test_rate_limit_reset_in_set_on_429(self):
        authorizer, gateway, _ = _make_authorizer(gateway_status=429)
        import time
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {"X-RateLimit-Reset": str(int(time.time()) + 60)}
        resp.data = {}
        resp.rate_limit_remaining = 0
        gateway.get.return_value = resp
        result = authorizer.authorize_command("deploy")
        assert result.rate_limit_reset_in is not None
        assert result.rate_limit_reset_in >= 0

    def test_gateway_error_enters_grace_period(self):
        authorizer, gateway, kv = _make_authorizer(gateway_status=500)
        from src.core.command_authorizer import GatewayValidationError, AuthorizationReason
        # Raise a GatewayValidationError to simulate gateway being down
        gateway.get.side_effect = GatewayValidationError("server error")
        # Use a FREE command so tier-check is bypassed; grace allows free commands
        # For a PRO command the gateway result has tier=None → "free" → INSUFFICIENT_TIER
        # Test the grace period path via a free command that still hits gateway
        # (only PRO commands reach gateway validation)
        # Use validate_with_gateway directly to test grace period logic
        result = authorizer._validate_with_gateway("mk_test_key")
        assert result.allowed is True
        assert result.reason == AuthorizationReason.GRACE_PERIOD

    def test_gateway_error_pro_command_gets_insufficient_tier_from_grace(self):
        authorizer, gateway, kv = _make_authorizer(gateway_status=500)
        from src.core.command_authorizer import GatewayValidationError, AuthorizationReason
        gateway.get.side_effect = GatewayValidationError("server error")
        # PRO command: grace period gives tier=None → "free" → INSUFFICIENT_TIER
        result = authorizer.authorize_command("deploy")
        # Grace period returns allowed=True but tier is None (free) → insufficient for PRO
        assert result.allowed is False
        assert result.reason == AuthorizationReason.INSUFFICIENT_TIER


# ---------------------------------------------------------------------------
# authorize_command — cache
# ---------------------------------------------------------------------------


class TestAuthorizationCache:
    def test_cache_prevents_second_gateway_call(self):
        authorizer, gateway, _ = _make_authorizer(gateway_status=200)
        authorizer.authorize_command("deploy")
        authorizer.authorize_command("deploy")
        # Gateway should only be called once; second call uses cache
        assert gateway.get.call_count == 1

    def test_expired_cache_calls_gateway_again(self):
        authorizer, gateway, _ = _make_authorizer(gateway_status=200)
        # Set last_validated_at to 2 minutes ago (TTL is 60s)
        authorizer._last_validated_at = datetime.now(timezone.utc) - timedelta(seconds=121)
        authorizer._last_validation_result = MagicMock(allowed=True)
        authorizer.authorize_command("deploy")
        assert gateway.get.call_count == 1  # forced re-validate


# ---------------------------------------------------------------------------
# authorize_command — tier check
# ---------------------------------------------------------------------------


class TestAuthorizeTierCheck:
    def test_insufficient_tier_blocked(self):
        # Gateway returns "free" tier but command requires "pro"
        authorizer, _, _ = _make_authorizer(
            gateway_status=200,
            gateway_data={"tenant_id": "t1", "tier": "free"},
        )
        from src.core.command_authorizer import AuthorizationReason
        result = authorizer.authorize_command("deploy")  # deploy is PRO
        assert result.allowed is False
        assert result.reason == AuthorizationReason.INSUFFICIENT_TIER

    def test_sufficient_tier_allowed(self):
        authorizer, _, _ = _make_authorizer(
            gateway_status=200,
            gateway_data={"tenant_id": "t1", "tier": "pro"},
        )
        result = authorizer.authorize_command("deploy")
        assert result.allowed is True

    def test_enterprise_tier_allows_pro_commands(self):
        authorizer, _, _ = _make_authorizer(
            gateway_status=200,
            gateway_data={"tenant_id": "t1", "tier": "enterprise"},
        )
        result = authorizer.authorize_command("deploy")
        assert result.allowed is True


# ---------------------------------------------------------------------------
# authorize_command — missing license key
# ---------------------------------------------------------------------------


class TestAuthorizeMissingKey:
    def test_blocked_when_no_env_key_and_no_manager_key(self):
        from src.core.command_authorizer import CommandAuthorizer, AuthorizationReason

        gateway = MagicMock()
        auth_client = MagicMock()
        license_manager = MagicMock()
        license_manager.is_valid.return_value = True
        lic = MagicMock()
        lic.is_expired = False
        lic.license_key = None  # no key from manager
        license_manager.get_license.return_value = lic
        kv_client = MagicMock()
        kv_client.get.return_value = None

        with (
            patch("src.core.command_authorizer.get_gateway_client", return_value=gateway),
            patch("src.core.command_authorizer.get_auth_client", return_value=auth_client),
            patch("src.core.command_authorizer.get_license_manager", return_value=license_manager),
            patch("src.core.command_authorizer.get_kv_client", return_value=kv_client),
            patch.dict("os.environ", {}, clear=True),
        ):
            authorizer = CommandAuthorizer(gateway_client=gateway)
            authorizer.auth_client = auth_client
            authorizer.license_manager = license_manager
            authorizer.kv_client = kv_client
            result = authorizer.authorize_command("deploy")

        assert result.allowed is False
        assert result.reason == AuthorizationReason.INVALID_LICENSE


# ---------------------------------------------------------------------------
# _check_grace_period
# ---------------------------------------------------------------------------


class TestCheckGracePeriod:
    def test_returns_false_when_no_state(self):
        authorizer, _, kv = _make_authorizer()
        kv.get.return_value = None
        in_grace, remaining = authorizer._check_grace_period("deploy")
        assert in_grace is False
        assert remaining is None

    def test_returns_false_when_grace_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        state = json.dumps({"grace_until": past.isoformat()})
        authorizer, _, kv = _make_authorizer(kv_state=state)
        kv.get.return_value = state
        in_grace, remaining = authorizer._check_grace_period("deploy")
        assert in_grace is False

    def test_returns_true_within_grace_period(self):
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        state = json.dumps({"grace_until": future.isoformat()})
        authorizer, _, kv = _make_authorizer(kv_state=state)
        kv.get.return_value = state
        in_grace, remaining = authorizer._check_grace_period("deploy")
        assert in_grace is True
        assert remaining is not None
        assert remaining > 0

    def test_returns_false_on_corrupt_kv_state(self):
        authorizer, _, kv = _make_authorizer()
        kv.get.return_value = "not-valid-json{{"
        in_grace, remaining = authorizer._check_grace_period("deploy")
        assert in_grace is False


# ---------------------------------------------------------------------------
# _enter_grace_period
# ---------------------------------------------------------------------------


class TestEnterGracePeriod:
    def test_writes_grace_state_to_kv(self):
        authorizer, _, kv = _make_authorizer()
        authorizer._enter_grace_period(hours=24)
        kv.set.assert_called_once()
        key, value = kv.set.call_args[0]
        assert key == "auth_grace_state"
        parsed = json.loads(value)
        assert "grace_until" in parsed

    def test_grace_state_reason_network_error_for_long_grace(self):
        authorizer, _, kv = _make_authorizer()
        authorizer._enter_grace_period(hours=24)
        _, value = kv.set.call_args[0]
        parsed = json.loads(value)
        assert parsed["reason"] == "network_error"

    def test_grace_state_reason_invalid_license_for_short_grace(self):
        authorizer, _, kv = _make_authorizer()
        authorizer._enter_grace_period(hours=1)
        _, value = kv.set.call_args[0]
        parsed = json.loads(value)
        assert parsed["reason"] == "invalid_license"

    def test_enter_grace_period_silently_handles_kv_error(self):
        authorizer, _, kv = _make_authorizer()
        kv.set.side_effect = Exception("kv down")
        # Should not raise
        authorizer._enter_grace_period(hours=24)


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


class TestRecordUsage:
    def test_does_not_record_blocked_command(self):
        authorizer, _, _ = _make_authorizer()
        from src.core.command_authorizer import AuthorizationResult, AuthorizationReason
        result = AuthorizationResult(allowed=False, reason=AuthorizationReason.INVALID_LICENSE)
        with patch("src.core.command_authorizer.logger"):
            authorizer.record_usage("deploy", result)
            # No emit call should happen; verify by checking no usage import crash

    def test_records_allowed_command(self):
        authorizer, _, _ = _make_authorizer()
        from src.core.command_authorizer import AuthorizationResult, AuthorizationReason
        result = AuthorizationResult(allowed=True, reason=AuthorizationReason.FREE_COMMAND)
        with patch("src.core.command_authorizer.logger"):
            # Should not raise even if usage_auto_instrument is missing
            authorizer.record_usage("cook", result)


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_includes_required_keys(self):
        authorizer, _, _ = _make_authorizer()
        status = authorizer.get_status()
        for key in ["license_valid", "in_grace_period", "grace_period_remaining_hours",
                    "last_validated_at", "cache_ttl_seconds"]:
            assert key in status

    def test_last_validated_at_none_initially(self):
        authorizer, _, _ = _make_authorizer()
        status = authorizer.get_status()
        assert status["last_validated_at"] is None

    def test_last_validated_at_set_after_validation(self):
        authorizer, _, _ = _make_authorizer(gateway_status=200)
        authorizer.authorize_command("deploy")
        status = authorizer.get_status()
        assert status["last_validated_at"] is not None


# ---------------------------------------------------------------------------
# get_authorizer / reset_authorizer
# ---------------------------------------------------------------------------


class TestGlobalAuthorizer:
    def test_get_authorizer_singleton(self):
        from src.core.command_authorizer import get_authorizer, reset_authorizer
        with (
            patch("src.core.command_authorizer.get_gateway_client"),
            patch("src.core.command_authorizer.get_auth_client"),
            patch("src.core.command_authorizer.get_license_manager"),
            patch("src.core.command_authorizer.get_kv_client"),
        ):
            reset_authorizer()
            a1 = get_authorizer()
            a2 = get_authorizer()
            assert a1 is a2

    def test_reset_clears_singleton(self):
        from src.core.command_authorizer import get_authorizer, reset_authorizer
        with (
            patch("src.core.command_authorizer.get_gateway_client"),
            patch("src.core.command_authorizer.get_auth_client"),
            patch("src.core.command_authorizer.get_license_manager"),
            patch("src.core.command_authorizer.get_kv_client"),
        ):
            a1 = get_authorizer()
            reset_authorizer()
            a2 = get_authorizer()
            assert a1 is not a2


# ---------------------------------------------------------------------------
# AuthorizationResult / CommandConfig dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_authorization_result_defaults(self):
        from src.core.command_authorizer import AuthorizationResult, AuthorizationReason
        r = AuthorizationResult(allowed=True, reason=AuthorizationReason.FREE_COMMAND)
        assert r.message is None
        assert r.is_cached is False

    def test_command_config_defaults(self):
        from src.core.command_authorizer import CommandConfig, CommandTier
        cfg = CommandConfig(tier=CommandTier.PRO)
        assert cfg.requires_license is True
        assert cfg.rate_limit_weight == 1
        assert cfg.timeout_seconds == 30
