from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from motorcad_studio.windows_production_qualification import REQUIRED_FAULT_GROUPS


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach observed Windows production fault evidence")
    parser.add_argument("matrix")
    parser.add_argument("fault_id", choices=sorted(REQUIRED_FAULT_GROUPS))
    parser.add_argument("--status", choices=("PASS", "FAIL"), required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    matrix = Path(args.matrix).resolve()
    evidence = Path(args.evidence).resolve()
    if not evidence.is_file():
        raise SystemExit(f"evidence file does not exist: {evidence}")
    payload = json.loads(matrix.read_text(encoding="utf-8"))
    rows = payload.get("failure_injections") or []
    row = next((item for item in rows if str(item.get("id")) == args.fault_id), None)
    if row is None:
        raise SystemExit(f"fault id missing from matrix: {args.fault_id}")
    row.update({
        "status": args.status,
        "group": REQUIRED_FAULT_GROUPS[args.fault_id],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            "path": str(evidence),
            "sha256": sha256(evidence),
            "size": evidence.stat().st_size,
            "note": args.note,
            "observed": True,
        },
    })
    matrix.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
