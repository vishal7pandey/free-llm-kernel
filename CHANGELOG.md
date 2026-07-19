# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `ExecutionError._redact` now properly redacts API key patterns instead of
  appending `***` after the full match
- `OpenAICompatibleAdapter.execute` now measures and reports actual `latency_ms`
  instead of always returning `0.0`
- `OpenAICompatibleAdapter._build_body` now sends `tool_choice` when tools are
  present in the request
- `UsageStore._load` no longer swallows all exceptions silently — only
  `JSONDecodeError`, `ValueError`, and `TypeError` are caught
- `OpenAICompatibleAdapter._parse_response` uses `contextlib.suppress` instead
  of bare `try/except/pass` for tool call validation

### Changed

- Ruff config updated from deprecated `select` to `lint.select` in
  `pyproject.toml`
- CI workflow uses `uv venv` instead of `--system` flag for reliable
  dependency installation
- All source and test files reformatted with `ruff format`

### Removed

- `archive/legacy_client.py` — dead code removed

### Added

- `project.urls`, `license`, and `authors` metadata in `pyproject.toml`
- `CHANGELOG.md`
- `HealthTracker` in runtime layer: tracks per-provider health status, rolling
  latency averages, and daily request counts with quota remaining calculation
- `BestFreePolicy` routing policy: combines health status, quota remaining,
  latency history, and model quality for optimal free provider selection
- `daily_request_limit` field on `ProviderMetadata` for free tier quota awareness
- `LLMClient` now wires `HealthTracker` into `Executor` and refreshes `WorldState`
  with live health/quota data before each request
- `.github/dependabot.yml` for automated dependency updates
- `SECURITY.md` with vulnerability reporting policy
- 17 new tests for health tracking and quota-aware routing (247 total)
