# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-07-20

### v1.0 — Stable Release

This is the first stable release of Free LLM Kernel. The public API is frozen
and backed by an automated stability test. The kernel provides intelligent
routing, automatic failover, quota tracking, circuit breaking, capability-based
routing, automatic model discovery, and a plugin API for community extensions.

**331 tests** · **6 modules** · **44 public exports** · **7 providers**

### Added in this release cycle

- Quota-aware routing (avoid providers nearing free tier limits)
- Latency-based routing with historical data
- Health scoring with circuit breaker integration
- Per-request policy selection (`policy="best_free"`)
- Provider Intelligence Engine (`client.provider_health()`)
- Capability-based routing (`capabilities="vision"`)
- Automatic model discovery (`client.refresh_models()`)
- Public plugin API (`ProviderPlugin`, `PolicyPlugin`, entry points)
- API freeze with stability test snapshotting all exports
- `__version__` attribute on package
- `CONTRIBUTING.md` with release process and deprecation policy
- `SECURITY.md` with vulnerability reporting policy
- `.github/dependabot.yml` for automated dependency updates
- `scripts/benchmark.py` reliability benchmark

### Providers

Groq, Google Gemini, Cerebras, SambaNova, Cloudflare Workers AI, Ollama (local)

### Routing Policies

`default`, `best_free`, `fastest`, `cheapest`, `quality` (extensible via plugins)

### Capabilities

`STREAMING`, `TOOLS`, `VISION`, `JSON_MODE`, `JSON_SCHEMA`, `FUNCTION_CALLING`,
`LONG_CONTEXT`, `REASONING` (with friendly aliases like `json`, `vision`, `tools`)

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
- Per-request policy selection: `client.chat(prompt, policy="best_free")` —
  policies are now first-class, overridable per request via string name or
  `RoutingPolicy` instance
- `provider_health()` method on `LLMClient`: Provider Intelligence Engine
  surface for introspecting live health, latency, and quota per provider
- `POLICY_REGISTRY` and `resolve_policy()` in planner for policy name resolution
- `scripts/benchmark.py` — reliability benchmark measuring per-provider latency,
  success rate, and failover behavior across routing policies
- Capability-based routing: `client.chat(prompt, capabilities="vision")` —
  users specify what they need (vision, json, tools, long_context) and the
  kernel routes to providers that support those capabilities
- `CAPABILITY_ALIASES` and `resolve_capabilities()` in core for friendly
  string-to-Capability resolution (e.g. "json" → JSON_MODE, "image" → VISION)
- `JSON_MODE` capability added to Cerebras and SambaNova models
- Automatic model discovery: `client.refresh_models()` queries each
  provider's `/models` endpoint, auto-detects available models, and
  infers capabilities from model names
- `infer_capabilities()`, `infer_context_tokens()`, `infer_quality_score()`,
  and `infer_model_metadata()` in planner for heuristic model metadata inference
- `discover_models()` method on `OpenAICompatibleAdapter`
- Public plugin API: `ProviderPlugin` and `PolicyPlugin` protocols,
  `PluginRegistry`, entry point discovery (`llm_kernel.providers`,
  `llm_kernel.policies` groups), `load_plugins()`, `register_policy()`
  and `available_policies()` on `LLMClient`, `from_env(plugins=True)`
- API freeze (v0.9): `__version__` attribute on package, API stability
  test snapshotting all `__all__` exports across 6 modules, version
  bumped to 0.9.0
- `.github/dependabot.yml` for automated dependency updates
- `SECURITY.md` with vulnerability reporting policy
- 101 new tests for health tracking, quota-aware routing, per-request policy,
  capability-based routing, model discovery, plugin system, and API stability
  (331 total)
