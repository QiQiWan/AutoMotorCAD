"""Synthetic binary FieldData throughput and topology-reuse benchmark.

The benchmark is diagnostic: it exercises the exact MotorCADFieldDataBinaryV1
encoder used by the HTTP adapter, models first-frame topology transfer plus
scalar-only transient updates, and reports memory/time evidence without claiming
browser GPU or licensed Motor-CAD qualification.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import tracemalloc
from array import array
from pathlib import Path
from typing import Any

from ..modules.field_data.binary import decode_header, encode_frame
from ..release import PRODUCT_VERSION


def _grid_mesh(requested_triangles: int) -> tuple[array, array, int]:
    requested = max(2, int(requested_triangles))
    side = max(2, math.ceil(math.sqrt(requested / 2.0)) + 1)
    positions = array("f")
    denominator = max(1, side - 1)
    for row in range(side):
        y = row / denominator
        for column in range(side):
            x = column / denominator
            positions.extend((x, y, 0.0))
    indices = array("I")
    emitted = 0
    for row in range(side - 1):
        if emitted >= requested:
            break
        base = row * side
        for column in range(side - 1):
            a = base + column
            b = a + 1
            c = a + side
            d = c + 1
            if emitted < requested:
                indices.extend((a, b, c)); emitted += 1
            if emitted < requested:
                indices.extend((b, d, c)); emitted += 1
            if emitted >= requested:
                break
    return positions, indices, emitted


def _scalars(vertex_count: int, frame: int, frame_count: int) -> array:
    phase = (2.0 * math.pi * frame) / max(1, frame_count)
    values = array("f")
    for index in range(vertex_count):
        values.append(math.sin(index * 0.0007 + phase) + 0.25 * math.cos(index * 0.0013 - phase))
    return values


def run_benchmark(*, triangles: int = 250_000, frames: int = 30) -> dict[str, Any]:
    frames = max(1, int(frames))
    tracemalloc.start()
    build_started = time.perf_counter()
    positions, indices, actual_triangles = _grid_mesh(triangles)
    build_seconds = time.perf_counter() - build_started
    vertex_count = len(positions) // 3

    encode_seconds: list[float] = []
    payload_sizes: list[int] = []
    scalar_sizes: list[int] = []
    topology_hashes: list[str] = []
    scalar_hashes: list[str] = []
    topology_bytes = 0
    for frame in range(frames):
        values = _scalars(vertex_count, frame, frames)
        started = time.perf_counter()
        payload, manifest = encode_frame(
            positions,
            indices,
            values,
            metadata={
                "field": "synthetic",
                "region": None,
                "bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
                "benchmark": True,
            },
            source_hash="0" * 64,
            frame_index=frame,
        )
        encode_seconds.append(time.perf_counter() - started)
        payload_sizes.append(len(payload))
        header = decode_header(payload)
        arrays = header["arrays"]
        if frame == 0:
            topology_bytes = (
                int(arrays["positions"]["byte_length"])
                + int(arrays["indices"]["byte_length"])
            )
        scalar_sizes.append(int(arrays["scalars"]["byte_length"]))
        topology_hashes.append(str(manifest["topology_hash"]))
        scalar_hashes.append(str(manifest["scalar_hash"]))
        del payload, values

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    full_transfer_bytes = sum(payload_sizes)
    optimized_transfer_bytes = payload_sizes[0] + sum(scalar_sizes[1:])
    savings = 0.0 if full_transfer_bytes <= 0 else 1.0 - optimized_transfer_bytes / full_transfer_bytes
    compatible = bool(
        actual_triangles == int(triangles)
        and len(topology_hashes) == frames
        and len(set(topology_hashes)) == 1
        and len(set(scalar_hashes)) == frames
        and all(value > 0 for value in payload_sizes)
        and topology_bytes > 0
    )
    return {
        "authority": "MotorCADStudioFieldDataBenchmarkV1",
        "product_version": PRODUCT_VERSION,
        "compatible": compatible,
        "qualification_scope": "synthetic_cpu_encoder_and_wire_model",
        "browser_gpu_qualification": "PENDING_TARGET_WORKSTATION",
        "licensed_motorcad_export_qualification": "PENDING_TARGET_WORKSTATION",
        "requested_triangle_count": int(triangles),
        "triangle_count": actual_triangles,
        "vertex_count": vertex_count,
        "frame_count": frames,
        "mesh_build_seconds": round(build_seconds, 6),
        "first_frame_encode_seconds": round(encode_seconds[0], 6),
        "median_frame_encode_seconds": round(statistics.median(encode_seconds), 6),
        "p95_frame_encode_seconds": round(sorted(encode_seconds)[max(0, math.ceil(len(encode_seconds) * 0.95) - 1)], 6),
        "max_frame_encode_seconds": round(max(encode_seconds), 6),
        "first_frame_payload_bytes": payload_sizes[0],
        "topology_bytes": topology_bytes,
        "scalar_frame_bytes": scalar_sizes[0],
        "full_transfer_bytes": full_transfer_bytes,
        "topology_reuse_transfer_bytes": optimized_transfer_bytes,
        "topology_reuse_savings_ratio": round(savings, 6),
        "topology_hash_unique_count": len(set(topology_hashes)),
        "scalar_hash_unique_count": len(set(scalar_hashes)),
        "peak_traced_memory_bytes": peak_bytes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triangles", type=int, default=250_000)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_benchmark(triangles=args.triangles, frames=args.frames)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["compatible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
