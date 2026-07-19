# myfans 下載設定指南

[myfans.jp](https://myfans.jp) 是付費粉絲訂閱平台，yt-dlp 沒有對應的解析器，且它的
**付費影片串流只有在請求帶上你的登入 token 時，官方 API 才會回傳**。因此本工具用一個
專屬 handler 直接呼叫 myfans API 取得付費串流，你只需要提供一個 token。

> ⚠️ token 等同你的帳號登入憑證，請勿外流、勿提交到 git。用完想撤銷就到 myfans
> 登出，舊 token 即失效。伺服器全程不落地、不寫入審查日誌（只記 `with_cookies: true`）。
>
> 前提：**你的帳號必須已訂閱／購買該貼文**。本工具用的是你自己的登入態，不會、也不能
> 繞過付費牆；未購買的貼文只會拿到免費預覽片。

## 為什麼不能像其他平台一樣直接貼連結

myfans 的網頁把登入 token 存在瀏覽器 localStorage，**不是**會自動送出的 cookie，所以：

- 一般貼 cookie 沒用（token 根本不在 cookie 裡）。
- 瀏覽器嗅探回退也只會抓到頁面預設載入的**免費預覽片**（付費流要帶 token 才拿得到）。

實際的媒體 CDN（`content.mfcdn.jp`）授權是簽在網址裡的、不吃標頭，所以 token 只用在
**呼叫 API 那一步**；拿到串流網址後的下載不需要 token。

## 步驟一：取得你的 token（最可靠：從 API 請求的標頭抄）

1. 在瀏覽器**登入 myfans**，打開任一支你**已訂閱**的付費影片，讓它開始播放。
2. 按 `F12` 開發者工具，切到 **Network（網路）** 分頁，勾 **Fetch/XHR**。
3. 在上方 filter 框輸入 `api.myfans.jp`（或 `posts`）過濾掉雜訊。
4. 點一個 host 是 `api.myfans.jp`、路徑類似 `/api/v2/posts/...` 的請求。
5. 在 **Request Headers（請求標頭）** 找到 **Authorization**，值長這樣：

   ```
   Authorization: Token token=abcdef0123456789...
   ```

6. 複製 `Token token=` **後面那一整串值**（只要 `abcdef0123456789...`，不含 `Token token=`）。

> localStorage 裡雖有 `_mf_session` 等鍵，但值常被 JSON／URL-encode 包過，不一定能直接用；
> **Network 標頭那串是 100% 準的**，建議用它。

## 步驟二：貼進下載介面

展開首頁的「進階選項」，把 token 貼進 cookie 輸入框，格式為：

```
_mfans_token=<你複製的那串 token>
```

`_mfans_token` 這個名字只是本工具用來辨識 token 的標籤，跟 myfans 實際存在哪無關——
照這個格式包起來即可。接著把 myfans 貼文連結
（`https://myfans.jp/<創作者>/posts/<id>` 或 `https://myfans.jp/posts/<id>`）貼到下載框、送出。

送出後 handler 會：呼叫 `GET api.myfans.jp/api/v2/posts/{id}` → 檢查你有無權限
（`free` / `subscribed`）→ 從 `videos.main` 自動挑最高畫質（`uhd → fhd → hd → sd → ld`）→
下載並合併為 mp4。你**不用**自己判斷該用哪個 m3u8。

## 常見問題

| 訊息 | 原因 / 處理 |
| --- | --- |
| `myfans token rejected (expired or invalid)` | token 抄錯或已過期。回 Network 標頭重抄一次（別含 `Token token=` 前綴）。 |
| `No access to this post ...` | 你的帳號沒訂閱／購買這支貼文。付費內容無法繞過，先在 myfans 訂閱。 |
| `Post has no downloadable video` | 該貼文是圖片貼文，或只有預覽、沒有可下載的主影片。 |
| 抓到的是短短幾秒的預覽 | 多半是 token 沒帶到（落到嗅探回退）。確認 cookie 欄位有 `_mfans_token=...` 且值正確。 |

## 臨時替代法（單支、想馬上測）

不想弄 token 時，可在 Network 分頁直接抓那支影片的 m3u8 網址（host `content.mfcdn.jp`、
路徑 `/videos/processed/hls/...`，挑畫質最高的或沒帶畫質的 master），把**完整網址**貼進
下載框即可（走一般 m3u8 handler，本工具會自動補上 myfans 需要的 `Origin`/`Referer`）。

缺點：此網址**內含限時簽名、會過期**，且每支要手動複製。要「貼貼文連結就自動下載、可
重複使用」還是走上面的 token 流程。

## 技術細節（給維護者）

- Handler：`backend/app/handlers/myfans.py`（`MyfansHandler`），註冊在
  `handlers/__init__.py` 最前面，只匹配 myfans 貼文 URL。
- API：`GET https://api.myfans.jp/api/v2/posts/{post_id}`，帶
  `Authorization: Token token=<t>`；回傳 `{free, subscribed, videos:{main:[{resolution,url}]}}`。
- token 來源沿用既有 cookie 機制：從寫出的 cookies.txt 找名為 `_mfans_token` 的項
  （或任何名稱含 `token` 的作為後備）。
- 下載交給共用的 `_hls_png.run_hls()`（自動追 master→最佳變體、AES-128、PNG 前綴去殼皆現成）。
- 失敗時（沒 token／沒權限）回退鏈仍會往下試嗅探器，不會中斷。
