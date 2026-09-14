# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Backward-compatibility re-export for ``src.core.adapters.llm.client``.

The canonical LLM client moved to ``src/providers/llm/client.py`` per the
DEPRECATION.md resolution target. This module is a thin shim that re-exports
it so legacy importers — including the Gate 5 deployment smoke test in
``.github/workflows/ai-native-ci.yml``, which is outside this PR's ownership
and must not be edited — keep resolving the historical path.

New code should ``from src.providers.llm import ...`` directly.
"""

from src.providers.llm import *  # noqa: F401,F403
from src.providers.llm import __all__ as _all  # noqa: F401

__all__ = list(_all)