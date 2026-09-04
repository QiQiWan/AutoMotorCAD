"""MotorCAD Studio ASGI entry point.

The composition root owns process services and the application factory owns HTTP
assembly.  Runtime services are available through ``app.state.container``.
"""
from __future__ import annotations

import uvicorn

from .bootstrap.app_factory import create_app
from .bootstrap.composition_root import build_container
from .settings import settings

container = build_container(settings)
app = create_app(container)


def run() -> None:
    uvicorn.run(
        "motorcad_studio.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
