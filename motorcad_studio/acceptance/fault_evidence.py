from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

FAULT_IDS = {
    "EXECUTABLE_MISSING_OR_UNSUPPORTED", "LICENSE_UNAVAILABLE", "PYMOTORCAD_INCOMPATIBLE",
    "RPC_SESSION_DISCONNECT", "WORKER_CRASH", "STALE_REVISION", "STALE_NATIVE_BINDING",
    "INVALID_GEOMETRY", "INVALID_WINDING_OR_MATERIAL", "INVALID_OPERATING_POINT",
    "SOLVER_TIMEOUT_OR_FAILURE", "INCOMPLETE_RESULT_EXTRACTION", "RESULT_INTEGRITY_FAILURE",
    "BROWSER_REFRESH_ACTIVE_TASK", "STUDIO_RESTART_REOPEN", "NON_ASCII_SPACE_PATH", "LARGE_HEAVY_DATA_LAZY_READ",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description="Attach observed V0.82 workstation fault evidence to the formal matrix")
    p.add_argument("matrix")
    p.add_argument("fault_id", choices=sorted(FAULT_IDS))
    p.add_argument("--status", choices=("PASS", "FAIL"), required=True)
    p.add_argument("--evidence", required=True, help="observed log/zip/json/screenshot evidence file")
    p.add_argument("--note", default="")
    args = p.parse_args()
    matrix_path = Path(args.matrix)
    evidence_path = Path(args.evidence)
    if not evidence_path.is_file():
        raise SystemExit(f"evidence file does not exist: {evidence_path}")
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = payload.get("failure_injections") or []
    row = next((r for r in rows if r.get("id") == args.fault_id), None)
    if row is None:
        raise SystemExit(f"fault id missing from matrix: {args.fault_id}")
    row.update({
        "status": args.status,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            "path": str(evidence_path.resolve()),
            "sha256": sha256(evidence_path),
            "size": evidence_path.stat().st_size,
            "note": args.note,
        },
    })
    matrix_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
