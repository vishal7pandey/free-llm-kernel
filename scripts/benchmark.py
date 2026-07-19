"""Reliability benchmark — measures per-provider latency, success rate, and failover.

Sends N requests per provider (round-robin), then sends mixed requests through
the kernel's routing policies to measure failover behavior. Outputs a reliability
matrix showing which providers are healthy, their latency, and how the kernel
routes under different policies.

Requires real API keys in .env. Does NOT make any claims about model quality —
only measures infrastructure reliability.

Run: uv run python scripts/benchmark.py
     uv run python scripts/benchmark.py --requests 10 --prompt "What is 2+2?"
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field

from llm_kernel import LLMClient
from llm_kernel.core import KernelError


@dataclass
class ProviderResult:
    provider: str
    model: str
    successes: int = 0
    failures: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def p95_latency(self) -> float:
        if len(self.latencies) < 2:
            return self.avg_latency
        return statistics.quantiles(self.latencies, n=20)[18]

    @property
    def status(self) -> str:
        if self.total == 0:
            return "skipped"
        if self.success_rate >= 0.95:
            return "healthy"
        if self.success_rate >= 0.7:
            return "degraded"
        return "unhealthy"


@dataclass
class PolicyResult:
    policy: str
    successes: int = 0
    failures: int = 0
    providers_used: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0


def benchmark_providers(
    client: LLMClient,
    prompt: str,
    requests_per_provider: int,
) -> dict[str, ProviderResult]:
    """Send requests to each provider individually to measure baseline reliability."""
    results: dict[str, ProviderResult] = {}

    for provider in client.providers:
        model = provider.default_model
        result = ProviderResult(provider=provider.name, model=model)
        results[provider.name] = result

        for _ in range(requests_per_provider):
            try:
                start = time.monotonic()
                response = client.chat(
                    prompt,
                    model=model,
                    max_tokens=50,
                )
                elapsed = time.monotonic() - start

                if response.provider == provider.name:
                    result.successes += 1
                    result.latencies.append(elapsed)
                else:
                    # Kernel failed over to a different provider
                    result.failures += 1
                    result.errors.append(f"failover to {response.provider}")
            except KernelError as exc:
                result.failures += 1
                result.errors.append(str(exc)[:80])
            except Exception as exc:
                result.failures += 1
                result.errors.append(f"{type(exc).__name__}: {exc!s}"[:80])

            # Brief pause to avoid rate limits
            time.sleep(0.2)

    return results


def benchmark_policies(
    client: LLMClient,
    prompt: str,
    requests_per_policy: int,
) -> dict[str, PolicyResult]:
    """Send requests through each routing policy to measure routing behavior."""
    policies = ["best_free", "fastest", "quality", "cheapest", "default"]
    results: dict[str, PolicyResult] = {}

    for policy_name in policies:
        result = PolicyResult(policy=policy_name)
        results[policy_name] = result

        for _ in range(requests_per_policy):
            try:
                start = time.monotonic()
                response = client.chat(
                    prompt,
                    policy=policy_name,
                    max_tokens=50,
                )
                elapsed = time.monotonic() - start

                result.successes += 1
                result.latencies.append(elapsed)
                provider_used = response.provider
                result.providers_used[provider_used] = (
                    result.providers_used.get(provider_used, 0) + 1
                )
            except KernelError:
                result.failures += 1
            except Exception:
                result.failures += 1

            time.sleep(0.2)

    return results


def print_provider_matrix(results: dict[str, ProviderResult]) -> None:
    print("\n" + "=" * 80)
    print("Provider Reliability Matrix")
    print("=" * 80)
    print()

    header = (
        f"{'Provider':<14} {'Model':<28} {'Status':<10} "
        f"{'Success':<8} {'Avg(s)':<8} {'P95(s)':<8} {'Errors'}"
    )
    print(header)
    print("-" * 80)

    for name, r in sorted(results.items()):
        print(
            f"{name:<14} {r.model:<28} {r.status:<10} "
            f"{r.success_rate:>5.1%}  {r.avg_latency:>6.3f}s {r.p95_latency:>6.3f}s "
            f"{r.failures}/{r.total}"
        )
        if r.errors:
            for err in r.errors[:3]:
                print(f"  └─ {err}")
            if len(r.errors) > 3:
                print(f"  └─ ... and {len(r.errors) - 3} more errors")


def print_policy_matrix(results: dict[str, PolicyResult]) -> None:
    print("\n" + "=" * 80)
    print("Policy Routing Matrix")
    print("=" * 80)
    print()

    header = f"{'Policy':<12} {'Success':<10} {'Avg(s)':<10} {'Providers Used'}"
    print(header)
    print("-" * 80)

    for name, r in sorted(results.items()):
        providers_str = ", ".join(
            f"{p}({n})" for p, n in sorted(r.providers_used.items(), key=lambda x: -x[1])
        )
        print(
            f"{name:<12} {r.success_rate:>5.1%}    {r.avg_latency:>6.3f}s   {providers_str}"
        )


def print_intelligence(client: LLMClient) -> None:
    print("\n" + "=" * 80)
    print("Provider Intelligence Engine (live state)")
    print("=" * 80)
    print()

    health = client.provider_health()
    header = (
        f"{'Provider':<14} {'Status':<10} {'Latency':<10} "
        f"{'Requests':<10} {'Quota':<10} {'Limit'}"
    )
    print(header)
    print("-" * 80)

    for name, info in sorted(health.items()):
        latency_str = f"{info['latency_ms']:.0f}ms" if info["latency_ms"] else "—"
        limit_str = str(info["daily_limit"]) if info["daily_limit"] else "∞"
        print(
            f"{name:<14} {info['status']:<10} {latency_str:<10} "
            f"{info['requests_today']:<10} {info['quota_remaining']:>5.1%}   {limit_str}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Free LLM Kernel reliability benchmark")
    parser.add_argument(
        "--requests",
        type=int,
        default=5,
        help="Number of requests per provider/policy (default: 5)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="What is 2+2? Answer with just the number.",
        help="Prompt to send (default: simple math)",
    )
    parser.add_argument(
        "--skip-providers",
        action="store_true",
        help="Skip per-provider benchmark (only test policies)",
    )
    parser.add_argument(
        "--skip-policies",
        action="store_true",
        help="Skip per-policy benchmark (only test providers)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Free LLM Kernel — Reliability Benchmark")
    print("=" * 80)
    print(f"\nPrompt: {args.prompt!r}")
    print(f"Requests per provider/policy: {args.requests}")

    print("\n[1] Building client from .env...")
    try:
        client = LLMClient.from_env(
            env_path=".env",
            usage_path="usage.json",
        )
    except Exception as exc:
        print(f"FAILED to build client: {exc}")
        return 1

    print(f"    Providers configured: {[p.name for p in client.providers]}")

    if not args.skip_providers:
        print(f"\n[2] Benchmarking individual providers ({args.requests} req each)...")
        provider_results = benchmark_providers(client, args.prompt, args.requests)
        print_provider_matrix(provider_results)
    else:
        print("\n[2] Skipping per-provider benchmark.")

    if not args.skip_policies:
        print(f"\n[3] Benchmarking routing policies ({args.requests} req each)...")
        policy_results = benchmark_policies(client, args.prompt, args.requests)
        print_policy_matrix(policy_results)
    else:
        print("\n[3] Skipping per-policy benchmark.")

    print_intelligence(client)

    print("\n" + "=" * 80)
    print("Benchmark complete!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
