#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUN_DIFF_CHECK="${RUN_DIFF_CHECK:-1}"
RUN_TESTS="${RUN_TESTS:-0}"
RUN_INTEGRATION="${RUN_INTEGRATION:-0}"
RUN_E2E="${RUN_E2E:-0}"
RUN_LIVE="${RUN_LIVE:-0}"
RUN_LINT="${RUN_LINT:-0}"

require_file() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    echo "ERROR: required path is missing: ${path}" >&2
    exit 1
  fi
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: required command is missing: ${cmd}" >&2
    exit 1
  fi
}

find_python() {
  if [[ -x ".venv/bin/python" ]]; then
    echo ".venv/bin/python"
  elif [[ -x ".venv/Scripts/python.exe" ]]; then
    echo ".venv/Scripts/python.exe"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "ERROR: python3 or python is required" >&2
    exit 1
  fi
}

PYTHON_BIN="$(find_python)"

echo "==> Working directory: ${PWD}"

echo "==> Checking required PA Agent artifacts"
for path in \
  AGENTS.md \
  ARCHITECTURE.md \
  EVALUATION_RUBRIC.md \
  LESSON_PREFERENCE.md \
  README.md \
  SESSION_HANDOFF.md \
  CONTRIBUTING.md \
  SECURITY.md \
  pyproject.toml \
  Makefile \
  run.py \
  docs/plan/index.md \
  docs/plan/activated-plan-template.json \
  docs/plan/active/.gitkeep \
  docs/plan/blocked/.gitkeep \
  docs/plan/completed/.gitkeep \
  config/README.md \
  config/settings.example.json \
  config/exception_state.example.json \
  config/tv_symbol_aliases.example.json \
  pa_agent/main.py \
  pa_agent/app_context.py \
  pa_agent/orchestrator/harness.py \
  pa_agent/web/app.py \
  prompt_engineering/_reference/pattern_enum.md \
  tests/unit/test_harness.py \
  tests/unit/test_web_api.py; do
  require_file "${path}"
done

echo "==> Checking harness docs for wrong-project references"
"${PYTHON_BIN}" - <<'PY'
from pathlib import Path
import sys

roots = [
    Path("AGENTS.md"),
    Path("ARCHITECTURE.md"),
    Path("EVALUATION_RUBRIC.md"),
    Path("SESSION_HANDOFF.md"),
    Path("LESSON_PREFERENCE.md"),
    Path("docs/plan/index.md"),
    Path("docs/plan/activated-plan-template.json"),
]
roots.extend(sorted(Path("docs/plan/active").glob("*.json")))
roots.extend(sorted(Path("docs/plan/blocked").glob("*.json")))
roots.extend(sorted(Path("docs/plan/completed").glob("*.json")))

forbidden = ("gHVCCL", "ghZCCL", "FSZ", "ACES", "Polaris")
errors: list[str] = []
for path in roots:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    for token in forbidden:
        if token in text:
            errors.append(f"{path}: contains wrong-project token {token!r}")

if errors:
    for error in errors:
        print("ERROR:", error, file=sys.stderr)
    sys.exit(1)
PY

echo "==> Validating plan JSON and layout"
"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

plan_root = Path("docs/plan")
valid_status = {"template", "active", "blocked", "completed"}
required = {
    "file_name",
    "title",
    "status",
    "created",
    "last_updated",
    "owner",
    "feature_id",
    "source_of_truth",
    "overview",
    "scope",
    "dependencies",
    "steps",
    "verification",
    "evidence",
    "progress_log",
    "completion",
}
errors: list[str] = []
active: list[str] = []

template = plan_root / "activated-plan-template.json"
try:
    template_data = json.loads(template.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001 - this script prints concise diagnostics.
    errors.append(f"{template}: unreadable JSON: {exc}")
else:
    if template_data.get("status") != "template":
        errors.append(f"{template}: template must use status='template'")
    missing = sorted(required - template_data.keys())
    if missing:
        errors.append(f"{template}: missing keys {', '.join(missing)}")

for directory, expected_status in (
    (plan_root / "active", "active"),
    (plan_root / "blocked", "blocked"),
    (plan_root / "completed", "completed"),
):
    if not directory.exists():
        errors.append(f"{directory}: missing plan directory")
        continue
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: unreadable JSON: {exc}")
            continue
        status = data.get("status")
        if status not in valid_status:
            errors.append(f"{path}: invalid status {status!r}")
        if status != expected_status:
            errors.append(f"{path}: expected status {expected_status!r}, got {status!r}")
        missing = sorted(required - data.keys())
        if missing:
            errors.append(f"{path}: missing keys {', '.join(missing)}")
        expected_name = str(path.relative_to(plan_root)).replace("\\", "/")
        if data.get("file_name") != expected_name:
            errors.append(
                f"{path}: file_name must be {expected_name!r}, got {data.get('file_name')!r}"
            )
        if status == "active":
            active.append(str(path))

if len(active) > 1:
    errors.append("more than one active plan: " + ", ".join(active))

if errors:
    for error in errors:
        print("ERROR:", error, file=sys.stderr)
    sys.exit(1)
PY

if [[ "${RUN_DIFF_CHECK}" == "1" ]]; then
  echo "==> Checking whitespace"
  git diff --check
else
  echo "==> Skipping whitespace check"
fi

echo "==> Checking shell script syntax"
bash -n init.sh
if [[ -f .githooks/pre-commit ]]; then
  sh -n .githooks/pre-commit
fi

if [[ -d worktree-dev-dispatch-qt ]]; then
  echo "==> Checking nested worktree ignore rule"
  if ! git check-ignore -q worktree-dev-dispatch-qt/; then
    echo "ERROR: worktree-dev-dispatch-qt/ exists but is not ignored" >&2
    exit 1
  fi
fi

echo "==> Running Python import smoke"
PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" - <<'PY'
import pa_agent
from pa_agent.config.settings import Settings
from pa_agent.records.schema import AnalysisRecord

assert pa_agent is not None
assert Settings() is not None
assert AnalysisRecord is not None
print("Python import smoke: OK")
PY

if [[ "${RUN_TESTS}" == "1" ]]; then
  echo "==> Running unit and property tests"
  QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" \
    "${PYTHON_BIN}" -m pytest tests/unit tests/property -m "not live"
else
  echo "==> Skipping unit/property tests; set RUN_TESTS=1 to run them"
fi

if [[ "${RUN_INTEGRATION}" == "1" ]]; then
  echo "==> Running integration tests"
  QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" \
    "${PYTHON_BIN}" -m pytest tests/integration -m "not live"
else
  echo "==> Skipping integration tests; set RUN_INTEGRATION=1 to run them"
fi

if [[ "${RUN_E2E}" == "1" ]]; then
  echo "==> Running e2e tests"
  QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" \
    "${PYTHON_BIN}" -m pytest -m "e2e and not live"
else
  echo "==> Skipping e2e tests; set RUN_E2E=1 to run them"
fi

if [[ "${RUN_LIVE}" == "1" ]]; then
  echo "==> Running live tests"
  "${PYTHON_BIN}" -m pytest -m live
else
  echo "==> Skipping live tests; set RUN_LIVE=1 only with credentials/services available"
fi

if [[ "${RUN_LINT}" == "1" ]]; then
  echo "==> Running lint and format checks"
  "${PYTHON_BIN}" -m ruff check pa_agent tests
  "${PYTHON_BIN}" -m black --check pa_agent tests
else
  echo "==> Skipping lint; set RUN_LINT=1 to run ruff and black checks"
fi

echo "==> PA Agent startup checks completed"
