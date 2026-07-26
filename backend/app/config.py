from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (repo checkout) and backend dir; .env is looked up in both so it
# works whether you run from the repo root, backend/, or Docker.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# Only real files: Docker creates a *directory* at a bind-mount target whose
# source is missing, and pointing pydantic at a directory would blow up at
# import time — with a confusing traceback, on a machine that just forgot to
# copy .env.example.
ENV_FILES = tuple(
    p for p in (ROOT_DIR / ".env", BACKEND_DIR / ".env") if p.is_file()
)


class Settings(BaseSettings):
    """Application settings.

    One place to configure this service: the .env file at the project root
    (see .env.example). Real environment variables still win over it, which is
    what makes `ACCESS_PASSWORD=x uvicorn ...` and compose overrides work, but
    .env is the documented home for every setting — there is deliberately no
    second config format to keep in sync.
    """

    tmp_dir: str = "/tmp/neko_dl"
    max_concurrent: int = 2
    max_queue_size: int = 50
    file_ttl_seconds: int = 3600
    cleanup_interval_seconds: int = 60
    sniff_timeout_seconds: int = 20
    # Netscape-format cookies file passed to yt-dlp; needed for
    # login-required content (e.g. private Facebook/X/TikTok posts).
    cookies_file: str = ""
    # Alternatively read cookies straight from a local browser profile,
    # e.g. "firefox", "chrome", "chrome:Profile 1". cookies_file wins if both
    # are set. Only meaningful on bare-metal installs (browser on same host).
    cookies_from_browser: str = ""
    # Audit log path ("" disables the file; events still go to stdout).
    # Relative paths resolve against backend/ (= /srv in Docker).
    audit_log_file: str = "logs/audit.log"
    # Shared password for the whole API/WebSocket. "NONE" (the value shipped
    # in .env.example) or empty = no authentication at all, which is the
    # original behaviour. See app/auth.py for what it does and does not protect.
    access_password: str = "NONE"

    # -- Telegram branch (MTProto, real user account) ----------------------
    # Credentials from https://my.telegram.org/apps. Empty = branch disabled.
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    # Holds the MTProto auth key (= full account access), so the directory is
    # forced to 0700 and the session file to 0600. Relative paths resolve
    # against backend/. Must NOT live under tmp_dir, which is wiped on boot.
    telegram_session_dir: str = ".secrets"
    telegram_session_name: str = "neko_user"

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
