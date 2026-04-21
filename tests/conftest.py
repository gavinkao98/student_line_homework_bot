from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("CRON_SECRET", "test-cron-secret")
os.environ.setdefault("TEACHER_USER_ID", "U_teacher_test")
os.environ.setdefault("STUDENT_USER_ID", "U_student_test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("PHOTO_DIR", str(Path(__file__).parent / "_photos_tmp"))
os.environ.setdefault("TZ", "Asia/Taipei")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base, get_session


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(engine, session_factory, monkeypatch):
    # Patch the module-level engine + SessionLocal so production code uses our test DB.
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)

    from app.main import create_app

    app = create_app()

    def override_get_session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as c:
        yield c
