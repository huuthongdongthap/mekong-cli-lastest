# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Harness Agent Registry Module (Converged Facade).

Re-exports canonical AgentRegistry, AgentMeta, and get_registry from
src.core.agent_registry to ensure a single, authoritative registry contract.
Preserves complete backward compatibility for all harness callers.
"""

from __future__ import annotations

from src.core.agent_registry import (
    AgentMeta,
    AgentRegistry,
    get_registry,
)

__all__ = [
    "AgentMeta",
    "AgentRegistry",
    "get_registry",
]
