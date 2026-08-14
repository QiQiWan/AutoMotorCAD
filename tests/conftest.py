from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="motorcad-studio-tests-"))
os.environ.setdefault("MOTORCAD_STUDIO_RUNTIME_DIR", str(_TEST_ROOT / "runtime"))
os.environ.setdefault("MOTORCAD_STUDIO_RESULTS_DIR", str(_TEST_ROOT / "results"))
os.environ.setdefault("MOTORCAD_STUDIO_BASELINES_DIR", str(_TEST_ROOT / "baselines"))
os.environ.setdefault("MOTORCAD_STUDIO_FACTORY_DIR", str(_TEST_ROOT / "factory"))
os.environ.setdefault("MOTORCAD_STUDIO_LOG_DIR", str(_TEST_ROOT / "logs"))
os.environ.setdefault("MOTORCAD_STUDIO_LOG_LEVEL", "DEBUG")
os.environ.setdefault("MOTORCAD_STUDIO_MAX_WORKERS", "3")
os.environ.setdefault("MOTORCAD_STUDIO_CASE_PARALLELISM", "3")
os.environ.setdefault("MOTORCAD_STUDIO_MOCK_DELAY", "0.02")
os.environ.setdefault("MOTORCAD_STUDIO_ENABLE_MOCK", "1")
