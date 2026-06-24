# Evaluator Rubric

Use this rubric after implementation and before final acceptance. For large or
high-risk changes, apply it with a code-review stance before declaring the work
done.

| Category | Question | Score (0-2) | Notes |
| --- | --- | --- | --- |
| Correctness | Does the implementation match the requested PA Agent behavior without stale or wrong-project assumptions? |  |  |
| Safety and secrets | Are API keys, encrypted keys, settings, logs, records, and private user data kept out of tracked files and output? |  |  |
| Prompt/schema integrity | If prompts, schemas, validation, routing, or records changed, are downstream UI/API consumers and tests updated? |  |  |
| UI/API behavior | For GUI or web changes, are user-visible states, error paths, streaming/cancel behavior, and record display still coherent? |  |  |
| Tests | Were targeted tests run, and were live/e2e skips explicitly justified? |  |  |
| Surgical scope | Did the change avoid unrelated refactors, generated artifacts, formatting churn, and private worktree changes? |  |  |
| Maintainability | Are docs, code, and harness files clear enough for the next agent to resume without guessing? |  |  |
| Restart readiness | Can a fresh session restart from `./init.sh`, `SESSION_HANDOFF.md`, and any active plan? |  |  |

## Verdict

- Accept
- Revise
- Block

## Required Follow-Up

- Missing implementation:
- Safety or secret issue:
- Required tests:
- Skipped checks and reason:
- Next review trigger:
