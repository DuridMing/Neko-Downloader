# 手動取得 Cookies 指南（自己開瀏覽器尋找）

不想用腳本或擴充功能時，可以直接打開瀏覽器的**開發者工具**，把登入用的
cookies 抄出來，手寫成 `cookies.txt`。本文說明去哪裡找、要抄哪幾個、
以及檔案格式怎麼寫。

> ⚠️ Cookies 等同你的帳號登入憑證，請妥善保管檔案（建議 `chmod 600 cookies.txt`），
> 不要提交到 git（本專案的 `.gitignore` 已排除 `cookies.txt`）。用完若要撤銷，
> 到該平台的「登出所有裝置／工作階段」即可讓抄出來的 cookies 失效。

本指南是三種取得方式中最手動的一種；若覺得麻煩，可改用 `./scripts/get-cookies.sh`
（互動式登入自動匯出）或 `COOKIES_FROM_BROWSER`（直接讀本機瀏覽器），詳見
[README 的「社群平台」章節](../README.md#社群平台facebook--x--tiktok)。

## 第一步：打開瀏覽器找到 Cookies

先在瀏覽器**登入**目標平台，停留在該網站的任一頁面，然後：

### Chrome / Edge / Brave

1. 按 `F12`（或右鍵 → 檢查）打開開發者工具
2. 切到 **Application** 分頁（中文介面為「應用程式」；看不到就點 `»` 展開）
3. 左側選單展開 **Storage → Cookies**（儲存空間 → Cookies），點選目標網域
   （例如 `https://www.tiktok.com`）
4. 右側表格會列出所有 cookies，欄位有 **Name / Value / Domain / Path /
   Expires / Secure** 等——這些正是等一下要填進檔案的資料

### Firefox

1. 按 `F12` 打開開發者工具
2. 切到 **Storage**（儲存空間）分頁
3. 左側展開 **Cookies**，點選目標網域
4. 同樣會看到 Name / Value / Domain / Expires 等欄位（點某一列可看完整 Value）

## 第二步：要抄哪幾個 Cookie

不需要全部，只要登入辨識用的關鍵幾個。各平台對照（名稱可能隨改版微調，
以實際看到的為準）：

| 平台 | 網域 | 關鍵 cookies |
| --- | --- | --- |
| Facebook | `.facebook.com` | `c_user`、`xs`（這兩個最關鍵）、`fr`、`datr` |
| X (Twitter) | `.x.com` | `auth_token`、`ct0` |
| TikTok | `.tiktok.com` | `sessionid`、`tt_chain_token`、`msToken` |
| Instagram | `.instagram.com` | `sessionid`、`ds_user_id`、`csrftoken` |
| YouTube | `.youtube.com` | `SID`、`HSID`、`SSID`、`APISID`、`SAPISID`、`__Secure-*` 系列 |

> 拿不準時，把該網域底下所有 cookies 全抄也可以，yt-dlp 會自己挑用得到的。

## 第三步：寫成 Netscape 格式 cookies.txt

yt-dlp 吃的是 **Netscape cookie 檔**格式。用純文字編輯器建立 `cookies.txt`，
第一行必須是標頭，之後每個 cookie 一行，**欄位之間用 Tab 分隔（不是空格）**：

```text
# Netscape HTTP Cookie File
<domain>	<include_subdomains>	<path>	<secure>	<expiry>	<name>	<value>
```

七個欄位的意思：

| 欄位 | 內容 | 怎麼填 |
| --- | --- | --- |
| `domain` | cookie 網域 | 照抄，通常以 `.` 開頭（如 `.tiktok.com`） |
| `include_subdomains` | 是否套用到子網域 | domain 以 `.` 開頭就填 `TRUE`，否則 `FALSE` |
| `path` | 路徑 | 通常是 `/` |
| `secure` | 僅限 HTTPS | DevTools 的 Secure 打勾就填 `TRUE`，否則 `FALSE` |
| `expiry` | 到期時間 | Unix 秒數時間戳；session cookie 或不確定就填 `0` |
| `name` | cookie 名稱 | 照抄 |
| `value` | cookie 值 | 照抄（很長是正常的，不要換行、不要加引號） |

### 完整範例（TikTok）

```text
# Netscape HTTP Cookie File
.tiktok.com	TRUE	/	TRUE	0	sessionid	1a2b3c4d5e6f7g8h9i0j
.tiktok.com	TRUE	/	TRUE	0	tt_chain_token	AbCdEfGhIjKlMnOp
```

> 每行的分隔一定要是 **Tab**。很多編輯器會把 Tab 自動轉成空格，若 yt-dlp 報
> 「cookies 檔格式錯誤」，多半是這個原因——把編輯器的「以空格代替 Tab」關掉，
> 或在 VS Code 右下角把該檔切成 Tab 縮排重打一次。

## 第四步：啟用

把路徑設給 `COOKIES_FILE`（見 [設定章節](../README.md#設定)）：

```bash
# .env
COOKIES_FILE=/path/to/cookies.txt
```

Docker 部署要把檔案掛進容器：

```yaml
# docker-compose.yml 的 service 底下
volumes:
  - ./cookies.txt:/srv/cookies.txt:ro
# 並設定 COOKIES_FILE=/srv/cookies.txt
```

## 第五步：驗證

可以先用 yt-dlp 直接測這份 cookies 能不能存取目標內容：

```bash
backend/.venv/bin/python -m yt_dlp --cookies cookies.txt --simulate "<你的影片連結>"
```

若印出影片標題與格式清單就代表 cookies 有效；若提示需要登入／私人內容，
表示抄漏了關鍵 cookie 或 cookies 已過期，回第二步重抄。

## 常見問題

- **抄完隔天就失效**：部分平台的 session 有效期短，或你在瀏覽器登出會一併讓
  cookies 失效。需要長期使用建議改用 `COOKIES_FROM_BROWSER`（每次即時讀取）。
- **`value` 很長、含特殊符號**：照原樣貼上即可，Netscape 格式不需跳脫，但不要
  夾帶換行。
- **分隔用了空格而非 Tab**：最常見的錯誤，會導致整份檔案無法解析，見第三步提示。
- **網域填錯**：X 的 cookies 在 `.x.com`（舊的 `.twitter.com` 多半已不適用）；
  以 DevTools 實際顯示的 Domain 為準。
