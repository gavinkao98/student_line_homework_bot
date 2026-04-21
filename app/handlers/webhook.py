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
from app.handlers.student import handle_student_image, handle_student_postback
from app.handlers.teacher import handle_teacher_command, handle_teacher_postback
from app.line_client import reply_text
from app.logging import get_logger
from app.models import EventLog

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


def _dispatch(session: Session, event: dict[str, Any]) -> None:
    settings = get_settings()
    source = event.get("source") or {}
    user_id = source.get("userId", "")
    event_type = event.get("type")
    reply_token = event.get("replyToken", "")

    message = event.get("message") or {}
    text = (message.get("text") or "").strip() if event_type == "message" else ""

    # Bootstrap: allow /whoami for anyone if both role IDs are empty
    bootstrap = not settings.TEACHER_USER_ID and not settings.STUDENT_USER_ID

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

    if not bootstrap:
        role = _role_of(user_id, settings)
        if role is None:
            if reply_token and event_type == "message":
                reply_text(reply_token, "此帳號為私人教學用途，恕不提供回應。")
            return
        if role == "teacher":
            _dispatch_teacher(session, event, reply_token, text)
            return
        if role == "student":
            _dispatch_student(session, event, reply_token)
            return


def _role_of(user_id: str, settings) -> str | None:
    if user_id and user_id == settings.TEACHER_USER_ID:
        return "teacher"
    if user_id and user_id == settings.STUDENT_USER_ID:
        return "student"
    return None


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


def _dispatch_student(session: Session, event: dict[str, Any], reply_token: str) -> None:
    event_type = event.get("type")
    if event_type == "postback":
        data = (event.get("postback") or {}).get("data", "")
        handle_student_postback(session, reply_token, data)
        return
    if event_type == "message":
        message = event.get("message") or {}
        mtype = message.get("type")
        if mtype == "image":
            handle_student_image(session, reply_token, message.get("id", ""))
            return
        if mtype == "text":
            text = (message.get("text") or "").strip()
            cmd = parse_command(text)
            if cmd and cmd.name == "whoami":
                # already handled upstream, but redundant safety
                if reply_token:
                    source = event.get("source") or {}
                    reply_text(reply_token, f"你的 User ID 是：{source.get('userId','')}")
            # other student text: ignore silently
            return
