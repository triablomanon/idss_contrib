#!/usr/bin/env python3
"""Inspect Neo4j database schema to find actual property names."""
import os
import sys
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

load_dotenv()

from neo4j import GraphDatabase

# Properties that CODE expects to exist
EXPECTED_PROPERTIES = {
    # Common
    "name", "slug", "brand", "series", "product_type", "namespace",
    "price", "price_avg", "price_min", "price_max", "seller", "rating", "rating_count",
    
    # CPU-specific
    "primary_use_case", "cooling_requirement", "integrated_graphics",
    "overclocking_support", "cpu_generation", "core_count", "thread_count",
    "boost_clock", "cache", "cpu_performance_tier",
    
    # GPU-specific
    "gpu_tdp", "power_connector", "recommended_psu", "target_resolution",
    "ray_tracing", "upscaling_support", "gpu_performance_tier",
    "card_length", "slot_thickness", "video_encoder", "display_outputs",
    
    # Motherboard-specific
    "supported_cpu_gen", "bios_flashback", "dimm_slots", "max_ram_speed",
    "m2_slots", "sata_ports", "usb_c_support", "lan_speed", "vrm_tier",
    
    # Common attributes
    "socket", "vram", "capacity", "wattage", "form_factor", "chipset",
    "ram_standard", "storage_type", "cooling_type", "certification",
    "pcie_version", "tdp", "year", "condition"
}

def inspect_schema():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        print("=" * 70)
        print("Neo4j PCProduct Schema Inspection")
        print("=" * 70)

        # Get all unique property keys
        result = session.run("""
            MATCH (p:PCProduct)
            UNWIND keys(p) AS key
            RETURN DISTINCT key
            ORDER BY key
        """)

        actual_properties = set()
        for record in result:
            actual_properties.add(record["key"])

        # Show properties that EXIST
        print("\n✅ Properties that EXIST in database:\n")
        for key in sorted(actual_properties):
            print(f"  - {key}")

        # Show properties that are MISSING but expected by code
        missing = EXPECTED_PROPERTIES - actual_properties
        if missing:
            print("\n" + "=" * 70)
            print("❌ Properties that CODE EXPECTS but DON'T EXIST:")
            print("=" * 70)
            print()
            for key in sorted(missing):
                print(f"  - {key}  ← WILL CAUSE QUERY FAILURES")

        # Show if primary_use_case exists
        print("\n" + "=" * 70)
        print("CRITICAL CHECK: primary_use_case")
        print("=" * 70)
        if "primary_use_case" in actual_properties:
            print("\n✅ primary_use_case EXISTS - queries will work")
        else:
            print("\n❌ primary_use_case DOES NOT EXIST - THIS IS CAUSING YOUR HALLUCINATION BUG")
            print("   Location in code: idss_agent/tools/kg_compatibility.py:869-871")

        # Count products by type
        print("\n" + "=" * 70)
        print("Product Counts by Type")
        print("=" * 70)

        result = session.run("""
            MATCH (p:PCProduct)
            RETURN p.product_type AS type, COUNT(*) AS count
            ORDER BY count DESC
        """)

        print()
        for record in result:
            print(f"  {record['type']}: {record['count']} products")

    driver.close()

if __name__ == "__main__":
    inspect_schema()
