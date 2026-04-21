from __future__ import annotations

from typing import Any

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    FlexContainer,
    FlexMessage,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)


def _messaging_api() -> tuple[ApiClient, MessagingApi]:
    settings = get_settings()
    config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    client = ApiClient(config)
    return client, MessagingApi(client)


def _blob_api() -> tuple[ApiClient, MessagingApiBlob]:
    settings = get_settings()
    config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    client = ApiClient(config)
    return client, MessagingApiBlob(client)


def reply_text(reply_token: str, text: str) -> None:
    client, api = _messaging_api()
    try:
        api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    finally:
        client.close()


def push_text(user_id: str, text: str) -> None:
    if not user_id:
        log.warning("push_text_skipped_empty_user_id")
        return
    client, api = _messaging_api()
    try:
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text)],
            )
        )
    finally:
        client.close()


def push_flex(user_id: str, alt_text: str, flex_contents: dict[str, Any]) -> None:
    if not user_id:
        log.warning("push_flex_skipped_empty_user_id")
        return
    client, api = _messaging_api()
    try:
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[
                    FlexMessage(
                        altText=alt_text,
                        contents=FlexContainer.from_dict(flex_contents),
                    )
                ],
            )
        )
    finally:
        client.close()


def get_message_content(message_id: str) -> bytes:
    client, api = _blob_api()
    try:
        return api.get_message_content(message_id=message_id)
    finally:
        client.close()
