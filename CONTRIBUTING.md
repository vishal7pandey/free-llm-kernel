# Contributing to Free LLM Kernel

Thank you for your interest in contributing! This document covers the basics.

## Development Setup

```bash
git clone https://github.com/vishal7pandey/free-llm-kernel.git
cd free-llm-kernel
uv venv
uv pip install -e ".[dev]"
cp .env.example .env  # fill in at least one API key
```

## Workflow

1. **Fork & branch** — Create a feature branch from `main` (e.g., `feat/add-provider`).
2. **Write tests first** — Every new feature or bug fix should include tests.
3. **Run the full suite** before pushing:

```bash
uv run pytest              # all tests
uv run mypy src            # type checking
uv run ruff check src tests  # linting
uv run bandit -r src        # security scan
uv run lint-imports         # architecture layer verification
```

4. **Keep commits focused** — One logical change per commit. Use [conventional commits](https://www.conventionalcommits.org/):

```
feat: add SambaNova provider
fix: handle 429 retry-after header
docs: update provider catalogue
test: add property tests for state machine
refactor: extract RoutingPolicy from Planner
```

5. **Open a PR** — Reference any related issues. Ensure CI passes.

## Architecture Rules

This project enforces a four-layer architecture via import-linter:

```
Extensions → Runtime → Planner → Core
```

- **Core** is pure — no network, no disk, no env, no mutable state.
- **Planner** is deterministic — same input → same plan.
- **Runtime** is the only layer that touches the network.
- **Extensions** observe and can modify requests/responses but cannot break correctness.

Adding a new provider only requires a runtime adapter — no Core or Planner changes.

## Security

- **Never commit real API keys.** Use `.env` (gitignored) for local development.
- Test files must use fake placeholder keys only.
- The `Secret` type redacts in `repr()` and `str()` — always use it for credentials.

## Style

- Python 3.11+, line length 100, type-hinted everywhere.
- Follow `ruff` configuration in `pyproject.toml`.
- No comments or docstrings unless they explain *why*, not *what*.
