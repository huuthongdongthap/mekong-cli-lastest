# AGENTS.md — Mekong CLI
# Read by: Claude Code, Gemini CLI, OpenCode, Cursor, Codex, Amp

## Project
**CEO Solo Agentic Harness Engineering Platform.**
One CEO delegates to 4 layer agents (Business, Product, Engineering, Ops).
Harness engineering: shape the environment around AI agents for reliability.

## Commands
Commands live in `.claude/commands/*.md`. Execute via: `python3 -m src.main <name> <args>`
Engine: Python CLI (Typer) → Harness PEV → LLM Router → Agent Layer

## Build & Test
```bash
pip install -e .       # Python CLI
python3 -m pytest tests/  # Tests
python3 -m src.main --help
```

## Style
Python: snake_case, type hints. Commits: conventional (feat/fix/refactor/docs/test).

## Architecture

```
mekong cook "your goal"
        │
        ▼
┌─────────────────────────┐
│  Harness Engine         │  src/harness/
│  ├── pev/               │  Plan → Execute → Verify
│  ├── agents/            │  Agent dispatcher, classifier, queue
│  ├── core/              │  LLM router, config, permissions, governance
│  └── observability/     │  Traces, metrics, Prometheus
└─────────────────────────┘
        │
        ▼
┌─────────────────────────┐
│  SOPs (sops/)           │  CEO / Business / Engineering / Ops
│  Agent Registry         │  agents/registry.yaml
│  Evals                  │  evals/solo-ceo-eval.md
│  Runtime Contract       │  HARNESS.md
└─────────────────────────┘
```

## Harness Engineering

Mekong applies **harness engineering** principles (shaping the environment around AI agents for reliability).

> Inspired by [walkinglabs/awesome-harness-engineering](https://github.com/walkinglabs/awesome-harness-engineering)

### Runtime Contract
- **`HARNESS.md`** — context budget, guardrails, CEO override, high-risk gates, delegation matrix
- **`docs/core-contract.md`** — canonical agent lifecycle (goal → … → commit), protocol surface, invariants enforced by tests (`tests/test_core_lifecycle_contract.py`, `tests/test_core_boundary.py`)
- **`docs/autonomy-model.md`** — risk levels (LOW/MEDIUM/HIGH/CRITICAL), approval path, `GOVERNANCE_AUTO_APPROVE` semantics

Status quo (v0.1): the harness PEV engine reuses the core planner
(`src.core.planner`); lifecycle and boundary contracts are pinned by tests —
read `docs/core-contract.md` before changing anything in `src/core/`.

### Directory Structure
```
mekong-cli/
├── HARNESS.md            # Runtime contract (load at session start)
├── sops/                 # Standard Operating Procedures
│   ├── ceo/             # CEO decision-making, weekly-review, approval-gate
│   ├── business/        # Client lifecycle, revenue engine
│   ├── engineering/     # Code review, deployment
│   ├── ops/             # Incident response, monitoring
│   └── shared/          # Review cycles (shared across layers)
├── agents/
│   └── registry.yaml    # Declarative agent definitions (CEO/AE/PM/ENG/OPS)
├── evals/
│   └── solo-ceo-eval.md # 6 harness quality evals
├── observability/
│   ├── traces/          # OpenTelemetry-compatible traces
│   └── dashboards/      # Prometheus + Grafana
├── docs/
│   └── harness-engineering.md
├── .claude/commands/    # Slash commands
│   ├── cook.md          # PEV workflow
│   ├── cook-auto.md     # Autonomous goal runner
│   └── cook-auto-parallel.md
├── src/harness/         # Core engine modules
│   ├── pev/             # Plan-Execute-Verify engine
│   ├── agents/          # Agent layer (dispatcher, classifier, queue)
│   ├── core/            # LLM router, config, governance, permissions
│   └── observability/   # Tracing, metrics, health
└── .archive/            # Archived legacy code (not deleted, preserved)
```

### CEO Solo Model
One CEO → 4 layer agents (AE/PM/ENG/OPS). CEO has override authority.
All high-risk actions require approval (`.claude/settings.json` deny/ask lists).

### 6 Harness Principles

| Principle | Implementation |
|-----------|----------------|
| **Context Engineering** | HARNESS.md context budget (≤40k tokens), layer-specific tool allowlists |
| **Constraints & Guardrails** | `.claude/settings.json` deny/ask lists, SOP hard gates |
| **Specs & Workflow** | `sops/` as executable specs with acceptance criteria |
| **Evals & Observability** | `evals/` + `observability/` (OTel, Prometheus, dashboards) |
| **Orchestration** | `agents/registry.yaml`, `/cook-auto-parallel` |
| **Safe Autonomy** | CEO override (`--ceo-override`), high-risk approval gates |
