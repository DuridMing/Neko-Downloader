# CLAUDE.md

給在此 repo 工作的 Claude Code 的工作說明。面向使用者的完整文件在 [README.md](README.md)、
未完成事項與踩坑記錄在 [TODO.md](TODO.md)；本檔聚焦「架構心智模型、不變式、慣例、怎麼建置測試、
容易踩雷的地方」。

## 專案是什麼

Neko Downloader — 內部用的網路影片下載工具（概念驗證階段）。使用者貼一行連結，系統自動判斷
下載方式（`.m3u8`、上千個平台、Telegram 貼文、或無頭瀏覽器嗅探），完成後把檔案回傳。
**伺服器不長期儲存檔案**（暫存在磁碟，取走/逾時/重啟即刪）、有佇列與即時進度、無帳號系統
（只有一組選用的共用密碼）。封裝成 Docker，也支援直接裝在主機。

技術棧：後端 Python 3.12（Docker image）+ FastAPI + yt-dlp + ffmpeg + Playwright + Kurigram；
前端 Vue 3 + Vite + Tailwind v4；即時更新走 WebSocket。

## 核心設計：Handler 註冊表 + 失敗回退鏈（最重要的擴充點）

下載邏輯全部封裝在 `backend/app/handlers/` 的 handler 裡，**佇列／API／WebSocket／前端
對「格式」完全無知**——它們只認識抽象的 `Job`。這是專案最關鍵的擴充彈性，改動時務必維持。

- `handlers/base.py` — `DownloadHandler` 抽象介面（`can_handle()` + `download()`）與 `registry`
- `handlers/__init__.py` — 註冊順序＝優先序，catch-all 放最後
- worker（`queue.py` 的 `_run_job`）呼叫 `registry.resolve_all(url)` 取得**所有**符合的 handler，
  **依序嘗試、前一個失敗自動換下一個**。這就是瀏覽器嗅探當「最後防線」的機制。

目前的 handler（優先序由高到低，見 `handlers/__init__.py`）：

| # | 檔案 / 類別 | 負責 |
| --- | --- | --- |
| 1 | `myfans.py` `MyfansHandler` | myfans.jp 貼文，直接打其 API，用使用者的 token |
| 2 | `telegram_handler.py` `TelegramHandler` | `t.me/<頻道>/<訊息id>` 單則貼文，走 MTProto |
| 3 | `m3u8.py` `M3u8Handler` | `.m3u8`/`.m3u`，走 `_hls_png.run_hls()`，注入推導的 Origin/Referer |
| 4 | `direct_stream.py` `DirectStreamHandler` | `.mpd`/`.mp4`… 直連 CDN，保留推導的 Origin/Referer |
| 5 | `ytdlp_platform.py` `YtDlpPlatformHandler` | catch-all，yt-dlp 內建上千平台解析器（含 FB/X/TikTok） |
| 6 | `browser_sniff.py` `BrowserSniffHandler` | 無頭 Chromium 載入網頁、攔截流量找出真正的媒體串流與標頭 |

`browser_sniff` 在 Playwright 沒裝時自動停用（`__init__.py` try/except import）。

**新增格式只需**：在 `handlers/` 加一個 handler 檔、在 `__init__.py` 註冊。若 yt-dlp 本身支援，
直接重用 `_ytdlp_common.run_ytdlp()`（progress／取消／cookie／檔名處理都現成）。

兩個共用模組（底線開頭＝不是 handler，是工具）：

- `_ytdlp_common.py` — `run_ytdlp()`、`derive_stream_headers()`、`cookie_opts()`、
  `write_cookiefile()`、`BROWSER_UA`、curl_cffi impersonate 目標
- `_hls_png.py` — `run_hls()`：處理兩種 yt-dlp 搞不定的 HLS：**PNG 偽裝的 TS segment**
  （自己抓、逐段剝前綴、concat 後 ffmpeg remux）與 **AES-128 加密**（自己驅動 ffmpeg 並解析
  `-progress` 回報真實進度）。兩種都不符合就退回 yt-dlp native HLS。細節見 TODO.md 的案例記錄。

## 資料流與檔案地圖

```text
POST /api/jobs ─▶ JobQueue.submit ─▶ asyncio.Queue（上限 MAX_QUEUE_SIZE）
                                       │ N 個 worker（MAX_CONCURRENT）
                                       ▼
            _run_job：依序試 handler → 下載在 to_thread 執行（同步阻塞）
                                       │ progress 經 call_soon_threadsafe 回主迴圈
                                       ▼
            WebSocket 廣播 job_update ◀─┘   檔案落在 TMP_DIR/<job_id>/（磁碟暫存，啟動時清空）
                                       ▼
GET /api/jobs/{id}/download ─▶ FileResponse 串回 ─▶ BackgroundTask: mark_done → 刪檔
```

後端 `backend/app/`：

- `main.py` — FastAPI 組裝、lifespan（啟動 worker + 清理排程）、存取密碼 middleware、
  serve `backend/static/` 前端
- `config.py` — pydantic-settings；**唯一設定檔是 `.env`**（環境變數 > .env > 預設）
- `auth.py` — 共用密碼閘門（見下方專節）
- `models.py` — `Job`、`JobStatus`、`JobCreate`、`DownloadContext`、`DownloadResult`、
  `CancelledByUser`、`NeedsSelection`（皆無格式知識）
- `queue.py` — `JobQueue`：佇列、worker、取消、TTL 清理、cookie 暫存檔生命週期
- `api.py` — REST 路由 + `/ws`（含 websocket 的密碼檢查）
- `ws.py` — WebSocket 連線管理與廣播
- `audit.py` — 審查日誌（JSON Lines，RotatingFileHandler）
- `handlers/` — 見上一節（`telegram_handler.py` 刻意跟 `telegram/` 套件區隔命名）
- `telegram/` — MTProto 分支（見下方專節）

前端 `frontend/src/`：

- `App.vue` — 外殼（sticky header、連線狀態、設定齒輪）；`locked` 時整個換成 `LockScreen.vue`
- `components/` — `UrlForm`、`QueueList`、`JobCard`、`AppSheet`（共用彈窗）、`SettingsSheet`、
  `TelegramLoginSheet`、`LockScreen`
- `composables/` — `useApi`（共用 `request()` + `locked` 狀態）、`useWebSocket`（連線+自動重連+
  reactive store）、`useTelegram`（狀態與登入動作）、`useCookies`（sessionStorage 共用值）
- `style.css` — 唯一的設計來源（見「前端」專節）

任務狀態機：`queued → downloading → processing → ready → done`，
旁支 `needs_selection`（嗅探到多個候選、等使用者選）與 `failed / cancelled / expired`。

## 重要不變式（改動時別破壞）

- **格式無關**：queue/api/ws/前端不得出現特定格式的判斷；格式邏輯只能在 handler 裡。
  Telegram 的 flood-wait 重試也因此留在 handler，不進 `queue.py`。
- **不長期持久化**：job 全存記憶體 dict，重啟即清空（設計如此）。檔案放磁碟暫存目錄（非 tmpfs ——
  長影片 ffmpeg remux 尖峰約 2× 檔案大小，RAM 撐不住），取走/逾時/失敗即刪，且 `JobQueue.start()`
  啟動時清空 TMP_DIR 維持「重啟＝乾淨」。別把暫存改回 RAM-only 預設。
- **敏感資料不外洩**：`Job.public_dict()` 必須排除 `file_path`、`cookies`、`selected`，
  candidates 只露 url/kind/size（擷取到的 headers 含 Cookie）。API 回應、WebSocket 廣播、
  審查日誌都只能用 public 視圖；cookie 值、手機號碼、驗證碼、密碼**絕不**進日誌。
- **同步阻塞的下載包在 `asyncio.to_thread`**；progress/cancel 透過 `DownloadContext` 的回呼橋接，
  cancel 用 flag + 下載迴圈內檢查。跨執行緒回主迴圈一律 `loop.call_soon_threadsafe`。

## 存取密碼（`auth.py`）

`settings.access_password` 不是 `NONE`（也不是空字串）時：

- `main.py` 的 HTTP middleware 擋下所有 `/api/*`（`/api/unlock` 除外）。
- **`/ws` 由 `api.py` 的 endpoint 自己再檢查一次** —— Starlette 的 HTTP middleware 看不到
  websocket，這段不能刪。
- 靜態檔不擋，否則沒有頁面可以輸入密碼。
- cookie 值是 `HMAC(密碼, "neko-v1")`：無狀態、重啟不掉、改密碼即全失效；`HttpOnly`、
  30 天、只有在 https 下才加 `Secure`（否則明文 LAN 上 cookie 會被瀏覽器丟掉）。
- 密碼比對用 `hmac.compare_digest`，錯誤時 sleep 1 秒並記 `unlock_failed`（含 IP）。
- `NONE`／留空＝完全不驗證，是**刻意保留的向後相容行為**，不要改成強制。哨兵值用 `NONE` 而不是
  註解掉整行，是為了讓這個安全開關在設定檔裡看得見（`auth.DISABLED`）。

前端所有請求走 `composables/useApi.js` 的 `request()`，401 就把 `locked` 打開換成 `LockScreen.vue`；
解鎖成功後直接 `location.reload()`（WebSocket / 佇列 / Telegram 狀態本來就都要重抓）。

擋不住的：HTTP 明文下能側錄流量的人一樣拿得到密碼。macvlan 部署時容器有自己的區網 IP，
外部反向代理擋不住直連容器。

## Cookie 處理（四層優先序）

`_ytdlp_common.cookie_opts(cookiefile)` 決定 yt-dlp 用哪個 cookie 來源，優先序：

1. **使用者瀏覽器在網頁貼上的 cookie**（每次任務）— 前端存 `sessionStorage`（關閉分頁即清），
   隨 `POST /api/jobs` 的 `cookies` 欄位傳來；`_run_job` 寫成 `TMP_DIR/<job_id>/_cookies.txt`
   （權限 600），下載結束在 `finally` 立即刪除，記憶體副本寫檔後即清空
2. 系統 `COOKIES_FILE`（Netscape 檔）
3. 系統 `COOKIES_FROM_BROWSER`（如 `firefox`、`chrome:Profile 1`，僅主機直裝）
4. 都沒有 → 無權限（匿名）下載

`write_cookiefile()` 同時接受原始 `name=value; ...` 字串（綁到 URL 網域）或 Netscape 格式。
myfans 的 token 也走這個欄位（`_mfans_token=<值>`），由 `myfans.py` 自己解析出來打它的 API。
使用者指南在 [docs/COOKIES.md](docs/COOKIES.md) 與 [docs/MYFANS.md](docs/MYFANS.md)；
輔助腳本 `scripts/get-cookies.sh`（包 `get-cookies.py`）。

## Telegram 分支（`backend/app/telegram/`）

以使用者本人的帳號走 MTProto（Kurigram，import 名仍是 `pyrogram`）。硬規則，別破壞：

- **絕不自動加入頻道**：`TelegramSource` 上不存在 join/invite 方法，`test_telegram_seam.py` 會擋下
  任何 `join_chat(` / `JoinChannel(` / `ImportChatInvite(` 的呼叫。頻道由使用者自己在正式客戶端加入。
- **library 只能出現在 `*_source.py`**：`types.py` / `source.py` / `index.py` / `weblogin.py`
  不得 import pyrogram/kurigram/telethon（同樣由 seam 測試把關）。Telethon 已封存、Pyrogram 已無人
  維護，換 library 只該寫一個新 adapter。
- **session 檔＝帳號完整存取權**：`backend/.secrets/`，目錄 0700、檔案 0600，不進日誌／API／備份，
  也絕不能放在 `TMP_DIR`（開機會清空）。`.env.example` 裡的 api_id/api_hash/密碼必須維持註解狀態（有測試檢查）。
- 索引只讀 metadata（`TgIndex` 記憶體字典，重啟即空，與 `JobQueue.jobs` 同調）；下載才碰 bytes。
- FloodWait 是節流不是失敗：`TelegramHandler` 用一把 process 級 `_account_lock` 序列化所有 Telegram
  下載，遇到 flood wait 就抱著鎖等過去再重試（>300 秒才放棄）。
- `parse_ref()` 在 `types.py`（純字串處理，不能放在 adapter，因為 adapter 是選用 import）：
  回傳 `(peer, message_id)`。貼文連結 `t.me/<頻道>/<id>` 預設只掃那一則。
- 檔名是不可信輸入：`download_media()` 只取 basename，否則頻道可以用 `../..` 寫到 dest_dir 外面。

模組職責：

| 檔案 | 職責 |
| --- | --- |
| `types.py` | domain 型別、例外、`parse_ref()`。不得碰 library |
| `source.py` | `TelegramSource` 抽象介面（seam） |
| `kurigram_source.py` | 唯一允許 import pyrogram 的檔案 |
| `index.py` | `TgIndex` 記憶體索引（metadata、去重、水位） |
| `weblogin.py` | 把 seam 的阻塞式 `ask_code/ask_password` 接到 HTTP 三段式登入 |
| `__init__.py` | `build_source()`、`status()`（含帳號快取）、選用 import 的 AVAILABLE 旗標 |

登入有兩條等價路徑：`scripts/telegram-login.py`（CLI）與網頁設定面板
（`POST /api/telegram/login` → `/login/verify`，一次只允許一組）。網頁登入代表手機號碼／驗證碼／
兩步驟密碼會經過 HTTP，所以 `ACCESS_PASSWORD` 更該設。登入／刪除 session 前會擋
`telegram_handler.is_busy()`，避免兩個 client 同時寫 session 檔。

## 前端（Apple HIG 風格，改動時請維持）

- `style.css` 是唯一的設計來源：色票用 CSS 變數（`--c-*`）定義一次，`@media (prefers-color-scheme: dark)`
  覆寫，再用 `@theme inline` 對應成 Tailwind utility。**不要在元件裡寫 `dark:` 前綴**，
  也不要硬編十六進位色；新顏色先加變數。
- 用 Apple 系統色（system blue/green/red/orange）與 SF 字級（`text-footnote/subhead/body/title3/large`）。
  顏色只用來表達語意（藍＝進行中、綠＝可取走、紅＝壞了），其餘交給 label / label-2 / label-3 三階灰。
- `.btn` / `.field` / `.card` 是 `@utility`，元件只組合它們。回饋放在 `:active`（縮放）而非 hover。
- 全域 `:focus-visible` 規則刻意寫成 `:not(.field)`：未分層的 CSS 會贏過 Tailwind 的
  `@layer utilities`，不排除就會在輸入框上畫出雙層藍框。
- 彈出視窗一律用 `AppSheet.vue`（Teleport＋scrim＋Esc 關閉＋鎖背景捲動；手機貼底、桌機置中）。
  Telegram 驗證就是疊在設定 sheet 之上的第二層 sheet。
- 錯誤訊息一律翻成白話：`JobCard.vue` 的 `ERROR_HINTS`、`TelegramLoginSheet.vue` 的
  `ERROR_HINTS`（Telegram 原始錯誤碼）。對不到的原文照顯示，不要吞掉。
- 已顧到 `prefers-reduced-motion` 與 `prefers-reduced-transparency`，別把它們改掉。

## 建置 / 執行 / 測試

### ⚠️ 本機工具鏈不在 PATH（重要）

這台開發機沒有 `node`/`npm`/`docker`/`ffmpeg` 在 PATH，且不用 sudo。可用副本在 `~/.local/opt/`：

```bash
export PATH="$HOME/.local/opt/node-v22.16.0-linux-x64/bin:$HOME/.local/opt/ffmpeg-btbn/bin:$PATH"
```

- **ffmpeg 一定要用 `~/.local/opt/ffmpeg-btbn/`（BtbN build）**。另一份
  `~/.local/opt/ffmpeg`（johnvansickle static）的 ffmpeg/ffprobe **會 segfault**（處理網路 HLS
  與 MPEG-TS 時），導致 yt-dlp 後處理炸成 `Expecting value: line 1 column 1`。
- 後端 venv：`backend/.venv`（Python 3.13；Docker image 是 3.12）。
- **Docker 在本機不可用**，所以 `docker compose` 流程無法在此驗證，只能在目標機跑。

### 後端

```bash
# 安裝
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# 跑（從 repo 根；注意 --app-dir 與 ffmpeg PATH）
PATH="$HOME/.local/opt/ffmpeg-btbn/bin:$PATH" \
  backend/.venv/bin/uvicorn app.main:app --port 8000 --app-dir backend
```

### 測試

```bash
cd backend && .venv/bin/pip install -r requirements-dev.txt   # 只有測試才需要
.venv/bin/python -m pytest tests -q      # 從 repo 根跑也可以：pytest backend/tests
```

`backend/conftest.py` 負責把 `backend/` 塞進 `sys.path`，所以從哪個目錄跑都行。
測試相依（pytest / httpx / pyflakes）在 `requirements-dev.txt`，**不進 image**。
目前 79 個測試：純函式與假物件為主，加上 `test_http_gate.py` 用 FastAPI TestClient 蓋
middleware 與 `/ws` 的密碼閘門。

### 前端（build 後由後端 serve）

```bash
export PATH="$HOME/.local/opt/node-v22.16.0-linux-x64/bin:$PATH"
cd frontend && npm install && npm run build   # 產出到 backend/static/
# 開發模式：npm run dev（:5173，proxy /api 與 /ws 到 :8000）
```

### 一鍵腳本（主機直裝路徑）

`scripts/setup.sh`（裝 venv+相依+Chromium+build 前端）、`scripts/start.sh`（前景跑）、
`scripts/install-service.sh`（裝成 systemd 服務）。

### 端到端驗證的慣用招式

- 公開 HLS 測試源：`https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8`（約 488MB）
- 小檔 mp4（測 catch-all）：`https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4`
- 後端用 `run_in_background` 啟動，curl 打 `/api/jobs` 觀察狀態流轉；測完收掉背景行程、
  清 `TMP_DIR` 與 `backend/logs`
- 視覺檢查前端：用 `backend/.venv/bin/python` 跑 Playwright 截圖（專案已裝），再用 Read 看 PNG；
  淺色/深色都要看（`color_scheme="light"|"dark"`）
- 改 handler/cookie/queue 後，至少重跑一次 m3u8 + 一個平台連結，確認回退鏈與進度回報
- **不要**用真的手機號碼跑 Telegram 登入流程去「測試」；無效號碼（`+10000000000`）就能驗證
  錯誤路徑，也不要按下「刪除登入資料」的確認鍵——那會撤銷使用者真正的 session

## 部署形態

- 目標機是 **Rocky Linux + (rootless) Podman**，SELinux 多半 enforcing → bind mount 都要 `:Z`（含 logs）。
- `docker-compose.yml` — bridge，port mapping，暫存掛 host `/var/tmp/neko_dl:/tmp/neko_dl:Z`，
  logs `./logs:/srv/logs:Z`，`.env` 唯讀掛入 `/srv/.env`（不是 `env_file:`——掛載才能改完
  restart 就生效，也不會進 image 層），`backend/.secrets` 掛入（session 不進 image）。
  容器內固定監聽 8000，`PORT` 只決定 compose 發佈到宿主機的哪個埠。
  選 `/var/tmp` 是因為它在磁碟、又被 Rocky 的 `systemd-tmpfiles` 預設清理（30 天 backstop）涵蓋，
  硬當機殘檔由 OS 回收。RAM-only 的 tmpfs 寫法留註解可切換。
- `docker-compose.macvlan.yml` — 容器取得獨立區網 IP（`.env` 設 `MACVLAN_*`），掛載同上。
- 主機直裝 — systemd 服務，`PrivateTmp=yes` 給磁碟上的私有 `/tmp`（停止即清），`ReadWritePaths` 只開放 logs。
- **Dockerfile 沒有 COPY `scripts/`**：容器內沒有 CLI 登入腳本，Docker 部署只能用網頁登入。
- **Dockerfile 刻意不設定 `ENV` 調校值**（`PORT` 除外，CMD 需要）：真的環境變數優先序高於
  `.env`，內建值會讓使用者掛進來的設定被無聲忽略。

## 慣例

- 後端與前端註解用英文、面向「為什麼/約束」而非「做什麼」；面向使用者的文件（README/docs/TODO）用繁中。
- 設定一律走 `config.py` 的 `settings`，新設定要同步更新 `.env.example`（唯一的範例檔）。
- 新增 yt-dlp 相關功能前，記得 yt-dlp 是同步阻塞的，務必包 `to_thread` 且透過 ctx 回呼。
- 刻意的簡化用 `ponytail:` 註解標記，並寫出天花板與升級路徑。
- markdownlint：表格分隔列用 `| --- |`（有空格）。cookie 範例的 hard tab 是格式硬需求，**保留**。
- `.env`、`logs/`、`cookies.txt`、`.secrets/`、`/test/` 已被 git/docker 忽略，不要提交。
  `CLAUDE.md` 已納入版控（它是唯一的架構文件，clone 之後要看得到）。
