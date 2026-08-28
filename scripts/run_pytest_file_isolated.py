"""Run one pytest target with a deterministic post-session process boundary.

V0.89-C release qualification executes every test file in a fresh interpreter.
Some application/plugin stacks leave background threads or interpreter-exit hooks
after pytest has completed all item/fixture teardown.  The isolation runner exits
from ``pytest_sessionfinish`` after flushing output, so those unrelated hooks cannot
stall the next qualification file.
"""
from __future__ import annotations

import os
import sys

import pytest


class _DeterministicSessionExit:
    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):  # noqa: ANN001
        code = int(exitstatus)
        print(f"\nMCS_ISOLATED_SESSION_FINISH exitstatus={code}", flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
        # Successful sessions cross the deterministic process boundary here.
        # Failed sessions are allowed to return through pytest's terminal
        # reporter so the release matrix retains the full failure traceback;
        # the outer per-file timeout still owns process-tree recovery.
        if code == 0:
            os._exit(0)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("usage: run_pytest_file_isolated.py <pytest target> [pytest args...]", file=sys.stderr)
        os._exit(2)
    # The call is intentionally not expected to return: the plugin exits only
    # after pytest has completed the whole test session and fixture teardown.
    code = int(pytest.main(args, plugins=[_DeterministicSessionExit()]))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
