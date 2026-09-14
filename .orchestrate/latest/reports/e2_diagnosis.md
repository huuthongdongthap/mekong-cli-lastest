# Lane E2 — world_model collection/run hang: DIAGNOSIS

**Date:** 2026-08-27 · **Worktree:** `/Users/macbook/mekong-cli/.claude/worktrees/super-command-2` @ `d71e13fa02`
**Scope:** diagnosis only — no source modified. All commands wrapped in `timeout`.

---

## 1. Verdict (one line)

**A prune-before-descend bounded walk FIXES it.** The hang is not a repo-size problem (worktree walk = 0.03s); it is `WorldModel()` defaulting `working_dir=os.getcwd()` combined with a cwd leak to `/` from another test, so `rglob("*")` walks the entire filesystem. A bounded walk from `/` completes in 0.11s. Fix the walk AND harden the test to pass an explicit `working_dir`; the fallback (keep `--ignore`) is NOT needed.

---

## 2. Confirmed root cause (evidence chain)

1. `src/core/world_model.py:111` — `self.working_dir = working_dir or os.getcwd()`. No explicit dir ⇒ cwd.
2. `src/core/world_model.py:334` — `for item in root.rglob("*"):` descends the **entire** tree unpruned.
   - Exclusions (`:326-330`) are filtered **post-hoc** at `:340` — descent already happened.
   - Depth skip (`:337`) does `continue` but does **not** prune descent into deeper dirs.
   - Cap 500 (`:344`) limits **output** only, not the walk.
3. `tests/test_world_model.py:129-153` — `test_predict_*` and `test_get_latest_snapshot` instantiate `WorldModel()` with **no** `working_dir` ⇒ inherits cwd.
4. **The leak:** `tests/test_company_init_cli.py:62-72` — the `initialized` fixture does `os.chdir(tmp_path)` then `os.chdir("/")` and **never restores** cwd. After it runs, cwd is `/`.
5. When `test_world_model` runs after `test_company_init_cli` in the same session, `WorldModel()` sees cwd=`/`, and `rglob("*")` walks the whole filesystem → hang.

**Note on the plan's named leakers:** the plan listed 5 files (`test_build_cli`, `test_company_init_cli`, `test_plan_cli`, `test_run_command_wiring`, `test_zx_executor`). Verified: only `test_company_init_cli` actually leaks (to `/`). The others either restore cwd (`test_zx_executor`, `test_run_command_wiring` via `monkeypatch.chdir`) or don't leak in a way that matters. `test_build_cli`/`test_plan_cli` use `monkeypatch.chdir` (auto-restored). The **confirmed** leaker is `test_company_init_cli.py:72` (`os.chdir("/")` with no restore).

---

## 3. Measurements

| # | Command | Result |
|---|---------|--------|
| 1 | `timeout 120 pytest tests/test_world_model.py --collect-only -q` | **Completes in 0.05s** (18 tests). Collection is NOT the hang. |
| 2 | `timeout 120 pytest tests/test_world_model.py -q` (standalone) | **PASSES, 18 passed in 10.83s.** No hang standalone (cwd = repo root, walk = 0.03s). |
| 3 | `timeout 120 pytest tests/test_company_init_cli.py tests/test_world_model.py -q` | **HANGS.** Killed at 120s. Output stalls mid-`test_world_model` (after `test_company_init_cli` leaked cwd to `/`). This is the reproduction. |
| 4 | faulthandler script (`/tmp/wm_hang_diag.py`, cwd=`/`, `dump_traceback_later(15)`) | **Stack confirms stuck at `src/core/world_model.py:334`** (`for item in root.rglob("*")`), inside `_get_file_tree`, called from `snapshot()`. |
| 5a | `find <worktree> -type f \| wc -l` | **6601 files** (7602 total entries incl. dirs). |
| 5b | Unpruned `os.walk('/')` (25s budget) | **>1.5M entries and still counting** (partial: 550k at one checkpoint, never completes). This is what `rglob("*")` from `/` does. |
| 5c | Worktree walk with explicit `working_dir` | **0.03s, 500 entries** (cap hit). Repo size is NOT the problem. |
| 5d | Simulated bounded walk (prune-before-descend + visited cap 50k) from `/` | **0.11s, visited=5315, files=537.** The fix bounds the `/` case. |

---

## 4. Exact reproduction steps

```bash
cd /Users/macbook/mekong-cli/.claude/worktrees/super-command-2
# Reproduces the hang (cwd leak to / then world_model inherits it):
timeout 120 python3 -m pytest tests/test_company_init_cli.py tests/test_world_model.py -q --tb=line
# → stalls inside test_world_model, killed at 120s

# Confirms the stuck stack:
python3 /tmp/wm_hang_diag.py   # chdir('/'), WorldModel(), faulthandler dump at 15s
# → File "src/core/world_model.py", line 334, in _get_file_tree
```

---

## 5. Confirmed stuck stack (faulthandler)

```
Timeout (0:00:15)!
Current thread 0x... (most recent call first):
  File ".../src/core/world_model.py", line 334, in _get_file_tree
  File ".../src/core/world_model.py", line 127, in snapshot
  ...
```
Points exactly at the `root.rglob("*")` line. Confirmed.

---

## 6. Fix guidance for the next agent

**Primary fix (recommended):** rewrite `_get_file_tree()` (`src/core/world_model.py:324-348`) as a bounded iterative walk:
- Check exclusions + depth **before** descending (prune-before-descend), not post-hoc.
- Keep output cap 500 AND add a hard visited-entry cap (e.g. 50k) so a leaked cwd can never walk millions of entries.
- Preserve output shape (list of relative path strings).
- Measured: bounded walk from `/` = 0.11s / 5315 visited. Safe.

**Test hardening (required alongside):** `tests/test_world_model.py:129-153` must pass an explicit `working_dir` (e.g. `tmp_path`) so it never inherits a leaked cwd. Add a guard test: WorldModel over a tmp tree containing a large excluded dir must not descend into it.

**Also fix the actual leaker:** `tests/test_company_init_cli.py:72` `os.chdir("/")` should restore cwd (or use `monkeypatch.chdir`). This is the true source of the leak; fixing it removes the hazard for any future cwd-sensitive test.

**Fallback (NOT needed):** keeping `--ignore=tests/test_world_model.py` is unnecessary — the bounded walk provably bounds the worst case. Only re-escrow if the fix changes output semantics in a way tests reject.

---

## 7. Open questions

- None blocking. The fix is well-bounded. Only decision left for the fixer: exact visited-cap value (50k suggested) and whether to also patch the `test_company_init_cli` leaker in the same commit (recommended, it's the root leak source).
