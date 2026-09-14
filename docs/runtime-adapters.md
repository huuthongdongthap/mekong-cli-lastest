# Runtime Adapters

> Refreshed: 2026-08-26 · Code: `src/core/exec_runtime/`
> (`types.py`, `local.py`, `cloudflare.py`, `docker.py`), reuse of `src/core/command_sanitizer.py`

`ExecutionRuntime` is the Protocol that isolates *where and how* agent
actions actually run. v0.2 ships three implementations: local-first,
plus Cloudflare and Docker remote runtimes (hermetic by construction).

## ExecutionRuntime protocol

| Method | Contract |
|--------|----------|
| `execute(command, *, timeout_s=None) -> ExecResult` | run a command; failures return `ExecResult(ok=False)`, never raise |
| `filesystem()` | facade confined to a root directory (path-traversal safe) |
| `process()` | tracked process control (terminate/kill) |
| `network_policy()` | declared policy struct |
| `environment()` | environment snapshot |
| `preview(request)` | dry-run: what would execute, blocked reasons |
| `health()` | liveness/state report |
| `destroy()` | terminate all tracked processes; execute refuses afterwards |

## LocalExecutionRuntime

- **Subprocess with real timeouts** — `communicate(timeout=...)`, kill +
  reap on expiry; SIGTERM→SIGKILL escalation for cancellation.
- **Shell-shaped commands are sanitized** — string commands pass through
  `CommandSanitizer(strict_mode=True)` first; injection attempts return
  `ExecResult(ok=False, error="blocked by sanitizer: ...")`.
- **Filesystem confinement** — `SandboxSpec.resolve_in_root` resolves then
  verifies the path stays inside the root (symlink-aware). `../../etc/passwd`,
  absolute paths outside the root, and symlink escapes all raise
  `PermissionError`.
- **Network policy is honest about being a placeholder** — default is a
  deny-all struct (`allow_outbound=False`, description "not enforced").
  There is NO enforcement layer yet; do not treat it as a security
  boundary.

## CloudflareExecutionRuntime (v0.2)

Remote adapter behind an **injected transport** — hermetic by construction.

- **Injected `CloudflareTransport`** — every remote call goes through the
  transport passed at construction. No transport is ever constructed
  implicitly, so this module can never reach the real Cloudflare API on its
  own. Implementations own the wire protocol (HTTP, RPC, in-memory fake).
- **Same confinement + sanitization as local** — filesystem ops use
  `SandboxSpec.resolve_in_root`; shell-shaped commands pass
  `CommandSanitizer(strict_mode=True)`. No second confinement path.
- **`WorkerConfig`** translates the spec into the payload the remote worker
  receives (account_id, script_name, command, shell, cwd, env, timeout_s).
- **Network policy defaults to deny-all** (placeholder struct, not enforced).

## DockerExecutionRuntime (v0.2)

Container-backed adapter via the docker CLI, behind an injected runner.

- **Injected `DockerRunner` Protocol** — mirrors `subprocess.run` semantics
  for the subset used. `CliDockerRunner` is the real-CLI default (never used
  in tests); tests inject a fake to stay hermetic.
- **Same confinement + sanitization as local** — `SandboxSpec.resolve_in_root`
  and `CommandSanitizer(strict_mode=True)`.
- **Network policy maps to `--network none`** by default (deny-all); an
  allow-outbound policy maps to the default bridge network.
- **Hermetic unit path** — command construction, spec-to-container
  translation, and error handling run without a daemon. The only daemon
  touchpoint is the `docker info` probe in `health()`, gated skip-if-no-daemon.

## Planned (not built in v0.2)

- **Real network enforcement** — replace the deny-all placeholder struct
  with an enforced policy (applies to all three runtimes).

Both remote adapters satisfy the same structural Protocol as
`LocalExecutionRuntime`; no core code changes were needed to adopt them.

## Tests

| Test File | Runtime | Tests |
|-----------|---------|-------|
| `tests/test_local_execution_runtime.py` | Local | exec success/failure, stderr capture, timeout kill, cancel/destroy, injection blocking (`rm -rf /`, chained commands, backticks), path traversal, symlink escape, policy/env/preview/health, Protocol conformance |
| `tests/test_cloudflare_execution_runtime.py` | Cloudflare | WorkerConfig→payload translation, injected transport dispatch, timeout propagation, deny-all network policy, filesystem confinement, sanitizer passthrough |
| `tests/test_docker_execution_runtime.py` | Docker | container run/stop, network policy mapping (`--network none` vs bridge), injected runner hooks, daemon probe skip-if-no-daemon, hermetic unit path |

All three adapters share the same `SandboxSpec.resolve_in_root` + `CommandSanitizer(strict_mode=True)` test patterns.
