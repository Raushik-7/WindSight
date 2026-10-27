"""FastAPI application entry point.

Run locally with ``uvicorn app.main:app --reload`` from ``backend/``.

Startup sequence (documented in the README):

1. resolve ``DATABASE_URL`` (SQLite file by default, PostgreSQL when provided),
2. apply pending Alembic migrations (idempotent, never drops data),
3. seed durable storage from the committed Elexon snapshot when the database
   is empty and ``SEED_ON_STARTUP`` allows it,
4. warm the analytics cache.

A failure at any step is recorded and surfaced by ``/api/health``; it never
invents data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import Settings
from .db.migrations import upgrade_head
from .importer import ensure_history
from .db.session import session_scope
from .service import AnalysisService
from .source import DataUnavailableError
from .store import DatabaseStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("windsight")

DESCRIPTION = """
WindSight evaluates how reliable published UK wind generation forecasts were
against actual outturn, using two Elexon BMRS datasets (FUELHH and WINDFOR).

The API is read-only for analytics: results are computed from durable,
previously imported observations. A protected operator endpoint can refresh
the imported history.
"""

TAGS = ["WindSight"]


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store: DatabaseStore = app.state.store
        app.state.startup = {"ready": False, "message": "starting"}
        try:
            database_url = store.database_url
            logger.info("Applying database migrations to %s", database_url)
            revision = upgrade_head(database_url)
            logger.info("Schema at revision %s", revision)

            with session_scope(store.session_factory) as session:
                ready, message = ensure_history(
                    session,
                    settings,
                    seed_if_missing=settings.seed_on_startup,
                )
            app.state.startup = {"ready": ready, "message": message}
            logger.info("Data check: %s", message)
        except Exception as exc:
            app.state.startup = {"ready": False, "message": f"startup failed: {exc}"}
            logger.exception("Startup data preparation failed")

        try:
            source = app.state.service.source_data()
            logger.info(
                "Analytics ready: origin=%s actuals=%d forecasts=%d",
                source.origin,
                len(source.actuals),
                len(source.forecasts),
            )
        except DataUnavailableError as exc:
            logger.error("Analytics data unavailable: %s", exc)
        yield

    app = FastAPI(
        title="WindSight API",
        description=DESCRIPTION,
        version="1.0.0",
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    store = DatabaseStore(settings)
    app.state.store = store
    app.state.service = AnalysisService(settings, store=store)
    app.state.startup = {"ready": False, "message": "not started"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request parameters failed validation.",
                    "details": [
                        {"loc": list(e.get("loc", [])), "msg": e.get("msg", "")}
                        for e in exc.errors()[:5]
                    ],
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred while processing the request.",
                }
            },
        )

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - manual entry point
    import os

    import uvicorn

    # ``python -m app.main``: bind every interface (0.0.0.0, never localhost,
    # so a container accepts external traffic) and honour the platform's
    # dynamic port. Render/Heroku inject PORT (Render's default is 10000);
    # local runs fall back to 8000.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT") or "8000"))
