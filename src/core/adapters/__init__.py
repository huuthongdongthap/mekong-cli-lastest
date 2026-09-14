# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Memory bridge adapters package.

Provides bridge implementations for each backend:
- SeedBridge   → src.seed.memory (SQLite)
- MemoryStoreBridge → src.core.memory_canonical (YAML + vector)
- ScopedBridge → src.core.memory_scope (in-memory, scoped)
- PevBridge    → src.harness.pev.memory (in-memory dict)
"""
