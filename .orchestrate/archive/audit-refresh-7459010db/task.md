# Architecture Audit Task — Mekong CLI → Autonomous Runtime

Original user request:
```
You are the Principal Architect for the existing Mekong CLI repository.

DO NOT rewrite the project.
DO NOT create a parallel architecture.
DO NOT add speculative features.
DO NOT delete working functionality.

Mission:
Transform the EXISTING Mekong CLI into an autonomous agent runtime that can later plug into Buzz as a runtime/extended-arm, while Cloudflare becomes the preferred external execution/distribution layer and MCP + x402/MPP become capability/economic buses.

First perform a repository-wide architecture audit.

Read and map these FIRST:
- AGENTS.md
- CLAUDE.md
- HARNESS.md
- README.md
- dna/
- agents/
- src/harness/
- engine/
- factory/
- cli/
- integrations/
- cloudflare-skills/
- recipes/cloudflare/
- workflows/
- observability/
- specs/
- tests/

Then trace actual execution paths from:
1. CLI entrypoint
2. command dispatch
3. harness
4. PEV
5. agent registry
6. LLM router
7. tool execution
8. verification
8. observability
10. billing/payment

Identify:
- duplicated orchestration systems
- dead code
- conflicting agent abstractions
- duplicated CLI surfaces
- duplicated billing/payment concepts
- Cloudflare code that should become adapters
- components that should become core primitives
- components that should be deprecated
- missing interfaces required for Buzz integration
- missing interfaces required for MCP
- missing abstraction required for x402/MPP
- unsafe autonomous execution paths
- missing approval/risk gates
- state/memory ownership problems

Produce:
CURRENT_ARCHITECTURE.md
DEPENDENCY_MAP.md
DUPLICATION_MAP.md
DEPRECATION_MAP.md
AUTONOMY_GAPS.md
MEKONG_CORE_CONTRACT.md

Do NOT modify production code yet.

The target architecture is:

Buzz
  -> Mekong Runtime Adapter
      -> Mekong Core
          -> Goal
          -> Context
          -> Plan
          -> Delegate
          -> Execute
          -> Observe
          -> Verify
          -> Repair
          -> Remember
          -> Commit

Mekong Core must remain provider-agnostic.

LLM providers are adapters:
Claude / Qwen / DeepSeek / OpenAI-compatible / local models.

Capability providers are adapters:
MCP / local tools / Cloudflare / filesystem / shell / browser.

Economic providers are adapters:
x402 / MPP / stablecoin payment rails.

Cloudflare must NOT become hard-coded into the core.
Buzz must NOT become hard-coded into the core.

Important:
Preserve existing business funnels and working commands unless the audit proves they conflict with the target architecture.

After the audit, give me:
1. architecture score /100
2. autonomy score /100
3. production-readiness score /100
4. top 10 architectural risks
5. top 10 highest-ROI changes
6. exact file-level implementation order
7. which existing files should be reused
8. which files should be wrapped
9. which files should be deprecated
10. the smallest v0.1 path to Buzz + Mekong = Autonomous Runtime

STOP after the audit.
Do not implement until explicitly instructed.
```

Phase 1: PLAN - Kongming to create plan.md