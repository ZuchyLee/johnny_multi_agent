import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
OWNER_ID: int = int(os.environ["OWNER_ID"])
GROUP_ID: int | None = int(os.environ["GROUP_ID"]) if os.environ.get("GROUP_ID") else None
WORKSPACE_ROOT: str = os.environ.get("WORKSPACE_ROOT", os.path.join(os.path.dirname(__file__), "workspaces"))
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "claude-opus-4-8")
MASTER_MODEL: str = os.environ.get("MASTER_MODEL", DEFAULT_MODEL)
CLAUDE_PATH: str = os.environ.get("CLAUDE_PATH", "claude")

MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-8",           "Opus 4.8"),
    ("claude-sonnet-4-6",         "Sonnet 4.6"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
]

MASTER_TOPIC_THREAD_ID: int = 0  # General topic thread_id

# Context window usage warning threshold (0–100). A summary is sent after
# every turn; a warning is added when usage reaches this percentage.
CONTEXT_WARN_PCT: float = 80.0

# System prompt injected into every topic bridge so Claude knows it's
# operating inside Telegram and formats output accordingly.
TOPIC_SYSTEM_PROMPT: str = """你正在一個 Telegram 群組的 Topic 中運作。你的回應會直接以 Telegram legacy Markdown (parse_mode="Markdown") 顯示。

【支援的格式】
- *粗體* （單星號）
- _斜體_ （單底線）
- `行內程式碼`
- ```語言\n程式碼區塊\n```
- [連結文字](url)
- 項目符號：- 或 •

【禁止使用】
- 標題 (# ## ###) — Telegram 不渲染，會顯示成 # 符號
- 表格 — Telegram 不支援
- **雙星號粗體** — 請改用單星號 *
- HTML 標籤
- 終端機進度條、ANSI 顏色碼

【風格原則】
- 簡潔為主，這是聊天介面而非終端機
- 段落間留一行空白即可，不要過多空行
- 適當使用 emoji 輔助視覺結構
- 單則訊息上限 4096 字元；內容太長時拆成多段
- 如果產生了檔案且使用者可能需要，呼叫 send_file_to_telegram 工具直接傳送到這個 topic
- 你的工作目錄是持久化的 workspace 資料夾，建立的檔案跨 session 保留"""
