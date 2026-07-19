"""Tests for llm_kernel.extensions — usage tracking, logging, cache.

Run: uv run pytest tests/unit/extensions -v
"""

import json
from pathlib import Path

import pytest


class TestUsageStore:
    @pytest.fixture
    def tmp_usage_file(self, tmp_path: Path) -> Path:
        return tmp_path / "usage.json"

    def test_record_usage_creates_entry(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        store.record(
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        records = store.get_today()
        assert len(records) == 1
        assert records[0].provider == "groq"
        assert records[0].model == "llama-3.3-70b"
        assert records[0].request_count == 1
        assert records[0].prompt_tokens == 10
        assert records[0].completion_tokens == 5

    def test_record_usage_accumulates(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        store.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        store.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        )

        records = store.get_today()
        assert len(records) == 1
        assert records[0].request_count == 2
        assert records[0].prompt_tokens == 30
        assert records[0].completion_tokens == 15

    def test_record_multiple_providers(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        store.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        store.record(
            "google",
            "gemini-2.0-flash",
            Usage(prompt_tokens=8, completion_tokens=4, total_tokens=12),
        )

        records = store.get_today()
        assert len(records) == 2

    def test_persists_to_disk(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        store.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )

        assert tmp_usage_file.exists()
        data = json.loads(tmp_usage_file.read_text())
        assert len(data) >= 1

    def test_loads_from_disk(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store1 = UsageStore(path=tmp_usage_file)
        store1.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )

        store2 = UsageStore(path=tmp_usage_file)
        records = store2.get_today()
        assert len(records) == 1
        assert records[0].request_count == 1

    def test_get_today_filters_by_date(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage, UsageRecord
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        # Inject an old record directly
        old_date = "2025-01-01"
        store._data[old_date] = {
            "groq:llama-3.3-70b": UsageRecord(
                provider="groq",
                model="llama-3.3-70b",
                day=old_date,
                request_count=5,
                prompt_tokens=100,
                completion_tokens=50,
            )
        }
        store._save()

        # Record today
        store.record(
            "google",
            "gemini-2.0-flash",
            Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        today = store.get_today()
        assert len(today) == 1
        assert today[0].provider == "google"

    def test_get_provider_usage_today(self, tmp_usage_file: Path):
        from llm_kernel.core import Usage
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        store.record(
            "groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        store.record(
            "google",
            "gemini-2.0-flash",
            Usage(prompt_tokens=8, completion_tokens=4, total_tokens=12),
        )

        groq_usage = store.get_provider_usage_today("groq")
        assert groq_usage is not None
        assert groq_usage.request_count == 1
        assert groq_usage.prompt_tokens == 10

        none_usage = store.get_provider_usage_today("nonexistent")
        assert none_usage is None

    def test_clear_expired_removes_old_entries(self, tmp_usage_file: Path):
        from llm_kernel.core import UsageRecord
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_usage_file)
        old_date = "2025-01-01"
        store._data[old_date] = {
            "groq:llama-3.3-70b": UsageRecord(
                provider="groq",
                model="llama-3.3-70b",
                day=old_date,
                request_count=5,
                prompt_tokens=100,
                completion_tokens=50,
            )
        }
        store._save()

        store.clear_expired(keep_days=1)
        assert old_date not in store._data
