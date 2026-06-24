# Session Handoff

Last updated: 2026-06-24

Use this file for current restart state, latest verification, skipped checks,
and unresolved work. Keep stable architecture in `ARCHITECTURE.md`.

## Status Vocabulary

- Plan status: `template`, `active`, `blocked`, `completed`.
- Work status: `not_started`, `in_progress`, `blocked`, `completed`.

## Current State

- Branch: `main` tracking `origin/main`.
- Recent baseline commit: `4045230 Implemented the Aion-style harness and the FastAPI/static-browser replacement path.`
- Current harness cleanup: `completed`.
- Completed plan: `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`.
- Active plans: none.

## Verified Now

- `./init.sh` passed.
  - Required artifact checks passed.
  - Harness docs contain no wrong-project references checked by the script.
  - Plan JSON and active/blocked/completed folder layout passed validation.
  - `git diff --check` passed.
  - `bash -n init.sh` and `.githooks/pre-commit` shell syntax checks passed.
  - Nested `worktree-dev-dispatch-qt/` is ignored by the root repo.
  - Python import smoke passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_decision_panel.py -q` passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_harness.py tests/unit/test_web_api.py -q` passed: 11 tests.

## Known Follow-Up

- `RUN_TESTS=1 ./init.sh` now runs unit/property tests with offscreen Qt. It no
  longer aborts in Qt widget setup, but the existing suite currently reports 31
  application-level failures unrelated to this harness cleanup.
- `RUN_LINT=1 ./init.sh` currently reports existing source/test lint drift. The
  run observed 3603 ruff findings.
- `RUN_INTEGRATION=1 ./init.sh`, `RUN_E2E=1 ./init.sh`, and `RUN_LIVE=1
  ./init.sh` were not required for this documentation/harness cleanup.

## Open Work

- No active harness plan remains.
- Before making `RUN_TESTS=1` or `RUN_LINT=1` required gates, fix the existing
  app test failures and lint drift in separate focused work.

## Restart Notes

For a fresh session:

```bash
pwd
git status --short --branch
./init.sh
```

Then inspect `docs/plan/active/` for any active plan before starting new work.
