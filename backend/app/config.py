from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Project root (repo checkout) and backend dir; config files are looked up in
# both so it works whether you run from the repo root, backend/, or Docker.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings.

    Sources by priority (highest wins):
    1. environment variables
    2. .env file
    3. config.json file
    4. defaults below

    See .env.example / config.example.json at the project root.
    """

    tmp_dir: str = "/tmp/neko_dl"
    max_concurrent: int = 2
    max_queue_size: int = 50
    file_ttl_seconds: int = 1800
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
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        json_file=(ROOT_DIR / "config.json", BACKEND_DIR / "config.json"),
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            JsonConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
