# Project Changelog

## v6.9.0 — 2026-09-13

**Core Protocol Conformance Expansion & Architecture Documentation Alignment (100% Complete):**

- **Core Protocol Conformance Suite Expansion (`tests/test_protocol_compliance.py`):**
  - Expanded test suite from 12 to 25 unit tests covering all 10 core `@runtime_checkable` protocols in `src/core/protocols.py` (`MekongCoreRuntime`, `LLMRouter`, `ToolRegistry`, `BillingMeter`, `MemoryStore`, `MemorySeparation`, `ObservabilitySink`, `VerificationEngine`, `GoalEngine`, `PaymentProvider`) and `CapabilityBus`.
  - Added method presence assertions for `BillingMeter.settle_payment()`, `ToolRegistry.list_mcp_tools()`, `GoalEngine.adapt()`, `PaymentProvider.quote()`, `PaymentProvider.verify()`, `PaymentProvider.request_payment()`, and `MemorySeparation.flush_session()` / `prune_expired()`.
  - Added structural runtime conformance assertions (`isinstance(..., Protocol)`) for 13 concrete adapters:
    - `BillingAdapter` (`BillingMeter` + `PaymentProvider`)
    - `NowPaymentsProvider` (`PaymentProvider` in `src.raas.nowpayments_provider`)
    - `NowPaymentsProvider` (`PaymentProvider` alias in `src.core.adapters.payment.nowpayments`)
    - `MockPaymentProvider` (`PaymentProvider` in `src.core.adapters.payment_mock`)
    - `X402SettlementProvider` (`PaymentProvider` in `src.core.adapters.payment.x402`) with mock governance and transport injection
    - `MPPSettlementProvider` (`PaymentProvider` in `src.core.adapters.payment.mpp`) with mock governance and transport injection
    - `ToolRegistry` (`ToolRegistry`)
    - `MemorySeparation` (`MemorySeparation`)
    - `MemoryStore` (`MemoryStore` canonical with `restore_real_memory_store` fixture)
    - `JsonlMemoryAdapter` (`MemoryStore`)
    - `MemoryStoreConformant` (`MemoryStore` in `src.core.adapters.memory_store_conformant`)
    - `MekongCoreRuntimeImpl` (`MekongCoreRuntime`)
    - `InMemoryCapabilityBus` (`CapabilityBus`)
    - `RecipeVerifier` (`VerificationEngine`)
    - `MemoryStoreAdapter` (`MemoryStore`)
    - `TelemetrySinkAdapter` (`ObservabilitySink`)
    - `LLMRouterAdapter` (`LLMRouter`)
    - `GoalEngineAdapter` (`GoalEngine`)
  - 25/25 tests passing in `tests/test_protocol_compliance.py`.

- **Documentation & Invariants Synchronization:**
  - Synchronized `docs/architecture/CURRENT_ARCHITECTURE.md`, `docs/architecture/AUTONOMY_GAPS.md`, and `docs/architecture/ARCHITECTURE_ASSESSMENT.md` to HEAD `fb369617b`.
  - Recorded PR #41 in the merged PR ledger in `docs/architecture/ARCHITECTURE_ASSESSMENT.md`.
  - Re-verified all 11 Autonomy Gaps remain 100% closed with live test evidence.
  - Confirmed repository invariants: 39 Typer CLI command groups, 0 ruff lint errors, and 100% passing test suites across all core and Vietnam modules.

## v6.8.0 — 2026-09-12

**Phase 5 AI Video Factory (Sophia) Full Integration & Conformance (100% Complete):**

- **Sophia AI Video Factory Service (`src/services/sophia_video_service.py`):**
  - Implemented core RaaS video production engine `SophiaVideoService` supporting avatar and voice catalogs, aspect ratio formatting (16:9 landscape, 9:16 vertical/shorts, 1:1 square), and layout templates (`news_anchor`, `faceless_explainer`, `product_showcase`, `youtube_deepdive`).
  - Integrated with Design DNA memory (`src.design_intelligence.design_memory.load_approved`) to automatically brand videos using approved design tokens (colors, typography, surface treatments, density).
  - Wired MCU credit billing via `MCUBilling` singleton (50 MCU per 30s block with 1.5x template multiplier for deepdive videos) with atomic SQLite WAL transactions.
  - Implemented strict input validation and command injection guards (`validate_identifier`, `validate_job_id`, `sanitize_script`) with regex safe-character enforcement and length limits.
  - Provided deterministic dry-run rendering mode (`--dry-run`) producing local container artifacts with zero external network dependencies for CI verification.
  - Added multi-tenant job isolation and filesystem state persistence under `.sophia/jobs` and `.sophia/artifacts`.

- **CLI Sub-App Registration & Commands (`src/commands/sophia_video.py` & `src/cli/tools_browse_collab_commands.py`):**
  - Created standalone Typer sub-app `app` in `src/commands/sophia_video.py` exposing 8 subcommands: `render`/`create`, `status`, `list`, `avatars`, `voices`, `templates`, and `cost`.
  - Mounted under `tools_app` in `src/cli/tools_browse_collab_commands.py` as `mekong tools video <subcommand>`, preserving the strict 39-group total count invariant and 60-command manifest root contract.
  - Re-exported `sophia_app` alongside Zalo OA, Thuế, and Kế toán in `src/cli/funnel_commands.py` with explicit `__all__` declaration.
  - Supported dual output modes: formatted Rich tables/panels for interactive human use and clean JSON (via `typer.echo` to prevent ANSI escape sequences) for programmatic parsing.

- **Test Coverage & Verification:**
  - Added 19 unit tests in `tests/test_sophia_video_service.py` covering catalog queries, filtering, security validators, MCU cost estimation, dry-run rendering, Design DNA styling, job state persistence, and multi-tenant isolation.
  - Added 24 CLI integration tests in `tests/cli/test_sophia_video_commands.py` covering Typer registration, dry-run renders, file script inputs, job status queries, job listing, discovery commands, cost estimations, and injection defense rejections.
  - Verified 100% test pass rate across all 43 Sophia tests and confirmed zero regressions across the entire test suite.

## v6.7.0 — 2026-09-11

**Phase 6 Cloud Deploy Unification & CLI Hardening (100% Complete):**

- **CLI Sub-App Unification (`src/cli/sdlc/deploy.py` & `src/commands/deploy.py`):**
  - Unified the split between SDLC feature gate reporting (`mekong deploy new <feature>`) and multi-platform infrastructure deployment (`mekong deploy run/status/rollback`).
  - Mounted `run`, `status`, and `rollback` onto `deploy_app` under canonical `deploy` CLI group, maintaining exact 39-group total count.
  - Added support for `--dry-run` and `--build/--no-build` flags.
- **Fail-Closed Platform Operations:**
  - Hardened Cloudflare (`wrangler`), Docker (`docker`), Kubernetes (`kubectl`), and custom shell script deployments against missing binaries with explicit `FileNotFoundError` handling and `typer.Exit(code=1)`.
  - Added status inspection and rollback commands for Cloudflare Workers/Pages deployments with dry-run verification.
- **Test Coverage & Conformance:**
  - Added 21 tests in `tests/cli/test_deploy_commands.py` covering registration, dry-run simulations, missing dependencies, subprocess execution, error handling, and unsupported platform rejections.
  - Updated `COMMAND_REGISTRY.md` and `docs/development-roadmap.md` (Phase 6 marked 100% complete).

## v6.6.0 — 2026-09-10

**Architectural Duplication Convergence & Tier Configuration Consolidation (DUPLICATION_MAP #1, #2, #3, #6, #7, #8, #9):**

- **Phase 4 Vietnam Hub Full Surface Convergence (100%):**
  - Consolidated and verified all 3 Vietnam business funnels (`zalo-oa`, `thue`, `ke-toan`) across Typer CLI command sub-apps and REST API endpoints.
  - Hardened VietQR webhook processing (`src/api/vn_payments_routes.py`, `src/services/vietqr_webhook_handler.py`) with HMAC-SHA256 signature verification, idempotent transaction handling, and bank-friendly HTTP 200 error policy.
  - Verified multi-tenant organization isolation (`src/api/org_routes.py`, `tests/vn/test_org_id_isolation.py`, `tests/vn/test_org_id_full_surface.py`) with tenant-scoped storage backends (JSONL and SQLite).
  - Enforced soft paywall via `PilotCreditGateMiddleware` (`src/middleware/pilot_credit_gate.py`) returning HTTP 402 with bilingual payment instructions and VietQR bank details.
  - Achieved 100% test pass rate across all 467 tests in the Vietnam Hub test surface (`tests/vn/`, `tests/commands/test_thue_dnvn.py`, `tests/cli/test_funnel_commands.py`, `tests/zenos/test_vietnam_feature_regression.py`, `tests/core/test_service_credits.py`, `tests/test_onboarding_funnel_store.py`).

- **Phase 3 Programmatic Auth Refresh & Token Rotation:**
  - Implemented `POST /auth/refresh` endpoint in `src/api/auth_routes.py` with rotating 30-day refresh tokens and 1-hour access tokens.
  - Added claim verification distinguishing `"token_type": "access"` from `"token_type": "refresh"`, rejecting access token replay attempts with HTTP 401.
  - Wired live license store lookup on token refresh, dynamically resolving license tier upgrades and enforcing active license status (HTTP 402 on cancelled/inactive licenses).
  - Configured `RateLimitGatewayMiddleware` preset resolution for `/auth/refresh` and `/v1/auth/refresh` to map to `RateLimitPreset.AUTH_REFRESH` (30/hour).
  - Added comprehensive test suite `TestRefreshEndpoint` in `tests/test_api_auth_routes.py` covering token rotation, dynamic tier upgrades, expiration, revocation, malformed claims, and rate limit presets.

- **Phase 3 Quota Status Endpoints, Tier Config API & License Gate Conformance:**
  - Mounted `/v1/quota` router (`src/api/quota_status_endpoints.py`) and `/api/tier-configs` router (`src/api/tier_config_routes.py`) into central gateway (`src/gateway.py`).
  - Refactored `EngineLicenseGateMiddleware` (`engine/license/license_gate_middleware.py`) to inherit from Starlette `BaseHTTPMiddleware` implementing canonical `dispatch(request, call_next)`.
  - Added `ActiveLicense` and multi-identifier `get_active_license(user_id)` to `LicenseStore` (`engine/license/license_store.py`) matching license keys, customer IDs, emails, and subscription IDs.
  - Added `_get_or_create_ledger` alias and `charge_mcu` method to `BillingService` (`src/api/raas_billing_service.py`).
  - Added test suites `tests/test_quota_status_endpoints.py`, `tests/test_tier_config_routes.py`, `tests/test_engine_license_gate_middleware.py`, and extended `tests/test_lib_license_store.py` (all passing 100%).

- **Security Pattern Accumulation & Fixture Isolation (PR #22):**
  - Removed premature exit on command chaining detection in `src/core/command_sanitizer.py`, ensuring all dangerous patterns (`curl_pipe_shell`, `sudo_execution`, `rm_root`, etc.) evaluate and accumulate in `blocked_patterns`.
  - Patched dynamic agent discovery module path in `tests/test_plugin_loading.py` to target `src.core.registry.dynamic.Path`.
  - Restored unmocked `MemoryStore` fixture in `tests/test_smart_router.py` via `_pre_gateway_originals`.

- **Tier Configuration & Rate Limiting Consolidation (PR #20, Item 9):**
  - Consolidated tier keys, pricing, MCU credits, and endpoint rate limits into authoritative single source of truth `src/seed/config/tiers.py`.
  - Added dynamic case-insensitive alias lookup via `TierKey._missing_` (`basic` -> `starter`, `premium` -> `growth`, `master` -> `pro`, `enterprise_plus` -> `enterprise`).
  - Added `Tier = TierKey` canonical alias.
  - Converted `engine/billing/tier_config.py` into a thin backward-compatible re-export façade exporting all symbols with zero regression to external callers.
  - Upgraded `LicenseEnforcer` to enforce monotonic 6-tier hierarchy (`FREE: 0, TRIAL: 1, STARTER: 2, GROWTH: 3, PRO: 4, ENTERPRISE: 5`).
  - Added dedicated conformance test suite `tests/test_tier_config_conformance.py` (28/28 tests passing).

- **Architectural Duplication Convergence (PR #19, Items 1, 2, 6, 8):**
  - **Item 1:** Converted duplicate `src/harness/agents/base.py` and `registry.py` to backward-compatible re-export façades forwarding to canonical `src.core.agent_base` and `src.core.agent_registry`.
  - **Item 2:** Converged payment routing; `NowPaymentsProvider` implements `protocols.PaymentProvider`, routing IPN callbacks through canonical interface.
  - **Items 6 & 8:** Ported natural language bilingual router into canonical `src/cli/workflow_commands.py:ask_cmd`, shimmed `src/commands/core_commands.py` to `src.cli.app_setup.build_app()`, pruned dead command stubs `ci.py` and `env.py`.

- **RecipeVerifier Merge & Autonomous Execution Loop (PR #18, Item 7):**
  - Unified `RecipeVerifier` into `MekongCoreRuntimeImpl.verify()` via duck-typed `_ExecResultLike` adapter and `_criteria_to_verifier_dict`.
  - Wired DAG task dependency execution and downstream cancellation through `DAGScheduler.mark_failed`.
  - Completed autonomous `execute()` → `verify()` → `repair()` recovery cycle across 4 strategies (`RETRY`, `FALLBACK`, `ESCALATE`, `ROLLBACK`).

- **Memory Store Convergence (PR #17, Item 3):**
  - Retrofitted `src/core/memory_canonical.py:MemoryStore` with `store()`, `retrieve()`, `delete()`, and `search()`, satisfying `protocols.MemoryStore` runtime checkable protocol natively.
  - Standardized byte-exact base64 encoding and TTL expiry.
  - Created `src/core/adapters/jsonl_memory_adapter.py:JsonlMemoryAdapter` as conformant second backend.

- **Quality & CI:**
  - 100% green on all 22 GitHub Actions CI/CD checks.
  - `ruff check` clean across all modules.

## v6.5.0 — 2026-09-09

**Gap #5 — External MCP Client Adapter + Gap #10 Funnel Restoration:**

- New `src/core/adapters/external_mcp_client.py` — synchronous facade over the
  async `mcp` SDK (stdio + Streamable-HTTP transports). Lets Mekong consume
  tools from third-party MCP servers (Claude Desktop / Cursor / VS Code configs).
- Single-task session loop via `anyio.BlockingPortal.start_task_soon` — keeps
  the MCP SDK's `BaseSession.__aenter__`/`__aexit__` inside the same task,
  avoiding the "Attempted to exit a cancel scope" RuntimeError in anyio 4.13.
- Lazy SDK import with fail-loud `ExternalMcpError` when `mcp` is absent.
- `from_config` / `parse_mcp_servers` parse Claude-Desktop-style `mcpServers`
  blocks (command+args for stdio, url+headers for HTTP).
- **26 new tests** in `tests/test_external_mcp_client.py` (factories, config
  parsing, error paths, mocked list_tools/call_tool, plus 2 live-server
  integration tests guarded by `_has_npx()`).
- Vietnam funnel restoration (`src/cli/funnel_commands.py`): reconnected
  `zalo-oa`, `thue`, `ke-toan` to the `mekong` binary. Registered groups 36 → 39.
  **22 new CLI tests** in `tests/cli/test_funnel_commands.py`.
- `COMMAND_REGISTRY.md` rewritten from 48 phantom entries to actual 39 groups /
  128 commands sourced from `build_app()`.
- Added `anyio ^4.0.0` to `pyproject.toml` (runtime dep of the new adapter;
  was previously transitive-only).
- **Parity:** 8224 passed, 262 failed, 77 skipped. **0 new failures** vs v6.4.0
  baseline (the +26/+22 pass counts come from the new test files).
- `ruff check` clean on all changed files.
- Gap #5 marked CLOSED in `docs/development-roadmap.md`.

## v6.4.0 — 2026-09-09

**Gap #10 — Funnel Restoration (Zalo OA + Tax + Accounting → CLI):**

- Reconnected the three Vietnam business funnels to the `mekong` binary as Typer
  sub-apps via `src/cli/funnel_commands.py` (previously reachable only via `python -m`):
  - `mekong zalo-oa` — send, broadcast, followers, caption, post
  - `mekong thue` — tncn, tndn, gtgt (offline tax calculations)
  - `mekong ke-toan` — create, xml, journal, summary (TT78/2021 invoices, VAS journal)
- Registered groups: 36 → 39 (3 new sub-apps added in `src/cli/app_setup.py`).
- **22 new tests** in `tests/cli/test_funnel_commands.py` covering registration,
  offline calculations, token-gated commands (exit 1 without `ZALO_OA_ACCESS_TOKEN`),
  and help output.
- `COMMAND_REGISTRY.md` rewritten from 48 phantom entries to actual 39 groups / 128
  commands sourced from `build_app()`.
- **Parity:** 8198 passed, 262 failed, 77 skipped. Net −15 vs baseline (277 failures);
  **0 new failures from funnel restoration**.
- `ruff check` clean on all changed files.
- Architecture score +2 (72 → 73); risk #8 (funnel orphaning) marked CLOSED in
  `docs/architecture/ARCHITECTURE_ASSESSMENT.md`.

## v6.3.0 — 2026-09-08

**Super Command #8 — Gap #4: Harness Verifier Merge + DAG Scheduler Swap:**

- `MekongCoreRuntimeImpl.verify()` now delegates to `RecipeVerifier` (was: thin
  `_evaluate_check` with only `exit_code` + `output_pattern`). Three helpers bridge
  the gap: `_ExecResultLike` (core `Result` → `ExecutionResult`-shaped object),
  `_criteria_to_verifier_dict` (core `CheckSpec` → verifier criteria-dict),
  `_report_to_verification` (`VerificationReport` → core `Verification`).
  Empty-criteria path falls back to legacy `Verification(passed=(result.error is None))`.
- `_run_goal` executes multi-step plans in topological (DAG) order via
  `_topological_task_order` (string-ID-keyed Kahn's algorithm, NOT `DAGScheduler`,
  which keys by int `order`). Fast path via `_plan_has_dependencies` preserves
  single-step `mekong run` behavior exactly.
- `verify()` injected via `__init__(verifier=None)` defaulting to
  `RecipeVerifier(strict_mode=True)`.
- **27 new tests** across 3 files:
  - `tests/test_runtime_verify_merge.py` — 14 tests (verifier delegation)
  - `tests/test_runtime_dag_order.py` — 8 tests (topological ordering)
  - `tests/test_runtime_multistep_cycle.py` — 5 E2E tests (full multi-step cycle)
- **Parity:** 8182 passed, 256 failed, 77 skipped. Baseline 277 failures → −21 net
  improvement; **0 new failures from SC8** (1 pre-existing `test_plugin_loading`,
  verified on base commit `8dcb6f759`).
- `ruff check` clean on changed files.
- Architecture doc refreshed to v0.2; gap #4 marked CLOSED in
  `docs/development-roadmap.md`.

## v6.2.0 — 2026-08-29

**Super Command #5 — Economic Bus + Capability Bus + Agent Registry (PR #11):**
- Clean `src/core/` ↔ `src/core/adapters/` boundary: no vendor SDK imports in core at module level
- Canonical `LLMProvider` port (`generate/stream/structured_output/tool_call/health`); two conformant providers
- YAML single-source agent registry (`agents/registry.yaml`); Python discovery + CLI are adapters
- Capability bus wired into `mekong run` (11 builtin capabilities, failure-tolerant)
- MCP→capability bridge (`mcp:<tool_name>` ids) via `McpCapabilityAdapter` + `ToolCapabilityAdapter`
- Scheme-agnostic economic bus: x402 + MPP providers, fail-closed config, no custody
- Canonical Buzz transport (hermetic-by-injection, fail-loud `BuzzConfigError` at call time)
- `CloudflareTransport(Protocol)` with `.dispatch(payload) -> dict`; single import site isolated
- Agent-loop E2E test driving the full GOAL→CONTEXT→PLAN→DELEGATE→EXECUTE→OBSERVE→VERIFY→REPAIR→REMEMBER→COMMIT lifecycle
- 54 files, +5,127 / −843 lines; Core DNA manifest bumped to v2026.08.29
- Quality gates green: ruff clean, pyright 0 new errors, parity gate EMPTY at 277 baseline
- Architecture doc refreshed to v0.2 (scores + next-actions reflect SC5 deliverables)

## v6.1.0 — 2026-08-23

**Design Intelligence (Hallmark deep integration):**
- New `src/design_intelligence/` package: Pydantic v2 schemas (DesignDNA 23 fields,
  DesignBrief, AuditReport, Theme), 58 gates (29 objective / 29 heuristic / 8 visual),
  9-axis scoring, archetype→macrostructure pipeline, provider-agnostic visual QA
- Knowledge base: 58 gates, 21 macrostructures, 12 themes, 4 genres, 16 archetypes
- New `mekong ui` sub-app: audit, study, redesign, build, approve, benchmark
- Three evidence tiers (objective/heuristic/opinion) and three visual-QA tiers
  (full/screenshot/static) kept strictly separate — never over-claimed
- Design memory: approved DNA / rejected patterns via MemoryStore `design:` namespace
  (Sophia contract); `study --export-json` emits parseable DesignDNA JSON
- Change detection + opt-in `mekong deploy --design-audit` advisory hook
  (frontend diffs suggest audit; backend/migration/CLI/infra-only skip)
- Anti-gaming benchmark: 10 fixtures, 7 derived metrics, good vs slop separation
- 140 design-intelligence tests; docs/design-intelligence.md

## v6.0.0 — 2026-08-16

**Highlights:**
- MIT license applied
- Python-only contributor workflow finalized
- 48 commands mapped in COMMAND_REGISTRY.md
- spec-kit SDD artifacts added (specs/, trace.rb, traceability.json)

**Repo parity fixes:**
- Release metadata synced to `minhlongs/mekong-cli`
- GitHub Actions PyPI-only publish path validated