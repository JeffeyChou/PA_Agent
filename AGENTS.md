# Repository Guidelines

## Project Structure & Module Organization
PA Agent is a Python 3.11 desktop/AI assistant. Core package code lives in `pa_agent/`: `gui/` contains PyQt6 UI code, `ai/` LLM routing, prompts, validation, and connectors, `data/` market data backends, `orchestrator/` analysis flows, `config/` settings helpers, `indicators/` calculations, and `security/` safeguards. Tests are split across `tests/unit`, `tests/property`, `tests/integration`, and `tests/e2e`, with fixtures in `tests/fixtures`. Prompt source material is in `prompt_engineering/`; docs are in `docs/`; examples are in `config/*.example.json`; utilities are in `tools/`.

## Build, Test, and Development Commands
- `python -m venv .venv` then `pip install -e ".[dev]"`: create a local editable development install.
- `make run` or `python -m pa_agent.main`: start the GUI application.
- `make test` or `pytest -q`: run the configured test suite.
- `pytest -m "not e2e"`: skip end-to-end smoke tests during faster local checks.
- `make lint`: run `ruff check .` and `black --check .`.
- `make setup-secrets`: install the local hook that blocks accidental commits of settings, logs, and records.

## Coding Style & Naming Conventions
Use Black formatting with 100-character lines and Python 3.11 syntax. Ruff enforces import ordering and bug/style rules (`E`, `F`, `I`, `UP`, `B`, `SIM`, `RUF`). Prefer typed, explicit interfaces for data passed between `ai`, `data`, and `gui`. Name tests `test_*.py`, functions `test_*`, modules in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`.

## Testing Guidelines
Pytest is the test runner. Keep narrow logic tests in `tests/unit`, Hypothesis/property checks in `tests/property`, cross-module behavior in `tests/integration`, and GUI or workflow smoke coverage in `tests/e2e`. Mark tests using the markers in `pyproject.toml`, especially `live` for cases requiring real API keys or external services. Add or update tests when changing JSON schemas, prompt routing, retry logic, or data-source behavior.

## Commit & Pull Request Guidelines
Recent history includes both descriptive messages and version-only commits; use concise imperative summaries such as `Add East Money backend validation` and avoid bare `1.0` messages. Keep each PR focused on one feature, fix, or documentation update. Include motivation, test commands run, linked issues when applicable, and screenshots or short recordings for visible GUI changes.

## Security & Configuration Tips
Do not commit `config/settings.json`, `config/exception_state.json`, `.env`, API keys, private keys, logs, or generated records. Start from `config/settings.example.json` and configure secrets locally through the GUI settings flow when possible. Live tests must read credentials from environment variables, not committed configuration files.
