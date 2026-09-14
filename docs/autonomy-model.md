# Autonomy Model

> Refreshed: 2026-08-27 · Code: `src/core/governance.py`,
> `src/core/agent_registry.py`, gate hook in
> `src/core/runtime_adapter.py::execute`

Autonomy is governed by ONE decision path: every capability-backed execution
flows through `Governance`. There is no second permission system.

## Risk levels → decision classes

`RISK_LEVEL_MAP` (class-level, deterministic):

| Capability risk level | Action class | Behavior |
|----------------------|--------------|----------|
| `LOW` | `SAFE` | auto-execute; audit entry recorded |
| `MEDIUM` | `SAFE` (+ mandatory audit) | auto-execute; audit entry recorded |
| `HIGH` | `REVIEW_REQUIRED` | blocked until approval |
| `CRITICAL` | `FORBIDDEN` | always denied — no approval can unlock |

Unknown risk levels fall back to `SAFE` with a logged warning (fail-open,
explicitly chosen and documented).

## Decision path for an execution

```
task.params has capability_id?
        │ no → legacy gates only (goal governance, cost ceiling)
        ▼ yes
capability on bus? ──no──▶ DENY (unauthorized capability)
        │ yes
Governance.classify_risk(cap.risk_level)
        │
   ┌────┴─────────┬───────────────────┐
   ▼              ▼                   ▼
 SAFE          REVIEW_REQUIRED     FORBIDDEN
 proceed       request_approval    step blocked
 (audited)     → approved: run     status=blocked_by_governance
               → denied: blocked
```

Cost ceiling (`max_cost_usd`) is enforced as a separate later gate inside
`execute()`.

## GOVERNANCE_AUTO_APPROVE semantics

Setting `GOVERNANCE_AUTO_APPROVE=true|1|yes` bypasses the human approval
step for non-forbidden actions. The bypass is **loud**, never silent:

- a `WARNING`-level log line names the action being auto-approved;
- an audit entry (`result="approved"`) is recorded on the audit trail.

This is an explicit operator decision kept intact from earlier versions —
v0.1 makes it observable instead of removing it. `CRITICAL` actions ignore
the flag entirely. The rejection path (env unset) also logs a WARNING and
records `result="rejected"`.

## Declarative agent policy fields

`AgentMeta` declares autonomy up front:

| Field | Default | Validation |
|-------|---------|------------|
| `risk_level` | `"LOW"` | must be LOW/MEDIUM/HIGH/CRITICAL |
| `allowed_tools` | `[]` | empty or `["*"]` = unrestricted |
| `approval_policy` | `"AUTO"` | AUTO/MANUAL/DENY |
| `max_budget` | `None` | optional ceiling |
| `max_iterations` | `None` | optional loop bound |
| `model_preference` | `None` | optional routing hint |

Hard rule: **a CRITICAL-risk agent cannot declare `approval_policy=AUTO`**
(registration raises). Defaults keep every existing registration valid.

## Agent policy enforcement (v0.2)

When a task carries a `capability_id` and the bus has that capability,
`execute()` enforces the acting agent's policy fields BEFORE any dispatch,
as five ordered gates in `runtime_adapter.py::execute`:

| # | Gate | Behavior |
|---|------|----------|
| 1 | `risk_level` | effective risk = max(agent.risk_level, capability.risk_level); `FORBIDDEN` blocks immediately |
| 2 | `allowed_tools` | capability not in the agent's allowlist → rejected (empty list or `["*"]` = unrestricted) |
| 3 | `max_budget` | projected spend (current + capability cost) over the agent's ceiling → rejected; spend recorded only after successful dispatch |
| 4 | `max_iterations` | repair count at/over the agent's cap → rejected |
| 5 | `approval_policy` | `DENY` always rejects; `MANUAL`/`AUTO` route `REVIEW_REQUIRED` through `request_approval()` (AUTO bypassable via `GOVERNANCE_AUTO_APPROVE`) |

Ordering matters: `allowed_tools` runs before approval so a disallowed
capability is never surfaced to a human approver. Unknown/unregistered
agents keep capability-only classification but still fail-closed on an
unknown capability risk level (invalid risk string can never default-allow).

## Audit guarantee

Every classify/classify_risk/approval path writes an audit entry
(`record_audit`). Audit persistence is failure-tolerant: if the sink is
unwritable the decision still proceeds with the entry retained in memory.
