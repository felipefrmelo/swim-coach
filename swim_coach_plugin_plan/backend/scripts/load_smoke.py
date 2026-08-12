"""Bounded concurrent REST/MCP transport smoke with latency and error thresholds."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import Counter

import httpx


async def run(base_url: str, requests: int, concurrency: int, p95_limit_ms: float) -> int:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    paths = ("/health/live", "/api/v1/auth/config", "/mcp/")

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:

        async def probe(index: int) -> None:
            path = paths[index % len(paths)]
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(path)
                latencies.append((time.perf_counter() - started) * 1_000)
                statuses[response.status_code] += 1

        await asyncio.gather(*(probe(index) for index in range(requests)))

    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    accepted = {200, 406}
    errors = sum(count for status, count in statuses.items() if status not in accepted)
    report = {
        "load_smoke": "passed" if errors == 0 and p95 <= p95_limit_ms else "failed",
        "requests": requests,
        "concurrency": concurrency,
        "status_counts": dict(sorted(statuses.items())),
        "p95_ms": round(p95, 2),
        "p95_limit_ms": p95_limit_ms,
        "mcp_406_meaning": "reachable transport rejected a non-MCP GET as expected",
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["load_smoke"] == "passed" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--requests", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--p95-limit-ms", type=float, default=500)
    args = parser.parse_args()
    if args.requests < 1 or not 1 <= args.concurrency <= 100:
        parser.error("requests must be positive and concurrency must be between 1 and 100")
    raise SystemExit(
        asyncio.run(run(args.base_url, args.requests, args.concurrency, args.p95_limit_ms))
    )


if __name__ == "__main__":
    main()
