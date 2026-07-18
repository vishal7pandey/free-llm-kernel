"""
Thin LLM client that routes across free-tier providers with automatic fallback.

All providers expose OpenAI-compatible APIs, so we just swap base_url + api_key.
If one provider rate-limits (429) or errors, we try the next.

Usage:
    from services import LLMClient

    client = LLMClient()                       # auto-detects configured providers from env
    response = client.chat("Hello!")           # returns string
    for chunk in client.chat("Tell me a story", stream=True):
        print(chunk, end="", flush=True)

    # Pick a specific provider
    response = client.chat("Hello!", provider="groq")

    # List available providers
    print(client.available_providers())
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

from openai import OpenAI
from openai import RateLimitError, APIConnectionError, APIStatusError
from dotenv import load_dotenv

load_dotenv()

_USAGE_FILE = Path(__file__).parent / ".usage.json"


# Daily free-tier limits (requests per day). 0 = unknown/unlimited.
DAILY_LIMITS: dict[str, int] = {
    "groq": 1000,
    "google": 1500,
    "cerebras": 30,       # 1M tokens/day, ~30 requests for large models
    "mistral": 100,       # 2 RPM -> ~2880/day, but conservatively capped
    "sambanova": 100,
    "cohere": 100,        # trial key, rate-limited
    "openrouter": 50,
    "nvidia": 1000,       # 40 RPM -> ~57600/day, but free credits limited
    "cloudflare": 200,    # 10k neurons/day, varies by model size
    "ollama": 0,           # local, unlimited
}


@dataclass
class Provider:
    name: str
    base_url: str
    api_key_env: str
    models: list[str]
    default_model: str
    priority: int = 0
    daily_limit: int = 0

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)

    @property
    def is_configured(self) -> bool:
        key = self.api_key
        return key is not None and key.strip() != "" and key.strip() != "your-key-here"


PROVIDERS: list[Provider] = [
    Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        default_model="llama-3.3-70b-versatile",
        priority=1,
        daily_limit=DAILY_LIMITS["groq"],
    ),
    Provider(
        name="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        models=["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"],
        default_model="gemini-2.0-flash",
        priority=2,
        daily_limit=DAILY_LIMITS["google"],
    ),
    Provider(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        models=["llama-3.3-70b", "llama-3.1-8b"],
        default_model="llama-3.3-70b",
        priority=3,
        daily_limit=DAILY_LIMITS["cerebras"],
    ),
    Provider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        models=["mistral-small-latest", "mistral-large-latest"],
        default_model="mistral-small-latest",
        priority=4,
        daily_limit=DAILY_LIMITS["mistral"],
    ),
    Provider(
        name="sambanova",
        base_url="https://api.sambanova.ai/v1",
        api_key_env="SAMBANOVA_API_KEY",
        models=["Meta-Llama-3.3-70B-Instruct", "Meta-Llama-3.1-8B-Instruct"],
        default_model="Meta-Llama-3.3-70B-Instruct",
        priority=5,
        daily_limit=DAILY_LIMITS["sambanova"],
    ),
    Provider(
        name="cohere",
        base_url="https://api.cohere.ai/v1",
        api_key_env="COHERE_API_KEY",
        models=["command-r-plus", "command-r"],
        default_model="command-r-plus",
        priority=6,
        daily_limit=DAILY_LIMITS["cohere"],
    ),
    Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        models=["meta-llama/llama-3.3-70b-instruct:free", "google/gemini-2.0-flash-exp:free"],
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        priority=7,
        daily_limit=DAILY_LIMITS["openrouter"],
    ),
    Provider(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        models=["meta/llama-3.3-70b-instruct", "meta/llama-3.1-8b-instruct"],
        default_model="meta/llama-3.3-70b-instruct",
        priority=8,
        daily_limit=DAILY_LIMITS["nvidia"],
    ),
    Provider(
        name="cloudflare",
        base_url="https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1",
        api_key_env="CLOUDFLARE_API_TOKEN",
        models=["llama-3.3-70b-instruct", "llama-3.1-8b-instruct"],
        default_model="llama-3.3-70b-instruct",
        priority=9,
        daily_limit=DAILY_LIMITS["cloudflare"],
    ),
    Provider(
        name="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        models=["llama3.3", "llama3.1", "qwen2.5"],
        default_model="llama3.3",
        priority=10,
        daily_limit=DAILY_LIMITS["ollama"],
    ),
]


class LLMClient:
    """
    Multi-provider LLM client with automatic fallback.

    Reads API keys from environment variables (or .env file).
    Only uses providers that have valid keys configured.
    Falls back to the next provider on rate limits or errors.
    Tracks daily usage per provider and skips providers that hit their daily limit.
    """

    def __init__(self, providers: list[Provider] | None = None):
        self._all_providers = providers or PROVIDERS
        self._active: list[Provider] = [p for p in self._all_providers if p.is_configured]
        if not self._active:
            raise RuntimeError(
                "No LLM providers configured. Set at least one API key in your .env file. "
                "See .env.example for all available variables."
            )
        self._active.sort(key=lambda p: p.priority)
        self._usage = self._load_usage()

    def available_providers(self) -> list[str]:
        """Return names of providers with valid API keys."""
        return [p.name for p in self._active]

    def usage(self) -> dict[str, dict]:
        """Return per-provider usage stats for today."""
        today = str(date.today())
        result = {}
        for p in self._active:
            count = self._usage.get(today, {}).get(p.name, 0)
            limit = p.daily_limit
            remaining = (limit - count) if limit > 0 else None
            result[p.name] = {
                "used": count,
                "limit": limit if limit > 0 else "unlimited",
                "remaining": remaining if remaining is not None else "unlimited",
            }
        return result

    def print_usage(self) -> None:
        """Print a formatted usage table to stdout."""
        u = self.usage()
        print(f"\n{'Provider':<14} {'Used':>6} {'Limit':>8} {'Remaining':>10}")
        print("-" * 42)
        for name, stats in u.items():
            print(f"{name:<14} {stats['used']:>6} {str(stats['limit']):>8} {str(stats['remaining']):>10}")
        print()

    def _load_usage(self) -> dict:
        """Load usage from disk, resetting if it's a new day."""
        if _USAGE_FILE.exists():
            try:
                data = json.loads(_USAGE_FILE.read_text())
                today = str(date.today())
                if today not in data:
                    data = {today: {}}
                return data
            except (json.JSONDecodeError, KeyError):
                pass
        return {str(date.today()): {}}

    def _save_usage(self) -> None:
        """Persist usage to disk."""
        try:
            _USAGE_FILE.write_text(json.dumps(self._usage, indent=2))
        except OSError:
            pass

    def _increment_usage(self, provider_name: str) -> None:
        """Increment the request counter for a provider (today)."""
        today = str(date.today())
        if today not in self._usage:
            self._usage = {today: {}}
        self._usage[today][provider_name] = self._usage[today].get(provider_name, 0) + 1
        self._save_usage()

    def _is_exhausted(self, provider: Provider) -> bool:
        """Check if a provider has hit its daily limit."""
        if provider.daily_limit == 0:
            return False
        today = str(date.today())
        used = self._usage.get(today, {}).get(provider.name, 0)
        return used >= provider.daily_limit

    def _get_client(self, provider: Provider) -> OpenAI:
        base_url = provider.base_url
        if "{CF_ACCOUNT_ID}" in base_url:
            account_id = os.getenv("CF_ACCOUNT_ID", "")
            base_url = base_url.replace("{CF_ACCOUNT_ID}", account_id)

        api_key = provider.api_key or "ollama"
        return OpenAI(base_url=base_url, api_key=api_key)

    def chat(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        system: str | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> str | Iterator[str]:
        """
        Send a chat completion request.

        Args:
            prompt: The user message.
            provider: Force a specific provider (e.g. "groq"). None = auto-select with fallback.
            model: Force a specific model. None = use provider's default.
            system: Optional system prompt.
            stream: If True, returns an iterator of string chunks.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            **kwargs: Extra args passed to the OpenAI API call.

        Returns:
            Response string, or iterator of string chunks if stream=True.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if provider:
            candidates = [p for p in self._active if p.name == provider]
            if not candidates:
                raise ValueError(
                    f"Provider '{provider}' not configured. Available: {self.available_providers()}"
                )
        else:
            candidates = self._active

        last_error = None
        for prov in candidates:
            if self._is_exhausted(prov):
                continue

            try:
                client = self._get_client(prov)
                use_model = model or prov.default_model

                if stream:
                    self._increment_usage(prov.name)
                    return self._stream(client, use_model, messages, temperature, max_tokens, **kwargs)

                response = client.chat.completions.create(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                self._increment_usage(prov.name)
                return response.choices[0].message.content or ""

            except (RateLimitError, APIConnectionError, APIStatusError) as e:
                last_error = e
                continue

        raise RuntimeError(
            f"All providers failed or exhausted. Last error: {last_error}"
        )

    def _stream(
        self,
        client: OpenAI,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int | None,
        **kwargs,
    ) -> Iterator[str]:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
