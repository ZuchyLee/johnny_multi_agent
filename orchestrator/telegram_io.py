"""Telegram send/edit helpers, inline keyboards, file download."""
import asyncio
import os
import time
import logging
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import RetryAfter, BadRequest

import config
from config import MODELS

log = logging.getLogger(__name__)

STREAM_EDIT_INTERVAL = 1.5  # seconds between edits while streaming


async def send(bot: Bot, thread_id: int | None, text: str, **kwargs) -> Message:
    """Send a message to GROUP_ID, optionally in a topic thread."""
    extra = {}
    if thread_id:
        extra["message_thread_id"] = thread_id
    return await bot.send_message(
        chat_id=config.GROUP_ID,
        text=text[:4096],
        parse_mode="Markdown",
        **extra,
        **kwargs,
    )


async def safe_edit(msg: Message, text: str) -> None:
    """Edit a message, swallowing 'message not modified' and handling rate limits."""
    try:
        await msg.edit_text(text[:4096], parse_mode="Markdown")
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            log.debug("edit_text BadRequest: %s", e)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            await msg.edit_text(text[:4096], parse_mode="Markdown")
        except Exception:
            pass
    except Exception as e:
        log.debug("edit_text error: %s", e)


class StreamBuffer:
    """Accumulates streaming text and throttles Telegram edits."""

    def __init__(self, bot: Bot, thread_id: int | None):
        self.bot = bot
        self.thread_id = thread_id
        self._text = ""
        self._msg: Optional[Message] = None
        self._last_edit = 0.0

    async def append(self, delta: str) -> None:
        self._text += delta
        now = time.monotonic()
        if self._msg is None:
            try:
                self._msg = await send(self.bot, self.thread_id, self._text or "…")
                self._last_edit = now
            except Exception as e:
                log.warning("StreamBuffer initial send failed: %s", e)
        elif now - self._last_edit >= STREAM_EDIT_INTERVAL:
            await safe_edit(self._msg, self._text)
            self._last_edit = now

    async def finalize(self, final: str | None = None) -> None:
        """Flush final text; called when stream ends."""
        if final:
            self._text = final
        if self._msg:
            await safe_edit(self._msg, self._text)
        elif self._text:
            try:
                self._msg = await send(self.bot, self.thread_id, self._text)
            except Exception as e:
                log.warning("StreamBuffer finalize send failed: %s", e)

    @property
    def text(self) -> str:
        return self._text


def permission_keyboard(request_id: str, tool_name: str) -> InlineKeyboardMarkup:
    """Two-button allow/deny keyboard for tool permission requests."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ 允許",
            callback_data=f"perm:allow:{request_id}",
        ),
        InlineKeyboardButton(
            "❌ 拒絕",
            callback_data=f"perm:deny:{request_id}",
        ),
    ]])


def model_keyboard(current_model: str) -> InlineKeyboardMarkup:
    """Inline keyboard for model selection; checkmarks current model."""
    buttons = []
    for model_id, label in MODELS:
        mark = "✓ " if model_id == current_model else ""
        buttons.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"model:{model_id}",
        ))
    return InlineKeyboardMarkup([buttons])


async def download_file(bot: Bot, file_id: str, dest_dir: str, filename: str) -> str:
    """Download a Telegram file to dest_dir/filename, return full path."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)
    return dest


async def send_document(
    bot: Bot,
    thread_id: int | None,
    file_path: str,
    caption: str = "",
) -> None:
    """Send a local file as a Telegram document to GROUP_ID."""
    import config
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    extra: dict = {}
    if thread_id:
        extra["message_thread_id"] = thread_id
    with open(file_path, "rb") as fh:
        await bot.send_document(
            chat_id=config.GROUP_ID,
            document=fh,
            filename=os.path.basename(file_path),
            caption=caption[:1024] if caption else "",
            **extra,
        )
