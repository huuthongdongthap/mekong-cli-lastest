# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Canonical port interfaces for Mekong Core.

Ports live in ``src/core/ports/`` — pure structural typing (Protocol) defining
the boundary between core spine and adapter implementations. Core imports only
from here + ``protocols.py``; adapters import from core.

``src/core/protocols.py`` (LLMRouter, PaymentProvider, ...) is the
**router/orchestration-level** surface. The ports in this package are
**provider-level** — e.g. ``LLMProviderPort`` is the single-provider contract
that ``LLMRouter`` routes between, whereas ``LLMRouter`` itself selects among
providers. Two distinct layers, no overlap.

Ports contain NO implementation imports — the factory that builds concrete
adapters lives in ``src/core/adapters/llm/__init__.py`` (``build_llm_provider``).
"""

from .llm import LLMConfigError, LLMNotSupportedError, LLMProviderPort

__all__ = [
    "LLMProviderPort",
    "LLMConfigError",
    "LLMNotSupportedError",
]
