# Free LLM Kernel

A minimal, provider-agnostic inference kernel for free LLM APIs with automatic fallback, retry, circuit breaking, and usage tracking.

## Why?

You want to build a GenAI app without paying for OpenAI. There are many free LLM providers (Groq, Google Gemini, Cerebras, SambaNova, Cloudflare, Ollama) — but each has different APIs, quotas, and reliability. This kernel abstracts them all behind one interface with automatic fallback when one provider goes down.

## Quick Start

```bash
cd C:\Dev\personal\free-llm-kernel
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

```python
from llm_kernel.planner import Planner, WorldState, FastestPolicy, CheapestPolicy, QualityPolicy
from llm_kernel.config import default_providers, build_world_state

providers = default_providers()
world_state = build_world_state(providers)

# Use fastest policy (prioritize latency)
planner = Planner(world_state, policy=FastestPolicy())

# Or cheapest, or quality
planner = Planner(world_state, policy=CheapestPolicy())
planner = Planner(world_state, policy=QualityPolicy())

# Custom policy
from llm_kernel.planner import RoutingPolicy, HealthSnapshot, QuotaSnapshot

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

## Test Suite

```bash
uv run pytest          # 230 tests
uv run lint-imports    # architecture verification
```
