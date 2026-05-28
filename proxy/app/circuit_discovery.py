"""
Discover Apex Timing URL and WS port for a karting circuit name.

Flow:
  1. Check circuits DB by name/slug similarity
  2. DuckDuckGo HTML search: "live timing karting {name} apex-timing.com"
  3. Fetch candidate Apex page, regex configPort
  4. Add to DB if new
"""
import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import circuits_db

logger = logging.getLogger(__name__)

_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def _fetch_sync(url: str, timeout: int = 10) -> str:
    import gzip
    req = Request(url, headers=_HDRS)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except (URLError, HTTPError) as e:
        logger.debug("fetch %s: %s", url, e)
        return ""


async def _afetch(url: str) -> str:
    return await asyncio.get_event_loop().run_in_executor(None, _fetch_sync, url)


async def _ddg_apex_urls(query: str) -> list[str]:
    """DuckDuckGo search, return apex-timing.com URLs found in results."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html = await _afetch(url)
    if not html:
        return []
    urls = re.findall(
        r"https?://(?:www\.|live\.|live-data\.)?apex-timing\.com/[^\s\"'<>]+",
        html,
    )
    return list(dict.fromkeys(urls))  # deduplicate preserving order


async def _config_port(url: str) -> Optional[int]:
    """Fetch an Apex Timing page and extract configPort, trying multiple URL variants."""
    base = url.rstrip("/").removesuffix("index.html").rstrip("/")
    for candidate in [url, base + "/index.html", base + "/javascript/config.js"]:
        html = await _afetch(candidate)
        m = re.search(r"configPort\s*=\s*(\d+)", html)
        if m:
            return int(m.group(1))
    return None


def _ws_host_from_url(url: str) -> str:
    m = re.match(r"https?://([^/]+)/", url)
    return m.group(1) if m else "www.apex-timing.com"


def _slug_from_url(url: str) -> str:
    url = url.rstrip("/")
    return url.split("/")[-1]


async def discover(circuit_name: str, country: str = "") -> tuple[Optional[str], Optional[int]]:
    """
    Find Apex Timing URL and WS port for a circuit.
    Returns (circuit_url, ws_port) or (None, None).
    Also upserts the circuit to DB when found.
    """
    name_lower = circuit_name.lower()

    # 1. DB lookup by name / slug similarity
    for c in circuits_db.get_all():
        c_name = (c.get("name") or "").lower()
        c_slug = (c.get("slug") or "").lower()
        if (name_lower in c_name or c_name in name_lower
                or name_lower in c_slug or c_slug in name_lower):
            url, port = c.get("url"), c.get("port")
            if url and port:
                logger.info("discover: found '%s' in DB → %s port %s", circuit_name, url, port)
                return url, port

    # 2. DuckDuckGo search — plusieurs variantes si nécessaire
    queries = [f"live timing karting {circuit_name} apex-timing.com"]
    if country:
        queries[0] += f" {country}"
    # Variante sans contrainte de site (pour retrouver une URL différente du nom)
    queries.append(f'"{circuit_name}" site:apex-timing.com live timing')
    if country:
        queries.append(f"karting {circuit_name} {country} live timing apex")

    apex_urls: list[str] = []
    for query in queries:
        found = await _ddg_apex_urls(query)
        logger.info("discover: DDG '%s' → %d apex URLs", query, len(found))
        for u in found:
            if u not in apex_urls:
                apex_urls.append(u)
        if apex_urls:
            break  # Stop dès qu'on a des résultats

    for raw_url in apex_urls[:6]:
        # Normalize: ensure trailing slash, keep https
        apex_url = re.sub(r"^http://", "https://", raw_url.rstrip("/")) + "/"
        # Skip if not a page-level URL (e.g. direct to .js/.png)
        if re.search(r"\.(js|css|png|jpg|ico)$", apex_url, re.IGNORECASE):
            continue

        config_port = await _config_port(apex_url)
        if config_port is None:
            continue

        ws_port = config_port + 3
        slug = _slug_from_url(apex_url)
        ws_host = _ws_host_from_url(apex_url)

        # Add to DB (upsert)
        try:
            circuits_db.upsert({
                "slug": slug,
                "name": circuit_name,
                "url": apex_url,
                "port": ws_port,
                "ws_host": ws_host,
                "country": country,
                "tested": None,
                "timezone": circuits_db.COUNTRY_TZ.get(country, "UTC"),
            })
            logger.info("discover: added '%s' slug=%s port=%d", circuit_name, slug, ws_port)
        except Exception as e:
            logger.warning("discover: upsert failed for %s: %s", circuit_name, e)

        return apex_url, ws_port

    logger.info("discover: no Apex Timing found for '%s'", circuit_name)
    return None, None
