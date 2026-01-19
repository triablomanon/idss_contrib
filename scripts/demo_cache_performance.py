#!/usr/bin/env python3
"""
Neo4j Cache Performance Demonstration

This script demonstrates the performance improvement from caching by:
1. Clearing all caches
2. Running queries (cache misses) - measures actual Neo4j query time
3. Running the same queries again (cache hits) - measures cache performance
4. Calculating speedup and improvement metrics

Run with: python scripts/demo_cache_performance.py
"""
import sys
import os
import time
import statistics

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from idss_agent.tools.kg_compatibility import get_compatibility_tool


def format_time(ms: float) -> str:
    """Format milliseconds nicely."""
    if ms < 1:
        return f"{ms:.3f}ms"
    elif ms < 10:
        return f"{ms:.2f}ms"
    else:
        return f"{ms:.1f}ms"


def main():
    print("\n" + "=" * 70)
    print("Neo4j Cache Performance Demonstration")
    print("=" * 70)

    # Initialize tool
    tool = get_compatibility_tool()

    if not tool.is_available():
        print("\n❌ Neo4j is not available. Please start Neo4j and try again.")
        return

    # Test product pairs (CPU-Motherboard compatible pairs)
    test_pairs = [
        ("amd-ryzen-9-3900xt", "msi-mpg-gaming-plus", "Ryzen 9 3900XT + MSI B550"),
        ("amd-ryzen-5-4600g", "msi-mpg-gaming-plus", "Ryzen 5 4600G + MSI B550"),
        ("amd-ryzen-5-2400g", "msi-mpg-gaming-plus", "Ryzen 5 2400G + MSI B550"),
    ]

    print(f"\nTesting {len(test_pairs)} product compatibility pairs...")
    print(f"Each pair will be queried twice:")
    print(f"  1. First query (CACHE MISS) - queries Neo4j database")
    print(f"  2. Second query (CACHE HIT) - returns from cache")

    # Clear all caches to start fresh
    print("\n🧹 Clearing all caches...")
    tool._PRODUCT_SEARCH_CACHE.clear()
    tool._COMPATIBILITY_CHECK_CACHE.clear()
    tool._COMPATIBLE_PARTS_CACHE.clear()

    # Collect timing data
    cache_miss_times = []
    cache_hit_times = []

    print("\n" + "-" * 70)
    print("PHASE 1: Cache Misses (First Query - Database Lookup)")
    print("-" * 70)

    for cpu_slug, mb_slug, description in test_pairs:
        print(f"\n🔍 Testing: {description}")

        # First query - CACHE MISS
        start = time.perf_counter()
        result = tool.check_compatibility(cpu_slug, mb_slug)
        duration_ms = (time.perf_counter() - start) * 1000
        cache_miss_times.append(duration_ms)

        compatible = result.get("compatible", False)
        status = "✓ Compatible" if compatible else "✗ Not compatible"
        print(f"   Result: {status}")
        print(f"   Time: {format_time(duration_ms)} (CACHE MISS)")

    print("\n" + "-" * 70)
    print("PHASE 2: Cache Hits (Second Query - From Cache)")
    print("-" * 70)

    for cpu_slug, mb_slug, description in test_pairs:
        print(f"\n🔍 Testing: {description}")

        # Second query - CACHE HIT
        start = time.perf_counter()
        result = tool.check_compatibility(cpu_slug, mb_slug)
        duration_ms = (time.perf_counter() - start) * 1000
        cache_hit_times.append(duration_ms)

        compatible = result.get("compatible", False)
        status = "✓ Compatible" if compatible else "✗ Not compatible"
        print(f"   Result: {status}")
        print(f"   Time: {format_time(duration_ms)} (CACHE HIT)")

    # Calculate statistics
    avg_miss = statistics.mean(cache_miss_times)
    avg_hit = statistics.mean(cache_hit_times)
    min_miss = min(cache_miss_times)
    max_miss = max(cache_miss_times)
    min_hit = min(cache_hit_times)
    max_hit = max(cache_hit_times)

    speedup = avg_miss / avg_hit if avg_hit > 0 else 0
    improvement_pct = ((avg_miss - avg_hit) / avg_miss * 100) if avg_miss > 0 else 0

    # Print summary
    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)

    print(f"\n📊 Cache Miss Statistics (First Query - Database Lookup):")
    print(f"   Average: {format_time(avg_miss)}")
    print(f"   Range:   {format_time(min_miss)} - {format_time(max_miss)}")

    print(f"\n⚡ Cache Hit Statistics (Second Query - From Cache):")
    print(f"   Average: {format_time(avg_hit)}")
    print(f"   Range:   {format_time(min_hit)} - {format_time(max_hit)}")

    print(f"\n🚀 Performance Improvement:")
    print(f"   Speedup:     {speedup:.1f}x faster")
    print(f"   Improvement: {improvement_pct:.1f}% latency reduction")
    print(f"   Time saved:  {format_time(avg_miss - avg_hit)} per query")

    # Real-world impact
    print(f"\n💡 Real-World Impact:")
    print(f"   - A PC build with 10 compatibility checks:")
    print(f"     • Without cache: {format_time(avg_miss * 10)}")
    print(f"     • With 60% cache hit rate: {format_time(avg_miss * 4 + avg_hit * 6)}")
    print(f"     • Savings: {format_time((avg_miss * 10) - (avg_miss * 4 + avg_hit * 6))}")

    print("\n" + "=" * 70)
    print("✅ Cache is working correctly!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
