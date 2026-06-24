# Session Handoff

Last updated: 2026-06-24

Use this file for current restart state, latest verification, skipped checks,
and unresolved work. Keep stable architecture in `ARCHITECTURE.md`.

## Status Vocabulary

- Plan status: `template`, `active`, `blocked`, `completed`.
- Work status: `not_started`, `in_progress`, `blocked`, `completed`.

## Current State

- Branch: `main` tracking `origin/main`.
- Recent local merge commit message: `Merge upstream_main and remove local provider SDK routes`.
- Merge target: `origin/upstream_main` at `4ca75c1`.
- Merge status: `committed`, with conflicts resolved in:
  - `pa_agent/ai/prompt_assembler.py`
  - `pa_agent/gui/main_window.py`
  - `pa_agent/orchestrator/free_chat.py`
  - `pa_agent/orchestrator/two_stage.py`
- User-requested provider cleanup: `completed`.
  - Removed OpenClaw/QClaw provider auto-configuration, relay, fallback, and tests.
  - Removed Cursor SDK provider route, client, dependency, and tests.
  - Removed WorkBuddy provider auto-configuration, fallback, and tests.
  - Kept explicit OpenAI-compatible HTTP provider settings through
    `provider.model`, `provider.base_url`, and `provider.api_key`.
- Completed plans:
  - `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`
  - `docs/plan/completed/2026-06-24-upstream-main-merge.json`
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
- `.venv/bin/python -m py_compile ...` passed for the touched app modules:
  - `pa_agent/app_context.py`
  - `pa_agent/ai/deepseek_client.py`
  - `pa_agent/ai/mimo_compat.py`
  - `pa_agent/ai/prompt_assembler.py`
  - `pa_agent/ai/provider_errors.py`
  - `pa_agent/ai/stage2_normalizer.py`
  - `pa_agent/gui/ai_model_settings_dialog.py`
  - `pa_agent/gui/settings_dialog.py`
  - `pa_agent/gui/main_window.py`
  - `pa_agent/orchestrator/two_stage.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_deepseek_client.py tests/unit/test_kv_prefix_cache.py tests/unit/test_prompt_assembler.py tests/unit/test_provider_errors.py tests/unit/test_settings_round_trip.py -q` passed: 66 tests.
- Repository search found no remaining OpenClaw/QClaw, Cursor SDK, or WorkBuddy
  app/test/doc references outside unrelated UI cursor terminology.

## Known Follow-Up

- Full unit/property suite was not run for this merge; use `RUN_TESTS=1
  ./init.sh` when a broader validation pass is needed.
- Lint/format was not run for this merge; use `RUN_LINT=1 ./init.sh` before
  making lint a gate.
- `RUN_INTEGRATION=1 ./init.sh`, `RUN_E2E=1 ./init.sh`, and `RUN_LIVE=1
  ./init.sh` were not required. Live checks need explicit credentials and local
  services.

## Open Work

- No active merge or harness plan remains.
- Any future AI provider work should keep the explicit OpenAI-compatible HTTP
  boundary unless a new product decision approves local SDK/agent integrations.

## Restart Notes

For a fresh session:

```bash
pwd
git status --short --branch
./init.sh
```

Then inspect `docs/plan/active/` for any active plan before starting new work.
