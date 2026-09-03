"""Reproducible, isolated 100,000-product SQLite search benchmark."""
import shutil
import tempfile
import time
from pathlib import Path

from database.db import configure_database


def main():
    directory = Path(tempfile.mkdtemp(prefix="pos_benchmark_100k_"))
    try:
        db = configure_database(str(directory / "benchmark.db"))
        rows = [(f"BENCH-{index:06d}", f"Benchmark Brake Pad {index}", "Benchmark", 10.0, 15.0, 20, 1) for index in range(100_000)]
        started = time.perf_counter()
        with db.transaction() as conn:
            conn.executemany("INSERT INTO products(part_no,description,brand,cost_price,selling_price,quantity_on_hand,active) VALUES(?,?,?,?,?,?,?)", rows)
        insert_seconds = time.perf_counter() - started
        started = time.perf_counter()
        result = db.execute_query("SELECT id, part_no FROM products WHERE part_no=? AND active=1", ("BENCH-099999",))
        exact_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        matches = db.execute_query("SELECT id FROM products WHERE description LIKE ? AND active=1 LIMIT 50", ("%Brake Pad 999%",))
        contains_ms = (time.perf_counter() - started) * 1000
        if not result or not matches:
            raise RuntimeError("Benchmark search did not return expected products")
        print(f"INSERT_100K_SECONDS={insert_seconds:.3f}")
        print(f"EXACT_PART_NUMBER_MS={exact_ms:.3f}")
        print(f"CONTAINS_SEARCH_MS={contains_ms:.3f}")
        print(f"CONTAINS_MATCHES={len(matches)}")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == '__main__':
    main()