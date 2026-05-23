"""Benchmark client: concurrent requests to demonstrate batching speedup."""

import asyncio
import time

import aiohttp


URL = "http://127.0.0.1:8000/v2/models/compute_model/infer"
CONCURRENT_REQUESTS = 64


async def send_one(session: aiohttp.ClientSession, number: int) -> dict:
    async with session.post(
        URL,
        headers={"Content-Type": "application/json"},
        json={"number": number},
    ) as resp:
        return await resp.json()


async def benchmark():
    print(f"🚀 Sending {CONCURRENT_REQUESTS} concurrent requests...\n")

    async with aiohttp.ClientSession() as session:
        start = time.perf_counter()
        tasks = [send_one(session, i) for i in range(CONCURRENT_REQUESTS)]
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

    # Stats
    batch_sizes = [r.get("batch_size", 1) for r in results]
    throughput = CONCURRENT_REQUESTS / elapsed
    avg_latency = elapsed / CONCURRENT_REQUESTS * 1000  # ms

    print("📊 Results")
    print("=" * 40)
    print(f"  Total requests:     {CONCURRENT_REQUESTS}")
    print(f"  Total time:         {elapsed:.3f}s")
    print(f"  Throughput:         {throughput:.1f} req/s")
    print(f"  Avg latency:        {avg_latency:.1f}ms")
    print(f"  Batch sizes seen:   {sorted(set(batch_sizes))}")
    print(f"  Max batch size:     {max(batch_sizes)}")
    print("=" * 40)
    print()

    # Theoretical comparison
    no_batch_time = CONCURRENT_REQUESTS * 0.05
    speedup = no_batch_time / elapsed
    print("📈 Batching impact")
    print(f"  Without batching:   ~{no_batch_time:.1f}s (64 × 50ms serial)")
    print(f"  With batching:      {elapsed:.3f}s")
    print(f"  Speedup:            {speedup:.1f}×")


if __name__ == "__main__":
    asyncio.run(benchmark())
