"""Production-oriented local launcher for MotorCAD Studio."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .release import PRODUCT_VERSION

ROOT = Path(__file__).resolve().parent.parent


def _default_log_dir() -> Path:
    configured = os.getenv("MOTORCAD_STUDIO_LOG_DIR")
    if configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else ROOT / candidate).resolve(strict=False)
    return (ROOT / "logs").resolve(strict=False)


def _log(message: str, *, level: str = "INFO") -> None:
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{stamp} [{level}] {message}"
    print(line, flush=True)
    try:
        directory = _default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "startup.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def _port_open(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex((probe_host, port)) == 0


def _health(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _browser_when_ready(url: str, *, timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    health_url = url.rstrip("/") + "/api/health"
    while time.monotonic() < deadline:
        payload = _health(health_url)
        if payload:
            _log(f"Service is ready: {url}")
            webbrowser.open(url, new=2)
            return
        time.sleep(0.4)
    _log(f"Browser was not opened because the service did not become ready within {timeout_s:.0f}s.", level="WARNING")


def _preflight() -> dict[str, Any]:
    from .package_integrity import verify_manifest
    from .tools.module_audit import audit
    from .tools.sync_release_versions import synchronize

    sync = synchronize(write=False).to_dict()
    modules = audit()
    integrity = verify_manifest(Path(__file__).resolve().parent.parent)
    return {
        "version": PRODUCT_VERSION,
        "release_sync": sync,
        "module_audit": modules,
        "package_integrity": integrity,
        "compatible": bool(sync.get("compatible") and modules.get("compatible") and integrity.get("compatible")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start MotorCAD Studio")
    parser.add_argument("--host", default=os.getenv("MOTORCAD_STUDIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MOTORCAD_STUDIO_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--mock", action="store_true", help="enable the offline mock solver for UI/integration testing")
    args = parser.parse_args(argv)

    if not (1 <= args.port <= 65535):
        _log(f"Invalid port: {args.port}", level="ERROR")
        return 2
    os.environ["MOTORCAD_STUDIO_HOST"] = args.host
    os.environ["MOTORCAD_STUDIO_PORT"] = str(args.port)
    if args.mock:
        os.environ["MOTORCAD_STUDIO_ENABLE_MOCK"] = "1"

    _log(f"MotorCAD Studio {PRODUCT_VERSION} startup preflight")
    try:
        report = _preflight()
    except Exception as exc:
        _log(f"Preflight crashed: {type(exc).__name__}: {exc}", level="ERROR")
        return 3
    if not report["compatible"]:
        _log("Release or module validation failed. Run from a clean, complete package directory.", level="ERROR")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 4
    _log("Release and module validation passed.")
    if args.check_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    probe_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    root_url = f"http://{probe_host}:{args.port}/"
    if _port_open(args.host, args.port):
        existing = _health(root_url + "api/health")
        existing_version = str((existing or {}).get("version") or (existing or {}).get("product_version") or "")
        if existing and existing_version == PRODUCT_VERSION:
            _log(f"MotorCAD Studio {PRODUCT_VERSION} is already running at {root_url}")
            if not args.no_browser:
                webbrowser.open(root_url, new=2)
            return 0
        _log(f"Port {args.port} is already occupied. Stop the old service before starting this package.", level="ERROR")
        return 5

    if not args.no_browser:
        threading.Thread(target=_browser_when_ready, args=(root_url,), daemon=True, name="mcs-browser-opener").start()

    try:
        import uvicorn
        from .main import app

        _log(f"Starting service at {root_url}")
        config = uvicorn.Config(app=app, host=args.host, port=args.port, log_level="info", access_log=False)
        server = uvicorn.Server(config)
        server.run()
        return 0 if server.started else 6
    except KeyboardInterrupt:
        _log("Shutdown requested.")
        return 0
    except Exception as exc:
        _log(f"Service startup failed: {type(exc).__name__}: {exc}", level="ERROR")
        return 7


if __name__ == "__main__":
    raise SystemExit(main())
