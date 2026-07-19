"""Configuration: provider registry, env loading, WorldState and adapter construction.

This module is not part of the layered architecture — it sits above all layers
and wires them together.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llm_kernel.core import (
    Capability,
    PrivacyLevel,
    Secret,
)
from llm_kernel.planner import ModelMetadata, ProviderMetadata, WorldState
from llm_kernel.runtime import AdapterConfig, OpenAICompatibleAdapter

# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------


def default_providers() -> list[ProviderMetadata]:
    """Return the built-in provider registry with known free-tier providers."""
    return [
        ProviderMetadata(
            name="groq",
            display_name="Groq",
            adapter_type="openai",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            models=[
                ModelMetadata(
                    id="llama-3.3-70b-versatile",
                    display_name="Llama 3.3 70B",
                    max_context_tokens=131_072,
                    max_output_tokens=32_768,
                    capabilities=frozenset(
                        {
                            Capability.STREAMING,
                            Capability.TOOLS,
                            Capability.FUNCTION_CALLING,
                        }
                    ),
                    quality_score=0.8,
                    latency_score=0.95,
                ),
                ModelMetadata(
                    id="llama-3.1-8b-instant",
                    display_name="Llama 3.1 8B",
                    max_context_tokens=131_072,
                    max_output_tokens=8_192,
                    capabilities=frozenset(
                        {
                            Capability.STREAMING,
                            Capability.TOOLS,
                            Capability.FUNCTION_CALLING,
                        }
                    ),
                    quality_score=0.6,
                    latency_score=0.98,
                ),
            ],
            default_model="llama-3.3-70b-versatile",
            priority=0,
            capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
            privacy_level=PrivacyLevel.NO_TRAINING,
        ),
        ProviderMetadata(
            name="google",
            display_name="Google AI Studio",
            adapter_type="openai",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GOOGLE_API_KEY",
            models=[
                ModelMetadata(
                    id="gemini-2.0-flash",
                    display_name="Gemini 2.0 Flash",
                    max_context_tokens=1_048_576,
                    max_output_tokens=8_192,
                    capabilities=frozenset(
                        {
                            Capability.STREAMING,
                            Capability.VISION,
                            Capability.JSON_MODE,
                            Capability.TOOLS,
                        }
                    ),
                    quality_score=0.75,
                    latency_score=0.8,
                ),
                ModelMetadata(
                    id="gemini-2.0-flash-lite",
                    display_name="Gemini 2.0 Flash Lite",
                    max_context_tokens=1_048_576,
                    max_output_tokens=8_192,
                    capabilities=frozenset(
                        {
                            Capability.STREAMING,
                            Capability.VISION,
                            Capability.JSON_MODE,
                        }
                    ),
                    quality_score=0.65,
                    latency_score=0.85,
                ),
            ],
            default_model="gemini-2.0-flash",
            priority=1,
            capabilities=frozenset({Capability.STREAMING, Capability.VISION, Capability.JSON_MODE}),
            privacy_level=PrivacyLevel.NO_TRAINING,
        ),
        ProviderMetadata(
            name="cloudflare",
            display_name="Cloudflare Workers AI",
            adapter_type="openai",
            base_url="https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1",
            api_key_env="CLOUDFLARE_API_TOKEN",
            models=[
                ModelMetadata(
                    id="@cf/meta/llama-3.1-8b-instruct",
                    display_name="Llama 3.1 8B (CF)",
                    max_context_tokens=8_192,
                    max_output_tokens=2_048,
                    capabilities=frozenset({Capability.STREAMING}),
                    quality_score=0.55,
                    latency_score=0.7,
                ),
            ],
            default_model="@cf/meta/llama-3.1-8b-instruct",
            priority=2,
            capabilities=frozenset({Capability.STREAMING}),
            privacy_level=PrivacyLevel.NO_TRAINING,
        ),
        ProviderMetadata(
            name="cerebras",
            display_name="Cerebras",
            adapter_type="openai",
            base_url="https://api.cerebras.ai/v1",
            api_key_env="CEREBRAS_API_KEY",
            models=[
                ModelMetadata(
                    id="llama-3.3-70b",
                    display_name="Llama 3.3 70B (Cerebras)",
                    max_context_tokens=131_072,
                    max_output_tokens=8_192,
                    capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
                    quality_score=0.8,
                    latency_score=0.97,
                ),
            ],
            default_model="llama-3.3-70b",
            priority=0,
            capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
            privacy_level=PrivacyLevel.UNKNOWN,
        ),
        ProviderMetadata(
            name="sambanova",
            display_name="SambaNova",
            adapter_type="openai",
            base_url="https://api.sambanova.ai/v1",
            api_key_env="SAMBANOVA_API_KEY",
            models=[
                ModelMetadata(
                    id="Meta-Llama-3.3-70B-Instruct",
                    display_name="Llama 3.3 70B (SambaNova)",
                    max_context_tokens=131_072,
                    max_output_tokens=4_096,
                    capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
                    quality_score=0.8,
                    latency_score=0.85,
                ),
            ],
            default_model="Meta-Llama-3.3-70B-Instruct",
            priority=1,
            capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
            privacy_level=PrivacyLevel.UNKNOWN,
        ),
        ProviderMetadata(
            name="ollama",
            display_name="Ollama (Local)",
            adapter_type="openai",
            base_url="http://localhost:11434/v1",
            api_key_env="OLLAMA_API_KEY",
            models=[
                ModelMetadata(
                    id="llama3.2",
                    display_name="Llama 3.2 (Local)",
                    max_context_tokens=131_072,
                    max_output_tokens=4_096,
                    capabilities=frozenset({Capability.STREAMING}),
                    quality_score=0.6,
                    latency_score=0.5,
                ),
            ],
            default_model="llama3.2",
            priority=3,
            capabilities=frozenset({Capability.STREAMING}),
            privacy_level=PrivacyLevel.NO_TRAINING,
        ),
    ]


# ---------------------------------------------------------------------------
# Env Loading
# ---------------------------------------------------------------------------


def load_env(path: Path | str | None = None) -> dict[str, str]:
    """Load environment variables from a .env file.

    If path is None, looks for .env in the current directory.
    Does NOT override existing os.environ values.
    """
    path = Path(".env") if path is None else Path(path)

    if not path.exists():
        return {}

    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        env[key] = value

    return env


def resolve_env(env_path: str | None = None) -> dict[str, str]:
    """Merge .env file with os.environ. os.environ takes precedence."""
    merged = load_env(env_path)
    # os.environ always wins
    for key in list(merged.keys()):
        if key in os.environ:
            merged[key] = os.environ[key]
    return merged


# ---------------------------------------------------------------------------
# WorldState & Adapter Construction
# ---------------------------------------------------------------------------


def build_world_state(
    providers: list[ProviderMetadata],
    usage: dict[str, Any] | None = None,
    latency: dict[str, float] | None = None,
    health: dict[str, str] | None = None,
) -> WorldState:
    """Build a WorldState from a list of providers."""
    return WorldState(
        providers=providers,
        usage=usage or {},
        latency=latency or {},
        health=health or {},
    )


def build_adapters(
    providers: list[ProviderMetadata],
    env: dict[str, str],
) -> dict[str, OpenAICompatibleAdapter]:
    """Build adapter instances for all providers that have API keys in env."""
    adapters: dict[str, OpenAICompatibleAdapter] = {}

    for provider in providers:
        api_key = env.get(provider.api_key_env)
        if not api_key or api_key == "your-key-here":
            continue

        base_url = provider.base_url
        # Cloudflare needs account ID substitution
        if "{CF_ACCOUNT_ID}" in base_url:
            account_id = env.get("CF_ACCOUNT_ID", "")
            if not account_id or account_id == "your-account-id-here":
                continue
            base_url = base_url.replace("{CF_ACCOUNT_ID}", account_id)

        config = AdapterConfig(
            provider_name=provider.name,
            base_url=base_url,
            api_key=Secret(api_key),
        )
        adapters[provider.name] = OpenAICompatibleAdapter(
            config=config,
            provider=provider,
        )

    return adapters


def filter_available_providers(
    providers: list[ProviderMetadata],
    env: dict[str, str],
) -> list[ProviderMetadata]:
    """Return only providers whose API key is present in env."""
    available = []
    for provider in providers:
        api_key = env.get(provider.api_key_env)
        if not api_key or api_key == "your-key-here":
            continue
        if "{CF_ACCOUNT_ID}" in provider.base_url:
            account_id = env.get("CF_ACCOUNT_ID", "")
            if not account_id or account_id == "your-account-id-here":
                continue
        available.append(provider)
    return available


__all__ = [
    "default_providers",
    "load_env",
    "resolve_env",
    "build_world_state",
    "build_adapters",
    "filter_available_providers",
]
