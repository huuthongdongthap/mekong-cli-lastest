# Design Intelligence

Native design-quality system for Mekong CLI, adapted from
[Hallmark](https://github.com/nutlope/hallmark) (MIT). Instead of prompt-only
design knowledge, Mekong ships structured schemas, deterministic gates, and a
reusable Design DNA model that agents can read, audit, and build from.

## Commands

All verbs live under `mekong ui`:

| Command | Purpose |
|---|---|
| `mekong ui audit <target> [--llm] [--render] [--json]` | Deterministic gate run + 9-axis DESIGN SCORE block |
| `mekong ui study <target> --name <n> [--llm] [--export-json]` | Analyse a target into DesignDNA + `design.md`/`design.json` |
| `mekong ui redesign <study> [--out <n>]` | Re-fingerprint a study: preserve copy/IA/brand, change macrostructure |
| `mekong ui build <design.json>` | Emit a tokenized design system (`tokens.css`) from a DesignDNA file |
| `mekong ui approve <study> [--reject --reason <r>]` | Store approved DNA / rejected patterns in design memory |
| `mekong ui benchmark` | Score 10 benchmark fixtures, report axis deltas (anti-gaming) |

Examples:

```bash
mekong ui audit tests/design_intelligence/fixtures/good-dashboard.html
mekong ui study https://example.com --name landing --export-json
mekong ui approve landing
mekong ui build .mekong/design/studies/landing/design.json
```

## Architecture

```
src/design_intelligence/
  schemas.py        Pydantic v2 models: DesignDNA (23 fields), DesignBrief,
                    AuditReport, Theme; enums ProductType (16), Density,
                    Genre, EvidenceTier, VisualQATier
  gates.py          58 gates: 29 objective (deterministic regex/static on
                    HTML+CSS), 29 heuristic (LLM judge), 8 visual
  checks.py         Objective gate implementations
  scoring.py        Folds gate results into 9 axis scores (0-100) + report
  dna.py            DesignDNA helpers
  pipeline.py       Archetype + brief -> macrostructure selection, build_dna
  visual.py         Provider-agnostic visual QA (screenshot + judges)
  change_detect.py  Diff classification for the deploy design-audit hook
  design_memory.py  Approved DNA / rejected patterns via MemoryStore
  knowledge/        gates.yaml (58), macros.yaml (21), themes.yaml (12),
                    genres.yaml (4), archetypes/ (16 product types)

src/cli/
  ui_commands.py    Typer sub-app wiring (audit/study/redesign/build/
                    approve/benchmark)
  ui_study.py       Study + redesign logic
  ui_benchmark.py   Benchmark runner + 7-metric derivation
```

## Evidence tiers (never conflated)

Every audit finding carries an evidence tier, and the report never claims a
higher tier than it actually ran:

- **OBJECTIVE** — deterministic regex/static check on HTML+CSS. Always runs.
- **HEURISTIC** — LLM judge. Only with `--llm`; otherwise marked UNVERIFIED
  with confidence 0.0, never a fake pass.
- **OPINION** — requires a rendered screenshot. Never claimed without one.

## Visual QA tiers (degrade in order, never over-claim)

| Tier | Requires | Claimed when |
|---|---|---|
| `full` | render + vision judge | screenshot captured AND judge scored |
| `screenshot` | render only | screenshot captured, judge unavailable/failed |
| `static` | neither | no screenshot provider (the real default here) |

`detect_tier()` probes the environment; `run_visual_qa()` degrades
gracefully. A judge failure degrades to `screenshot`, never to `full`.
Playwright is not installed in this environment, so `static` is the honest
default — `--render` requests a screenshot but reports `static` with a note
when the provider is absent.

## Scoring: 9 axes, 12 gate categories

Gate categories fold into 9 reported axes:

| Gate category | Axis |
|---|---|
| TYPOGRAPHY | typography |
| COLOR | color |
| STRUCTURE, RESPONSIVENESS | structure |
| COMPONENTS, INTERACTION, MOTION | interaction |
| CONTENT | hierarchy |
| SPACING | density |
| ACCESSIBILITY | accessibility |
| DISTINCTIVENESS | distinctiveness |
| AI-SLOP | anti_slop |

The benchmark reports 7 metrics derived from these axes via an explicit map
(`_METRICS` in `ui_benchmark.py`) so every metric traces back to real gates —
e.g. `readability = mean(typography, hierarchy)`.

## Agent lifecycle + change detection

`mekong deploy <feature> --design-audit` (opt-in, advisory, never blocks)
classifies the diff via `change_detect.py`:

- Frontend surface (html/jsx/tsx/css/scss/svelte/vue, pages/layouts/routes/
  components dirs, tailwind.config.*, tokens.*) → suggests `mekong ui audit`.
- Backend-only, migration-only, CLI-only, infra-only → skipped, no noise.
- Mixed diff → frontend wins.

## Sophia contract (design memory)

Downstream agents (Sophia) consume design decisions without Hallmark:

- `mekong ui study --export-json` emits the DesignDNA JSON as the **last**
  thing on stdout — parse the trailing object.
- `mekong ui approve <study>` persists approved DNA into the shared JSONL
  memory store under the `design:` namespace
  (`design:approve:<name>` / `design:reject:<name>`, tags `design` +
  `approved`/`rejected`).
- Only **approved** DNA enters memory. Unapproved studies stay on disk under
  `.mekong/design/studies/` but are never offered to agents.
- `load_approved(name)` returns the most recent approved DesignDNA; corrupt
  memory entries return `None`, never crash.

## Benchmark (anti-gaming)

`mekong ui benchmark` scores 10 fixtures (good + slop archetypes) and asserts
separation: `good-dashboard` scores highest (900), `ai-slop-landing` lowest
(180), and good `anti_slop` (100) beats slop (0). The scorer reads fixtures
from disk and applies gate rules — fixtures are never in the scorer's path,
so the suite cannot be gamed by tuning one example. Runs in ~0.35s, fully
deterministic (no LLM).

## Extension points

- **New archetype**: add `knowledge/archetypes/<product-type>.yaml` with the
  9 spec attributes; `pipeline.archetype_for` picks it up by ProductType.
- **New macrostructure**: add to `knowledge/macros.yaml` with `best_for` /
  `avoid` lists; selection is deterministic scoring.
- **New gate**: add to `knowledge/gates.yaml` + implement in `checks.py`
  (objective) or wire an LLM judge (heuristic).
- **New benchmark fixture**: drop an HTML file in
  `tests/design_intelligence/fixtures/`; the benchmark picks it up.

## Rejected / upstream-only capabilities

Deliberately NOT ported from Hallmark:

- **Pixel cloning** — studies are analysis/inspiration, never clones. Reuse
  the DNA, never the pixels.
- **Visual opinion without a screenshot** — opinion-tier findings are never
  emitted from static analysis.
- **Fabricated heuristic scores** — when the LLM judge is unavailable,
  heuristic axes are UNVERIFIED at confidence 0.0, not guessed.
- **Blocking design gate** — the deploy hook is advisory only; it never
  blocks a deploy.

## Attribution

Adapted from [Hallmark](https://github.com/nutlope/hallmark) by Nutlope,
MIT License. Mekong CLI is MIT licensed; see `LICENSE`.
