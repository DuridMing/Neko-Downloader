import logging

from .base import registry
from .direct_stream import DirectStreamHandler
from .m3u8 import M3u8Handler
from .ytdlp_platform import YtDlpPlatformHandler

logger = logging.getLogger("neko.handlers")

# Order matters: specific handlers first. The worker tries every matching
# handler in this order, falling back to the next one on failure.
# m3u8 + direct-stream keep the derived Origin/Referer (raw CDN URLs need
# them); the catch-all strips those, so it must come after.
registry.register(M3u8Handler())
registry.register(DirectStreamHandler())
registry.register(YtDlpPlatformHandler())

try:
    from .browser_sniff import BrowserSniffHandler

    registry.register(BrowserSniffHandler())
except ImportError:
    logger.warning("playwright not installed; browser-sniffing fallback disabled")
