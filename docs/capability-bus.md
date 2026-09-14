# Capability Bus

> Refreshed: 2026-08-26 · Code: `src/core/capability.py`,
> `src/core/adapters/tool_capability_adapter.py`, wiring in
> `src/commands/run.py`

The CapabilityBus is the backbone through which the runtime discovers and
executes tools. Every tool becomes a `Capability` with declared risk,
schema, and source; execution always goes through the bus so governance can
see it.

## Model

```
ToolRegistry ──(ToolCapabilityAdapter)──▶ Capability ──▶ InMemoryCapabilityBus
MCP server   ──(mcp_capability_adapter)─▶                    │
                                                             ▼
                                            bus.list_capabilities() / bus.execute()
```

- `Capability` fields include `capability_id`, `name`, `source`,
  `risk_level` (`LOW|MEDIUM|HIGH|CRITICAL`), input/output schema, cost
  estimate, and an `execute(params, context)` delegate.
- `CapabilitySource`: `BUILTIN | CLI | API | MCP | CUSTOM`.

## Wiring in v0.1

`mekong run` injects an `InMemoryCapabilityBus` by default
(`--with-capabilities` / `--no-capabilities` flag, default ON):

1. `_build_runtime(with_capabilities=True)` creates the bus.
2. `ToolCapabilityAdapter` maps `ToolRegistry.list_tools()` (7 builtins,
   11 registered names including aliases) into capabilities via
   `sync_to_bus`.
3. The bus is passed into `MekongCoreRuntimeImpl(capability_bus=...)`.
4. Failure-tolerant by design: if bus construction raises, `run` logs and
   continues with `capability_bus=None` — capability injection never kills
   a mission.

## Execution path

When a task carries `params["capability_id"]`:

1. Adapter layer denies unknown capabilities (not on bus → DENY).
2. `Governance.classify_risk(cap.risk_level)` decides
   ALLOW / approval-required / deny (see [autonomy-model.md](./autonomy-model.md)).
3. Cost gate runs after governance.
4. `bus.execute(capability_id, params, context)` delegates to the
   capability's execute callable.

## MCP integration

`mcp_capability_adapter.sync_from_mcp()` ingests external FastMCP tool
lists as `CapabilitySource.MCP` entries; e2e tests exercise
sync → list ≥20 tools → `bus.execute("mcp:...", ...)`. Client-side MCP
consumption (this repo acting as an MCP client of other servers) is
deferred beyond v0.1.

## Guarantees

- No capability executes without passing the single governance decision
  path when invoked from the core loop.
- Bus failures degrade gracefully (no hard dependency).
- Hermetic tests: adapter fixtures use tmp registries and never persist
  outside the test sandbox (`tests/test_tool_capability_adapter.py`).
