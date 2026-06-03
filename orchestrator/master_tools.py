"""
MCP tools for the master topic's Claude.
Provides: list_topics, create_topic, send_to_topic, broadcast, topic_status.
Loaded as a McpSdkServerConfig into the master bridge's ClaudeAgentOptions.
"""
import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from orchestrator.bridge import TopicBridge

import config
from orchestrator import registry

log = logging.getLogger(__name__)

mcp = FastMCP("master-orchestrator")

# Will be set by run.py after bridges dict is ready
_bridges: "dict[int, TopicBridge]" = {}
_bot = None
_create_topic_fn = None  # async fn(name, description, model) -> TopicEntry


def init(bridges: "dict[int, TopicBridge]", bot, create_topic_fn):
    global _bridges, _bot, _create_topic_fn
    _bridges = bridges
    _bot = bot
    _create_topic_fn = create_topic_fn


# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_topics() -> str:
    """List all registered topics with name, model, folder, and session status."""
    entries = registry.get_all()
    if not entries:
        return "No topics registered yet."
    lines = []
    for e in entries:
        tag = " [master]" if e.is_master else ""
        sess = f"session={e.session_id[:8]}…" if e.session_id else "no session"
        lines.append(f"- **{e.name}**{tag}  thread={e.thread_id}  model={e.model}  {sess}  folder={e.folder}")
    return "\n".join(lines)


@mcp.tool()
async def create_topic(name: str, description: str = "", model: str = "") -> str:
    """
    Create a new Telegram forum topic and its workspace folder.
    Returns the new thread_id and folder path.
    """
    if _create_topic_fn is None:
        return "ERROR: orchestrator not initialised"
    effective_model = model.strip() or config.DEFAULT_MODEL
    try:
        entry = await _create_topic_fn(name, description, effective_model)
        return (
            f"✅ Created topic **{entry.name}** (thread_id={entry.thread_id})\n"
            f"Model: {entry.model}\nFolder: {entry.folder}"
        )
    except Exception as e:
        log.exception("create_topic failed: %s", e)
        return f"ERROR: {e}"


@mcp.tool()
async def send_to_topic(topic_name: str, prompt: str) -> str:
    """
    Send a prompt to a specific dev topic's Claude and return a summary.
    topic_name can be the slug or display name (case-insensitive substring match).
    """
    entry = _find_entry(topic_name)
    if entry is None:
        return f"ERROR: No topic found matching '{topic_name}'"
    bridge = _bridges.get(entry.thread_id)
    if bridge is None:
        return f"ERROR: No bridge for topic '{entry.name}'"
    await bridge.run_turn(prompt)
    return f"✅ Sent to **{entry.name}** (thread_id={entry.thread_id})"


@mcp.tool()
async def broadcast(prompt: str) -> str:
    """
    Send the same prompt to ALL dev topics concurrently and report results.
    """
    dev_entries = registry.get_dev_topics()
    if not dev_entries:
        return "No dev topics to broadcast to."

    async def _send_one(e):
        bridge = _bridges.get(e.thread_id)
        if bridge is None:
            return f"⚠️ {e.name}: no bridge"
        try:
            await bridge.run_turn(prompt)
            return f"✅ {e.name}"
        except Exception as ex:
            return f"❌ {e.name}: {ex}"

    results = await asyncio.gather(*[_send_one(e) for e in dev_entries])
    return "\n".join(results)


@mcp.tool()
async def topic_status(topic_name: str) -> str:
    """Return file/git status of a topic's workspace folder."""
    entry = _find_entry(topic_name)
    if entry is None:
        return f"ERROR: No topic found matching '{topic_name}'"
    folder = entry.folder
    if not os.path.exists(folder):
        return f"Folder does not exist: {folder}"

    lines = [f"**{entry.name}** — `{folder}`"]

    # File listing
    try:
        files = os.listdir(folder)
        lines.append(f"Files ({len(files)}): " + ", ".join(sorted(files)[:20]))
    except Exception as e:
        lines.append(f"ls error: {e}")

    # Git status if applicable
    git_dir = os.path.join(folder, ".git")
    if os.path.exists(git_dir):
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", folder, "status", "--short",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines.append("Git status:\n```\n" + stdout.decode()[:500] + "\n```")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────

def _find_entry(name: str) -> registry.TopicEntry | None:
    """Case-insensitive substring match on name or slug."""
    name_lower = name.lower()
    for e in registry.get_all():
        if e.is_master:
            continue
        if name_lower in e.name.lower() or name_lower in e.slug.lower():
            return e
    return None


def get_mcp_server_config() -> dict:
    """Return a McpSdkServerConfig (TypedDict) pointing to our FastMCP app."""
    return {
        "type": "sdk",
        "name": "master-orchestrator",
        "instance": mcp._mcp_server,
    }
