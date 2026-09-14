# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Cloudflare execution adapter package (T8 of SUPER COMMAND #5).

Single import site that binds the core to the Cloudflare Worker runtime
(:mod:`src.core.exec_runtime.cloudflare`). The core spine has ZERO direct
Cloudflare imports — this adapter is the only bridge, and it is importable
with zero arguments and zero credentials. Any call that needs a real worker
raises :class:`CloudflareAdapterConfigError` at call time, never at import.

Public entry point: :class:`CloudflareExecutionAdapter`.
"""

from src.core.adapters.cloudflare.adapter import (
    CloudflareAdapterConfigError,
    CloudflareExecutionAdapter,
)

__all__ = ["CloudflareExecutionAdapter", "CloudflareAdapterConfigError"]