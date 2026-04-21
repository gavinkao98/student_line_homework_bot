# LINE Homework Bot

一位老師 ↔ 一位學生的作業派發與追蹤機器人，運行於 LINE 官方帳號。

## 功能

- 老師在 LINE 輸入 `/assign <內容>` 登錄今日作業
- 每日 19:00（台北時區）自動 push 作業 Flex Message 給學生（含「✅ 完成」按鈕）
- 學生點按鈕回報完成 → 回覆確認 + 通知老師
- 學生傳照片 → 綁定到今日作業 → 通知老師
- 21:00 未完成的作業會發提醒（每日最多一次）
- 老師可查 `/today`、`/history`、`/history N`、`/pending`、`/whoami`、`/help`

完整規格請看 `line-homework-bot-plan.md`。

## 本地開發

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env   # 填入自己的 token
alembic upgrade head
uvicorn app.main:app --reload
```

打 `curl http://localhost:8000/health` 會回 `{"ok": true}`。

### 跑測試

```bash
pytest -q
```

### 本地接 LINE webhook

1. 到 [LINE Developers Console](https://developers.line.biz/) 建 Messaging API channel，取得 channel secret + access token。
2. 關閉 Auto-reply / Greeting（Messaging API 頁籤下方）。
3. 本地 `uvicorn app.main:app --reload`。
4. 另開一個終端 `ngrok http 8000`，拿到 `https://xxxx.ngrok-free.app`。
5. 把 `https://xxxx.ngrok-free.app/callback` 填到 LINE console 的 Webhook URL。
6. 手機把官方帳號加好友，傳 `/whoami` 拿到 User ID，寫回 `.env` 的 `TEACHER_USER_ID` 與 `STUDENT_USER_ID`，重啟服務。

## 部署到 Fly.io

```bash
fly launch --no-deploy
fly volumes create data --size 3
fly secrets set \
  LINE_CHANNEL_ACCESS_TOKEN=xxxx \
  LINE_CHANNEL_SECRET=xxxx \
  CRON_SECRET=$(openssl rand -hex 16) \
  TEACHER_USER_ID=Uxxx \
  STUDENT_USER_ID=Uxxx
fly deploy
```

部署完把 `https://<app>.fly.dev/callback` 回填到 LINE console 的 Webhook URL，按 **Verify**。

## 排程

部署 GitHub Actions（`.github/workflows/cron.yml`）前，先設兩個 secrets：

- `APP_URL` — 例如 `https://line-homework-bot.fly.dev`
- `CRON_SECRET` — 與 fly secrets 的 `CRON_SECRET` 相同

排程時間：

| UTC cron | 台北時間 | 行為 |
|---|---|---|
| `0 23 * * *` | 07:00 | push 今日作業 |
| `0 13 * * *` | 21:00 | 未完成則提醒 |

可手動觸發：GitHub Actions → Cron → Run workflow。

## 專案結構

```
app/
├── main.py              # FastAPI entry
├── config.py            # pydantic-settings
├── db.py                # SQLAlchemy engine / session
├── models.py            # ORM models
├── line_client.py       # LINE SDK wrapper
├── messages.py          # Flex / text message builders
├── cron.py              # /cron/* endpoints
├── handlers/
│   ├── webhook.py       # /callback + role dispatch
│   ├── teacher.py       # teacher command handler
│   ├── student.py       # student message / postback handler
│   └── commands.py      # command parser
├── services/
│   ├── assignment.py    # business logic
│   └── photo.py         # photo download / save
└── logging.py           # structlog config
alembic/                 # DB migrations
tests/                   # pytest suite
```

## 故障排除

- **Webhook Verify 失敗** — 檢查 `LINE_CHANNEL_SECRET` 是否與 console 一致；fly logs 看 `webhook_bad_signature`。
- **Cron 401** — `X-Cron-Token` 要與 `CRON_SECRET` 完全相同，注意尾部換行。
- **學生沒收到作業** — 檢查 `/cron/push-assignment` 回應；若 `reason: no_student_id`，表示 `STUDENT_USER_ID` 未設。
- **照片沒存到** — 確認 Fly volume 有 mount 到 `/data`，`PHOTO_DIR=/data/photos` 有權限寫入。
