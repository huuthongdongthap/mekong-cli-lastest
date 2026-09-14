# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Buzz Adapter — v0.1 integration between Buzz goals and MekongCoreRuntime.

Receives goal payloads from Buzz, parses them into runtime-compatible dicts,
and sends status updates back. No Buzz hardcoding — protocol-driven.

Outbound updates are delivered through an injectable ``transport`` callable
with the contract ``(url, payload_dict) -> int`` (HTTP status code; ``0``
signals failure). The default transport is stdlib ``urllib.request`` — no
extra dependency. When a payload carries no ``callback_url``, delivery is a
silent no-op so existing callers stay backward-compatible.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT_S = 5.0

Transport = Any  # callable (url: str, payload: dict) -> int

# Sentinel default: ``BuzzAdapter()`` wires the stdlib transport (backward
# compatible). Passing ``transport=None`` explicitly opts out — delivery then
# raises ``BuzzConfigError`` at call time, never silently no-ops.
_NO_TRANSPORT: Any = object()


class BuzzConfigError(ValueError):
    """Required Buzz configuration is missing (fail-loud).

    Importing this module never requires credentials — the adapter is fully
    usable with no arguments. This fires only at call time when a delivery is
    requested but no transport is wired, mirroring ``LLMConfigError`` semantics
    in :mod:`src.core.ports.llm`.
    """


def _urllib_transport(url: str, payload: dict[str, Any]) -> int:
    """Default transport: stdlib JSON POST with a short timeout.

    Never raises — network failures are logged and reported as status 0 so a
    dead callback endpoint can never crash a mission.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_CALLBACK_TIMEOUT_S) as response:
            return int(response.status)
    except Exception as exc:
        logger.warning("Buzz callback POST failed url=%s: %s", url, exc)
        return 0


@dataclass
class BuzzPayload:
    """Parsed representation of a Buzz webhook payload."""

    goal_text: str
    context: dict[str, Any] = field(default_factory=dict)
    callback_url: str | None = None
    mission_id: str | None = None


class BuzzAdapter:
    """Receives goals from Buzz and feeds them into MekongCoreRuntime."""

    # Class-level factory — never imports credentials.
    @classmethod
    def without_transport(cls, runtime: Any | None = None) -> "BuzzAdapter":
        """Construct an adapter that refuses delivery (no transport wired).

        Importable with zero arguments and zero credentials; any
        ``send_update`` call with a callback URL then raises
        ``BuzzConfigError`` instead of silently no-opping.
        """
        return cls(runtime=runtime, transport=None)

    def __init__(
        self,
        runtime: Any | None = None,
        transport: Transport | None = _NO_TRANSPORT,
    ) -> None:
        self._runtime = runtime
        self._transport = _urllib_transport if transport is _NO_TRANSPORT else transport

    @property
    def runtime(self) -> Any:
        return self._runtime

    @runtime.setter
    def runtime(self, value: Any) -> None:
        self._runtime = value

    @property
    def transport(self) -> Transport:
        return self._transport

    @transport.setter
    def transport(self, value: Transport | None) -> None:
        """Wire a transport. Passing ``None`` opts out of delivery (fail-loud)."""
        self._transport = _urllib_transport if value is _NO_TRANSPORT else value

    def receive_goal(self, payload: dict) -> dict:
        """Parse Buzz webhook payload into a Goal dict for runtime.run().

        Accepts either ``{"goal": "..."}`` or ``{"text": "..."}`` as the
        primary goal field.
        """
        bp = BuzzPayload(
            goal_text=payload.get("goal", payload.get("text", "")),
            context=payload.get("context", {}),
            callback_url=payload.get("callback_url"),
            mission_id=payload.get("mission_id"),
        )
        if not bp.goal_text:
            raise ValueError("Buzz payload missing 'goal' field")
        return {
            "text": bp.goal_text,
            "context": bp.context,
            "mission_id": bp.mission_id,
            "callback_url": bp.callback_url,
        }

    def send_update(self, status: str, data: dict, callback_url: str | None = None) -> dict:
        """Build a status update dict destined for the Buzz callback URL.

        When ``callback_url`` is provided and a transport is wired, the update
        is POSTed through the transport; transport errors are swallowed with a
        logged warning so a failed delivery never crashes a mission. Without a
        callback URL this is a silent no-op (backward-compatible) — the built
        dict is still returned so callers can inspect or log it.
        """
        update = {"status": status, "data": data}
        if not callback_url:
            return update
        if self._transport is None:
            raise BuzzConfigError(
                "no transport wired — construct BuzzAdapter(transport=...) or "
                "use BuzzAdapter.without_transport() only if delivery is unwanted"
            )
        try:
            code = int(self._transport(callback_url, update))
        except Exception as exc:
            logger.warning("Buzz transport raised for %s: %s", callback_url, exc)
            return update
        if 200 <= code < 300:
            logger.info("Buzz callback delivered (%d) to %s", code, callback_url)
        else:
            logger.info("Buzz callback non-2xx (%d) for %s", code, callback_url)
        return update

    def receive_feedback(self, feedback: dict) -> dict:
        """Parse feedback from Buzz for plan adaptation."""
        return feedback


__all__ = ["BuzzAdapter", "BuzzConfigError", "BuzzPayload", "_urllib_transport"]
