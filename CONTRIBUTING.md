# Contributing to Free LLM Kernel

Thank you for your interest in contributing! This project is at **v1.0 — stable**.
The API is frozen, so contributions should follow these guidelines.

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
uv run pytest              # 331 tests
uv run mypy src            # type checking
uv run ruff check src tests scripts  # linting
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

## API Stability Rules (v1.0+)

The public API surface is frozen. This means:

- **No breaking changes** to existing function signatures, class names, enum values, or `__all__` exports
- **Additive changes are OK**: new keyword-only parameters, new methods, new classes, new enum values
- **Removals or renames** require a major version bump (v1.0 → v2.0) and a deprecation cycle
- The [API stability test](tests/unit/test_api_stability.py) enforces this automatically

If you need to change the API surface:
1. Update the snapshot in `test_api_stability.py`
2. Document the change in `CHANGELOG.md`
3. Explain why the change is necessary in your PR

## Deprecation Policy

- Deprecated APIs get a `DeprecationWarning` and remain functional for at least one minor version
- Removed APIs require a major version bump
- Deprecations are documented in `CHANGELOG.md`

## Architecture Rules

This project enforces a layered architecture via import-linter:

```
extensions  ←  client  ←  runtime  ←  planner  ←  core
    ↑             ↑          ↑          ↑          ↑
  plugins    MiddlewareChain  Executor   Planner   Models
  UsageStore  LLMClient       Adapter    Policies  Request/Response
```

- **Core** is pure — no network, no disk, no env, no mutable state.
- **Planner** is deterministic — same input → same plan.
- **Runtime** is the only layer that touches the network.
- **Extensions** observe and can modify requests/responses but cannot break correctness.
- **Plugins** register providers and policies via entry points or runtime registration.

Adding a new provider only requires a runtime adapter — no Core or Planner changes.
Alternatively, create a community plugin package (see [Plugin API](README.md#plugin-api)).

## Release Process

1. Update `version` in `pyproject.toml`
2. Update `__version__` expectation in `test_api_stability.py`
3. Update `CHANGELOG.md` with the release entry
4. Run full verification: `pytest`, `ruff`, `mypy`, `lint-imports`
5. Commit with message `release: vX.Y.Z`
6. Tag: `git tag vX.Y.Z && git push --tags`
7. GitHub Actions CI validates and publishes

## Security

- **Never commit real API keys.** Use `.env` (gitignored) for local development.
- Test files must use fake placeholder keys only.
- The `Secret` type redacts in `repr()` and `str()` — always use it for credentials.

## Style

- Python 3.11+, line length 100, type-hinted everywhere.
- Follow `ruff` configuration in `pyproject.toml`.
- No comments or docstrings unless they explain *why*, not *what*.
