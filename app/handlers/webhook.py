from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app import db as _db
from app.config import get_settings
from app.handlers.commands import parse_command
from app.handlers.student import (
    handle_student_image,
    handle_student_postback,
    handle_student_text_command,
)
from app.handlers.teacher import handle_teacher_command, handle_teacher_postback
from app.line_client import get_profile, reply_text
from app.logging import get_logger
from app.models import EventLog
from app.services import student as student_svc

router = APIRouter()
log = get_logger(__name__)


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    secret = get_settings().LINE_CHANNEL_SECRET
    if not secret:
        return False
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/callback")
async def callback(
    request: Request,
    background: BackgroundTasks,
    x_line_signature: str | None = Header(default=None),
) -> dict[str, bool]:
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        log.warning("webhook_bad_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        log.warning("webhook_bad_json")
        raise HTTPException(status_code=400, detail="Invalid JSON") from e

    events = payload.get("events", [])
    for event in events:
        background.add_task(_process_event, event)

    return {"ok": True}


def _process_event(event: dict[str, Any]) -> None:
    session = _db.SessionLocal()
    try:
        _log_event(session, "webhook_in", event)
        _dispatch(session, event)
    except Exception as exc:
        log.exception("process_event_failed", error=str(exc), event_type=event.get("type"))
        try:
            _log_event(session, "error", {"error": str(exc), "event": event})
        except Exception:
            pass
    finally:
        session.close()


def _log_event(session: Session, event_type: str, payload: Any) -> None:
    try:
        row = EventLog(event_type=event_type, payload_json=json.dumps(payload, ensure_ascii=False, default=str))
        session.add(row)
        session.commit()
    except Exception as exc:
        log.warning("event_log_failed", error=str(exc))
        session.rollback()


def _ensure_student_registered(session: Session, user_id: str) -> None:
    """Register a non-teacher user as student (idempotent). Fetches display name from LINE."""
    settings = get_settings()
    if not user_id or user_id == settings.TEACHER_USER_ID:
        return
    existing = student_svc.get_by_line_id(session, user_id)
    if existing is not None and existing.active:
        return
    profile = get_profile(user_id)
    display_name = profile.get("displayName") if profile else None
    student_svc.register_student(session, user_id, display_name=display_name)
    # Best-effort: link student rich menu
    try:
        from app.services.rich_menu import link_student_menu_for_user

        link_student_menu_for_user(user_id)
    except Exception as exc:
        log.warning("auto_link_rich_menu_failed", error=str(exc))


def _dispatch(session: Session, event: dict[str, Any]) -> None:
    settings = get_settings()
    source = event.get("source") or {}
    user_id = source.get("userId", "")
    event_type = event.get("type")
    reply_token = event.get("replyToken", "")

    # Always seed legacy student if configured
    student_svc.ensure_seed(session, settings.STUDENT_USER_ID)

    # Handle follow / unfollow
    if event_type == "follow":
        _ensure_student_registered(session, user_id)
        return
    if event_type == "unfollow":
        if user_id and user_id != settings.TEACHER_USER_ID:
            student_svc.deactivate(session, user_id)
        return

    message = event.get("message") or {}
    text = (message.get("text") or "").strip() if event_type == "message" else ""

    bootstrap = not settings.TEACHER_USER_ID

    # Allow /whoami from anyone
    if event_type == "message" and message.get("type") == "text":
        cmd = parse_command(text)
        if cmd and cmd.name == "whoami":
            if reply_token:
                reply_text(reply_token, f"你的 User ID 是：{user_id}")
            return
        if bootstrap:
            if reply_token:
                reply_text(
                    reply_token,
                    "系統初次設定中，請先在 LINE 傳 /whoami 取得 User ID 並寫入 .env。",
                )
            return

    if bootstrap:
        return

    # Dispatch by role
    if user_id and user_id == settings.TEACHER_USER_ID:
        _dispatch_teacher(session, event, reply_token, text)
        return

    # Non-teacher: auto-register as student on first interaction
    _ensure_student_registered(session, user_id)
    student = student_svc.get_by_line_id(session, user_id)
    if student is None or not student.active:
        if reply_token and event_type == "message":
            reply_text(reply_token, "系統錯誤，請稍後再試。")
        return
    _dispatch_student(session, event, reply_token, student.id)


def _dispatch_teacher(session: Session, event: dict[str, Any], reply_token: str, text: str) -> None:
    event_type = event.get("type")
    if event_type == "postback":
        data = (event.get("postback") or {}).get("data", "")
        handle_teacher_postback(session, reply_token, data)
        return
    if event_type != "message":
        return
    message = event.get("message") or {}
    if message.get("type") != "text":
        return
    cmd = parse_command(text)
    if cmd is None:
        log.info("teacher_non_command_ignored", text=text)
        return
    handle_teacher_command(session, reply_token, cmd)


def _dispatch_student(
    session: Session, event: dict[str, Any], reply_token: str, student_id: int
) -> None:
    event_type = event.get("type")
    if event_type == "postback":
        data = (event.get("postback") or {}).get("data", "")
        handle_student_postback(session, reply_token, data, student_id)
        return
    if event_type == "message":
        message = event.get("message") or {}
        mtype = message.get("type")
        if mtype == "image":
            handle_student_image(session, reply_token, message.get("id", ""), student_id)
            return
        if mtype == "text":
            text = (message.get("text") or "").strip()
            # Try command handler (e.g. /stuck). If handled, done. Else ignore.
            handle_student_text_command(session, reply_token, text, student_id)
            return
        return
