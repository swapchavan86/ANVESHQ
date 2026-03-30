from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import admin, auth, payments, stocks
from src.auth.schema import ensure_identity_schema
from src.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_identity_schema()

    app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    def healthcheck():
        return {"status": "ok", "app": settings.APP_NAME}

    app.include_router(auth.router, prefix=settings.API_PREFIX)
    app.include_router(admin.router, prefix=settings.API_PREFIX)
    app.include_router(stocks.router, prefix=settings.API_PREFIX)
    app.include_router(payments.router, prefix=settings.API_PREFIX)
    return app


app = create_app()
