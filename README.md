# Mekong CLI — AI-Powered Business Operations for Vietnam

> Open-source autonomous runtime for Solo Companies / Solo Vibe Coders.
> MIT license.

## What is Mekong CLI?

Mekong CLI is an **open-source autonomous runtime** for Solo Companies /
Solo Vibe Coders: one operator delegates goals to AI agents that plan,
execute, verify, repair, and pay for tools — all running on your own
infrastructure.

It also powers [mekongmind.com](https://www.mekongmind.com), an AI-operated
business platform built for Vietnamese one-person companies and small
businesses.

**Core mission:** Replace a full back-office team with AI agents — accounting, tax filing, sales outreach, and customer communication — all running on your infrastructure.

## Autonomous Runtime (v0.1)

The runtime core ships a canonical agent lifecycle, a capability bus, a
single policy decision path, an economic bus (mock-only providers), a
versioned Buzz adapter interface, and a local-first execution runtime:

- [docs/architecture.md](docs/architecture.md) — v0.1 overview + component map
- [docs/core-contract.md](docs/core-contract.md) — lifecycle stages, protocol surface, invariants
- [docs/capability-bus.md](docs/capability-bus.md) — tool discovery + governance-aware execution
- [docs/economic-bus.md](docs/economic-bus.md) — PaymentProvider interface; no custody, no keys
- [docs/buzz-runtime-adapter.md](docs/buzz-runtime-adapter.md) — versioned external-orchestrator facade
- [docs/runtime-adapters.md](docs/runtime-adapters.md) — local execution sandbox
- [docs/autonomy-model.md](docs/autonomy-model.md) — risk levels, approvals, audit
- [docs/architecture/ARCHITECTURE_AFTER_PHASE_2.md](docs/architecture/ARCHITECTURE_AFTER_PHASE_2.md) — after-report, gaps, next actions

## Three Business Funnels

1. **Zalo OA** — Automated customer communication and lead capture via Zalo Official Account
2. **Tax & Accounting (thue_dnvn / ke_toan)** — Full Vietnamese tax compliance: TNCN, TNDN, GTGT, TT78 invoices
3. **AI Video Factory (sophia)** — AI-powered video generation for marketing

## Design Intelligence

Native design-quality system adapted from [Hallmark](https://github.com/nutlope/hallmark) (MIT).
Audit, study, and build design systems from structured schemas and deterministic gates —
not prompt-only knowledge.

```bash
mekong ui audit page.html                 # deterministic gate run + 9-axis score
mekong ui study page.html --name landing # -> DesignDNA + design.md/design.json
mekong ui approve landing                # store approved DNA for agent reuse
mekong ui benchmark                      # anti-gaming fixture suite
```

See [docs/design-intelligence.md](docs/design-intelligence.md).

## Quick Start

```bash
git clone https://github.com/minhlongs/mekong-cli.git
cd mekong-cli && source scripts/shell-init.sh

# Configure LLM (any OpenAI-compatible provider)
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_API_KEY=your-key
export LLM_MODEL=anthropic/claude-sonnet-4

mekong  # Start the CLI
```

Vietnam domestic payments (PayOS) for TNCN/TNDN/GTGT compliance workflows.

## Links

- **Website:** [mekongmind.com](https://www.mekongmind.com)
- **API:** [api.cashclaw.cc](https://api.cashclaw.cc/health)
- **Docs:** [docs/](docs/)

## License

MIT
