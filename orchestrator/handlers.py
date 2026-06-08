"""Telegram update handlers: messages, callbacks, files, commands."""
import logging
import os

from telegram import Update, BotCommand, MenuButtonCommands
from telegram.ext import ContextTypes

import config
from config import MODELS
from orchestrator import registry, permissions
from orchestrator.telegram_io import send, model_keyboard, download_file

log = logging.getLogger(__name__)

# Populated by run.py after bridges are ready
bridges: dict[int, "TopicBridge"] = {}  # noqa: F821


# ─────────────────────────────────────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == config.OWNER_ID


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", None)
    await update.message.reply_text(
        f"👋 JohnnyCCHelper 已啟動\n"
        f"`chat_id = {chat_id}`\n"
        f"`thread_id = {thread_id}`\n"
        f"請把 `GROUP_ID={chat_id}` 填入 .env 重啟（若尚未填寫）。",
        parse_mode="Markdown",
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    entries = registry.get_all()
    if not entries:
        await update.message.reply_text("目前沒有任何 topic。")
        return
    lines = []
    for e in entries:
        tag = " 🎛️主控" if e.is_master else ""
        model_label = next((lb for mid, lb in MODELS if mid == e.model), e.model)
        lines.append(f"• *{e.name}*{tag}  `{model_label}`  thread={e.thread_id}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    await update.message.reply_text(
        "在 General (主控 topic) 對 Claude 說「建立一個叫 _<名稱>_ 的 topic」即可。\n"
        "或直接告訴主控 Claude 要幾個 topic、各自做什麼。",
        parse_mode="Markdown",
    )


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    thread_id = getattr(update.message, "message_thread_id", None) or 0
    entry = registry.get(thread_id)
    current = entry.model if entry else config.DEFAULT_MODEL
    log.info("CMD_MODEL thread_id=%s  entry_model=%s  current=%s",
             thread_id, entry.model if entry else "N/A", current)
    kb = model_keyboard(current)
    label = next((lb for mid, lb in MODELS if mid == current), current)
    await update.message.reply_text(
        f"目前模型：*{label}*\n選擇新模型：",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def cmd_reload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Close and reconnect the Claude session for the current topic (or all topics).

    Flags:
      --all    reload every topic
      --fresh  also clear session_id so next connection starts a brand-new
               session (context window reset to 0%)
    """
    if not _is_owner(update):
        return

    args = ctx.args or []
    reload_all = "--all" in args
    fresh = "--fresh" in args

    async def _do_reload(tid: int) -> str:
        bridge = bridges.get(tid)
        entry = registry.get(tid)
        name = entry.name if entry else f"thread={tid}"
        if bridge is None:
            return f"❓ {name}: 無 bridge"
        await bridge.close()
        if fresh and entry:
            registry.update_session(tid, None)
            bridge.entry.session_id = None
        return name

    if reload_all:
        targets = list(bridges.keys())
        if not targets:
            await update.message.reply_text("目前沒有任何 topic。")
            return
        names = [await _do_reload(tid) for tid in targets]
        tag = "（全新 session）" if fresh else ""
        await update.message.reply_text(
            f"🔄 已重載 *{len(names)}* 個 topic {tag}：\n" +
            "\n".join(f"• {n}" for n in names),
            parse_mode="Markdown",
        )
    else:
        thread_id = getattr(update.message, "message_thread_id", None) or 0
        if bridges.get(thread_id) is None:
            await update.message.reply_text(
                f"❓ 此 topic (thread\\_id={thread_id}) 尚未註冊。",
                parse_mode="Markdown",
            )
            return
        name = await _do_reload(thread_id)
        tag = "（全新 session，context 歸零）" if fresh else "（保留對話記憶）"
        await update.message.reply_text(
            f"🔄 *{name}* 已重載 {tag}\n下一則訊息將以新設定啟動。",
            parse_mode="Markdown",
        )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    await update.message.reply_text(
        "*指令說明*\n"
        "/start — 顯示 chat\\_id\n"
        "/list — 列出所有 topic\n"
        "/new — 如何建立新 topic\n"
        "/model — 切換當前 topic 的 LLM 模型\n"
        "/reload — 重載當前 topic（保留記憶）\n"
        "/reload --fresh — 重載並清除 context（歸零）\n"
        "/reload --all --fresh — 所有 topic 全部清除重啟\n"
        "/help — 顯示此說明\n\n"
        "📌 在任何 topic 直接輸入文字即可與該 topic 的 Claude 對話。\n"
        "📎 傳送檔案會自動存到該 topic 的 `inbox/` 並通知 Claude。",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Message routing
# ─────────────────────────────────────────────────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return

    thread_id = getattr(update.message, "message_thread_id", None) or 0

    bridge = bridges.get(thread_id)
    if bridge is None:
        await update.message.reply_text(
            f"❓ 此 topic (thread\\_id={thread_id}) 尚未註冊。\n"
            "請在 General (主控) 建立新 topic，或加入已有的 topic。",
            parse_mode="Markdown",
        )
        return

    await bridge.run_turn(text)


# ─────────────────────────────────────────────────────────────────────────────
# File upload
# ─────────────────────────────────────────────────────────────────────────────

async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    msg = update.message
    if not msg:
        return

    thread_id = getattr(msg, "message_thread_id", None) or 0
    entry = registry.get(thread_id)
    if entry is None:
        await msg.reply_text("❓ 此 topic 尚未註冊，檔案無法儲存。")
        return

    # Determine file_id and filename
    file_id = None
    filename = None
    if msg.document:
        file_id = msg.document.file_id
        filename = msg.document.file_name or f"file_{msg.message_id}"
    elif msg.photo:
        ph = msg.photo[-1]
        file_id = ph.file_id
        filename = f"photo_{msg.message_id}.jpg"
    elif msg.audio:
        file_id = msg.audio.file_id
        filename = msg.audio.file_name or f"audio_{msg.message_id}"
    elif msg.video:
        file_id = msg.video.file_id
        filename = msg.video.file_name or f"video_{msg.message_id}"
    else:
        return

    inbox = os.path.join(entry.folder, "inbox")
    dest = await download_file(ctx.bot, file_id, inbox, filename)
    await msg.reply_text(f"📥 已儲存：`{dest}`", parse_mode="Markdown")

    bridge = bridges.get(thread_id)
    if bridge:
        await bridge.run_turn(f"使用者上傳了一個檔案到 inbox: `{dest}`")


# ─────────────────────────────────────────────────────────────────────────────
# Callback query (buttons)
# ─────────────────────────────────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if query.from_user.id != config.OWNER_ID:
        await query.answer("Not authorized")
        return

    data: str = query.data or ""
    await query.answer()

    # Permission button: perm:allow:<rid> | perm:deny:<rid>
    if data.startswith("perm:"):
        parts = data.split(":", 2)
        log.info("CALLBACK  data=%r  parts=%s", data, parts)
        _, decision, rid = parts
        resolved = permissions.resolve(rid, decision)
        status = "✅ 已允許" if decision == "allow" else "❌ 已拒絕"
        if resolved:
            # 1. 立刻移除按鈕 (無論文字更新是否成功,按鈕都消失)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            # 2. 再更新文字 (不帶 Markdown,避免特殊字元炸掉)
            try:
                original = query.message.text or ""
                # 截斷過長的原始訊息,避免超過 4096
                if len(original) > 3800:
                    original = original[:3800] + "…"
                await query.edit_message_text(f"{original}\n\n{status}")
            except Exception:
                pass
        else:
            # rid not found — stale button from a previous session
            try:
                await query.answer("⚠️ 此授權請求已過期，請重新發送指令。", show_alert=True)
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        return

    # Model selection: model:<model_id>
    if data.startswith("model:"):
        model_id = data[6:]
        thread_id = getattr(query.message, "message_thread_id", None) or 0

        # Update registry
        entry = registry.get(thread_id)
        if entry is None:
            await query.edit_message_text("❓ 此 topic 尚未註冊。")
            return

        # Update bridge model if exists
        bridge = bridges.get(thread_id)
        if bridge:
            await bridge.set_model(model_id)
        else:
            registry.update_model(thread_id, model_id)

        label = next((lb for mid, lb in MODELS if mid == model_id), model_id)
        # 先移除按鈕,再更新文字
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await query.edit_message_text(
                f"✅ 已切換到 {label}\n下一回合生效。",
            )
        except Exception:
            pass
        return


# ─────────────────────────────────────────────────────────────────────────────
# Bot commands / menu button registration
# ─────────────────────────────────────────────────────────────────────────────

async def setup_commands(bot) -> None:
    commands = [
        BotCommand("model",  "切換 LLM 模型"),
        BotCommand("reload", "重載 Claude session（套用新設定）"),
        BotCommand("list",   "列出所有 topic"),
        BotCommand("new",    "建立新 topic"),
        BotCommand("start",  "顯示 chat_id"),
        BotCommand("help",   "說明"),
    ]
    await bot.set_my_commands(commands)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    log.info("Commands and menu button registered.")
