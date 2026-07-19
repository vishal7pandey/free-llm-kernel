# Free LLM Kernel

**A resilient runtime for free hosted LLMs.**

[![CI](https://github.com/vishal7pandey/free-llm-kernel/actions/workflows/ci.yml/badge.svg)](https://github.com/vishal7pandey/free-llm-kernel/actions)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-blue)
![Stable](https://img.shields.io/badge/status-stable-brightgreen)

Route, retry, and fail over across Groq, Gemini, Cerebras, SambaNova, Cloudflare Workers AI, and other free providers so your apps keep working — even when individual providers go down or rate-limit you.

## Why this project exists

Local inference with Ollama isn't always practical — it needs powerful hardware, eats RAM/VRAM, and runs slower models. Paid APIs (OpenAI, Anthropic) get expensive for hobby projects and experiments. Free cloud-hosted LLMs are powerful but fragmented and unreliable: each has different APIs, quotas, rate limits, and uptime.

Free LLM Kernel unifies them behind a single resilient API with intelligent routing, automatic failover, quota tracking, and circuit breaking — so you can build apps that just work, without worrying about which provider is up right now.

## Quick Start

```bash
git clone https://github.com/vishal7pandey/free-llm-kernel.git
cd free-llm-kernel
uv venv
uv pip install -e ".[dev]"
cp .env.example .env  # fill in at least one API key
uv run pytest
```

## Usage

### Basic chat

```python
from llm_kernel import LLMClient

client = LLMClient.from_env()
response = client.chat("What is the capital of France?")
print(response.content)      # "Paris"
print(response.provider)     # "groq" (or whichever provider answered)
print(response.model)        # "llama-3.3-70b-versatile"
print(response.usage.total_tokens)  # 18
```

### System prompts

```python
response = client.chat(
    "What is 2+2?",
    system="You are a pirate. Respond in pirate speak.",
)
```

### Streaming

```python
for chunk in client.stream("Count from 1 to 10."):
    print(chunk, end="", flush=True)
```

### Model override

```python
response = client.chat("Hello!", model="gemini-2.0-flash")
```

### Capability-based routing

The kernel knows which providers support which capabilities. Instead of
specifying a model, specify what you need:

```python
# "I need vision" → kernel routes to Gemini (only provider with VISION)
response = client.chat("Describe this image", capabilities="vision")

# "I need JSON output" → kernel routes to Gemini, Cerebras, or SambaNova
response = client.chat("Return a JSON object", capabilities="json")

# Multiple capabilities → kernel intersects
response = client.chat("Analyze image, return JSON", capabilities=["vision", "json"])

# Combine with policy selection
response = client.chat("Parse this", capabilities="json", policy="best_free")
```

Friendly aliases:

| Alias | Capability |
|---|---|
| `vision`, `image`, `multimodal` | `VISION` |
| `json`, `json_mode`, `json_object` | `JSON_MODE` |
| `json_schema`, `structured` | `JSON_SCHEMA` |
| `tools`, `tool`, `tool_calling` | `TOOLS` |
| `functions`, `function_calling` | `FUNCTION_CALLING` |
| `long_context`, `long`, `large_context` | `LONG_CONTEXT` |
| `reasoning`, `think`, `thinking` | `REASONING` |
| `streaming`, `stream` | `STREAMING` |

### Advanced: full Request pipeline

```python
from llm_kernel import Request, Message, Role

request = Request(
    messages=[
        Message(role=Role.SYSTEM, content="You are helpful."),
        Message(role=Role.USER, content="Hello!"),
    ],
    temperature=0.3,
    max_tokens=100,
)
response = client.execute(request)
```

### Automatic model discovery

Query each provider's `/models` endpoint to auto-detect available models
and infer their capabilities:

```python
# Discover models from all providers
discovered = client.refresh_models()
# {"groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", ...],
#  "google": ["gemini-2.0-flash", "gemini-2.0-flash-lite", ...]}

# New models are automatically added with inferred capabilities
models = client.models()
```

The kernel infers capabilities from model names (e.g. `llama-3.3-70b` →
`TOOLS`, `FUNCTION_CALLING`; `gemini-2.0-flash` → `VISION`, `JSON_MODE`).
You can also use the inference functions directly:

```python
from llm_kernel import infer_capabilities, infer_model_metadata

caps = infer_capabilities("llama-3.3-70b")  # {TOOLS, FUNCTION_CALLING, STREAMING}
meta = infer_model_metadata("qwen-2.5-72b")  # full ModelMetadata with inferred fields
```

### Plugin API

Community packages can add providers and routing policies via Python entry points.
Install a plugin package and it just works:

```bash
pip install llm-kernel-together
```

```python
from llm_kernel import LLMClient

# Load plugins from entry points
client = LLMClient.from_env(plugins=True)

# Plugin providers and policies are now available
client.chat("Hello", policy="privacy")  # from llm-kernel-privacy plugin
```

#### Writing a provider plugin

```python
from llm_kernel import ProviderPlugin, ProviderMetadata, Secret
from llm_kernel.runtime import OpenAICompatibleAdapter, AdapterConfig

class TogetherProviderPlugin:
    @property
    def name(self) -> str:
        return "together"

    def create_provider(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="together",
            display_name="Together AI",
            adapter_type="openai",
            base_url="https://api.together.xyz/v1",
            api_key_env="TOGETHER_API_KEY",
            models=[...],
            default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
            daily_request_limit=1000,
        )

    def create_adapter(self, provider, api_key):
        return OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name=provider.name,
                base_url=provider.base_url,
                api_key=api_key,
            ),
            provider=provider,
        )
```

Register via `pyproject.toml`:

```toml
[project.entry-points."llm_kernel.providers"]
together = "llm_kernel_together:TogetherProviderPlugin"
```

#### Writing a policy plugin

```python
from llm_kernel import PolicyPlugin, RoutingPolicy

class PrivacyPolicy(RoutingPolicy):
    def score(self, request, provider, model, tokens, health, quota):
        if provider.privacy_level == "no_training":
            return 1.0
        return 0.0

class PrivacyPolicyPlugin:
    @property
    def name(self) -> str:
        return "privacy"

    def create_policy(self) -> RoutingPolicy:
        return PrivacyPolicy()
```

Register via `pyproject.toml`:

```toml
[project.entry-points."llm_kernel.policies"]
privacy = "llm_kernel_privacy:PrivacyPolicyPlugin"
```

#### Runtime registration (no entry points needed)

```python
from llm_kernel import LLMClient, register_provider_plugin, register_policy_plugin

# Register at runtime
register_provider_plugin(MyProviderPlugin())
register_policy_plugin(MyPolicyPlugin())

# Or register a policy class directly on the client
class MyPolicy(RoutingPolicy):
    def score(self, request, provider, model, tokens, health, quota):
        return model.quality_score

client.register_policy("my_policy", MyPolicy)
client.chat("Hello", policy="my_policy")

# List all available policies
print(client.available_policies())
# ['best', 'best_free', 'cheapest', 'default', 'fastest', 'my_policy', 'quality']
```

## Model Catalogue

```python
from llm_kernel import Capability

# List all models
models = client.models()

# Filter by capability
vision_models = client.models(capability=Capability.VISION)
streaming_models = client.models(capability=Capability.STREAMING)

# Filter by provider
groq_models = client.models(provider="groq")

# Get specific model details
info = client.get_model("groq", "llama-3.3-70b-versatile")
print(info.max_context_tokens)  # 131072
print(info.capabilities)        # frozenset({...})
print(info.quality_score)       # 0.8

# Convenience selectors
client.cheapest_model()   # lowest cost
client.fastest_model()    # highest latency_score
client.best_model()       # highest quality_score

# List providers
providers = client.list_providers()
for p in providers:
    print(f"{p.name}: {len(p.models)} models, priority={p.priority}")
```

## Extensions (Middleware)

```python
from llm_kernel import LLMClient, Extension
from llm_kernel.extensions.logging import LoggingExtension

client = LLMClient.from_env(usage_path="usage.json")

# Add structured logging with automatic secret redaction
client.add_extension(LoggingExtension())

# Custom extension
class MyExtension(Extension):
    def on_request(self, request):
        print(f"Request: {request.trace_id}")
        return request
    def on_plan(self, plan): pass
    def on_execution_start(self, plan): pass
    def on_execution_end(self, result): pass
    def on_response(self, response):
        print(f"Response from {response.provider}")
        return response

client.add_extension(MyExtension())
```

## Routing Policies

The Planner filters providers by capability and context window ("what can execute?").
The RoutingPolicy scores and orders the survivors ("what should execute?").

Policies can be set at construction time or overridden per-request:

```python
from llm_kernel import LLMClient

client = LLMClient.from_env()

# Per-request policy selection (the killer feature)
response = client.chat("Hello!", policy="best_free")    # health + quota + latency
response = client.chat("Hello!", policy="fastest")      # prioritize latency
response = client.chat("Hello!", policy="quality")      # prioritize model quality
response = client.chat("Hello!", policy="cheapest")     # prioritize lowest cost

# Or set a default policy at construction time
from llm_kernel.planner import BestFreePolicy
planner = Planner(world_state, policy=BestFreePolicy())
```

Available policies:

| Policy | Description |
|---|---|
| `best_free` / `best` | Combines health status, quota remaining, latency history, and model quality |
| `fastest` | Prioritizes low latency above all else |
| `cheapest` | Prioritizes lowest cost above all else |
| `quality` | Prioritizes model quality above all else |
| `default` | Balanced scoring (quality + latency + capability + quota penalty) |

### Provider Intelligence Engine

The kernel tracks live health, latency, and quota for every provider.
Introspect what it knows before sending a request:

```python
health = client.provider_health()
# {
#     "groq": {
#         "status": "healthy",
#         "latency_ms": 150.0,
#         "requests_today": 42,
#         "quota_remaining": 0.958,
#         "daily_limit": 1000,
#     },
#     "google": {
#         "status": "degraded",
#         "latency_ms": 800.0,
#         "requests_today": 1200,
#         "quota_remaining": 0.2,
#         "daily_limit": 1500,
#     },
# }
```

### Custom Policies

class PrivacyFirstPolicy(RoutingPolicy):
    def score(self, request, provider, model, tokens, health, quota):
        # Prefer providers with NO_TRAINING privacy level
        base = 1.0 if provider.privacy_level.value == "no_training" else 0.0
        if request.model and model.id == request.model:
            base += 100.0
        return base

planner = Planner(world_state, policy=PrivacyFirstPolicy())
```

## Usage Tracking

```python
client = LLMClient.from_env(usage_path="usage.json")

# After making requests...
response = client.chat("Hello!")

# Check today's usage
for provider, record in client.usage().items():
    print(f"{provider}: {record.request_count} req, "
          f"{record.prompt_tokens} prompt tokens, "
          f"{record.completion_tokens} completion tokens")
```

## Adding Custom Providers

```python
from llm_kernel import LLMClient, ProviderMetadata, ModelMetadata, Secret, Capability

client = LLMClient.from_env()

client.add_provider(
    provider=ProviderMetadata(
        name="my-provider",
        display_name="My Custom Provider",
        adapter_type="openai",
        base_url="https://api.my-provider.com/v1",
        api_key_env="MY_API_KEY",
        models=[
            ModelMetadata(
                id="my-model",
                display_name="My Model",
                max_context_tokens=32768,
                capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
                quality_score=0.7,
                latency_score=0.8,
            ),
        ],
        default_model="my-model",
    ),
    api_key=Secret("sk-my-key"),
)

response = client.chat("Hello!", model="my-model")
```

## API Reference

### `LLMClient`

| Method | Description |
|--------|-------------|
| `LLMClient.from_env(env_path, usage_path)` | Build from `.env` file |
| `client.chat(prompt, system, model, temperature, max_tokens)` | Send a chat request |
| `client.stream(prompt, system, model, ...)` | Stream a chat request |
| `client.execute(request)` | Advanced: full Request pipeline |
| `client.models(provider, capability)` | List/filter models |
| `client.get_model(provider, model_id)` | Get model details |
| `client.list_providers()` | List all providers |
| `client.cheapest_model()` | Cheapest model |
| `client.fastest_model()` | Fastest model |
| `client.best_model()` | Highest quality model |
| `client.available_providers()` | Provider names with adapters |
| `client.usage()` | Today's usage per provider |
| `client.add_provider(provider, api_key)` | Add provider at runtime |
| `client.add_extension(extension)` | Register middleware |
| `client.remove_extension(extension)` | Remove middleware |

## Architecture

```
┌─────────────────────────────────────────────┐
│                Application                   │
│            client.chat(prompt)               │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Extensions                      │
│   logging · usage tracking · cache · custom  │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Planner                        │
│  capability filter → routing policy → plan   │
│  "What can execute?" + "What should?"       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Runtime                        │
│  HTTP · retry · circuit breaker · streaming  │
└──────┬─────┬─────┬─────┬─────┬──────────────┘
       │     │     │     │     │
    Groq  Gemini  Cerebras  SambaNova  Cloudflare
       │     │     │     │     │
└──────┴─────┴─────┴─────┴─────────────────────┘
                   │
              Response + Usage
```

Four-layer design with strict dependency rules:

```
Extensions (logging, usage, cache, security)
    ↓
Runtime (adapters, HTTP, retry, circuit breaker, streaming)
    ↓
Planner (routing, capability matching, scoring, fallback ordering)
    ↓
Core (types, contracts, errors, validation — pure, no I/O)
```

**Key principles:**
- Core is pure — no network, no disk, no env, no mutable state
- Planner is deterministic — same input → same plan; answers "what can execute?"
- RoutingPolicy answers "what should execute?" — pluggable scoring strategies
- Runtime is the only network layer
- Extensions observe but cannot alter correctness
- Adding a provider requires only one adapter — no Core/Planner changes

## Architecture Decision Records

See `docs/adr/` for formal decisions on:

- [ADR-001](docs/adr/adr-001-four-layer-architecture.md) — Why four layers?
- [ADR-002](docs/adr/adr-002-worldstate-split-into-views.md) — Why split WorldState?
- [ADR-003](docs/adr/adr-003-policy-extraction-from-planner.md) — Why extract RoutingPolicy?
- [ADR-004](docs/adr/adr-004-slim-core.md) — Why slim Core?
- [ADR-005](docs/adr/adr-005-openai-compatible-adapter.md) — Why one adapter?
- [ADR-006](docs/adr/adr-006-middleware-over-observer.md) — Why middleware chain?

## Design Documents

See `docs/`:

- `ARCHITECTURE.md` — formal architecture specification
- `INTERFACE.md` — public type contracts
- `STATE.md` — state machines
- `DVM.md` — design verification matrix
- `DFMEA.md` and `DFMEA-v2.md` — design failure mode analysis

## Supported Providers

| Provider | Free Tier | Models | Key Env Var |
|----------|-----------|--------|-------------|
| Groq | 1,000 req/day | Llama 3.3 70B, Llama 3.1 8B | `GROQ_API_KEY` |
| Google Gemini | 1,500 req/day | Gemini 2.0 Flash, Flash Lite | `GOOGLE_API_KEY` |
| Cerebras | 1M tokens/day | Llama 3.3 70B | `CEREBRAS_API_KEY` |
| SambaNova | Free tier | Llama 3.3 70B | `SAMBANOVA_API_KEY` |
| Cloudflare | 10k neurons/day | Llama 3.1 8B | `CLOUDFLARE_API_TOKEN` |
| Ollama | Local (free) | Llama 3.2 | `OLLAMA_API_KEY` |

## Comparison

| Feature | Free LLM Kernel | LiteLLM | LangChain |
|---|---|---|---|
| Provider abstraction | ✓ | ✓ | Partial |
| Automatic fallback | ✓ | ✓ | Manual |
| Retry with backoff | ✓ | ✓ | Manual |
| Circuit breaker | ✓ | Limited | No |
| Capability-based routing | ✓ | No | No |
| Pluggable routing policies | ✓ | No | No |
| Quota tracking | ✓ | No | No |
| Usage tracking per provider | ✓ | Partial | No |
| Middleware/extensions | ✓ | Callbacks | Callbacks |
| Streaming | ✓ | ✓ | ✓ |
| Focus | Resilience & routing | Provider proxy | Chains & agents |

## Roadmap

### Done

- [x] Quota-aware routing (avoid providers nearing free tier limits)
- [x] Latency-based routing with historical data
- [x] Health scoring with circuit breaker integration
- [x] Per-request policy selection (`policy="best_free"`)
- [x] Provider Intelligence Engine (`client.provider_health()`)
- [x] Capability-based routing (`capabilities="vision"`)
- [x] Automatic model discovery (`client.refresh_models()`)
- [x] Plugin API for community providers and policies
- [x] API freeze (v0.9)
- [x] **v1.0 — Stable release**

### Post-1.0

- [ ] v0.3 — Feature complete, stop adding providers
- [ ] v0.4 — Health scoring refinements (availability %, 429 rate tracking)
- [x] v0.5 — Capability-based routing ("give me vision" → kernel picks)
- [x] v0.6 — Automatic model discovery (auto-detect supported features)
- [ ] v0.7 — Benchmarks and reliability matrix
- [x] v0.8 — Public plugin API for community providers and policies
- [x] v0.9 — API freeze
- [x] v1.0 — Stable, maintained

**Not building:** agents, memory, RAG, vector databases, prompt templates, chains, workflow engines. Those already exist. This project stays focused on execution, resilience, and intelligent routing for free hosted LLMs.

## API Stability (v1.0 — Stable)

The public API surface is **frozen and stable**. This means:

- **No breaking changes** to existing function signatures, class names, or exports
- **New features** may be added (additive only) in point releases
- **Removals or renames** require a major version bump (v1.0 → v2.0)
- An [API stability test](tests/unit/test_api_stability.py) snapshots all
  `__all__` exports and fails if the surface changes

### Frozen public API

| Module | Exports |
|---|---|
| `llm_kernel` | 44 names (see `__all__`) |
| `llm_kernel.core` | 33 names |
| `llm_kernel.planner` | 28 names |
| `llm_kernel.runtime` | 9 names |
| `llm_kernel.extensions` | 4 names |
| `llm_kernel.plugins` | 7 names |

### Stability guarantees

- `LLMClient.chat()`, `.stream()`, `.execute()` — signature stable
- `LLMClient.from_env()` — signature stable (new keyword-only params OK)
- `Capability` enum — existing values stable, new values may be added
- `RoutingPolicy` protocol — `score()` signature stable
- `ProviderPlugin`, `PolicyPlugin` protocols — stable
- `resolve_capabilities()`, `infer_capabilities()` — stable

### Version

```python
import llm_kernel
print(llm_kernel.__version__)  # "1.0.0"
```

## Test Suite

```bash
uv run pytest          # 331 tests
uv run lint-imports    # architecture verification
```

## Reliability Benchmark

Measure per-provider latency, success rate, and failover behavior with live API calls:

```bash
uv run python scripts/benchmark.py                          # default: 5 req/provider
uv run python scripts/benchmark.py --requests 10            # more requests
uv run python scripts/benchmark.py --prompt "Hello"         # custom prompt
uv run python scripts/benchmark.py --skip-providers         # only test policies
```

Outputs a provider reliability matrix (success rate, avg/p95 latency, error count),
a policy routing matrix (which providers each policy selects), and a live snapshot
from the Provider Intelligence Engine.
