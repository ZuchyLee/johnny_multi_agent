# cc-topic-orchestrator 專案說明

## 服務啟動與重啟

### 正常重啟（不需殺程序）

```bash
touch /tmp/bot.restart
```

`watchdog.py` 每 2 秒偵測 `/tmp/bot.restart` 的修改時間，偵測到變更後自動 SIGTERM + 重啟 bot。

### 首次啟動 / watchdog 未在執行時

```bash
cd /Users/lizhaocheng/src/cc-topic-orchestrator
nohup .venv/bin/python watchdog.py > /tmp/watchdog.log 2>&1 &
```

watchdog 啟動後會自己起 bot，**不要再手動啟動 run.py**，否則會出現 409 Conflict。

### 查看 log

```bash
tail -f /tmp/bot.log        # bot log
tail -f /tmp/watchdog.log   # watchdog log
```

### 完全停止

```bash
pkill -f watchdog.py && pkill -f run.py
```

---

## 程序關係

```
watchdog.py (長期存活)
  └─ run.py (bot 本體，由 watchdog 管理)
```

- watchdog 負責監控 bot，bot 意外退出時自動重啟
- 重啟 bot 只需 `touch /tmp/bot.restart`，watchdog 不需重啟
- 若要強制殺程序，必須先殺 watchdog，再殺 run.py（否則 watchdog 會立刻重生）

---

## 架構概要

- **每個 Telegram Forum Topic = 一個 `TopicBridge`**，持有獨立的 `ClaudeSDKClient` session
- **General topic (thread_id=0)** 是主控，掛載 `master_tools.py` 的 MCP 工具（建立/廣播 topic）
- **Registry** (`registry.db`) 儲存 topic ↔ folder ↔ session_id ↔ model
- 工具授權：`AUTO_ALLOW_TOOLS`（Read/Edit/Write 等）自動放行；其他工具發 Telegram 按鈕等待使用者同意

## 常用路徑

- Bot entry: `run.py`
- Watchdog: `watchdog.py`
- Topic bridges: `orchestrator/bridge.py`
- Handlers: `orchestrator/handlers.py`
- Registry DB: `registry.db`
- Workspaces: `workspaces/<slug>/`
- Bot log: `/tmp/bot.log`
- Watchdog log: `/tmp/watchdog.log`
- 重啟觸發檔: `/tmp/bot.restart`
