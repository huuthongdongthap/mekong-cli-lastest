# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Identity

Mekong CLI v6.0 — AI-operated business platform for Vietnamese one-person companies. MIT licensed. Public repo.

Core funnels:
1. Zalo OA — customer communication automation
2. Tax & Accounting (thue_dnvn, ke_toan) — TNCN/TNDN/GTGT compliance + TT78 invoices
3. AI Video Factory (sophia) — AI video generation on CF Workers

## Commands

Run from repo root. 39 command groups wired via `build_app()`
(`python3 -c "from src.cli.app_setup import build_app; print(len(build_app().registered_groups))"`).

- Design intelligence: `mekong ui {audit,study,redesign,build,approve,benchmark}`
  (see docs/design-intelligence.md)

- Python tests: python3 -m pytest tests/ -v
- Lint: python3 -m ruff check src/ tests/
- Single test file: python3 -m pytest tests/<path> -v

## Architecture

mekong (CLI) / api-gateway (FastAPI :8000)
  src/core/ — autonomous runtime core: lifecycle (runtime_adapter),
              governance, capability bus, protocols, MCU billing,
              exec_runtime sandbox, adapters (tool/MCP/payment/buzz)
  src/commands/ — command modules behind the 39 CLI groups
  src/cli/ — Typer app assembly (app_setup.build_app), build wizard
  src/harness/ — PEV engine (plan-execute-verify), agents, observability
  src/api/ — REST routes (raas, billing, gateway)
  src/middleware/ — license_gate (JWT + balance check)
  src/services/ — org service and clients
  src/mekongcli/ — GoalEngine service (cook/goal/implement consumers)
  src/seed/ — foundational auth, DB, config, types
  src/daemon/ — scheduler with fail-closed command sanitizer

Autonomous runtime docs: docs/architecture.md, docs/core-contract.md,
docs/capability-bus.md, docs/economic-bus.md, docs/buzz-runtime-adapter.md,
docs/runtime-adapters.md, docs/autonomy-model.md

## Billing

- MCU: 1 MCU = 1 credit (MCUBilling singleton)
- Polar.sh webhook → org activation
- Tier enum: BASIC | PREMIUM | ENTERPRISE | MASTER

## Quality

- Python: ruff, mypy
- No console statements in production
- Tests must pass before push

## Public Repo Boundary

- apps/ — private client projects
- .env* — never commit
- app/ — private client projects
- billing/ — internal workspace (dịch vụ, không public)
