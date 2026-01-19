# Performance Optimization Updates

**Optimization Focus**: Neo4j Knowledge Graph Query Caching

## Summary

This update implements a Thread-Safe TTL (Time-To-Live) + LRU (Least Recently Used) caching strategy for Neo4j knowledge graph queries. This addresses the primary latency bottleneck in the IDSS agent where repetitive compatibility checks (e.g., CPU-motherboard socket checks, GPU-PSU power checks) resulted in unnecessary network calls.

### Problem Statement

Neo4j compatibility queries were executing with no caching mechanism. Users performing PC builds or comparing products triggered repeated identical queries, resulting in cumulative latency and unnecessary load on the database driver.

### Solution

An in-memory `_TTLCache` has been implemented within the `kg_compatibility.py` module with a conservative configuration:

* **Cache Size**: 256 entries per cache type
* **TTL (Time-To-Live)**: 120 seconds (2 minutes)
* **Thread Safety**: Uses `threading.Lock` for concurrent access
* **LRU Eviction**: Automatically removes the least recently used entries when the cache is full

---

## Code Changes

The following modifications were made to `idss_agent/tools/kg_compatibility.py`.

### 1. New Class: `_TTLCache`

A helper class was added to manage in-memory caching. It provides thread-safe access with automatic expiration and eviction.

**Features:**

* **Thread Safety:** Utilizes `threading.Lock` to ensure safe concurrent access.
* **Ordered Storage:** Uses `collections.OrderedDict` to maintain insertion