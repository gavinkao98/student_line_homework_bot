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


@pytest.fixture(autouse=True)
def _seed_test_student(session_factory, monkeypatch):
    """Auto-register the test student for every test."""
    monkeypatch.setattr("app.line_client.get_profile", lambda uid: None)
    monkeypatch.setattr(
        "app.services.rich_menu.link_student_menu_for_user", lambda uid: None
    )
    from app.services.student import register_student

    s = session_factory()
    try:
        register_student(s, "U_student_test", "TestStudent")
    finally:
        s.close()
    yield


@pytest.fixture
def test_student_id(session_factory):
    from app.services.student import get_by_line_id

    s = session_factory()
    try:
        st = get_by_line_id(s, "U_student_test")
        return st.id
    finally:
        s.close()


@pytest.fixture
def pass_stuck_gate(session_factory):
    """Returns a helper fn(assignment_id, student_line_id='U_student_test') that
    marks the stuck-before-complete gate as satisfied, so completion tests
    don't have to walk through the interactive stuck prompt flow."""
    from app.services.stuck import mark_assignment_stuck_submitted
    from app.services.student import get_by_line_id

    def _pass(assignment_id, student_line_id: str = "U_student_test"):
        s = session_factory()
        try:
            st = get_by_line_id(s, student_line_id)
            if st is None:
                raise RuntimeError(f"student {student_line_id} not registered")
            mark_assignment_stuck_submitted(s, assignment_id, st.id)
        finally:
            s.close()

    return _pass


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
