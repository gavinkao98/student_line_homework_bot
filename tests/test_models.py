from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Assignment, Photo


def test_create_assignment(session):
    a = Assignment(assigned_date=date(2026, 4, 21), content="第12回")
    session.add(a)
    session.commit()
    assert a.id is not None
    assert a.assigned_date == date(2026, 4, 21)


def test_assignment_unique_date(session):
    session.add(Assignment(assigned_date=date(2026, 4, 21), content="A"))
    session.commit()
    session.add(Assignment(assigned_date=date(2026, 4, 21), content="B"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_photo_unique_message_id(session):
    a = Assignment(assigned_date=date(2026, 4, 21), content="A")
    session.add(a)
    session.commit()
    session.add(Photo(assignment_id=a.id, line_message_id="m1", file_path="/tmp/a.jpg"))
    session.commit()
    session.add(Photo(assignment_id=a.id, line_message_id="m1", file_path="/tmp/b.jpg"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_photo_assignment_id_nullable(session):
    p = Photo(assignment_id=None, line_message_id="m2", file_path="/tmp/c.jpg")
    session.add(p)
    session.commit()
    assert p.assignment_id is None
