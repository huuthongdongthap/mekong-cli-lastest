# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Developer Documentation Hub containing comprehensive guides:
  - `docs/setup-guide.md` (System prerequisites and model setups)
  - `docs/local-development-guide.md` (Workspace configurations, formatting)
  - `docs/env-vars.md` (Config variables for LLM, DB, and payments)
  - `docs/testing-guide.md` (pytest seed and core test suites)
  - `docs/troubleshooting.md` (Diagnostics for locks, ports, and model servers)
  - `docs/architecture-overview.md` (Core PEV loops and daemon processes)
  - `docs/deployment-notes.md` (Cloudflare RaaS infrastructure details)
  - `docs/glossary.md` (Vocabulary for Binh Phap strategic terms)
  - `docs/onboarding.md` (Sandbox guidelines for new developers and agents)
- `GET /metrics` — Prometheus text format endpoint for MCU/PEV/uptime gauges
- CSRF middleware (double-submit cookie, env-gated `CSRF_ENABLED=1`)
- Rate-limit gateway middleware wiring existing `RateLimiter` (`RATE_LIMIT_ENABLED=1`)
- Dependabot configuration for pip and GitHub Actions dependencies
- `GET /healthz` — lightweight liveness probe for load balancers

### Changed
- Architecture audit refresh at HEAD 0878f966f: all seven docs/architecture/ audit documents re-verified against the working tree (298 cited paths, zero dangling references); new DRIFT_REPORT.md documents PR #2 drift findings; scores re-based with evidence ledgers (architecture 66/100, autonomy 55/100, production-readiness 72/100)
- MCUBilling migrated from in-memory dict to SQLite WAL via CreditStore
- License gate changed to fail-closed (default `LICENSE_GATE_ENFORCE=1`)
- Coverage config: removed `*/raas/*` and `*/llm_client.py` from omit list

### Fixed
- JSONL append race conditions via `fcntl` advisory locking (8 files)
- Gateway CORS: explicit origin whitelist replaces wildcard
- Gateway: Swagger UI disabled in production
- Gateway: bare `except` narrowed to specific exception types
- Database health check added to `/health` endpoint

### Security
- `poetry.lock` committed to pin transitive dependencies
- CORS `allow_headers` restricted to known headers
- `.gitignore` no longer excludes `poetry.lock`

## [6.0.0] - 2026-05-10

### Added
- 342+ CLI commands across 6 organizational layers
- PEV Engine (Plan-Execute-Verify) orchestration loop
- MCU Billing with Polar.sh webhook integration
- VN Hub: kế toán, thuế, Zalo OA, VietQR webhook
- Agent layer: GitAgent, FileAgent, ShellAgent, LeadHunter, ContentWriter
- Universal LLM router with 7-provider fallback chain
- 3-layer Cloudflare-only infrastructure templates
