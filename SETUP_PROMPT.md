# 安裝提示詞 — 複製以下全部內容貼到你的 AI 編輯器

---

你是一個安裝助理，請幫我完整設定 **johnny_multi_agent** 這個 Telegram Multi-Agent 機器人。

請按照以下步驟執行，*每個步驟完成後再繼續*，需要我提供資訊時請暫停並詢問我。

---

## Step 1 — Clone 專案

執行：
```
git clone https://github.com/ZuchyLee/johnny_multi_agent.git
cd johnny_multi_agent
```

---

## Step 2 — 建立虛擬環境並安裝套件

執行：
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Step 3 — 詢問我以下資訊（逐一詢問，等我回答後再問下一個）

請依序問我：

1. **Telegram Bot Token**
   - 還沒有的話，去 Telegram 找 @BotFather，輸入 /newbot，照指示建立，最後會拿到一串 token

2. **你的 Telegram 使用者 ID（數字）**
   - 還不知道的話，去找 @userinfobot，傳任意訊息給它，它會回覆你的 ID

3. **你有沒有一個開啟 Forum（Topics）功能的 Telegram 群組？**
   - 如果沒有：請建立一個群組，進入群組設定，開啟「Topics」功能，然後把 Bot 加入群組並設為管理員，勾選「管理話題」權限
   - 如果有：直接繼續

---

## Step 4 — 建立 .env 設定檔

根據我的回答，建立 `.env` 檔案，內容如下（填入實際數值）：

```
BOT_TOKEN=（使用者提供的 token）
OWNER_ID=（使用者提供的 ID）
GROUP_ID=（先留空，下一步取得）
DEFAULT_MODEL=claude-opus-4-8
MASTER_MODEL=claude-opus-4-8
```

---

## Step 5 — 第一次啟動，取得 GROUP_ID

執行：
```
.venv/bin/python run.py
```

等 bot 啟動後，請我去 Telegram 群組傳任意一則訊息。
Bot 會自動回覆 `chat_id`（是負數，例如 -1001234567890）。
詢問我拿到的 chat_id 是什麼，然後更新 `.env` 的 `GROUP_ID`。
更新完後用 Ctrl+C 停止 bot。

---

## Step 6 — 用 Watchdog 正式啟動

執行以下兩行：
```
touch /tmp/bot.restart
nohup .venv/bin/python watchdog.py > /tmp/watchdog.log 2>&1 &
```

Watchdog 會自動啟動 bot，並在 bot 意外退出時自動重啟。

等待約 10 秒後，確認 Telegram 的 General Topic 是否收到啟動狀態報告訊息。
如果有收到，代表安裝成功。

---

## Step 7 — 完成！告訴我怎麼使用

安裝完成後，請告訴我：
- 如何在 Telegram 與 bot 對話
- 如何建立新的 Topic（在 General 說「幫我建立一個叫 XX 的 topic」）
- 常用指令（/model、/reload、/list）
- 如何重啟 bot（`touch /tmp/bot.restart`）

---

開始吧，先執行 Step 1。
