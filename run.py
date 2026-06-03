"""Entry point: builds the Application, restores bridges, starts polling."""
import asyncio
import logging
import os
import re
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

from telegram import Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from orchestrator import registry
from orchestrator.bridge import TopicBridge
from orchestrator.master_tools import init as master_tools_init, get_mcp_server_config
import orchestrator.handlers as handlers
from orchestrator.handlers import setup_commands

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

# Global bridges dict shared with handlers and master_tools
bridges: dict[int, TopicBridge] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Topic creation helper (called from master_tools and /new)
# ─────────────────────────────────────────────────────────────────────────────

async def create_topic(
    name: str,
    description: str = "",
    model: str = "",
    bot: Bot = None,
) -> registry.TopicEntry:
    """Create a TG forum topic + workspace folder + registry entry + bridge."""
    if not config.GROUP_ID:
        raise RuntimeError("GROUP_ID not set in .env — start bot, get chat_id, fill in .env.")

    # New topics inherit the master's current model (user-visible default),
    # falling back to MASTER_MODEL from .env only if master isn't in DB yet.
    if model:
        effective_model = model
    else:
        master_entry = registry.get(config.MASTER_TOPIC_THREAD_ID)
        effective_model = master_entry.model if master_entry else config.MASTER_MODEL
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "topic"

    # Ensure unique slug
    existing_slugs = {e.slug for e in registry.get_all()}
    base_slug = slug
    i = 1
    while slug in existing_slugs:
        slug = f"{base_slug}-{i}"
        i += 1

    # Create Telegram forum topic
    tg_topic = await bot.create_forum_topic(
        chat_id=config.GROUP_ID,
        name=name,
    )
    thread_id: int = tg_topic.message_thread_id

    folder = os.path.join(config.WORKSPACE_ROOT, slug)
    os.makedirs(folder, exist_ok=True)

    entry = registry.TopicEntry(
        thread_id=thread_id,
        name=name,
        slug=slug,
        folder=folder,
        model=effective_model,
        is_master=False,
    )
    registry.upsert(entry)

    bridge = TopicBridge(entry, bot)
    bridges[thread_id] = entry
    bridges[thread_id] = bridge

    # Send welcome message in the new topic
    await bot.send_message(
        chat_id=config.GROUP_ID,
        message_thread_id=thread_id,
        text=(
            f"🚀 *{name}*\n"
            f"Model: `{effective_model}`\n"
            f"Folder: `{folder}`\n\n"
            f"{description or '已就緒，直接輸入指令即可。'}"
        ),
        parse_mode="Markdown",
    )

    log.info("Created topic '%s' (thread_id=%s, slug=%s)", name, thread_id, slug)
    return entry


# ─────────────────────────────────────────────────────────────────────────────
# Restore existing topics from registry on startup
# ─────────────────────────────────────────────────────────────────────────────

def restore_bridges(bot: Bot) -> None:
    entries = registry.get_all()
    for entry in entries:
        bridge = TopicBridge(entry, bot)
        bridges[entry.thread_id] = bridge
    log.info("Restored %d bridges from registry.", len(entries))


# ─────────────────────────────────────────────────────────────────────────────
# Master topic bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_master_entry(bot: Bot) -> registry.TopicEntry:
    """Ensure the master (General, thread_id=0) is registered.

    First-time setup uses MASTER_MODEL from .env as the default.
    After that, the model is fully user-controlled via /model — no forced sync.
    """
    entry = registry.get(config.MASTER_TOPIC_THREAD_ID)
    if entry is None:
        entry = registry.TopicEntry(
            thread_id=config.MASTER_TOPIC_THREAD_ID,
            name="General (主控)",
            slug="master",
            folder=os.path.join(config.WORKSPACE_ROOT, "master"),
            model=config.MASTER_MODEL,
            is_master=True,
        )
        registry.upsert(entry)
        os.makedirs(entry.folder, exist_ok=True)
    return entry


def _make_master_bridge(entry: registry.TopicEntry, bot: Bot) -> TopicBridge:
    """Create a TopicBridge for master, injecting MCP server config."""
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from orchestrator.bridge import AUTO_ALLOW_TOOLS

    # Use a subclass to inject MCP server
    class MasterBridge(TopicBridge):
        async def _ensure_client(self):
            if self._client is not None:
                return
            os.makedirs(self.entry.folder, exist_ok=True)

            mcp_cfg = get_mcp_server_config()
            opts = ClaudeAgentOptions(
                cli_path=config.CLAUDE_PATH,
                permission_mode="acceptEdits",
                model=self.entry.model,
                cwd=self.entry.folder,
                resume=self.entry.session_id,
                can_use_tool=self._can_use_tool,
                mcp_servers={
                    "orchestrator": mcp_cfg,
                    "file-tools": self._make_file_mcp(),
                },
                system_prompt=config.TOPIC_SYSTEM_PROMPT,
            )
            from claude_agent_sdk import ClaudeSDKClient
            self._client = ClaudeSDKClient(opts)
            await self._client.connect()

    return MasterBridge(entry, bot)


# ─────────────────────────────────────────────────────────────────────────────
# Application setup
# ─────────────────────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    bot = application.bot

    # DB
    registry.init_db()

    # Restore
    restore_bridges(bot)

    # Master
    master_entry = _ensure_master_entry(bot)
    master_bridge = _make_master_bridge(master_entry, bot)
    bridges[config.MASTER_TOPIC_THREAD_ID] = master_bridge

    # Wire bridges into handlers and master_tools
    handlers.bridges = bridges
    master_tools_init(
        bridges=bridges,
        bot=bot,
        create_topic_fn=lambda name, desc, model: create_topic(name, desc, model, bot),
    )

    # Setup menu button / commands
    await setup_commands(bot)

    log.info("Bot initialised. Bridges: %s", list(bridges.keys()))


def main():
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)   # 允許 callback 與 message handler 並行,避免按鈕等待死鎖
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",  handlers.cmd_start))
    app.add_handler(CommandHandler("list",   handlers.cmd_list))
    app.add_handler(CommandHandler("new",    handlers.cmd_new))
    app.add_handler(CommandHandler("model",  handlers.cmd_model))
    app.add_handler(CommandHandler("reload", handlers.cmd_reload))
    app.add_handler(CommandHandler("help",   handlers.cmd_help))

    # Callback buttons (permissions + model selection)
    app.add_handler(CallbackQueryHandler(handlers.on_callback))

    # Files
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.AUDIO | filters.VIDEO,
        handlers.on_file,
    ))

    # Text messages (must be last, most general)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handlers.on_message,
    ))

    log.info("Starting polling…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
