from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn


async def run_server(host: str, port: int, stop_file: Path) -> int:
    if stop_file.exists():
        stop_file.unlink()
    config = uvicorn.Config("motorcad_studio.main:app", host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not task.done():
        if stop_file.exists():
            server.should_exit = True
            break
        await asyncio.sleep(0.25)
    await task
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Graceful Studio production-qualification server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stop-file", required=True)
    args = parser.parse_args()
    return asyncio.run(run_server(args.host, args.port, Path(args.stop_file).resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
