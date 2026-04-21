from fastapi import FastAPI

from app.cron import router as cron_router
from app.handlers.webhook import router as webhook_router
from app.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    configure_logging()
    log = get_logger(__name__)
    app = FastAPI(title="LINE Homework Bot", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(webhook_router)
    app.include_router(cron_router)

    log.info("app_started")
    return app


app = create_app()
