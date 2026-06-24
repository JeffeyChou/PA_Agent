# PA Agent Architecture

Last updated: 2026-06-24

This file records stable subsystem boundaries for PA Agent. It is not a
progress log. Put current work state in `SESSION_HANDOFF.md` and execution
plans under `docs/plan/`.

## Repository Domains

| Path | Domain | Ownership |
| --- | --- | --- |
| `AGENTS.md` | Agent routing | Short workflow entry point into the harness docs. |
| `ARCHITECTURE.md` | Architecture map | Stable subsystem map and dependency rules. |
| `SESSION_HANDOFF.md` | Restart state | Current verified state, active plans, blockers, skipped checks, and next steps. |
| `EVALUATION_RUBRIC.md` | Review gate | Acceptance checklist for code, docs, security, tests, and readiness. |
| `LESSON_PREFERENCE.md` | Lessons | Durable lessons and preferences learned during development. |
| `docs/plan/` | Plans | Template plus active, blocked, and completed JSON execution plans. |
| `pa_agent/` | Application package | Desktop app, browser UI, AI orchestration, data sources, records, config, and utilities. |
| `prompt_engineering/` | Prompt assets | Source prompt and strategy files loaded by `PromptAssembler`. |
| `tests/` | Verification | Unit, property, integration, e2e, and fixture coverage. |
| `tools/` | Local utilities | Diagnostics, secret-hook setup, encoding fixes, and live smoke helpers. |
| `config/` | Configuration | Example settings and local configuration docs. Runtime settings are ignored. |
| `experience/`, `records/`, `logs/`, `trade_records/` | Runtime data | Local user data roots; only `.gitkeep` placeholders are tracked. |
| `docs/tang-strategy/` | External/reference project | Ignored side material; not part of the PA Agent runtime package. |
| `worktree-*` | Local worktrees | Ignored nested Git worktrees; not primary source layout. |

## Layer Model

1. Workflow harness:
   `AGENTS.md`, `SESSION_HANDOFF.md`, `EVALUATION_RUBRIC.md`,
   `LESSON_PREFERENCE.md`, `docs/plan/`, and `init.sh`. This layer describes
   how agents work in the repo and must stay independent of generated runtime
   data.

2. Application bootstrap:
   `run.py`, `pa_agent/main.py`, and `pa_agent/app_context.py` create the Qt
   application, load settings, configure logging, connect the selected data
   source, wire the AI client, prompt assembler, validator, records writer, and
   token ledger.

3. Interface layer:
   `pa_agent/gui/` owns the PyQt6 desktop surface. `pa_agent/web/` owns the
   FastAPI/static browser surface. Both use the same application services and
   orchestrators rather than duplicating analysis rules.

4. Orchestration and safety layer:
   `pa_agent/orchestrator/two_stage.py` coordinates Stage 1 diagnosis, strategy
   routing, Stage 2 decision, validation retry, and record persistence.
   `pa_agent/orchestrator/harness.py` is application logic: it records immutable
   analysis contracts, audit events, and deterministic pre-delivery gate
   results.

5. AI and prompt layer:
   `pa_agent/ai/` owns provider connectors, prompt assembly, prompt schemas,
   JSON validation, normalizers, decision trees, coherence checks, semantic
   checks, routing, and token accounting. Prompt text lives in
   `prompt_engineering/`.

6. Data and indicator layer:
   `pa_agent/data/` owns market data adapters, symbol defaults, refresh policy,
   snapshots, and bar-close handling. `pa_agent/indicators/` owns indicator
   calculations used by snapshots and prompts.

7. Persistence and configuration layer:
   `pa_agent/config/` owns Pydantic settings and path constants.
   `pa_agent/records/` owns analysis records, pending writes, history, trade
   logs, and experience loading. Plaintext secrets and user records must remain
   in ignored runtime files.

8. Verification layer:
   `tests/unit`, `tests/property`, `tests/integration`, and `tests/e2e` cover
   the behavior at increasing scope. Tests should use fixtures and mocks unless
   explicitly marked `live`.

## Dependency Boundaries

- GUI and web surfaces may call orchestration/services; they should not
  implement separate Stage 1/Stage 2 decision rules.
- Prompt/schema/validation changes should be covered by targeted tests because
  they affect persisted records and downstream UI rendering.
- Data-source adapters should normalize into shared `KlineFrame`/bar concepts
  before orchestration. Analysis frames must contain only closed bars; live
  frames may include a forming bar for display.
- `pa_agent/orchestrator/harness.py` is the runtime safety harness. Root harness
  docs and `init.sh` are workflow tools and should not encode trade-decision
  behavior.
- Runtime directories (`config/settings.json`, `records/`, `experience/`,
  `logs/`, `trade_records/`) are local user state. Do not make tests or docs
  depend on private contents there.
- Live external systems include AI providers, MT5, TradingView, yfinance, and
  AkShare/East Money. Local verification must skip or mock them unless the test
  is explicitly marked `live`.
- PA Agent is an analysis assistant only. It may draw proposed entry, stop, and
  target lines, but must not add broker execution behavior without an explicit
  product decision and new safety review.
