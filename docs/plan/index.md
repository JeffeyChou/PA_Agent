# Plan Index

This directory stores execution plans for non-trivial PA Agent work. Plans are
durable state, not chat transcripts: a fresh agent should be able to resume from
`SESSION_HANDOFF.md` plus any JSON file in `docs/plan/active/`.

## When a plan is required

Create a plan when work:

- touches multiple subsystems;
- changes prompt/schema/validation behavior;
- changes UI, web API, record persistence, settings, or data-source behavior;
- has non-trivial verification or live-service constraints;
- depends on open decisions that should be preserved outside chat.

Small single-file fixes with obvious verification do not need a plan.

## Layout

- `docs/plan/activated-plan-template.json`: canonical template with
  `status: "template"`.
- `docs/plan/active/`: in-progress plans. There should be at most one active
  plan unless the handoff explicitly explains why.
- `docs/plan/blocked/`: paused plans with a documented blocker.
- `docs/plan/completed/`: implemented and verified plans.

Use lowercase hyphenated filenames:

```bash
cp docs/plan/activated-plan-template.json docs/plan/active/YYYY-MM-DD-short-topic.json
```

After copying the template, update at least `file_name`, `title`, `status`,
`created`, `last_updated`, `feature_id`, `overview`, `scope`, `steps`, and
`verification`.

## Required Fields

A plan file must include:

- `file_name`: path relative to `docs/plan/`, normally
  `active/YYYY-MM-DD-short-topic.json`.
- `status`: `template`, `active`, `blocked`, or `completed`.
- `feature_id`: related task id from `SESSION_HANDOFF.md`.
- `overview`: problem, target behavior, and current step.
- `scope`: in-scope and out-of-scope boundaries.
- `dependencies`: repo paths, external systems, credentials, and open decisions.
- `steps`: ordered work items with `pending`, `in_progress`, `completed`, or
  `blocked` status.
- `verification`: baseline, required, optional, and skipped checks.
- `evidence`: command, artifact, log, screenshot, or manual-smoke references.
- `progress_log`: dated progress entries.
- `completion`: resolution state, summary, and follow-up.

## After Implementation

Before moving an active plan to `completed/`:

- set `status` to `completed`;
- set `completion.resolved` to `true`;
- set `completion.resolved_date`;
- record commands in `evidence.commands_run`;
- add skipped checks with reasons and follow-up;
- update `SESSION_HANDOFF.md` so no completed work remains listed as active.
