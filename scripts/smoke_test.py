"""Live smoke test — makes real API calls to configured providers.

Run: uv run python scripts/smoke_test.py
"""

import sys
import time

from llm_kernel import LLMClient


def main() -> int:
    print("=" * 60)
    print("Free LLM Kernel — Live Smoke Test")
    print("=" * 60)

    # Build client from .env
    print("\n[1] Building client from .env...")
    client = LLMClient.from_env(
        env_path=".env",
        usage_path="usage.json",
    )
    print(f"    Providers configured: {[p.name for p in client.providers]}")

    # Test 1: Simple chat
    print("\n[2] Simple chat: 'Say hello in one sentence.'")
    try:
        start = time.monotonic()
        response = client.chat("Say hello in one sentence.")
        elapsed = time.monotonic() - start
        print(f"    Provider: {response.provider}")
        print(f"    Model:    {response.model}")
        print(f"    Content:  {response.content}")
        print(f"    Tokens:   {response.usage.total_tokens}")
        print(f"    Latency:  {elapsed:.2f}s")
        print(f"    Finish:   {response.finish_reason}")
    except Exception as exc:
        print(f"    FAILED: {exc}")
        return 1

    # Test 2: Chat with system prompt
    print("\n[3] System prompt: 'You are a pirate. Respond in pirate speak.'")
    try:
        response = client.chat(
            "What is 2+2?",
            system="You are a pirate. Respond in pirate speak. Keep it to one sentence.",
        )
        print(f"    Provider: {response.provider}")
        print(f"    Content:  {response.content}")
    except Exception as exc:
        print(f"    FAILED: {exc}")

    # Test 3: Model override
    print("\n[4] Model override: gemini-2.0-flash")
    try:
        response = client.chat(
            "What is the capital of France? One word.",
            model="gemini-2.0-flash",
        )
        print(f"    Provider: {response.provider}")
        print(f"    Model:    {response.model}")
        print(f"    Content:  {response.content}")
    except Exception as exc:
        print(f"    FAILED: {exc}")

    # Test 4: Streaming
    print("\n[5] Streaming: 'Count from 1 to 5.'")
    try:
        print("    Chunks: ", end="", flush=True)
        chunks = []
        for chunk in client.stream("Count from 1 to 5, with spaces between numbers."):
            chunks.append(chunk)
            print(chunk, end="", flush=True)
        print()
        print(f"    Total chunks: {len(chunks)}")
    except Exception as exc:
        print(f"\n    FAILED: {exc}")

    # Test 5: Usage tracking
    print("\n[6] Usage tracking:")
    if client.usage_store is not None:
        for record in client.usage_store.get_today():
            print(
                f"    {record.provider}:{record.model} — "
                f"{record.request_count} req, "
                f"{record.prompt_tokens} prompt, "
                f"{record.completion_tokens} completion"
            )
    else:
        print("    (no usage store configured)")

    print("\n" + "=" * 60)
    print("Smoke test complete!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
