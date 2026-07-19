"""Tests for llm_kernel.config — provider registry and WorldState construction.

Run: uv run pytest tests/unit/test_config -v
"""

from pathlib import Path


class TestProviderRegistry:
    def test_default_providers_contains_known_names(self):
        from llm_kernel.config import default_providers

        providers = default_providers()
        names = {p.name for p in providers}
        assert "groq" in names
        assert "google" in names
        assert "cloudflare" in names

    def test_default_providers_have_models(self):
        from llm_kernel.config import default_providers

        for provider in default_providers():
            assert len(provider.models) > 0
            assert provider.default_model in {m.id for m in provider.models}

    def test_default_providers_have_capabilities(self):
        from llm_kernel.config import default_providers

        for provider in default_providers():
            # At least streaming should be common
            assert len(provider.capabilities) > 0 or any(
                len(m.capabilities) > 0 for m in provider.models
            )


class TestLoadConfig:
    def test_load_env_file(self, tmp_path: Path):
        from llm_kernel.config import load_env

        env_file = tmp_path / ".env"
        env_file.write_text("GROQ_API_KEY=sk-test123\nGOOGLE_API_KEY=AIzaTest\n")

        env = load_env(env_file)
        assert env["GROQ_API_KEY"] == "sk-test123"
        assert env["GOOGLE_API_KEY"] == "AIzaTest"

    def test_load_env_missing_file_returns_empty(self, tmp_path: Path):
        from llm_kernel.config import load_env

        env = load_env(tmp_path / "nonexistent.env")
        assert env == {}

    def test_build_world_state_from_providers(self):
        from llm_kernel.config import build_world_state, default_providers
        from llm_kernel.planner import WorldState

        providers = default_providers()
        ws = build_world_state(providers)
        assert isinstance(ws, WorldState)
        assert len(ws.providers) == len(providers)

    def test_build_adapters_from_env(self, tmp_path: Path):
        from llm_kernel.config import build_adapters, default_providers, load_env
        from llm_kernel.runtime import OpenAICompatibleAdapter

        env_file = tmp_path / ".env"
        env_file.write_text("GROQ_API_KEY=sk-test123\n")
        env = load_env(env_file)

        providers = default_providers()
        adapters = build_adapters(providers, env)

        assert "groq" in adapters
        assert isinstance(adapters["groq"], OpenAICompatibleAdapter)
