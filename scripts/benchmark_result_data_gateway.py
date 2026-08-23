from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.result_domain.heavy_data import ResultDataGateway


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark V0.80-A chunk-native ResultDataGateway random access.")
    parser.add_argument("--items", type=int, default=100_000)
    parser.add_argument("--chunk-items", type=int, default=2048)
    parser.add_argument("--window", type=int, default=4096)
    parser.add_argument("--offset", type=int, default=None)
    args = parser.parse_args()
    count = max(1, args.items)
    offset = args.offset if args.offset is not None else max(0, count // 2 - args.window // 2)
    payload = {
        "points": [[index * 0.001, index * 0.002, 0.0] for index in range(count)],
        "values": [((index % 1000) - 500) / 1000 for index in range(count)],
        "coordinate_system": "synthetic",
    }
    with tempfile.TemporaryDirectory(prefix="mcs-v080a-bench-") as td:
        root = Path(td)
        db = Database(root / "benchmark.sqlite3")
        gateway = ResultDataGateway(db, root / "result_data", inline_max_bytes=1, chunk_size_items=args.chunk_items)
        started = time.perf_counter(); ref = gateway.put(payload, logical_type="field"); put_s = time.perf_counter() - started
        started = time.perf_counter(); window, window_meta = gateway.read_window(ref.content_hash, offset=offset, limit=args.window); window_s = time.perf_counter() - started
        started = time.perf_counter(); hydrated = gateway.read(ref.content_hash); full_s = time.perf_counter() - started
        output = {
            "contract": "0.80-A",
            "items": count,
            "encoding": ref.encoding,
            "chunk_count": ref.chunk_count,
            "chunk_size_items": ref.chunk_size_items,
            "logical_bytes": ref.size_bytes,
            "registered_stored_bytes": ref.stored_bytes,
            "put_seconds": round(put_s, 6),
            "window_seconds": round(window_s, 6),
            "full_read_seconds": round(full_s, 6),
            "window": window_meta,
            "window_points": len(window.get("points") or []),
            "full_points": len(hydrated.get("points") or []),
            "stored_byte_read_fraction": round((window_meta.get("stored_bytes_read") or 0) / max(1, ref.stored_bytes), 6),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
