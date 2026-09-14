# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Governance Layer.

Safety governance for autonomous operations.
Classifies actions as safe/review_required/forbidden.
Maintains audit trail in .mekong/audit.yaml.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from .event_bus import EventType, get_event_bus

logger = logging.getLogger(__name__)


class ActionClass(str, Enum):
    """Classification of an action's safety level."""

    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    FORBIDDEN = "forbidden"


@dataclass
class GovernanceDecision:
    """Result of governance classification."""

    action_class: ActionClass
    reason: str
    requires_approval: bool = False
    approved: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class AuditEntry:
    """Single audit trail entry."""

    timestamp: float = field(default_factory=time.time)
    goal: str = ""
    action_class: str = ""
    approved: bool = False
    result: str = ""  # "executed" | "blocked" | "rejected"


class Governance:
    """Safety governance layer for autonomous operations."""

    FORBIDDEN_PATTERNS: list[str] = [
        r"\brm\s+-rf\b",
        r"\bdrop\s+(database|table)\b",
        r"\bdelete\s+all\b",
        r"\bdestroy\b",
        r"\bformat\b",
        r"\btruncate\b",
    ]

    REVIEW_PATTERNS: list[str] = [
        r"\bdeploy\b.*\bprod",
        r"\bpush\b.*\bmain\b",
        r"\bmodify\b.*\bconfig\b",
        r"\bupdate\b.*\bdns\b",
        r"\bmigrate\b",
    ]

    # Risk-level mapping for capability-based governance (E3)
    RISK_LEVEL_MAP: dict[str, ActionClass] = {
        "LOW": ActionClass.SAFE,
        "MEDIUM": ActionClass.SAFE,
        "HIGH": ActionClass.REVIEW_REQUIRED,
        "CRITICAL": ActionClass.FORBIDDEN,
    }

    MAX_AUDIT: int = 1000

    def __init__(self, audit_path: str | None = None) -> None:
        """Initialize governance layer."""
        self.audit_path = audit_path or ".mekong/audit.yaml"
        self._halted = False
        self._audit: list[AuditEntry] = []
        self._load_audit()

    def classify(self, goal: str) -> GovernanceDecision:
        """Classify a goal as safe, review_required, or forbidden."""
        goal_lower = goal.lower()

        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, goal_lower):
                decision = GovernanceDecision(
                    action_class=ActionClass.FORBIDDEN,
                    reason=f"Matched forbidden pattern: {pattern}",
                )
                self._record_audit_for_decision(goal, decision, "blocked")
                return decision

        for pattern in self.REVIEW_PATTERNS:
            if re.search(pattern, goal_lower):
                decision = GovernanceDecision(
                    action_class=ActionClass.REVIEW_REQUIRED,
                    reason=f"Matched review pattern: {pattern}",
                    requires_approval=True,
                )
                # Don't record audit here — request_approval will handle it
                return decision

        decision = GovernanceDecision(
            action_class=ActionClass.SAFE,
            reason="No dangerous patterns detected",
        )
        self._record_audit_for_decision(goal, decision, "executed")
        return decision

    def classify_risk(self, risk_level: str) -> GovernanceDecision:
        """Classify a capability by its risk_level.

        Map:
          LOW → SAFE
          MEDIUM → SAFE (+mandatory audit)
          HIGH → REVIEW_REQUIRED
          CRITICAL → FORBIDDEN
        """
        risk_upper = risk_level.upper()
        action_class = self.RISK_LEVEL_MAP.get(risk_upper, ActionClass.SAFE)

        if action_class == ActionClass.FORBIDDEN:
            decision = GovernanceDecision(
                action_class=action_class,
                reason=f"CRITICAL risk level: {risk_level}",
            )
            self._record_audit_for_decision(f"capability:{risk_level}", decision, "blocked")
            return decision

        if action_class == ActionClass.REVIEW_REQUIRED:
            decision = GovernanceDecision(
                action_class=action_class,
                reason=f"{risk_level} risk requires review",
                requires_approval=True,
            )
            return decision

        # LOW or MEDIUM → SAFE
        decision = GovernanceDecision(
            action_class=action_class,
            reason=f"{risk_level} risk classified as safe",
        )
        self._record_audit_for_decision(f"capability:{risk_level}", decision, "executed")
        return decision

    def _record_audit_for_decision(self, goal: str, decision: GovernanceDecision, result: str) -> None:
        """Record audit entry for a governance decision."""
        entry = AuditEntry(
            goal=goal,
            action_class=decision.action_class.value,
            approved=decision.approved,
            result=result,
        )
        self.record_audit(entry)

    def request_approval(
        self, goal: str, decision: GovernanceDecision
    ) -> bool:
        """Request human approval for review_required actions.

        Returns False by default — approval must come from a human
        or from GOVERNANCE_AUTO_APPROVE=true for non-forbidden actions.

        When auto-approving via env var, logs WARNING and records audit entry.
        """
        if decision.action_class == ActionClass.FORBIDDEN:
            return False

        if decision.requires_approval:
            # Auto-approve only when explicitly enabled via env var
            auto_approve = os.getenv("GOVERNANCE_AUTO_APPROVE", "").lower()
            if auto_approve not in ("true", "1", "yes"):
                logger.warning(
                    "Governance: action '%s' requires human approval "
                    "(set GOVERNANCE_AUTO_APPROVE=true to bypass)",
                    goal,
                )
                decision.approved = False
                self._record_audit_for_decision(goal, decision, "rejected")
                return False
            logger.warning(
                "Governance: auto-approving '%s' via GOVERNANCE_AUTO_APPROVE",
                goal,
            )
            decision.approved = True
            self._record_audit_for_decision(goal, decision, "approved")
            return True

        # Non-review actions need no approval gate — approve explicitly so the
        # function never falls through to an implicit None.
        self._record_audit_for_decision(goal, decision, "executed")
        return True

    def record_audit(self, entry: AuditEntry) -> None:
        """Record an audit entry with FIFO eviction.

        The entry is always kept in memory. Persistence is best-effort and
        loud: if the audit file cannot be written (unwritable path, full
        disk), a WARNING is logged but the decision path never crashes.
        """
        self._audit.append(entry)
        if len(self._audit) > self.MAX_AUDIT:
            self._audit = self._audit[-self.MAX_AUDIT:]
        try:
            self._save_audit()
        except OSError as exc:
            logger.warning(
                "Governance: failed to persist audit trail to %s "
                "(entry kept in memory): %s",
                self.audit_path,
                exc,
            )

    def get_audit_trail(self, limit: int = 50) -> list[AuditEntry]:
        """Get recent audit entries."""
        return self._audit[-limit:]

    def is_halted(self) -> bool:
        """Check if system is halted."""
        return self._halted

    def halt(self) -> None:
        """Halt all autonomous operations."""
        self._halted = True
        bus = get_event_bus()
        bus.emit(EventType.HALT_TRIGGERED, {"timestamp": time.time()})

    def resume(self) -> None:
        """Resume autonomous operations."""
        self._halted = False

    def _load_audit(self) -> None:
        """Load audit trail from YAML."""
        path = Path(self.audit_path)
        if not path.exists():
            self._audit = []
            return
        try:
            data = yaml.safe_load(path.read_text()) or []
            self._audit = [
                AuditEntry(
                    timestamp=d.get("timestamp", 0),
                    goal=d.get("goal", ""),
                    action_class=d.get("action_class", ""),
                    approved=d.get("approved", False),
                    result=d.get("result", ""),
                )
                for d in data
            ]
        except Exception as e:
            logger.debug("Failed to load audit trail: %s", e)
            self._audit = []

    def _save_audit(self) -> None:
        """Save audit trail to YAML."""
        path = Path(self.audit_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "timestamp": e.timestamp,
                "goal": e.goal,
                "action_class": e.action_class,
                "approved": e.approved,
                "result": e.result,
            }
            for e in self._audit
        ]
        # Atomic write — write to temp file then rename
        import tempfile as _tmp

        _fd, _tmp_path = _tmp.mkstemp(
            dir=path.parent, suffix=".yaml.tmp"
        )
        try:
            with os.fdopen(_fd, "w") as _fh:
                _fh.write(yaml.dump(data, default_flow_style=False))
            os.replace(_tmp_path, str(path))
        except Exception:
            try:
                os.unlink(_tmp_path)
            except OSError:
                pass
            raise

    __all__ = [
        "ActionClass",
        "AuditEntry",
        "Governance",
        "GovernanceDecision",
    ]