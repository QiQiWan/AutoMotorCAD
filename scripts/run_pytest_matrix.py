"""Deterministic per-file pytest qualification matrix for MotorCAD Studio releases."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def expand_targets(raw: list[str]) -> list[Path]:
    out: list[Path] = []
    for item in raw:
        path = Path(item)
        if path.is_dir():
            out.extend(sorted(path.glob('test_*.py')))
        else:
            out.append(path)
    seen: set[str] = set()
    result: list[Path] = []
    for path in out:
        key = path.as_posix()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(0.05)
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        pass


def run_one(path: Path, *, data_root: Path, timeout_s: float, marker: str | None) -> tuple[bool, str]:
    data_dir = data_root / path.stem
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['MOTORCAD_STUDIO_DATA_DIR'] = str(data_dir.resolve())
    cmd = [sys.executable, 'scripts/run_pytest_file_isolated.py', '-q']
    if marker:
        cmd += ['-m', marker]
    cmd.append(path.as_posix())
    log_path = data_dir / '_pytest_output.log'
    with log_path.open('w+', encoding='utf-8') as log:
        proc = subprocess.Popen(
            cmd,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pgid = proc.pid
        timed_out = False
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(pgid)
            try:
                code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = -signal.SIGKILL
        finally:
            # A successful isolated pytest may have spawned descendants that no
            # longer belong to Studio's test lifecycle.  Its unique session is
            # always reaped before the next file starts.
            _kill_group(pgid)
        log.flush()
        log.seek(0)
        output = log.read()
    if timed_out:
        output += f'\nTIMEOUT after {timeout_s:.0f}s\n'
    return (not timed_out and code == 0), output


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-root', required=True)
    ap.add_argument('--timeout', type=float, default=75.0)
    ap.add_argument('--marker', default=None)
    ap.add_argument('targets', nargs='+')
    ns = ap.parse_args()
    files = expand_targets(ns.targets)
    root = Path(ns.data_root)
    root.mkdir(parents=True, exist_ok=True)
    passed = 0
    failed: list[str] = []
    for path in files:
        print(f'  - {path}', flush=True)
        ok, output = run_one(path, data_root=root, timeout_s=ns.timeout, marker=ns.marker)
        print(output.rstrip(), flush=True)
        if ok:
            passed += 1
        else:
            failed.append(path.as_posix())
    print(f'qualification files: {passed}/{len(files)} PASS', flush=True)
    if failed:
        print('failed files: ' + ', '.join(failed), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
