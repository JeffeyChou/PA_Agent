# Repository Guidelines

PA Agent is a Python 3.11 Price Action AI assistant. Keep this file short and
use it as the routing layer into the durable harness docs.

## Repository Map

- `pa_agent/`: application package.
  - `gui/`: PyQt6 desktop UI, charting, settings, decision panels, and widgets.
  - `web/`: FastAPI backend plus static browser UI.
  - `ai/`: LLM clients, prompt assembly, schemas, validation, routing, and
    decision logic.
  - `orchestrator/`: two-stage analysis flow, free chat, validation retry, and
    the deterministic analysis safety harness.
  - `data/`: MT5, TradingView, yfinance, AkShare/East Money, snapshots, and
    refresh policy.
  - `records/`, `config/`, `indicators/`, `util/`, `security/`, `demo/`: runtime
    support modules.
- `prompt_engineering/`: source strategy and analysis prompt files used at
  runtime.
- `tests/`: unit, property, integration, e2e, and fixtures.
- `config/`: example settings and local configuration docs. Runtime settings are
  gitignored.
- `experience/`, `records/`, `logs/`, `trade_records/`: runtime data roots with
  only `.gitkeep` files tracked.
- `docs/`: user docs, references, and execution plans under `docs/plan/`.
- Root harness docs:
  - `ARCHITECTURE.md`: stable subsystem map and dependency boundaries.
  - `SESSION_HANDOFF.md`: current session state, verification evidence, and
    restart notes.
  - `EVALUATION_RUBRIC.md`: final acceptance checklist.
  - `LESSON_PREFERENCE.md`: durable development lessons and preferences.

## Session Workflow

Before writing code:

1. Confirm location and state with `pwd` and `git status --short --branch`.
2. Read `SESSION_HANDOFF.md` for current unresolved work and verified state.
3. Read `ARCHITECTURE.md` before changing subsystem boundaries.
4. Review recent history with `git log --oneline -5`.
5. Run `./init.sh` for local harness validation when changing code or harness
   docs.
6. For non-trivial work, use `docs/plan/activated-plan-template.json` and keep
   active plans in `docs/plan/active/`.

During implementation:

- Keep changes surgical and aligned with the subsystem that owns the behavior.
- Prefer existing local helpers, schemas, and settings models over new
  abstractions.
- Preserve the boundary that PA Agent analyzes charts and records decisions; it
  does not connect to brokers or execute orders.
- Do not commit secrets, local settings, logs, generated records, or personal
  worktrees.
- Treat `pa_agent/orchestrator/harness.py` as application logic. The root
  harness docs are workflow guidance and should not duplicate that code.

## Verification

Use the narrowest checks that prove the change:

- Harness/docs: `./init.sh`
- Python logic: `RUN_TESTS=1 ./init.sh` for unit/property tests, or run a
  targeted `pytest` command for the subsystem being changed.
- Integration behavior: `RUN_INTEGRATION=1 ./init.sh` when the local GUI/data
  environment is suitable.
- Lint/format check: `ruff check pa_agent tests` and `black --check pa_agent tests`
- Web API surface: targeted `tests/unit/test_web_api.py`
- GUI-visible changes: targeted unit/e2e tests where feasible, plus manual smoke
  if a display environment is available.
- Live provider or market-data behavior: run only with explicit credentials and
  record what was skipped locally.

## End Of Session

Before ending a session:

1. Confirm the target behavior is implemented and the required verification ran.
2. Move completed plans from `docs/plan/active/` to `docs/plan/completed/`.
3. Update `SESSION_HANDOFF.md` with unresolved work, skipped checks, and restart
   instructions.
4. Update `ARCHITECTURE.md` only for stable boundary changes.
5. Update `LESSON_PREFERENCE.md` only for durable lessons or preferences.
6. Leave `git status --short` showing only intentional changes.
