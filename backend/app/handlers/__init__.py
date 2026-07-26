import logging

from .base import registry
from .direct_stream import DirectStreamHandler
from .m3u8 import M3u8Handler
from .myfans import MyfansHandler
from .telegram_handler import TelegramHandler
from .ytdlp_platform import YtDlpPlatformHandler

logger = logging.getLogger("neko.handlers")

# Order matters: specific handlers first. The worker tries every matching
# handler in this order, falling back to the next one on failure.
# m3u8 + direct-stream keep the derived Origin/Referer (raw CDN URLs need
# them); the catch-all strips those, so it must come after.
# myfans first: a site-specific API handler that only matches myfans post URLs;
# if it fails (no token / no access) the chain still falls back to the sniffer.
registry.register(MyfansHandler())
# telegram before the catch-all: only it can read a post the account has
# access to, but yt-dlp still gets a shot at public links if it is disabled.
registry.register(TelegramHandler())
registry.register(M3u8Handler())
registry.register(DirectStreamHandler())
registry.register(YtDlpPlatformHandler())

try:
    from .browser_sniff import BrowserSniffHandler

    registry.register(BrowserSniffHandler())
except ImportError:
    logger.warning("playwright not installed; browser-sniffing fallback disabled")
