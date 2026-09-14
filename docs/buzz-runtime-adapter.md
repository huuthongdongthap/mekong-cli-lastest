# Buzz Runtime Adapter

> Refreshed: 2026-08-26 · Code: `src/core/buzz_runtime_adapter.py`,
> `src/core/buzz_adapter.py`

`BuzzRuntimeAdapter` is the versioned facade between an external
orchestrator ("Buzz") and the Mekong core runtime. Callers pin against
`INTERFACE_VERSION = "v0.1"`.

Design rules:

- **No invented network protocol** — plain Python calls in-process, plus
  one injectable transport callable `(url, payload) -> int`.
- **Buzz-optional core** — the core runtime imports buzz lazily inside
  `run_from_payload`; without Buzz everything still runs.
- **Deny-by-default approvals** — mirrors governance semantics.

## Interface v0.1 (8 methods)

| Method | Purpose |
|--------|---------|
| `start_session(goal_hint="", session_id=None, metadata=None)` | open session (duplicate id → `ValueError`) |
| `stop_session(session_id)` | close session; idempotent on unknown ids |
| `assign_mission(payload, session_id=None)` | run a mission from a payload through the runtime |
| `stream_event(event, data, callback_url=None)` | progress event; no-op delivery without callback |
| `request_approval(goal, reason="")` | ask approver; no approver wired → denied |
| `cancel_mission()` | cooperative cancel flag checked between task-loop steps |
| `get_status(mission_id=None)` | tracer-backed status or live fallback |
| `get_artifacts(mission_id=None)` | step artifacts recorded by the tracer |

## Example

```python
from src.core.buzz_runtime_adapter import BuzzRuntimeAdapter
from src.core.runtime_adapter import MekongCoreRuntimeImpl
# Production wiring: src/commands/run.py:_build_runtime() constructs
# MekongCoreRuntimeImpl with memory/billing/tool_registry/governance/bus.

adapter = BuzzRuntimeAdapter(runtime=my_runtime, tracer=tracer)
adapter.start_session(goal_hint="weekly report")

payload = {
    "mission_id": "m_20260826_001",
    "goal": "Summarize this week's commits",
    "callback_url": "https://buzz.example.com/callback",  # optional
}
outcome = adapter.assign_mission(payload)
# outcome = {
#   "interface_version": "v0.1",
#   "mission_id": "m_20260826_001",
#   "status": "completed" | "cancelled" | "failed",
#   "data": {"output": ..., "error": None, "task_id": ...},
# }
```

Payload contract: `goal` (or `text`) is required; optional `mission_id`
(correlates the trace) and `callback_url`. When a callback URL is present,
completion/failure updates are POSTed as JSON via the injected transport
(default: stdlib `urllib`, 5s timeout); transport errors are logged and
swallowed — they never crash a mission. Without a callback URL,
`send_update` is a silent no-op.

## Cancellation semantics

`cancel_mission()` sets a cooperative flag on the runtime; the task loop
checks it before the first execution and between steps. The mission ends
with outcome `"cancelled"` and exactly the attempts already started.

## Versioning policy

Breaking changes to method signatures or outcome shapes bump
`INTERFACE_VERSION`. v0.1 makes no compatibility promises beyond the
string itself.
