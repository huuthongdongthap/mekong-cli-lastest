# Plan: Wrap LLMClient behind LLMRouter Protocol

## Reframed Problem

`LLMClient` (src/core/llm_client.py) contains real production logic — provider
failover, LRU caching, hooks pipeline, circuit breaker — and 32 caller files
depend on it. `LLMRouterAdapter` (src/core/llm_router_adapter.py) is a stub
that implements the `LLMRouter` Protocol but returns `"[stub]"` strings from
`generate()`. The goal is to make the adapter a real delegating wrapper so
callers can eventually migrate to the Protocol interface without losing any
production behavior.

**Decision:** WRAP, NOT REPLACE. `LLMClient` stays intact. The adapter
delegates to it. Callers are not migrated in this task.

---

## Scout Evidence

| Source | File | Key Fact |
|--------|------|----------|
| LLMClient | `src/core/llm_client.py` | 616 lines. Public API: `chat()`, `generate(prompt, **kwargs) -> str`, `generate_json()`, `is_available`, `get_client()`. Provider failover + hooks + cache + circuit breaker. |
| LLMRouterAdapter | `src/core/llm_router_adapter.py` | 110 lines. All 7 Protocol methods present. `generate()` returns `"[stub]"` strings. Lazy-loads `src.daemon.llm_router.LLMRouter` (different class, not the Protocol). |
| LLMRouter Protocol | `src/core/protocols.py:140-149` | 7 methods: `classify`, `select_model`, `estimate_cost`, `generate`, `stream`, `structured_output`, `health`. |
| Daemon LLMRouter | `src/daemon/llm_router.py` | Different class entirely — capability-based Task routing, health-check, circuit breaker. Used by `daemon/mission_dispatch.py`. NOT the Protocol. |
| DUPLICATION_MAP #5 | `docs/architecture/DUPLICATION_MAP.md:68` | Documents 3 routing systems. Status: DEFERRED — WRAP NOT REPLACE. |
| DEPRECATION_MAP #2 | `docs/architecture/DEPRECATION_MAP.md` | Status: DEFERRED — WRAP, NOT REPLACE. |
| Runtime adapter | `src/core/runtime_adapter.py:147-149` | `MekongCoreRuntimeImpl._default_llm_router()` instantiates `LLMRouterAdapter()`. Already wired as default. |
| Core exports | `src/core/__init__.py:89,134` | `LLMRouterAdapter` already exported in `__all__` and lazy import map. |
| Callers | 32 files across `src/` | All use `get_client()` or `LLMClient(...)` directly. None use `LLMRouterAdapter` for actual generation. |
| Existing tests | `tests/test_llm_router_expanded.py` | 10 tests — all test stub behavior (assert `"[stub]"` in output). These tests WILL need updating. |
| Existing tests | `tests/test_llm_router_stream.py` | 9 tests — stream/structured_output tests against stub. |
| Existing tests | `tests/test_protocol_compliance.py:51-54` | Adapter satisfies Protocol (still passes — duck typing). |

---

## Work Checklist

### Step 1: Implement real delegation in LLMRouterAdapter
**Agent:** code-simplifier or fullstack-developer

**What:**
- Modify `LLMRouterAdapter.__init__()` to accept an optional `LLMClient` instance.
  If none provided, create one via `get_client()`.
- Replace `generate()` stub: delegate to `self._llm_client.generate(prompt, **kwargs)`.
- Replace `stream()` stub: call `self._llm_client.chat()` (streaming not in LLMClient)
  then yield the full response as a single chunk. Log that streaming is not natively
  supported by LLMClient — yields `[text]` once.
- Replace `structured_output()` stub: use `self._llm_client.generate_json(prompt, **kwargs)`
  to get parsed JSON. Return `{"text": ..., "parsed": ..., "schema": schema}`.
- `classify()`, `select_model()`, `estimate_cost()`: keep current behavior (no change —
  these are classification/routing methods, not generation).
- `health()`: return `{"status": "ok", "providers": [p.name for p in client.providers]}`.

**Acceptance criteria:**
- `LLMRouterAdapter().generate("hello")` returns real LLM output, not `"[stub]"`.
- `LLMRouterAdapter(client=my_client).generate(...)` uses injected client.
- `isinstance(LLMRouterAdapter(), LLMRouter)` still passes.
- No import of `src.daemon.llm_router.LLMRouter` (remove the lazy import of the daemon
  class — it's a different system).

**Files:**
- Edit: `src/core/llm_router_adapter.py`

---

### Step 2: Update existing adapter tests
**Agent:** tester

**What:**
- Update `tests/test_llm_router_expanded.py`:
  - `test_generate_returns_string` — mock `LLMClient.generate()` to return real string,
    assert adapter delegates to it.
  - `test_generate_with_model` — assert adapter calls `LLMClient.generate(prompt, model=...)`.
  - `test_generate_passes_kwargs` — assert kwargs forwarded.
  - Remove assertions on `"[stub]"` content.
- Update `tests/test_llm_router_stream.py`:
  - `test_stream_yields_content` — mock `LLMClient.chat()`, assert chunk is yielded.
  - `test_stream_with_model_parameter` — assert model forwarded to chat().
  - Remove assertions on `"[stub]"` / `"[stub] ... (stream fallback)"`.
- Update `tests/test_protocol_compliance.py` — no change needed (duck typing test passes).

**Acceptance criteria:**
- `python3 -m pytest tests/test_llm_router_expanded.py -v` passes.
- `python3 -m pytest tests/test_llm_router_stream.py -v` passes.
- No test asserts on `"[stub]"` content.

**Files:**
- Edit: `tests/test_llm_router_expanded.py`
- Edit: `tests/test_llm_router_stream.py`

---

### Step 3: Add dual-provider interface test
**Agent:** tester

**What:**
- Create `tests/test_llm_router_adapter_real.py` with:
  - `test_two_providers_satisfy_same_protocol` — instantiate two different
    LLMClient configs (e.g., OpenAICompatibleProvider + OfflineProvider), wrap
    each in `LLMRouterAdapter`, assert both satisfy `LLMRouter` Protocol.
  - `test_generate_delegates_to_client` — mock LLMClient, verify `generate()`
    call chain.
  - `test_chat_delegates_to_client` — verify `chat()` method (LLMClient.chat)
    is accessible through adapter.
  - `test_is_available_reflects_client` — verify `is_available` property
    reflects underlying client state.

**Acceptance criteria:**
- `python3 -m pytest tests/test_llm_router_adapter_real.py -v` passes.
- Test proves at least 2 provider configs can satisfy the same interface.

**Files:**
- Create: `tests/test_llm_router_adapter_real.py`

---

### Step 4: Full test suite verification
**Agent:** tester

**What:**
- Run `python3 -m pytest tests/ -v` — full suite must pass.
- Run `ruff check src/ tests/` — no new lint errors.
- Run `python3 -m mypy src/core/llm_router_adapter.py --ignore-missing-imports` — type check.

**Acceptance criteria:**
- All existing tests pass (62+ tests).
- Zero new ruff errors.
- No type: ignore added.

**Files:** None (verification only).

---

### Step 5: Update DUPLICATION_MAP and DEPRECATION_MAP
**Agent:** docs-manager

**What:**
- Update `docs/architecture/DUPLICATION_MAP.md` entry #5:
  - Change status from DEFERRED to IN PROGRESS or RESOLVED (adapter now delegates to LLMClient).
  - Note: 3 systems remain (daemon LLMRouter is separate concern), but adapter now wraps LLMClient.
- Update `docs/architecture/DEPRECATION_MAP.md` entry #2:
  - Change status from DEFERRED to WRAPPED (adapter delegates, callers not yet migrated).

**Acceptance criteria:**
- Status updated in both docs.
- Rationale documented.

**Files:**
- Edit: `docs/architecture/DUPLICATION_MAP.md`
- Edit: `docs/architecture/DEPRECATION_MAP.md`

---

### Step 6: Pre-deploy checklist (typecheck / test / build)
**Agent:** tester

**What:**
- `ruff check src/ tests/` — 0 errors.
- `python3 -m pytest tests/ -v` — all pass.
- `python3 -m mypy src/core/llm_router_adapter.py --ignore-missing-imports` — no new errors.

**Acceptance criteria:** All three gates green.

**Files:** None (verification only).

---

### Step 7: Commit
**Agent:** git-manager

**What:**
- Stage: `src/core/llm_router_adapter.py`
- Stage: `tests/test_llm_router_expanded.py`
- Stage: `tests/test_llm_router_stream.py`
- Stage: `tests/test_llm_router_adapter_real.py`
- Stage: `docs/architecture/DUPLICATION_MAP.md`
- Stage: `docs/architecture/DEPRECATION_MAP.md`
- Conventional commit message:
  `feat(core): wrap LLMClient behind LLMRouter Protocol via real adapter delegation`

**Acceptance criteria:**
- Clean commit on feature branch.
- No secrets, no `[stub]` content in committed adapter code.

**Files:** None (git operation only).

---

### Step 8: PR
**Agent:** git-manager

**What:**
- Push branch.
- Create PR with description referencing DUPLICATION_MAP #5 and DEPRECATION_MAP #2.
- Link task: "Wrap LLMClient behind LLMRouter Protocol".

**Acceptance criteria:**
- PR created with descriptive title and body.
- CI triggers on PR.

**Files:** None (git operation only).

---

### Step 9: CI verify
**Agent:** tester (monitor CI)

**What:**
- Poll `gh run list -L 1 --json status,conclusion` until gates pass.
- All 5 gates (G1-G5 + merge-gate) must be green.
- If any gate red: fix and re-push.

**Acceptance criteria:** All CI gates green.

**Files:** None (CI verification only).

---

### Step 10: Merge
**Agent:** git-manager

**What:**
- Merge PR to main (squash merge preferred).
- Delete feature branch.

**Acceptance criteria:** Main has the adapter implementation.

**Files:** None (git operation only).

---

### Step 11: Deploy (per CLAUDE.deploy.md doctrine)
**Agent:** tester

**What:**
- Execute deploy smoke tests per doctrine:
  - `[PASS]` `python3 -m pytest tests/ -q --tb=short` exits 0.
  - `[PASS]` `ruff check src/` exits 0.
  - `[SKIP: no feature CLI command]` Feature command responds without error.
  - `[PASS]` No new type: ignore introduced.
  - `[PASS]` No secrets in output files.
- Check `gh run list -L 1 --json status,conclusion` for latest gate status.
- Write `.mekong/DEPLOY_REPORT.md` with verdict SHIP (all gates green).

**Acceptance criteria:**
- DEPLOY_REPORT.md written with SHIP verdict.
- All smoke tests PASS or SKIP (with reason).

**Files:** None (deploy verification only).

---

### Step 12: Prod smoke
**Agent:** tester

**What:**
- After merge, verify production environment:
  - `python3 -c "from src.core.llm_router_adapter import LLMRouterAdapter; a = LLMRouterAdapter(); print(a.health())"` — should return `{"status": "ok", ...}`.
  - `python3 -c "from src.core.protocols import LLMRouter; from src.core.llm_router_adapter import LLMRouterAdapter; assert isinstance(LLMRouterAdapter(), LLMRouter)"` — protocol compliance.

**Acceptance criteria:** Adapter works in prod environment.

**Files:** None (smoke only).

---

### Step 13: Feature smoke
**Agent:** tester

**What:**
- Verify existing callers still work (no migration done, but adapter exists):
  - `python3 -c "from src.core.llm_client import get_client; c = get_client(); print(c.generate('hello'))"` — should return real output.
  - `python3 -c "from src.core.runtime_adapter import MekongCoreRuntimeImpl; print('runtime importable')"` — runtime adapter still wires LLMRouterAdapter.

**Acceptance criteria:** Existing callers unaffected. Adapter available for future migration.

**Files:** None (smoke only).

---

### Step 14: Rollback readiness
**Agent:** tester

**What:**
- Document rollback plan:
  - `git revert HEAD` (revert commit, no force).
  - No feature flag needed (adapter is additive, not replacing).
  - No data migration needed.
  - No schema changes.

**Acceptance criteria:** Rollback plan documented in DEPLOY_REPORT.md.

**Files:** None (documentation only).

---

### Step 15: Ops journal
**Agent:** journal-writer

**What:**
- Record in journal:
  - What was done: LLMRouterAdapter now delegates to LLMClient (real production logic).
  - What was NOT done: 32 caller files not migrated (future task).
  - Impact: Adapter is now usable for new code; existing callers unchanged.
  - Risk: LOW — additive change, no existing behavior altered.

**Acceptance criteria:** Journal entry recorded.

**Files:** None (journal only).

---

## Risks & Gates

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking 32 existing callers | HIGH | No callers migrated — adapter is additive only. `LLMClient` public API unchanged. |
| Existing stub tests fail | MEDIUM | Step 2 explicitly updates tests before implementation. |
| Protocol compliance breaks | MEDIUM | `isinstance(adapter, LLMRouter)` tested in existing tests + new tests. |
| Daemon LLMRouter confusion | LOW | Adapter no longer imports `src.daemon.llm_router` — removes coupling to different system. |
| Stream not natively supported | LOW | LLMClient has no stream method. Adapter yields full response as single chunk. Documented limitation. |
| LLMClient constructor overhead | LOW | `get_client()` is singleton — adapter reuses it. No double-instantiation. |

**Gates:**
- Gate 1: Step 2 tests pass (adapter tests updated before implementation).
- Gate 2: Step 4 full suite passes.
- Gate 3: Step 6 pre-deploy (ruff + mypy + pytest).
- Gate 4: Step 9 CI gates all green.
- Gate 5: Step 11 deploy smoke tests pass.

---

## Agent Assignments

| Step | Agent | Rationale |
|------|-------|-----------|
| 1 | fullstack-developer | Core implementation — adapter delegation. |
| 2 | tester | Test updates — mock-based, protocol compliance. |
| 3 | tester | New test file creation. |
| 4 | tester | Full suite verification. |
| 5 | docs-manager | Documentation update. |
| 6 | tester | Pre-deploy gates. |
| 7 | git-manager | Commit. |
| 8 | git-manager | PR creation. |
| 9 | tester | CI monitoring. |
| 10 | git-manager | Merge. |
| 11 | tester | Deploy verification per doctrine. |
| 12 | tester | Prod smoke. |
| 13 | tester | Feature smoke. |
| 14 | tester | Rollback documentation. |
| 15 | journal-writer | Ops journal entry. |

---

## What to Avoid

- Do NOT rewrite `LLMClient` — it has real production logic that works.
- Do NOT migrate the 32 caller files — this task only makes the adapter work.
- Do NOT import `src.daemon.llm_router.LLMRouter` in the adapter — it's a
  different system (capability-based routing for daemon missions).
- Do NOT remove `"[stub]"` fallbacks from error paths in stream/structured_output —
  they become real fallbacks when LLMClient fails, not stubs.
- Do NOT add `# type: ignore` to the adapter.
- Do NOT change the public API of `llm_client.py` (`get_client()`, `LLMClient`,
  `LLMClient.generate()`, `LLMClient.chat()`).

---

## Assumptions

| Assumption | Confidence | What would change |
|------------|------------|-------------------|
| `get_client()` singleton is safe to use in adapter constructor | HIGH | If callers need different LLMClient instances, adapter must accept explicit client. |
| `LLMClient.generate()` signature (`prompt, **kwargs`) covers adapter needs | HIGH | If Protocol callers pass unsupported kwargs, adapter must filter. |
| Existing tests asserting `"[stub]"` content will be updated | HIGH | If tests are treated as source-of-truth, adapter must keep stub behavior (contradicts task). |
| Daemon LLMRouter (`src/daemon/llm_router.py`) is separate system, not part of this wrap | HIGH | If it's meant to be unified, task scope increases significantly. |
| `LLMClient` has no streaming support — adapter yields single chunk | MEDIUM | If streaming is critical, adapter must implement token-by-token iteration over LLMClient. |

---

## Success Metrics

- `isinstance(LLMRouterAdapter(), LLMRouter)` returns True.
- `LLMRouterAdapter().generate("hello")` returns real LLM output (not `"[stub]"`).
- All 62+ existing tests pass.
- Zero new ruff/type errors.
- DUPLICATION_MAP #5 and DEPRECATION_MAP #2 updated.
- 32 existing callers unaffected (no migration).
- PR merged, CI green, deploy smoke passes.
