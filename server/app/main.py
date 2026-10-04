import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import (
    alarms,
    auth,
    automation,
    backups,
    commands,
    connections,
    current_values,
    dashboards,
    devices,
    history,
    live,
    locations,
    notifications,
    runtime,
    tags,
    users,
)
from app.api.health import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.version import APP_VERSION
from app.db.session import Database
from app.services.auth import authorize
from app.services.live import LiveHub, NotificationListener, connect_listener, stale_loop

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        app.state.database = Database(config)
        app.state.settings = config
        if config.application_mode != "standalone":
            from app.sync.state import initialize

            await initialize(app.state.database, config)
        app.state.live_hub = LiveHub()
        tasks = []
        if config.live_updates_enabled:
            listener = NotificationListener(
                app.state.database, app.state.live_hub, lambda: connect_listener(config)
            )
            tasks = [
                asyncio.create_task(listener.run()),
                asyncio.create_task(stale_loop(app.state.database, config)),
            ]
        if config.application_mode == "cloud":
            from app.sync.runtime import maintenance

            tasks.append(asyncio.create_task(maintenance(app.state.database, config)))
        logger.info("API starting")
        app.state.started_monotonic = monotonic()
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await app.state.database.close()
            logger.info("API stopped")

    from app.api import sync

    app = FastAPI(title="Modbus Monitor API", version=APP_VERSION, lifespan=lifespan)
    app.include_router(router, dependencies=[Depends(authorize)])
    # Static /tags/values must precede the existing /tags/{identifier} route.
    app.include_router(current_values.router, dependencies=[Depends(authorize)])
    app.include_router(sync.machine_router)
    app.include_router(sync.router, dependencies=[Depends(authorize)])
    app.include_router(auth.router)
    app.include_router(users.router, dependencies=[Depends(authorize)])
    app.include_router(backups.router, dependencies=[Depends(authorize)])
    app.include_router(live.router)
    app.include_router(history.router, dependencies=[Depends(authorize)])
    app.include_router(runtime.router, dependencies=[Depends(authorize)])
    app.include_router(commands.router, dependencies=[Depends(authorize)])
    app.include_router(automation.router, dependencies=[Depends(authorize)])
    app.include_router(alarms.router, dependencies=[Depends(authorize)])
    app.include_router(notifications.router, dependencies=[Depends(authorize)])
    app.include_router(dashboards.router, dependencies=[Depends(authorize)])
    for configuration_router in (locations.router, connections.router, devices.router, tags.router):
        app.include_router(configuration_router, dependencies=[Depends(authorize)])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Raw inputs can include NaN/Infinity or sensitive data. Return only actionable errors.
        errors = [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request error: %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=config.allowed_hosts, www_redirect=False
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    return app
