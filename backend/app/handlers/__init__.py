import logging

from .base import registry
from .m3u8 import M3u8Handler
from .ytdlp_platform import YtDlpPlatformHandler

logger = logging.getLogger("neko.handlers")

# Order matters: specific handlers first. The worker tries every matching
# handler in this order, falling back to the next one on failure.
registry.register(M3u8Handler())
registry.register(YtDlpPlatformHandler())

try:
    from .browser_sniff import BrowserSniffHandler

    registry.register(BrowserSniffHandler())
except ImportError:
    logger.warning("playwright not installed; browser-sniffing fallback disabled")
