# LESSON_PREFERENCE.md

This file records durable lessons and preferences learned during development.
Keep it compact and link lessons to a plan file when one exists.

Record format:

```text
- `docs/plan/completed/YYYY-MM-DD-short-topic.json`: Lesson or preference.
```

## Lessons

- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Imported
  harness templates must be grounded against the current repository before they
  become source-of-truth docs. Wrong-project references in root workflow files
  can make local restart commands actively misleading.
- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Keep the
  root workflow harness distinct from `pa_agent/orchestrator/harness.py`; the
  former guides agents, while the latter is runtime analysis safety logic.

## Preferences

- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Keep
  `AGENTS.md` concise and route stable architecture, current state, acceptance
  review, and lessons to the dedicated root harness docs.
- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Keep
  execution plans under `docs/plan/active/`, `docs/plan/blocked/`, and
  `docs/plan/completed/`; leave `docs/plan/activated-plan-template.json` as the
  canonical template.
- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Preserve
  ignored runtime roots (`config/settings.json`, `records/`, `experience/`,
  `logs/`, `trade_records/`) as local user state. Do not use private contents
  there as test or documentation dependencies.
- `docs/plan/completed/2026-06-24-harness-ground-truth-cleanup.json`: Nested
  `worktree-*` directories are local working copies, not part of the primary
  PA Agent source layout.
