# Mekong CLI Command Registry

Single source of truth for all wired commands. Auto-generated from `build_app()`.

## Quick Count

| Metric | Count |
|--------|-------|
| Registered groups | 39 |
| Total commands | 128 |

## Command Index

| # | Group | Commands | Module |
|---|-------|----------|--------|
| 1 | agent | assemble, create, info, init, list, run | commands.agent_commands |
| 2 | agi | (sub-app) | commands.agi |
| 3 | analyze | check | commands.analyze |
| 4 | autonomous | predict, reflect, resume, run, status, world | cli.autonomous_commands |
| 5 | billing | emit-event, reconcile, simulate, status, submit-usage, sync, sync-status | cli.billing_commands |
| 6 | binh-phap | (sub-app) | cli.binh_phap_commands |
| 7 | bmad | catalog, info, list, run, search | cli.bmad-commands |
| 8 | browse | analyze, check, links | cli.tools_browse_collab_commands |
| 9 | build | from-plan | cli.commands.build |
| 10 | code | new | cli.sdlc.code |
| 11 | collab | agents, debate, review, stats | cli.tools_browse_collab_commands |
| 12 | company | init, reset, status | cli.commands.company_init |
| 13 | deploy | new, rollback, run, status | cli.sdlc.deploy + commands.deploy |
| 14 | design | new | cli.sdlc.design |
| 15 | doctor | check | cli.commands.doctor_command |
| 16 | founder | assess, list, review | cli.commands.founder |
| 17 | goal | cancel, create, list, resume, run, run-parallel, status, verify | cli.goal_commands |
| 18 | governance | list, propose, tally, vote | cli.governance_commands |
| 19 | idea | run | cli.idea_commands |
| 20 | implement | run | cli.commands.implement |
| 21 | ke-toan | create, journal, summary, xml | cli.funnel_commands |
| 22 | marketplace | list | cli.commands.marketplace_commands |
| 23 | memory | clear, list, search, stats | cli.memory_commands |
| 24 | particle | connect, init, status | cli.commands.particle_init |
| 25 | pev | history, run, status | cli.pev_commands |
| 26 | plan | from-init | cli.commands.plan |
| 27 | plugin | init, install, list, uninstall | cli.commands.plugin_install |
| 28 | schedule | add, list, remove | cli.schedule_commands |
| 29 | spec | new | cli.sdlc.spec |
| 30 | specify | new, run | cli.commands.specify |
| 31 | swarm | run, supervise | cli.commands.swarm_orchestration |
| 32 | tasks | run | cli.commands.tasks |
| 33 | telegram | start, status | cli.autonomous_commands |
| 34 | thue | gtgt, tncn, tndn | cli.funnel_commands |
| 35 | tools | discover, list, run, stats, video (sub-app) | cli.tools_browse_collab_commands + commands.sophia_video |
| 36 | ui | approve, audit, benchmark, build, redesign, study | cli.ui_commands |
| 37 | usage | export, overage, report, show, sync | cli.usage_commands |
| 38 | vendor | delist, list, onboard | cli.commands.vendor_marketplace |
| 39 | zalo-oa | broadcast, caption, followers, post, send | cli.funnel_commands |

## Vietnam Business Funnels (100% Complete)

Three core business funnels and Sophia Video Factory wired into the `mekong` binary:

| Group / Sub-App | Purpose | Offline / Dry-Run? |
|-----------------|---------|--------------------|
| `zalo-oa` | Zalo OA messaging, broadcast, followers, caption, posting | caption only |
| `thue` | Thuế TNCN lũy tiến, TNDN, GTGT | yes (offline calculations) |
| `ke-toan` | Hóa đơn TT78/2021, bút toán VAS, XML | yes (offline calculations) |
| `tools video` / `sophia` | AI Video Factory (Sophia) — RaaS video production, Design DNA, MCU billing | yes (deterministic dry-run) |

## Spec-kit SDD Pipeline Mapping

| spec-kit stage | Mekong command | Verification |
|----------------|----------------|--------------|
| `spec` | `mekong spec new` | `mekong spec verify` |
| `plan` | `mekong plan from-init` | pytest + ruff |
| `implement` | `mekong implement run` | make test |
| `tasks` | `mekong tasks run` | — |
| `analyze` | `mekong analyze check` | — |

## Change Log

- 2026-09-12 — Phase 5 Sophia AI Video Factory wired under `tools video` (8 subcommands: create, render, status, list, avatars, voices, templates, cost) and re-exported in `src/cli/funnel_commands.py`. 39 registered groups preserved.
- 2026-09-11 — Phase 6 Cloud Deploy Unification: `run`, `status`, and `rollback` mounted onto `deploy` group with dry-run support and flag smuggling defense.
- 2026-09-09 — Rewritten from 48 phantom entries to actual 39 groups / 128 commands from `build_app()`. Gap #10 CLOSED (zalo-oa, thue, ke-toan reconnected).
- 2026-08-16 — Initial registry created from 47 command files + spec-kit synthesis
- 2026-08-16 — PriorityStack wired in src/config/__init__.py
- 2026-08-16 — build-info.jsonc updated with specKit section
