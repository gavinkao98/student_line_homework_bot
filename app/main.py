from fastapi import FastAPI

from app.config import get_settings
from app.cron import router as cron_router
from app.handlers.webhook import router as webhook_router
from app.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    configure_logging()
    log = get_logger(__name__)
    app = FastAPI(title="LINE Homework Bot", version="0.2.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(webhook_router)
    app.include_router(cron_router)

    @app.on_event("startup")
    def _seed_legacy_student() -> None:
        settings = get_settings()
        if not settings.STUDENT_USER_ID:
            return
        try:
            from app import db as _db
            from app.services import student as student_svc

            session = _db.SessionLocal()
            try:
                student_svc.ensure_seed(session, settings.STUDENT_USER_ID)
            finally:
                session.close()
        except Exception as exc:
            log.warning("seed_legacy_student_failed", error=str(exc))

    log.info("app_started")
    return app


app = create_app()
