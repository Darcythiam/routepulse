"""Run reproducible indexed-versus-unindexed proximity plans on a temporary table.

Usage: python bench/geo_explain.py --rows 1000000 --repeats 5
The benchmark writes a temporary table in the configured PostgreSQL database.
"""

import argparse
import json
import os
import statistics

import psycopg2


def measure(cur, query, params, repeats):
    durations = []
    plans = []
    for _ in range(repeats):
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params)
        plan = cur.fetchone()[0][0]
        durations.append(plan["Execution Time"])
        plans.append(plan["Plan"])
    return durations, plans


def walk_plan(node):
    yield node["Node Type"]
    for child in node.get("Plans", []):
        yield from walk_plan(child)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", default=None, help="Optional path to JSON evidence")
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 2:
        parser.error("Use at least 1000 rows and 2 repeats")

    with psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                          dbname=os.getenv("DB_NAME", "routepulse"), user=os.getenv("DB_USER", "routeuser"),
                          password=os.getenv("DB_PASS", "local-only-password")) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cur.execute("""
                CREATE TEMP TABLE geo_bench (
                    point_id BIGINT PRIMARY KEY,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    location geography(Point, 4326) GENERATED ALWAYS AS
                        (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED
                ) ON COMMIT PRESERVE ROWS
            """)
            cur.execute("""
                INSERT INTO geo_bench (point_id, latitude, longitude)
                SELECT i,
                    44.5 + ((i * 7919) %% 2000000) / 1000000.0,
                    -95.5 + ((i * 104729) %% 2500000) / 1000000.0
                FROM generate_series(1, %s) AS i
            """, (args.rows,))
            cur.execute("CREATE INDEX geo_bench_location_gist ON geo_bench USING GIST (location)")
            cur.execute("ANALYZE geo_bench")
            naive = """
                SELECT COUNT(*) FROM geo_bench
                WHERE ST_Distance(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography,
                                  ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) <= %s
            """
            indexed = """
                SELECT COUNT(*) FROM geo_bench
                WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            """
            params = (-94.154, 45.553, 500.0)
            # Alternate query order to reduce warm-cache bias.
            naive_times, naive_plans = [], []
            indexed_times, indexed_plans = [], []
            for i in range(args.repeats):
                pair = [(naive, naive_times, naive_plans), (indexed, indexed_times, indexed_plans)]
                if i % 2:
                    pair.reverse()
                for query, times, plans in pair:
                    duration, plan = measure(cur, query, params, 1)
                    times.extend(duration)
                    plans.extend(plan)
            cur.execute(naive, params)
            naive_count = cur.fetchone()[0]
            cur.execute(indexed, params)
            indexed_count = cur.fetchone()[0]
            if naive_count != indexed_count:
                raise RuntimeError(f"Query results differ: {naive_count} versus {indexed_count}")

    baseline = statistics.median(naive_times)
    optimized = statistics.median(indexed_times)
    report = {
        "rows": args.rows,
        "radius_m": 500,
        "matched_rows": indexed_count,
        "naive_execution_ms": naive_times,
        "indexed_execution_ms": indexed_times,
        "naive_median_ms": baseline,
        "indexed_median_ms": optimized,
        "latency_reduction_percent": round(100 * (baseline - optimized) / baseline, 2),
        "indexed_plan_nodes": sorted(set(walk_plan(indexed_plans[-1]))),
    }
    print(json.dumps(report, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2)


if __name__ == "__main__":
    main()
