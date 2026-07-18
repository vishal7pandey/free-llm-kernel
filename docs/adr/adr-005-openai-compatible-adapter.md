# ADR-005: Single OpenAI-Compatible Adapter

## Status
Accepted

## Context
Most free LLM providers (Groq, Google Gemini, Cerebras, SambaNova, Cloudflare, Ollama)
expose OpenAI-compatible `/chat/completions` endpoints. Writing a separate adapter per
provider would duplicate nearly identical HTTP, parsing, and streaming logic.

## Decision
Implement a single `OpenAICompatibleAdapter` that handles all OpenAI-compatible providers.
Provider-specific differences (base URL, auth header, model ID format) are captured in
`AdapterConfig` and `ProviderMetadata`, not in adapter code.

## Alternatives Considered
1. **One adapter per provider** — maximum flexibility, but massive duplication
2. **Adapter with provider-specific branches** — violates open/closed, hard to maintain
3. **Plugin-based adapter registry** — overkill when all providers use the same protocol

## Consequences
- **Positive:** Adding a new OpenAI-compatible provider requires zero adapter code
- **Positive:** All providers share the same retry, timeout, and streaming logic
- **Negative:** Non-OpenAI-compatible providers (e.g., Anthropic native API) need a separate adapter
- **Negative:** Provider-specific features (e.g., Google's `thinking` config) require workarounds
