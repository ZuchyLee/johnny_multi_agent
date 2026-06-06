# 每個人都需要的小助理

一個基於 Multi-Agent 架構的 Telegram 機器人框架。
每個 Telegram Forum Topic 都是一個獨立的 AI 助理，由主控 Agent 統一調度。

## 功能特色

- 每個 Topic 擁有獨立的 AI Agent、記憶與工作區
- 主控 Agent 可以建立新 Topic、廣播訊息、並讀取子 Topic 的回應來繼續對話
- 即時狀態顯示：⏳ 思考中 → 🔧 執行工具中 → 串流回應
- 工具授權確認（Allow / Deny 按鈕），回應顯示在授權按鈕之後
- 可切換 AI 模型（Opus / Sonnet / Haiku）
- 支援檔案上傳與下載
- Watchdog 自動重啟守護程序
- 啟動時自動回報所有 Topic 狀態

---

## 事前準備

在開始之前，請確認以下項目都已就緒：

**1. 一台能 24 小時運行的機器**
- 家裡的舊電腦、樹莓派、雲端 VPS 都可以
- 作業系統：macOS / Linux（Windows 未測試）

**2. Python 3.12 以上**

```bash
python3 --version
```

**3. Claude CLI（或其他相容的 AI CLI 工具）**
- 安裝：`npm install -g @anthropic-ai/claude-code`
- 登入：`claude` 並完成認證
- 確認可以正常使用後再繼續

**4. Telegram Bot Token**
- 找 [@BotFather](https://t.me/BotFather) 建立一個新 Bot
- 取得 Bot Token

**5. 一個開啟 Forum（Topics）功能的 Telegram 群組**
- 建立群組 → 設定 → 開啟「Topics」
- 將你的 Bot 加入群組，並設為管理員，勾選「管理話題」權限

---

## 安裝步驟

### 1. Clone 專案

```bash
git clone https://github.com/ZuchyLee/johnny_multi_agent.git
cd johnny_multi_agent
```

### 2. 建立虛擬環境並安裝依賴

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 設定環境變數

```bash
cp .env.example .env
```

用任何編輯器開啟 `.env`，填入以下資訊：

```
BOT_TOKEN=你從 BotFather 取得的 Token
OWNER_ID=你的 Telegram 使用者 ID
GROUP_ID=先留空，下一步取得
```

> 找不到自己的 Telegram ID？去找 [@userinfobot](https://t.me/userinfobot) 傳一則訊息，它會告訴你。

### 4. 取得 GROUP_ID

先把 `BOT_TOKEN` 和 `OWNER_ID` 填好，暫時直接啟動 bot：

```bash
.venv/bin/python run.py
```

在 Telegram 群組裡傳任意一則訊息，bot 會回覆你 `chat_id`（是負數，例如 `-1001234567890`）。
把這個數字填進 `.env` 的 `GROUP_ID`，然後用 Ctrl+C 停止。

### 5. 用 Watchdog 正式啟動

```bash
touch /tmp/bot.restart
nohup .venv/bin/python watchdog.py > /tmp/watchdog.log 2>&1 &
```

Watchdog 會自動啟動 bot，並在 bot 意外退出時自動重啟。
啟動成功後，Telegram 的 General Topic 會收到一則狀態報告訊息。

---

## 使用方式

在 Telegram 群組的 General（主控）Topic 與 bot 對話：

- 「幫我建立一個叫『研究助理』的 topic」
- 「問排程管理今天有什麼任務，整理給我」
- 「告訴所有 topic 今天是週一，大家加油」

在各 Topic 直接輸入文字，即可與該 Topic 的 AI 對話。

### 指令列表

- `/model` — 切換當前 Topic 的 AI 模型
- `/reload` — 重載當前 Topic 的 AI session
- `/reload --all` — 重載所有 Topic
- `/list` — 列出所有已建立的 Topic
- `/help` — 顯示說明

---

## 重啟 Bot

程式碼更新後，觸發重啟只需要更新觸發檔：

```bash
touch /tmp/bot.restart
```

Watchdog 每 2 秒偵測一次，偵測到變更後自動重啟 bot。

查看 bot log：

```bash
tail -f /tmp/bot.log
```

查看 watchdog log：

```bash
tail -f /tmp/watchdog.log
```

停止所有程序：

```bash
pkill -f watchdog.py && pkill -f run.py
```

---

## 開機自動啟動（macOS）

建立 launchd plist 讓 watchdog 開機自動啟動：

```bash
cat > ~/Library/LaunchAgents/com.johnny.watchdog.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.johnny.watchdog</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/johnny_multi_agent/.venv/bin/python</string>
        <string>/path/to/johnny_multi_agent/watchdog.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/watchdog.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/watchdog.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.johnny.watchdog.plist
```

---

## 專案結構

```
.
├── run.py                  # Bot 入口點
├── watchdog.py             # 自動重啟守護程序
├── config.py               # 設定讀取
├── requirements.txt
├── .env.example            # 環境變數範本
├── SETUP_PROMPT.md         # 給 AI 編輯器的安裝提示詞
├── orchestrator/
│   ├── bridge.py           # TopicBridge：管理每個 Topic 的 AI session
│   ├── handlers.py         # Telegram 訊息與指令處理
│   ├── master_tools.py     # 主控 Agent 的 MCP 工具
│   ├── permissions.py      # 工具授權系統
│   ├── registry.py         # SQLite Topic 資料庫
│   └── telegram_io.py      # 訊息發送與串流
└── workspaces/             # 各 Topic 的工作區（自動建立，不進 git）
```

---

## 常見問題

**Q: Bot 沒有辦法建立 Topic**
確認群組已開啟 Forum 模式，且 Bot 有「管理話題」的管理員權限。

**Q: 按了授權按鈕沒有反應，顯示「已逾時」**
授權請求有 5 分鐘時效，逾時後需重新發送指令。按鈕的回應現在會出現在授權訊息之後。

**Q: 切換模型後重啟 bot，模型又跑回去了**
已修復：切換模型時會自動清除 session，重啟後正確使用新模型。

**Q: 某個 Topic 的回覆延遲一輪**
已修復：bot 啟動時會自動排空 CLI 重播的舊訊息。

---

## License

MIT
