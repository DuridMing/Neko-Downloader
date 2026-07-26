# Podman 更新指南（compose 與 Quadlet）

目標機是 Rocky Linux + (rootless) Podman。Podman 有兩種完全不同的跑法，**更新流程也不一樣**，
先確認自己是哪一種：

```bash
ls /etc/containers/systemd/*.container 2>/dev/null && echo "→ Quadlet" || echo "→ compose"
```

不管哪一種，共通前提都一樣：**程式碼從 git 拉，設定與登入狀態都在掛載進去的檔案裡**
（`.env`、`backend/.secrets/`），所以重建 image 不會動到你的密碼與 Telegram session。
暫存目錄與佇列本來就是重啟即清，更新／回滾不會留下髒資料。

`podman compose` 是 Podman 4.4+ 的寫法；舊版請把以下所有指令的 `podman compose` 換成
`podman-compose`。

## A. compose 部署的更新

```bash
cd /path/to/neko_downloader
git pull

# 1) 先確認 .env 存在（v2 起這是唯一的設定檔）
ls -l .env || cp .env.example .env

# 2) 重建並啟動（前端也在 image 內建置，主機不需要 node）
podman compose down
podman compose build
podman compose up -d
podman compose logs -f --tail=50      # Ctrl-C 離開
```

macvlan 部署把上面每個 compose 指令都加 `-f docker-compose.macvlan.yml`。

> Podman 不吃 compose 的 `restart: unless-stopped`。要開機自動啟動請用
> `podman generate systemd --new --files --name <容器名>` 產生 unit，或啟用
> `podman-restart.service`。

## B. Quadlet 部署（systemd 原生，不用 compose）

如果部署是 `/etc/containers/systemd/*.container`，compose 檔只是參考——**掛載要自己對齊**。
v2 需要的兩個新掛載：

```ini
[Container]
# 設定檔（v2 起唯一來源）。檔案必須先存在，否則 podman 會在這裡建出一個「目錄」，
# 設定就靜靜地不生效：cp .env.example .env && chmod 600 .env
Volume=/opt/Neko-Downloader/.env:/srv/.env:ro,Z

# Telegram session＝帳號完整存取權。掛載而非烤進 image，重建/重啟都不必重新登入。
Volume=/opt/Neko-Downloader/backend/.secrets:/srv/.secrets:Z
```

更新流程（Quadlet 的 `.build` 單元是 `Type=oneshot` + `RemainAfterExit=yes`，
**成功過一次就不會自己重跑**，所以 `git pull` 之後要主動 build）：

```bash
cd /opt/Neko-Downloader && git pull
sudo podman build -t localhost/neko-downloader:latest .   # 最可靠的重建方式
sudo systemctl daemon-reload            # 只有改過 .container / .build 才需要
sudo systemctl restart neko-downloader.service
journalctl -u neko-downloader -f
```

只改了 `.env`（沒動程式碼）時不必 build，`systemctl restart` 就夠了——`.env` 是掛載進去的。

macvlan 模式沒有 port mapping，容器直接監聽 `PORT`；而 `PORT` 是在程式啟動前由 CMD 讀取的，
**掛進去的 `.env` 來不及影響它**。要換埠請在 `.container` 寫 `Environment=PORT=9000`。

## 驗證（兩種都適用）

```bash
curl -si localhost:8000/api/jobs | head -1     # 有設密碼→401；ACCESS_PASSWORD=NONE→200
curl -s  localhost:8000/api/telegram            # 設密碼時要帶解鎖後的 cookie
```

再開網頁貼一個連結跑一次，確認下載與進度都正常。

## 回滾

```bash
# compose
git checkout HEAD~1 && podman compose up -d --build

# Quadlet
git checkout HEAD~1
sudo podman build -t localhost/neko-downloader:latest . && \
  sudo systemctl restart neko-downloader.service
```

`backend/.secrets/`（Telegram session）與 `.env` 都不在 git 裡，回滾不影響。

## 常見狀況

| 症狀 | 原因 |
| --- | --- |
| 設定改了卻沒生效 | `.env` 路徑不存在，podman 建出了同名**目錄**。`ls -ld` 確認是檔案，刪掉目錄後 `cp .env.example .env` |
| 容器寫不進暫存／logs | 掛載少了 `:Z`（SELinux enforcing 下必加，logs 也要） |
| 每次重建都要重新登入 Telegram | `backend/.secrets` 沒掛載進 `/srv/.secrets` |
| 改了程式卻跑舊版 | Quadlet 的 `.build` 不會自動重跑，要手動 `podman build` |
| 換了 `PORT` 沒反應（macvlan/Quadlet） | `PORT` 由 CMD 在讀 `.env` 之前取用，要寫在 `.container` 的 `Environment=` |
| 抓不到某平台的影片 | 平台改版，重建 image 取得最新 yt-dlp（`podman build --no-cache`） |
