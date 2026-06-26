# 🐱 Neko Downloader

內部使用的網路影片下載工具。貼上一行影片連結，系統自動判斷下載方式 —— 支援原始 `.m3u8` 串流（自動帶上 `Origin` / `Referer` 等標頭）以及 yt-dlp 涵蓋的上千個影音平台。檔案只暫存在磁碟上的暫存目錄，使用者取走、逾時或服務重啟後立即清除，伺服器不長期保留任何資料。

> ⚠️ 概念驗證階段的內部工具：無帳號系統、無認證，請勿直接暴露於公開網路。

## 功能

- **一行連結即可下載**：自動偵測來源類型，選擇對應的下載策略
- **`.m3u8` (HLS) 支援**：自動推導 `Origin`/`Referer`（可手動覆寫），ffmpeg 合併為 mp4
- **多平台支援**：YouTube、Facebook、X (Twitter)、TikTok、Bilibili… 凡 yt-dlp 支援的平台皆可；需要登入的內容可透過 `COOKIES_FILE` 帶入瀏覽器 cookies
- **瀏覽器嗅探回退**：遇到 yt-dlp 不認識的網頁，自動以無頭瀏覽器（Playwright + Chromium）載入頁面、攔截網路流量找出真正的媒體串流（m3u8/mpd/mp4）與其標頭後下載 —— 貼一般網頁連結也能用
- **反爬蟲規避**：下載一律以真 Chrome 的 TLS/HTTP2 指紋連線（curl_cffi impersonate，過 Cloudflare 等 JA3 指紋封鎖）；嗅探用的無頭瀏覽器會抹除 `navigator.webdriver`、補上 languages/plugins/WebGL 等特徵，降低被 bot 偵測擋下的機率
- **不長期保留**：下載暫存於磁碟暫存目錄，使用者取走後、TTL 逾時或服務重啟時自動刪除（每次啟動會清空暫存目錄）
- **佇列系統**：限制並行下載數，WebSocket 即時推送佇列狀態、進度、速度與 ETA
- **審查日誌**：所有任務事件（提交/完成/取走/失敗…）以 JSON Lines 寫入可輪替的稽核日誌，含來源 IP
- **現代化介面**：Vue 3 + Tailwind 深色單頁應用，附貓咪 favicon 🐱

## 快速開始（Docker）

```bash
docker compose up --build -d
```

開啟 <http://localhost:8000> 即可使用。

### macvlan 部署（容器取得獨立區網 IP）

想讓服務以獨立 IP 出現在內網（不佔用宿主機的埠），改用 macvlan 版 compose：

```bash
cp .env.example .env
# 編輯 .env 中的 MACVLAN_PARENT / MACVLAN_SUBNET / MACVLAN_GATEWAY / MACVLAN_IP
docker compose -f docker-compose.macvlan.yml up --build -d
```

之後從區網其他裝置開啟 `http://<MACVLAN_IP>:8000`。

> macvlan 先天限制：**宿主機本身無法直接連到容器的 macvlan IP**，請從其他裝置存取；若宿主機也要連，需另建宿主機端的 macvlan bridge interface。`MACVLAN_IP` 請選在 DHCP 派發範圍之外，避免 IP 衝突。

## 直接安裝在主機（不用 Docker）

需求：Python 3.11+、Node.js 20+（建置前端用）、ffmpeg。

```bash
# 1. 一次性安裝（venv、相依、無頭 Chromium、前端建置）
./scripts/setup.sh

# 2a. 前景執行（開發/試用）
./scripts/start.sh

# 2b. 或安裝為 systemd 服務（開機自動啟動）
sudo ./scripts/install-service.sh            # 預設以 sudo 呼叫者的身分執行
sudo ./scripts/install-service.sh someuser   # 或指定其他使用者
```

服務管理：

```bash
systemctl status neko-downloader      # 狀態
journalctl -u neko-downloader -f      # 日誌
sudo systemctl restart neko-downloader
# 移除服務
sudo systemctl disable --now neko-downloader
sudo rm /etc/systemd/system/neko-downloader.service
```

設定一樣走 `.env` / `config.json`（見上方「設定」章節）。systemd 版以 `PrivateTmp=yes` 給服務一個獨立的 `/tmp`（落在磁碟、服務停止即清空），暫存目錄 `/tmp/neko_dl` 即放在其中；服務啟動時也會主動清空暫存目錄。若自訂 `TMP_DIR` 到 `/tmp` 以外，請在 service 範本補上對應的 `ReadWritePaths`，並避開家目錄（服務以 `ProtectHome=read-only` 執行）。

## 架構

```
瀏覽器 ── POST /api/jobs ──▶ FastAPI ──▶ asyncio 佇列（N 個 worker）
   ▲                                          │
   │◀── WebSocket /ws（進度/狀態推播）◀────────┤
   │                                          ▼
   │                              Handler 註冊表（策略模式 + 失敗自動回退）
   │                              ├─ M3u8Handler   (.m3u8 → yt-dlp + ffmpeg)
   │                              ├─ YtDlpPlatformHandler (上千個平台)
   │                              └─ BrowserSniffHandler (無頭瀏覽器嗅探，最後防線)
   │                                          │
   └◀── GET /api/jobs/{id}/download ◀── 磁碟暫存（取走/逾時/重啟即刪）
```

任務狀態機：

```
queued → downloading → processing → ready → done（已取走）
                          ↘ failed / cancelled / expired
```

## 設定

設定來源優先序（高者覆蓋低者）：

```
環境變數  >  .env  >  config.json  >  程式預設值
```

從範例檔建立自己的設定（擇一即可，`.env` 為建議方式，docker compose 會自動讀取）：

```bash
cp .env.example .env                  # 環境變數風格
# 或
cp config.example.json config.json    # JSON 風格
```

`.env` / `config.json` 放在專案根目錄或 `backend/` 皆可，且已被 git / docker build 忽略，不會被提交或打包進 image。

| 設定（.env / config.json） | 預設 | 說明 |
|---|---|---|
| `MAX_CONCURRENT` / `max_concurrent` | `2` | 同時下載的任務數 |
| `MAX_QUEUE_SIZE` / `max_queue_size` | `50` | 佇列上限，滿了回 429 |
| `FILE_TTL_SECONDS` / `file_ttl_seconds` | `1800` | 完成檔案的保留秒數，逾時自動刪除 |
| `CLEANUP_INTERVAL_SECONDS` / `cleanup_interval_seconds` | `60` | 清理排程的掃描間隔（秒） |
| `SNIFF_TIMEOUT_SECONDS` / `sniff_timeout_seconds` | `20` | 瀏覽器嗅探等待媒體請求出現的上限（秒） |
| `COOKIES_FILE` / `cookies_file` | （空） | Netscape 格式 cookies 檔，抓需要登入的內容用 |
| `COOKIES_FROM_BROWSER` / `cookies_from_browser` | （空） | 直接讀本機瀏覽器登入狀態，如 `firefox`、`chrome:Profile 1`（`COOKIES_FILE` 優先） |
| `AUDIT_LOG_FILE` / `audit_log_file` | `logs/audit.log` | 審查日誌路徑（相對於 `backend/`），空字串停用檔案輸出 |
| `TMP_DIR` / `tmp_dir` | `/tmp/neko_dl` | 容器內暫存目錄（compose 已把 host `/var/tmp/neko_dl` 掛進來；啟動時會清空） |
| `PORT` / `port` | `8000` | 服務埠 |

> **暫存放磁碟，不放 RAM**：早期版本把暫存掛在 tmpfs（記憶體），但長影片放不下 —— 合併成 mp4 的最後一步
> （ffmpeg remux）會在同一個檔案系統上同時存在「下載檔 + 輸出檔」兩份，尖峰約為檔案的兩倍，一支 5.5GB 影片就要
> ~12GB，遠超一般機器的 RAM。現在 compose 預設把 host 的 **`/var/tmp/neko_dl`** 掛進容器：`/var/tmp` 是磁碟、
> 而且 Rocky Linux 的 `systemd-tmpfiles` 本來就會定期清（預設 30 天），所以萬一容器硬當機留下檔案，**作業系統會
> 自己回收**，不需要額外設定。正常情況下檔案在取走/逾時/失敗時就刪、每次啟動也會清空暫存目錄，根本不會留到 30 天。
> 請確認 `/var/tmp` 所在磁碟**有足夠空間**：約「最大預期影片大小 **× 2**（remux 尖峰）× MAX_CONCURRENT」。空間不夠時
> 長影片會在 `processing` 階段失敗、`job.error` 出現 `No space left on device`（ffmpeg 對外只印泛泛的
> `Conversion failed!`，但真因已一併記到 `job.error` / 審查日誌）。
>
> 掛載已加 `:Z`（SELinux relabel）讓 rootless Podman / Rocky 的 SELinux enforcing 下容器寫得進去。若機器 RAM
> 夠大、堅持用記憶體，compose 裡留有 `tmpfs` 的註解可切換回去。

### 社群平台（Facebook / X / TikTok）

公開貼文直接貼連結即可（由 yt-dlp 的官方解析器處理）。需要登入才能看的內容，提供 cookies 的方式擇一：

#### 方式一：直接在網頁介面貼上 Cookie（最簡單，逐次使用）

展開首頁的「進階選項」，把 cookie 貼進輸入框即可——支援原始字串
（`sessionid=abc; auth=xyz`，從瀏覽器開發者工具的 Network → 任一請求 → Request Headers
的 `Cookie` 複製最方便）或 Netscape 格式。

這個 cookie **只存在你當下的瀏覽器分頁**（sessionStorage），關閉分頁即自動清除；
送出下載時才隨該次任務傳給伺服器，伺服器寫成 tmpfs 暫存檔供 yt-dlp 使用、下載一結束
立即刪除，全程不落地、不寫入審查日誌、不回傳給其他使用者。適合臨時、個人、不想在
伺服器留設定的情境。

> 優先序：網頁貼上的 cookie ＞ 伺服器端設定（下列方式二～五）＞ 無權限下載。
> 也就是說即使伺服器沒設定任何 cookie，使用者仍可自備；反之伺服器有設定時，
> 個別使用者也能用自己的 cookie 覆蓋。

以下方式二～五是在**伺服器端**設定 cookie（對所有未自備 cookie 的請求生效）：

#### 方式二：互動式登入產生（不需要擴充功能）

```bash
./scripts/get-cookies.sh facebook        # 或 x / tiktok / instagram / youtube / bilibili
./scripts/get-cookies.sh tiktok -o my-cookies.txt
./scripts/get-cookies.sh https://example.com/login   # 任意網站登入頁
```

會開啟一個乾淨的 Chromium 視窗，登入完成後回終端機按 Enter，cookies 自動匯出成
`cookies.txt`（Netscape 格式，權限自動設為 600）。接著設定 `COOKIES_FILE` 指向它。
此工具需要圖形介面，請在桌面電腦執行後把檔案帶到部署機。

#### 方式三：直接讀取本機瀏覽器（零操作，僅限主機直裝）

```bash
# .env
COOKIES_FROM_BROWSER=firefox        # 或 chrome / edge / brave / chromium…
COOKIES_FROM_BROWSER=chrome:Profile 1   # 指定 profile
```

yt-dlp 會在每次下載時直接讀取該瀏覽器目前的登入狀態，免匯出、不會過期。
限制：瀏覽器要裝在跑本服務的同一台機器上（Docker 容器內沒有瀏覽器 profile，不適用）。

#### 方式四：瀏覽器擴充功能

用擴充功能（如「Get cookies.txt LOCALLY」）匯出已登入帳號的 cookies，再設定 `COOKIES_FILE`。

#### 方式五：自己開瀏覽器手動尋找

完全不裝任何工具，打開瀏覽器開發者工具（F12 → Application/Storage → Cookies）把登入
cookies 抄出來、手寫成 `cookies.txt`。各平台要抄哪幾個 cookie、Netscape 格式怎麼寫、
常見陷阱，詳見 **[手動取得 Cookies 指南](docs/COOKIES.md)**。

> Docker 部署使用 cookies 檔時記得掛進容器：`volumes: - ./cookies.txt:/srv/cookies.txt:ro`
> 並設 `COOKIES_FILE=/srv/cookies.txt`。
> 平台會頻繁改版／加強反爬蟲，失敗時優先更新 yt-dlp（重建 image 或 `pip install -U yt-dlp`）。

## 審查日誌

所有任務生命週期事件都會以 JSON Lines 格式寫入 `backend/logs/audit.log`（自動輪替，10MB × 5 份；Docker 部署掛載到宿主機 `./logs/`），同時輸出到 stdout（`docker logs` / `journalctl` 也查得到）。事件包含：

| 事件 | 記錄內容 |
|---|---|
| `job_submitted` | URL、來源 IP、自訂 referer |
| `job_ready` | 使用的 handler、標題、檔名、大小 |
| `file_downloaded` | 取走檔案的 IP、檔名、大小 |
| `job_failed` / `handler_failed` | 失敗原因（含回退鏈中每個 handler 的錯誤） |
| `job_cancelled` / `job_cancel_requested` / `job_expired` / `job_rejected_queue_full` | 對應細節 |

查詢範例：

```bash
# 某個 IP 抓走了哪些檔案
jq 'select(.event == "file_downloaded" and .client == "192.168.1.42")' logs/audit.log
# 今天所有失敗的任務
jq 'select(.event == "job_failed")' logs/audit.log
```

## API

| Method | Path | 說明 |
|---|---|---|
| `POST` | `/api/jobs` | `{"url": "...", "referer": "..."(選填)}` → 建立任務 |
| `GET` | `/api/jobs` | 所有任務列表 |
| `GET` | `/api/jobs/{id}` | 單一任務狀態 |
| `DELETE` | `/api/jobs/{id}` | 取消進行中任務／移除已結束任務 |
| `GET` | `/api/jobs/{id}/download` | 下載完成的檔案（取走後即刪除） |
| `WS` | `/ws` | 即時推播：`queue_snapshot`、`job_update`、`job_removed` |

範例：

```bash
curl -X POST localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"}'
```

## 本地開發

```bash
# 後端（需要系統已安裝 ffmpeg）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # 瀏覽器嗅探用的無頭 Chromium
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端（另開終端機；dev server 會 proxy /api 與 /ws 到 :8000）
cd frontend
npm install
npm run dev        # 開發模式 http://localhost:5173
npm run build      # 產出到 backend/static，由後端直接 serve
```

## 擴充新格式（Handler 架構）

下載核心採策略模式，佇列／API／前端與格式完全解耦。worker 會依註冊順序嘗試**所有** `can_handle()` 為真的 handler，前一個失敗自動換下一個（這也是瀏覽器嗅探作為最後防線的機制）。新增格式只需兩步：

1. 在 `backend/app/handlers/` 新增一個 handler：

```python
# backend/app/handlers/mpd.py
from .base import DownloadHandler
from ..models import Job, DownloadContext, DownloadResult

class MpdHandler(DownloadHandler):
    name = "dash"

    def can_handle(self, url: str) -> bool:
        return url.split("?")[0].lower().endswith(".mpd")

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        # ctx 提供：output_dir、headers（已推導 Origin/Referer）、
        # on_progress() 進度回呼、check_cancelled() 取消檢查
        ...
```

2. 在 `backend/app/handlers/__init__.py` 註冊（順序即優先序，catch-all 放最後）：

```python
registry.register(MpdHandler())
```

若新格式 yt-dlp 本身就支援，可直接重用 `_ytdlp_common.run_ytdlp()`，progress／取消／檔名處理都是現成的。

## 注意事項

- **更新 yt-dlp**：平台網站常改版，下載失敗時先重建 image 取得最新 yt-dlp（`docker compose build --no-cache`）。
- **Image 體積**：內含 ffmpeg 與無頭 Chromium（瀏覽器嗅探用），image 約 1.5GB；若用不到嗅探功能，可從 `requirements.txt` 移除 `playwright` 並刪掉 Dockerfile 中的 `playwright install` 步驟，系統會自動停用該 handler。
- **不長期保留**：佇列存在記憶體、暫存檔放磁碟暫存目錄；容器重啟後佇列清空、暫存目錄也會在啟動時清空（設計如此）。
- **僅限內部**：無任何認證機制，部署時請置於內網或加上反向代理的存取控制。
