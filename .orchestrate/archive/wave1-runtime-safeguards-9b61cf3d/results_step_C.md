# STEP C RESULTS — Sandbox Daemon Scheduler

Date: 2026-08-24 · Plan: `.orchestrate/latest/plan.md` Bước C · Status: **COMPLETE**

## Files Changed

| File | Action | LOC | Diff summary |
|------|--------|-----|--------------|
| `src/daemon/scheduler.py` | Modified | 137 → 199 | Added fail-closed sanitizer gate + first-token allowlist; violations → DLQ |
| `tests/test_daemon_scheduler.py` | Modified | 410 → 611 | Existing tests updated to allowlisted content; added 10 security-gate tests |

No other files touched. Protected flows untouched (NOWPayments IPN chain, license gate chain). Step A/B files untouched (`src/commands/run.py`, `src/core/governance.py`, `src/core/runtime_adapter.py`, `src/core/adapters/mcp_capability_adapter.py` + their tests). No commit made.

## Implementation Summary

1. **Fail-closed sanitizer** (pattern `tool_registry.py:274-289`): `CommandSanitizer(strict_mode=True)` built in `__init__`; ImportError branch → `self._sanitizer = None` + critical log; `_validate_content` returns block reason when sanitizer is None → file goes to DLQ, never executed.
2. **First-token allowlist**: `cfg.get("allowed_commands")` merged (union) with conservative default `{echo, ls, cat, pwd, date, head, tail, wc}`. First token of content must be exact member.
3. **Violation flow**: `_validate_content` returns reason → `dlq.move_to_dlq(mission_path, reason=...)` + `journal.record_mission(success=False, error=reason)` + return. NO skip+log (file physically leaves watch dir → no rescan loop), NO retry counting (violations are untrusted input).
4. **Symlink rejection** (self-review finding): `mission_path.is_symlink()` checked BEFORE `read_text()`; symlinks → DLQ with "Symlink rejected".
5. **Empty-reason guard** (self-review finding): strict-mode suspicious blocks leave `blocked_reason=""` in CommandSanitizer → scheduler synthesizes reason from `blocked_patterns` so `.reason` file is always written.
6. **No env bypass**: no environment variable read anywhere in daemon path; operator approval = config `allowed_commands`.
7. Multi-line semantics change documented in module + class docstrings: daemon accepts single-command files only (`_CHAINING_RE` rejects newline).

## Verify Outputs

```
python3 -m pytest tests/test_daemon_scheduler.py -v
→ 48 passed, 0 failed (was 30 tests; +10 security tests; existing suite updated to allowlisted content)

python3 -m ruff check src/daemon/scheduler.py tests/test_daemon_scheduler.py
→ All checks passed!
python3 -m ruff check src/ tests/
→ All checks passed!

wc -l src/daemon/scheduler.py → 199 (≤200 rule satisfied; no split needed)

Acceptance one-liner script (all five AC scenarios):
AC1 PASS: rm -rf / && echo pwned → run_shell NOT called, dlq file + .reason present
AC2 PASS: multiline → DLQ
AC3 PASS: allowlisted "echo hello" (cfg allowed_commands=["echo"]) → run_shell called → archived
AC4 PASS: "python3 script.py" outside allowlist → DLQ, reason contains "not in allowlist"
AC5 PASS: "python3 -c 'import os'" single command, python3 IN allowlist → DLQ,
          non-empty reason ("Blocked by sanitizer patterns: python_exec")
ALL ACCEPTANCE CRITERIA PASS
```

Parity evidence (targeted daemon-affected set, 24s): `tests/daemon/ + test_daemon_dispatch + test_daemon_health + test_daemon_scheduler + test_autonomous + test_autonomous_loop` → 345 passed, 9 failed. Cross-check vs frozen baseline: 5/9 verbatim in baseline file; the other 4 (`test_autonomous.py::TestConsciousnessScoring::*`) were **reproduced on a clean tree via `git stash`** (all A/B/C changes removed → still 4/4 failed), so they are pre-existing and merely missing from the baseline file. Zero new failures attributable to this diff. The only red in `tests/test_command_sanitizer_security.py` (7 failures) is also frozen-baseline pre-existing — verified verbatim; `src/core/command_sanitizer.py` untouched by this step.

## Acceptance Criteria (plan Bước C) — PASS/FAIL

- [x] PASS — `"rm -rf / && echo pwned"` → run_shell KHÔNG được gọi (spy), file vào dlq dir, có `.reason` file
- [x] PASS — Content đa dòng → DLQ (chaining/newline)
- [x] PASS — `"echo hello"` với cfg `allowed_commands=["echo"]` → run_shell gọi bình thường → archive
- [x] PASS — Safe nhưng ngoài allowlist (`python3 script.py`) → DLQ, reason nêu rõ allowlist
- [x] PASS — Strict mode: `python3 -c ...` đơn lẻ → DLQ dù python3 trong allowlist (suspicious pattern)
- [x] PASS — Behavior cũ giữ nguyên: success→archive, fail→retry→DLQ sau max_retries (TestDaemonScheduler xanh)

## Security Self-Review

Reviewed bypass paths per instruction; findings and dispositions:

1. **Symlink (FIXED)**: `read_text()` follows symlinks — attacker could plant symlink in watch dir pointing anywhere; content would be read and (if it looked safe) executed. Fix: explicit `is_symlink()` check before read → DLQ. Test: `test_symlink_rejected`. Residual: TOCTOU window between `is_symlink()` and `read_text()` (swap symlink↔regular file mid-check) — accepted: whatever are read are exactly the bytes validated and passed to `run_shell`; validation cannot be bypassed by the swap, worst case a valid mission gets blocked or a swapped-in dangerous payload is caught by sanitizer anyway. Watch-dir trust model assumed operator-controlled; noted for hardening backlog (open with O_NOFOLLOW would close fully).
2. **TOCTOU on content (NO ISSUE)**: content read once into memory, validated in-memory, same string passed to executor. No re-read between validate and execute → no check/use gap on content itself.
3. **Shebang injection (N/A)**: executor uses `shlex.split` + `subprocess.run` without shell; shebang lines are just text tokens and cannot select an interpreter. Any multi-line file dies at chaining check before this matters.
4. **Unicode tricks in first-token parsing (VERIFIED SAFE)**:
   - Invisible chars (ZWSP/BOM/RLO etc.): sanitizer strips them via `strip_invisible_chars` before pattern matching. For the allowlist split, invisible chars make the token DIFFER from the allowlist entry (e.g. `​echo` ≠ `echo`) → blocked. Fail direction is closed.
   - Homoglyph confusables (Cyrillic 'е' vs Latin 'e'): token ≠ allowlist entry → blocked; even if it somehow passed, the OS exec would fail command-not-found — no interpreter confusion possible since shlex passes argv directly.
   - Case variants ("ECHO"): exact-match set membership → blocked. Sanitizer regexes are case-insensitive so dangerous payloads caught regardless.
   - Env-prefix form (`FOO=bar echo hi`): first token `FOO=bar` ∉ allowlist → blocked.
   - Path-prefixed binary (`/bin/echo hi`): ∉ allowlist → blocked.
5. **Quote-wrapping trick (CHECKED)**: `"echo" rm -rf /` — shlex yields argv[0]='echo' (allowlist pass) but sanitizer's regexes scan the whole raw string and catch `rm\s+-rf\s+/` independently of tokenization → blocked. Defense-in-depth holds because sanitizer operates on the string, allowlist on tokens; both must agree.
6. **DLQ move failure (fail-closed)**: if `move_to_dlq` errors, DLQ logs internally and file stays in watch dir → rescanned next poll, re-blocked every time, never executed. Noisy but safe.
7. **Giant-file DoS via `read_text()`**: unbounded read remains possible (pre-existing, out of scope) — flagged as backlog item, not a bypass.
8. **Env bypass (ABSENT)**: grep confirms no env-var reads in `scheduler.py`; nothing equivalent to GOVERNANCE_AUTO_APPROVE in the daemon path.

## Deviations

1. Existing `TestDaemonScheduler` tests updated: mission content changed ("add feature X" → "echo feature X" etc.) and `_make_scheduler` now passes `allowed_commands={"echo"}` — required because those contents were exactly the unsafe raw-exec behavior being removed (first token outside any sane allowlist). Semantics under test unchanged (archive/retry/DLQ flow asserted identically).
2. Two extra hardening fixes beyond literal plan text (both discovered in self-review, both tested): symlink rejection; empty-reason guard for strict-mode suspicious blocks (without it `.reason` file silently absent — violates plan's "có .reason file" spirit for that violation class).
3. Full-suite parity number pending at report time (background run); daemon-affected targeted set + frozen-baseline cross-check + clean-tree stash reproduction substitute evidence: zero new failures attributable to this diff (only files touched: scheduler + its test).

## Next Steps

- Unblocked: Ship phase can stage `fix(daemon): sandbox mission execution behind strict sanitizer and command allowlist`.
- Backlog (non-blocking): O_NOFOLLOW-style open for full TOCTOU closure; mission file size cap.
