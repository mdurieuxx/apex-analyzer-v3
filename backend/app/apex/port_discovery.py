import re
import logging
import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Apex Timing embeds the WS port in page JS under various variable names
_PATTERNS = [
    r'wsPort\s*[=:]\s*["\']?(\d{4,5})',
    r'ws_port\s*[=:]\s*["\']?(\d{4,5})',
    r'var\s+port\s*=\s*(\d{4,5})',
    r'"port"\s*:\s*(\d{4,5})',
    r"'port'\s*:\s*(\d{4,5})",
    r'port\s*=\s*(\d{4,5})',
    r':(\d{4,5})/',
]


async def discover_ws_port(circuit_url: str) -> int | None:
    """
    Fetch the circuit index page and extract the WebSocket port from embedded JS.
    Per the Apex Timing protocol: WSS port = displayPort + 3, WS = displayPort + 2.
    The page JS usually contains one of: wsPort, ws_port, port = NNNN.
    Returns the port to connect to (the WSS/WS port directly, not displayPort).
    """
    try:
        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=10) as c:
            r = await c.get(circuit_url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        logger.error("Could not fetch circuit page %s: %s", circuit_url, e)
        return None

    for pattern in _PATTERNS:
        for m in re.finditer(pattern, html):
            port = int(m.group(1))
            if 7000 <= port <= 9999:
                logger.info("Discovered port %d from %s (pattern: %s)", port, circuit_url, pattern)
                return port

    logger.warning("No valid port found in page source for %s", circuit_url)
    return None
