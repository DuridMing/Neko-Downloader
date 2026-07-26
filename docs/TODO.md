# TODO

活的清單。**未完成的事**在上半部，**踩過的坑（含真因）**在下半部——後者留著是因為它解釋了
程式碼為什麼長這樣，刪掉會有人重蹈覆轍。已完成的實作步驟不再列，架構請看 [CLAUDE.md](CLAUDE.md)。

## 待辦

### 下載能力

- [ ] **DRM / Widevine**：目前會一路失敗到最後，前端只顯示通用訊息。至少要辨識出來給明確錯誤。
- [ ] **MSS / Smooth Streaming（.ism/manifest）**：少見，先觀望。
- [ ] **直播 / HLS live**：需要「錄到停」的語意（時長／檔案上限），跟現有「下載完成」模型不同，
      要先想清楚 job 狀態機怎麼擴。
- [ ] **blob: / MSE 串流**：sniffer 抓不到（媒體在 JS 內組裝）。要攔 XHR/fetch 的分段請求或
      segment 模板。難度高，排後面。
- [ ] `_hls_png.run_hls` 只處理**未加密**的 PNG-TS。若遇到 AES-128 + PNG 前綴，得在剝前綴後再自行解密。
- [ ] AES-128 以外的加密（`SAMPLE-AES` 等）仍走 yt-dlp，可能一樣卡 0%，遇到再說。
- [ ] AES-128 的進度是「總時長 × 播放速率」的線性估計；`-c copy` 夠穩，先不改。

### sniffer

- [ ] 多品質：抓到第一個 playlist 就停，沒挑最高畫質。考慮收集全部 variant 交給 yt-dlp 選。
- [ ] `AD_HOST_FRAGMENTS` 是 denylist，新廣告網路會漏（打地鼠）。同源 + 大小啟發式擋跨站的，
      denylist 補同源注入的；遇到新的就補字串。
- [ ] 假播放器點擊仍非 100% 成功（對抗性站本質是機率問題）。要更穩再考慮 residential proxy、
      真 Chrome channel、`playwright-stealth`。
- [ ] 逾時可調（`sniff_timeout_seconds`），但某些站要點兩三層才出串流——考慮可選的「互動腳本」。
- [ ] 使用者選擇候選後 resume 不重建 cookiefile（第一次跑就清了），靠 candidate 擷取的 Cookie header。
      若某站正片 URL 還需頁面 cookie，要把 cookiefile 生命週期延長到 selection 解決為止。

### 前端 / 體驗

- [ ] postprocessing 卡住時顯示更明確的狀態（目前 progress 停在 100% 沒有說明）。
- [ ] 設定面板可以有「立即鎖定」（現在 cookie 給 30 天，要提前失效只能改密碼）。
- [ ] 網頁上瀏覽 Telegram 頻道再挑檔案下載（現在只有 CLI 的 `scripts/telegram-index.py`）。
      `TgIndex` 是為此準備的地基。

### 部署 / 維運

- [ ] **部署前確認** `/var/tmp` 所在磁碟空間：約「最大影片 ×2（remux 尖峰）× MAX_CONCURRENT」，
      別讓它跟系統 `/` 搶爆。
- [ ] Podman 內驗證 curl_cffi 的 `impersonate target` 不是 None、Chromium 跑得起來。
- [ ] 網段不可信時要加 TLS；macvlan 模式下容器有自己的 IP，反代擋不住直連，TLS 得做進容器。

### 測試

- [ ] 各格式各留一個公開測試源（HLS 已有 mux.dev；補 DASH、直接 mp4、加密 HLS）。
- [ ] handler 回退鏈的單元測試：故意讓前面的 handler 失敗，確認自動換下一個。
- [ ] 空間不足時確認 remux 中途死掉也清得乾淨（`_delete_files` 應該有蓋到）。

### 觀察中

- [ ] `ffmpeg exited with code 183`（streamfastpro 那類）：2 秒內三個 handler 全失敗＝串流本身死掉／
      地區封鎖。stderr 捕捉已上線，回頭看真因，可能要加「來源失效」的友善訊息。

## 踩過的坑（真因記錄）

### `Conversion failed!`：長影片在 postprocessing 炸掉

`Conversion failed!` 只是 ffmpeg stderr 的**最後一行**，真因被吞掉。yt-dlp 先把串流下載成大檔，
ffmpeg 再 remux 成 mp4 —— 這一步需要**第二份完整副本**塞在同一個檔案系統，尖峰約 2×。
5.5GB 的片子要 ~11GB，當時的 4g tmpfs 必爆，錯誤卻只顯示 `Conversion failed!`。

修法：暫存從 tmpfs 改成磁碟（host `/var/tmp/neko_dl`，被 Rocky 的 systemd-tmpfiles 30 天 backstop
涵蓋），`JobQueue.start()` 啟動時清空維持「重啟＝乾淨」；`run_ytdlp` 開 verbose + logger 捕捉
ffmpeg stderr，把真因附在 `job.error`。**別把暫存改回 RAM-only。**

### 抓到廣告而非正片（javplayer 那類假播放器）

`javplayer.org` 用 `#clickfakeplayer` 假播放器，開頁時頁面上**只有廣告 mp4**、沒有真 `<video>`。
舊 sniffer 點 `video` 選擇器只點到廣告、又「拿第一個 media」，所以穩定地把 326KB 廣告當正片。
點假播放器還會觸發 popunder 廣告跳轉，真播放器始終沒載入。

修法：`context.route` abort 廣告網域、`context.on("page")` 關掉 popunder、candidate 依「來源 frame
主網域 ≠ 頁面主網域 **且** 檔案過小」丟棄（同源 CDN 不誤殺）、挑選改 playlist 優先＋同源最大；
過濾後仍 >1 個可信 candidate 就丟 `NeedsSelection` 讓使用者挑。

### 「辨識不到影片」時好時壞

假播放器被廣告 overlay 蓋住，且**需要點好幾下**（前幾下是開廣告）。`force=True` 沒用——它只跳過
actionability 檢查，瀏覽器仍會對座標做 hit-test，最上層的 overlay 收走事件。
修法：每輪用 JS `element.click()` 直接派發到元素（繞過 hit-test），外加一次 force 指標點擊，
再加整段 sniff 失敗自動重試一次。通常 5~6 輪才載入真 player。

### 下載完成但影片不能播（PNG 偽裝的 TS segment）

某些站的 HLS segment 是**假 PNG 包真 TS**：`[120B 1×1 PNG][~85B 0xFF padding][真正的 MPEG-TS]`。
CDN/WAF 與 yt-dlp 都以為是 image，yt-dlp 把 PNG 一起 muxed → 產出 `format_name=png_pipe` 的
無法播放檔案。瀏覽器播放器會先剝掉前綴再餵 MSE。
修法：`handlers/_hls_png.py` 的 `run_hls()` 會 peek 第一個 segment，偵測到 image 前綴就自己抓、
逐段剝前綴、concat 成 .ts、ffmpeg `-c copy` remux。偵測成本是多一個 request。

### 加密 HLS（AES-128）進度卡在 0%

把 `#EXT-X-KEY` 丟給 yt-dlp（`hls_prefer_native`）時，它雖印 `Invoking hlsnative downloader`，
**實際卻 silent 退回 ffmpeg**，而 ffmpeg 的進度走它自己的 stderr、不經 yt-dlp 的 `progress_hooks`
→ 前端看起來像當掉，其實一直在下載。
修法：偵測到 `METHOD=AES-128` 就自己驅動 ffmpeg（`-progress pipe:1`），對「playlist EXTINF 加總」
算出真實 %。ffmpeg 自己抓金鑰解密。

### 本機 ffmpeg 會 segfault

`~/.local/opt/ffmpeg`（johnvansickle static build）處理網路 HLS 與 MPEG-TS 時會 segfault，症狀是
yt-dlp 後處理炸成 `Expecting value: line 1 column 1`。**一定要用 `~/.local/opt/ffmpeg-btbn/`。**
