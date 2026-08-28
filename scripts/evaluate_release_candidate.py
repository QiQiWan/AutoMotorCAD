from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.main import release_candidate_gate
from motorcad_studio.release_candidate_gate import ReleaseCandidateHumanAcceptanceImport


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate V0.89-G1 Release Candidate Gate")
    parser.add_argument("--human-acceptance", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-formal", action="store_true")
    args = parser.parse_args()
    recorded = None
    if args.human_acceptance:
        raw = json.loads(args.human_acceptance.read_text(encoding="utf-8-sig"))
        recorded = release_candidate_gate.record_human_acceptance(ReleaseCandidateHumanAcceptanceImport.model_validate(raw))
    summary = release_candidate_gate.summary()
    payload = {"acceptance": recorded, "summary": summary}
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    if args.require_formal and not summary.get("formal_rc_qualified"):
        return 5
    return 0 if summary.get("local_rc_ready") else 3


if __name__ == "__main__":
    raise SystemExit(main())
