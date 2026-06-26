# TODO

活的清單。完成的打勾、有新想法直接補。面向「擴充下載能力」與「踩到的坑」。

## 🔥 進行中 / 已知問題

### conversion failed（長影片，~5h）— 真因已確認

- **現象**：長影片下載完整 30~40 分鐘後，在 postprocessing 階段炸 `Postprocessing: Conversion failed!`；
  同站的短片（~1.4GB）正常。
- **真因**：`Conversion failed!` 只是 ffmpeg stderr 的**最後一行**，真正原因被吞掉。yt-dlp 把串流
  先下載成一個大檔，ffmpeg 再 remux 成 mp4 — 這一步需要**第二份完整副本**塞在同一個 tmpfs。
  長影片放大後超過容量，ffmpeg 撞 `No space left on device`，最後印 `Conversion failed!`。
- [x] **錯誤可見性**：`_ytdlp_common.run_ytdlp` 加 `verbose + logger` 捕捉 ffmpeg stderr，失敗時把真因
      附在 `job.error`（`_ErrorCapture.tail`）。之後 log 會直接看到「No space left on device」之類訊息。
- [x] **重跑確認空間問題**：拿原本失敗的 `missav.ai/fc2-ppv-4919908` 在本機（`/tmp` 是 55G 真磁碟，
      非 tmpfs）重跑 → 檔案 **5.5GB**，remux 尖峰需 ~11GB。這在 4g tmpfs 必爆，在大磁碟則正常。
      量化證實：失敗 = tmpfs 空間不足，不是 ffmpeg/編碼問題。
- [x] **修空間 → 暫存改放磁碟（spill to disk）**。RAM 太小（本機 7.7GB），12g tmpfs 不可能，故放棄
      RAM-only。目標機是 Rocky Linux + Podman。改動：
  - [x] `docker-compose.yml` / `docker-compose.macvlan.yml`：`tmpfs` → host `/var/tmp/neko_dl:/tmp/neko_dl:Z`，
        logs 也加 `:Z`（rootless Podman / SELinux enforcing 才寫得進去）。RAM-only 寫法留註解可切換。
  - [x] 選 `/var/tmp` 而非專案內 `./neko_tmp`：`/var/tmp` 是磁碟，且被 Rocky 的 `systemd-tmpfiles` 預設
        清理（30 天 backstop）涵蓋 → **配合系統原本的自動刪除**，硬當機殘檔由 OS 回收，不必自加 tmpfiles 規則。
  - [x] systemd 範本：移除 `TemporaryFileSystem`(tmpfs)，靠 `PrivateTmp=yes` 給磁碟上私有 `/tmp`、停止即清。
  - [x] `JobQueue.start()` 啟動時 `rmtree(TMP_DIR)` 清空 —— 磁碟暫存會跨重啟存活，要主動清才維持
        「重啟＝乾淨」（RAM 本來免費給這保證）。OS 的 30 天清理只是最後防線，正常根本留不到。
  - [x] README / CLAUDE.md / `.gitignore` / `.dockerignore`：字樣與路徑同步更新。
  - [ ] **部署時**：確認 `/var/tmp` 所在磁碟有足夠空間（最大影片 ×2 × MAX_CONCURRENT），別讓它跟系統 `/` 搶爆。
- [ ] （備選，暫不做）HLS 直接用 ffmpeg 單通道下載到 mp4 省掉第二份副本 —— 但會失去 native 逐 fragment
      進度/取消，且要小心 ffmpeg build（johnvansickle 那份處理網路 HLS 會 segfault）。
- [x] 前端：失敗訊息改成白話說明 + 可展開「技術細節」（`JobCard.vue` 的 `ERROR_HINTS` 對照表，
      會把 `No space left` / 403 / 需登入 / 找不到來源 等對應成中文提示）。
- [ ] 前端：postprocessing 卡住時顯示更明確的狀態（目前 progress 停在 100% 沒有說明）。

### 其它

- [ ] `ffmpeg exited with code 183`（streamfastpro 那類）：2 秒內三個 handler 全失敗 = 串流本身死掉/
      地區封鎖。等 stderr 捕捉上線後回頭看真因，可能要加「來源失效」的友善訊息。

## 🧩 擴充：支援更多串流格式（非 m3u8）

照 handler 註冊表模式加（`handlers/` 新增檔 + `__init__.py` 註冊，優先序 = 註冊序）。

- [x] **MPEG-DASH（.mpd）+ 直接媒體檔（.mp4/.m4v/.webm/.mkv/.mov/.flv/.ts）** — 新增
      `direct_stream.py`（`DirectStreamHandler`，name=`stream`），註冊在 m3u8 之後、catch-all 之前。
      重點：catch-all 會「拔掉」Origin/Referer（對平台解析器是對的，對裸 CDN URL 是錯的），所以裸
      manifest/檔案要有自己的 handler **保留**推導出來的 headers —— 跟 m3u8 同理。webpage 內嵌的
      DASH/媒體則由 sniffer 自動辨別後一樣交給 yt-dlp。
      - [ ] DRM/Widevine 仍不支援，未來遇到要給清楚錯誤而非 silent fail（目前會走到失敗、前端顯示通用訊息）。
- [x] **加密 HLS（AES-128）+ 進度可見** — 實測源 `ppp.porn/v/3qm64o`（串流在 `bonsik.cdnlab.live`，
      `METHOD=AES-128`、金鑰偽裝成 `*.ts`）。重點踩雷：把 `#EXT-X-KEY` 丟給 yt-dlp（`hls_prefer_native`）
      時，yt-dlp 雖印 `Invoking hlsnative downloader`，**實際卻 silent 退回 ffmpeg 下載**（輸出全是 ffmpeg
      的 `size=/time=`、`crypto+https`），而 ffmpeg 的進度走它自己的 stderr、**不經 yt-dlp 的 progress_hooks**
      → 前端進度條卡在 0%（看起來像當掉，其實一直在下載）。
  - [x] **改**：`run_hls` 偵測 `METHOD=AES-128` 改成**自己驅動 ffmpeg**（`_download_ffmpeg_hls`）：
        `ffmpeg -i <m3u8> -c copy -progress pipe:1`，把 `out_time_us` 對「playlist EXTINF 加總的總時長」算出
        真實 %，逐次回報 `ctx.on_progress`；ffmpeg 自己抓金鑰解 AES。支援取消（kill process）。實測進度
        0.2%→0.8% 持續遞增、cancel 正常、輸出 h264 720p+aac 可播放。
  - [ ] 只處理 `METHOD=AES-128`（全段加密）。`SAMPLE-AES` 等仍走 yt-dlp（可能一樣卡 0%，遇到再說）。
  - [ ] 進度算法靠「總時長 × 播放速率」是線性估計；ffmpeg `-c copy` 速率夠穩,夠用。
- [ ] **MSS / Smooth Streaming（.ism/manifest）** — 少見，先觀望。
- [ ] **直播 / HLS live** — 需要「錄到停」的語意（時長/檔案上限），跟現有「下載完成」模型不同，
      要先想清楚 job 狀態機怎麼擴。
- [ ] **blob: / MSE 串流** — sniffer 目前抓不到（媒體在 JS 內組裝）。研究攔 XHR/fetch 的分段請求
      或 segment 模板。難度高，排後面。

## 🔎 sniffer 強化

### 抓到廣告而非正片（javplayer 那類「假播放器 + 點擊劫持」）— 已修

- **真因**：`javplayer.org` 用 `#clickfakeplayer` 假播放器，開頁時頁面上**只有廣告 mp4**、沒有真
  `<video>`。舊 sniffer 點 `video` 選擇器（只點到廣告）、又「拿第一個 media」，所以穩定地把 326KB
  廣告當正片回傳。點假播放器還會觸發 popunder 廣告跳轉，真播放器始終沒載入。
- [x] **A 廣告硬過濾**（`browser_sniff.py`）：`context.route` abort 廣告/追蹤網域（`AD_HOST_FRAGMENTS`，
  含 tsyndicate 這種從主 frame 注入 pre-roll 的）、`context.on("page")` 關掉 popunder、candidate 依
  「來源 frame 主網域 ≠ 頁面主網域 **且** 檔案過小」丟棄（同源 CDN 如 surrit.com 不誤殺，因為請求由
  主 frame 發出）、挑選改 playlist 優先＋同源最大。封掉 popunder 後，假播放器的點擊會落到真 handler →
  真 HLS 才載得出來。
- [x] **D 模糊時讓使用者挑**：sniffer 過濾後若仍 >1 個可信 candidate → 丟 `NeedsSelection`，job 進
  `NEEDS_SELECTION` 狀態並廣播候選（`public_dict` 只露 url/kind/size，**headers 含 cookie 不外洩**）；
  前端 `JobCard.vue` 顯示候選 chips，使用者點 → `POST /api/jobs/{id}/select` → 把選定 candidate +
  其擷取 headers 當 `job.selected` 重新入列，worker 只重跑該 handler 直接下載（省掉 worker 暫停）。
  - 驗證：javplayer 那頁現在 → 兩個真 HLS（turboviplay / turbosplayer 的 master.m3u8）讓使用者挑；
    選完正常進 downloading。自我檢查 `backend/tests/test_sniff_filter.py`（過濾/排序邏輯，含 missav
    跨網域 CDN 不誤殺）。
  - [ ] 已知限制：resume 不重建使用者 cookiefile（第一次跑就清了），靠 candidate 擷取的 Cookie header。
    若某站正片 URL 還需頁面 cookie，再把 cookiefile 生命週期延長到 selection 解決為止。
  - [ ] `AD_HOST_FRAGMENTS` 是 denylist，新廣告網路會漏（打地鼠）。frame 同源 + 大小啟發式擋跨站的，
    denylist 補同源注入的；遇到新的就補字串。

### 下載完成但影片不能播（PNG 偽裝的 TS segment）— 已修

- **現象**：javplayer 選對來源、下載完成、檔案 631MB，但 PotPlayer 打不開。`ffprobe` 顯示
  `format_name=png_pipe`、檔頭是 `89 50 4E 47`（PNG magic）——根本不是影片。
- **真因**：這站的 HLS segment 是**假 PNG 包真 TS**：`[120B 1×1 PNG][~85B 0xFF padding][真正的
  MPEG-TS，offset 205 起 0x47 週期同步]`。CDN/WAF 與 yt-dlp 都以為是 image，yt-dlp 直接把 PNG 一起
  muxed → 產出無法播放的檔。瀏覽器播放器會先剝掉前綴再餵 MSE。換 referer 沒用（四種都回 image/png）。
  segment 未加密（無 `EXT-X-KEY`），剝掉前綴後是乾淨的 H.264 1280×720 + AAC。
- [x] **修**：新增 `handlers/_hls_png.py` 的 `run_hls()`：抓 master→挑最高畫質 variant→peek 第一個
  segment，偵測到 image 前綴（找第一個週期性 0x47）就**自己抓所有 segment、逐段剝前綴、concat 成 .ts、
  ffmpeg `-c copy` remux 成 mp4**（含 progress/cancel）。非偽裝或加密的播放清單照舊退回 yt-dlp native HLS。
  `M3u8Handler` 與 sniffer 的 m3u8 candidate 都改走 `run_hls`。
  - 驗證：實際抓 4 個 segment 跑完整管線 → `ffprobe` 確認 h264 720p + aac、duration 正確、可播；
    純函式自我檢查 `backend/tests/test_hls_png.py`（offset 偵測 + master/media 清單解析）。
  - [ ] 只處理**未加密**的 PNG-TS。若日後遇到 AES-128 + PNG 前綴，得在剝前綴後再解密（yt-dlp 路徑無法
    同時做兩件事），屆時自抓 key 再 decrypt。
  - [ ] 偵測靠 peek 第一個 segment（多一個 request）。對一般 m3u8 是可接受成本；若想省，可只在 sniffer
    路徑啟用偵測、純 `.m3u8` 直貼維持 yt-dlp。先不優化。

### 偶發「辨識不到影片」（假播放器點擊不穩）— 已改善

- **現象**：同一個 javplayer 連結，有時 sniffer 回 `found no media stream`（同樣的程式碼前一次成功）。
- **真因**：假播放器被廣告 overlay 蓋住，且**需要點好幾下**（前幾下是開廣告，之後才載真 player）。舊
  sniffer 只點一次；改 `force=True` 後仍會被 overlay「搶走」座標點擊（force 只跳過 actionability 檢查，
  瀏覽器仍會對該座標做 hit-test，最上層的 overlay 收到事件）→ 真 player 沒觸發 → 零 candidate。廣告
  輪播 → 時好時壞。
- [x] **改**：每輪用 **JS `element.click()` 直接派發到元素**（繞過 overlay 的 hit-test），外加一個
  `force=True` 真指標點擊（給需要 trusted 座標的 handler）；再加 `download()` 內**整段 sniff 失敗自動
  重試一次**。實測 JS-click 版 3/3（force-click 版 2/3），通常 5~6 輪點擊後真 player 才載入，故每輪
  等 1.5s、靠 `sniff_timeout_seconds`(20s) 容納約 13 輪。
  - [ ] 仍非 100%：對抗性站本質上是機率問題（player 偶爾就是不 init / 連打同站會被節流）。真要更穩再考慮
    residential proxy、真 Chrome channel。失敗訊息已改白話引導「再送一次」。

- [x] **TLS/JA3 指紋規避**：`run_ytdlp` 全域開 curl_cffi `impersonate=chrome`，整個下載（含
      fragment）用真 Chrome 的 TLS/HTTP2 握手，過 Cloudflare 等指紋封鎖。curl_cffi 沒裝時自動退回。
- [x] **瀏覽器 stealth**：sniffer init script 從只拔 `navigator.webdriver` 擴成補 languages/plugins/
      chrome/permissions/WebGL vendor；UA 與 yt-dlp 統一（`BROWSER_UA`）；加 `locale` 與 Accept-Language；
      `--disable-dev-shm-usage` 讓 Podman 容器裡的 Chromium 不會崩。
- [x] **攔截 XHR/fetch 回傳的 JSON API**（很多站把真正的影片 URL 放在 API response 而非直接 media
      請求）。`browser_sniff._sniff` 的 `on_response` 對 **`resource_type in (xhr, fetch)`** 的回應讀 body、
      `MEDIA_URL_RE` 掃出內嵌的 m3u8/mp4（先 `\/`→`/` 還原 JSON 跳脫）。重點限制：
  - **只掃 xhr/fetch**，不掃靜態 `.js` 函式庫 —— 否則會撈到 player 函式庫的 demo URL（實測 `cdn.plyr.io`
    的 `blank.mp4` 就是這樣被誤抓）。
  - **只收同源 frame**（`_reg_domain == page_domain`）+ 跳過廣告 host + 跳過 image/video/audio body +
    body 上限 2MB，避免廣告 API 回傳 media URL 來綁架，以及讀大檔。
  - 抓出的 URL 沿用該 XHR 的 referer/cookie 當 headers。驗證：javplayer 無誤抓（它走直接請求）、單元
    測試 `test_sniff_filter.py` 蓋 JSON 跳脫/多個/非媒體三種 body。
- [ ] 多品質：目前抓到第一個 playlist 就停，沒有挑最高畫質。考慮收集全部 variant 後交給 yt-dlp 選。
- [ ] 偵測逾時可調（`sniff_timeout_seconds`），但某些站要點兩三層才出串流 — 加可選的「互動腳本」。
- [ ] 更強的反爬站：考慮 residential proxy 支援、`playwright-stealth` 套件、或真 Chrome channel
      （非 headless Chromium）。先觀望，現有 stealth 不夠再上。
- [ ] **container 注意**：Podman 裡 curl_cffi（impersonate）與 Playwright Chromium 都要裝進 image，
      驗證 `impersonate target` 不是 None、Chromium 能跑（`--disable-dev-shm-usage` 已加）。

## 🧪 測試 / 雜項

- [ ] 各格式各留一個公開測試源（HLS 已有 mux.dev；補 DASH、直接 mp4、加密 HLS）。
- [ ] handler 回退鏈的單元測試：故意讓前面的 handler 失敗，確認自動換下一個。
- [ ] 空間不足時不要把半成品留在 tmpfs（目前 `_delete_files` 會清，確認 remux 中途死也清得乾淨）。
