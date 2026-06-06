"""TopicBridge: one per topic, owns a ClaudeSDKClient session."""
import asyncio
import logging
import os
import uuid
from typing import Any, Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage, ResultMessage, SystemMessage, RateLimitEvent,
    PermissionResultAllow, PermissionResultDeny, ToolPermissionContext,
    TextBlock, ToolUseBlock,
)
from telegram import Bot

import config
from orchestrator import registry, permissions
from orchestrator.telegram_io import StreamBuffer, send, permission_keyboard, send_document

log = logging.getLogger(__name__)

# Tools that are always auto-allowed (read-only ops)
AUTO_ALLOW_TOOLS = {
    "Read", "Edit", "Write", "Glob", "Grep", "MultiEdit",
    "NotebookRead", "NotebookEdit",
}


class TopicBridge:
    def __init__(self, entry: registry.TopicEntry, bot: Bot):
        self.entry = entry
        self.bot = bot
        self._client: Optional[ClaudeSDKClient] = None
        self._lock = asyncio.Lock()
        self._session_task: Optional[asyncio.Task] = None
        self._current_buf: Optional[StreamBuffer] = None  # shared with _can_use_tool

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def run_turn(self, text: str, extra_system: str = "") -> str:
        """Send one user turn; stream response back to the topic.
        Returns the full response text so callers (e.g. send_to_topic) can
        read what the sub-topic said and continue a dialogue.
        """
        async with self._lock:
            await self._ensure_client()
            # Show immediate status so user knows something is happening
            status_msg = None
            try:
                status_msg = await send(self.bot, self.entry.thread_id, "⏳ 思考中...")
            except Exception:
                pass
            buf = StreamBuffer(self.bot, self.entry.thread_id, initial_msg=status_msg)
            self._current_buf = buf
            try:
                await self._client.query(text)
                async for event in self._client.receive_messages():
                    buf = self._current_buf  # may have been reset by _can_use_tool
                    if isinstance(event, AssistantMessage):
                        # Detect tool use vs text content
                        tool_blocks = [b for b in event.content if isinstance(b, ToolUseBlock)]
                        text_delta = "".join(
                            b.text for b in event.content if isinstance(b, TextBlock)
                        )
                        if tool_blocks and not text_delta:
                            # Pure tool use — update status indicator
                            names = ", ".join(f"`{b.name}`" for b in tool_blocks)
                            await buf.set_status(f"🔧 執行中：{names}")
                        elif text_delta:
                            await buf.append(text_delta)
                    elif isinstance(event, ResultMessage):
                        if event.session_id:
                            registry.update_session(self.entry.thread_id, event.session_id)
                            self.entry.session_id = event.session_id
                        await buf.finalize()
                        break
                    elif isinstance(event, RateLimitEvent):
                        log.info("[%s] rate limit event, waiting…", self.entry.slug)
                        await buf.set_status("⏳ Rate limit，稍等...")
            except Exception as e:
                log.exception("[%s] run_turn error: %s", self.entry.slug, e)
                await self._current_buf.finalize()
                await send(self.bot, self.entry.thread_id, f"⚠️ 錯誤: `{e}`")
                return f"[錯誤: {e}]"
            finally:
                response_text = (self._current_buf.text if self._current_buf else buf.text)
                self._current_buf = None
            return response_text

    async def set_model(self, model_id: str) -> None:
        """Switch model; takes effect on next turn.

        Also clears the session_id so that if the bot restarts, the new
        session is started with the correct model.  Without this, Claude CLI's
        ``--resume <session_id>`` would ignore the ``--model`` flag and revert
        to the model that was used when the session was originally created.
        """
        if self.entry.model == model_id:
            return
        self.entry.model = model_id
        registry.update_model(self.entry.thread_id, model_id)
        if self._client:
            await self._client.set_model(model_id)
        # Clear session_id so a future restart spawns a fresh Claude process
        # with the correct --model flag instead of being overridden by --resume.
        self.entry.session_id = None
        registry.update_session(self.entry.thread_id, None)

    async def close(self) -> None:
        permissions.cancel_all_for(self.entry.slug)
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _make_file_mcp(self) -> dict:
        """Build an in-process MCP server with send_file_to_telegram tool."""
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP(f"bridge-{self.entry.slug}")
        bot = self.bot
        entry = self.entry

        @mcp.tool()
        async def send_file_to_telegram(file_path: str, caption: str = "") -> str:
            """
            Send a file from the workspace to the Telegram topic.
            file_path: absolute path or relative to the workspace folder.
            caption: optional caption shown below the file (max 1024 chars).
            """
            # Resolve relative paths against the workspace folder
            if not os.path.isabs(file_path):
                file_path = os.path.join(entry.folder, file_path)
            try:
                await send_document(bot, entry.thread_id, file_path, caption)
                return f"✅ 已傳送: {os.path.basename(file_path)}"
            except FileNotFoundError:
                return f"❌ 找不到檔案: {file_path}"
            except Exception as e:
                return f"❌ 傳送失敗: {e}"

        return {
            "type": "sdk",
            "name": f"bridge-{self.entry.slug}",
            "instance": mcp._mcp_server,
        }

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        os.makedirs(self.entry.folder, exist_ok=True)

        opts = ClaudeAgentOptions(
            cli_path=config.CLAUDE_PATH,
            permission_mode="acceptEdits",
            model=self.entry.model,
            cwd=self.entry.folder,
            resume=self.entry.session_id,
            can_use_tool=self._can_use_tool,
            mcp_servers={"file-tools": self._make_file_mcp()},
            system_prompt=config.TOPIC_SYSTEM_PROMPT,
        )
        self._client = ClaudeSDKClient(opts)
        # connect without initial prompt (we query separately)
        await self._client.connect()
        # Drain any messages that --resume may have replayed from the previous
        # session (the CLI re-emits the last assistant turn on startup).
        # We consume until the queue is empty or we see a ResultMessage.
        if self.entry.session_id:
            await self._drain_resume_replay()

    async def _drain_resume_replay(self) -> None:
        """Discard any messages the CLI replays on --resume startup.

        When Claude Code CLI resumes a session it re-emits the last assistant
        turn before waiting for new input.  If we don't drain those messages
        here, they appear as the response to the *next* user message, causing
        a consistent one-turn delay.
        """
        try:
            async with asyncio.timeout(5):
                async for event in self._client.receive_messages():
                    log.debug("[%s] drain replay: %s", self.entry.slug, type(event).__name__)
                    if isinstance(event, ResultMessage):
                        break
        except TimeoutError:
            # No replay messages — that's fine, just continue
            log.debug("[%s] drain replay: timeout (no replay found)", self.entry.slug)
        except Exception as e:
            log.debug("[%s] drain replay error: %s", self.entry.slug, e)

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Auto-allow safe tools
        if tool_name in AUTO_ALLOW_TOOLS:
            log.debug("AUTO-ALLOW tool=%s", tool_name)
            return PermissionResultAllow(behavior="allow")

        # Finalize current response text so auth button appears AFTER it
        if self._current_buf:
            await self._current_buf.finalize()
            # Reset to a fresh buffer; post-auth reply will create a new message
            self._current_buf = StreamBuffer(self.bot, self.entry.thread_id)

        # Build a readable summary of the tool call
        summary = _tool_summary(tool_name, tool_input)
        request_id = f"{self.entry.slug}:{uuid.uuid4().hex[:8]}"
        log.info("CAN_USE_TOOL  slug=%s  tool=%s  rid=%s", self.entry.slug, tool_name, request_id)

        rid, fut = permissions.create(request_id)
        kb = permission_keyboard(rid, tool_name)
        try:
            await send(
                self.bot,
                self.entry.thread_id,
                f"🔐 *Claude 要使用工具*\n`{tool_name}`\n{summary}",
                reply_markup=kb,
            )
            log.info("CAN_USE_TOOL  button sent  rid=%s", rid)
        except Exception as e:
            log.error("CAN_USE_TOOL  send failed: %s", e)
            return PermissionResultDeny(behavior="deny", message=f"send error: {e}")

        log.info("CAN_USE_TOOL  awaiting future  rid=%s", rid)
        try:
            # Do NOT use asyncio.shield here: without it, wait_for cancels `fut`
            # on timeout, making `fut.done()` True so any late button press is
            # correctly detected as stale by permissions.resolve().
            decision: str = await asyncio.wait_for(fut, timeout=300)
            log.info("CAN_USE_TOOL  future resolved  rid=%s  decision=%s", rid, decision)
        except asyncio.TimeoutError:
            permissions.discard(rid)   # clean up stale entry
            await send(self.bot, self.entry.thread_id,
                       "⏰ 授權請求逾時（5 分鐘），已自動拒絕。\n請重新發送指令再次授權。")
            return PermissionResultDeny(behavior="deny", message="timeout")
        except asyncio.CancelledError:
            permissions.discard(rid)   # clean up stale entry
            log.warning("CAN_USE_TOOL  cancelled  rid=%s", rid)
            return PermissionResultDeny(behavior="deny", message="cancelled")

        if decision == "allow":
            return PermissionResultAllow(behavior="allow")
        return PermissionResultDeny(behavior="deny", message="user denied")


def _tool_summary(tool_name: str, tool_input: dict) -> str:
    """Return a short human-readable summary of a tool call."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"```\n{cmd[:300]}\n```"
    if tool_name in ("Read", "Edit", "Write"):
        return f"`{tool_input.get('file_path', '')}`"
    parts = [f"`{k}`: `{str(v)[:80]}`" for k, v in list(tool_input.items())[:3]]
    return "\n".join(parts) if parts else ""
