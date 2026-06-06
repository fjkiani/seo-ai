"""
agents/technical_agent.py
Fetches PageSpeed Insights for desktop + mobile.
Mobile runs as a FastAPI BackgroundTask (non-blocking) due to rate limit risk.
Desktop runs inline (blocking) as it is the primary signal.

Confirmed working params (2026-06-04):
  category=PERFORMANCE (uppercase)
  strategy=desktop (lowercase)
  timeout=90s (API can be slow under load)
"""
import logging
from typing import Optional

import aiohttp

from core.config import Settings
from core.models import TechnicalResult

logger = logging.getLogger(__name__)

SPA_TBT_THRESHOLD = 300        # ms — above this + high unused JS = SPA signal
SPA_UNUSED_JS_THRESHOLD = 100  # KiB
PAGESPEED_TIMEOUT = 90         # seconds — API can be slow


async def _fetch_pagespeed(
    session: aiohttp.ClientSession,
    url: str,
    strategy: str,
    settings: Settings,
) -> TechnicalResult:
    """Fetch PageSpeed Insights for one URL + strategy."""
    api_url = f"https://{settings.pagespeed_host}/run_pagespeed"
    headers = {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": settings.pagespeed_host,
        "Content-Type": "application/json",
    }
    params = {
        "url": f"https://{url}" if not url.startswith("http") else url,
        "category": "PERFORMANCE",
        "strategy": strategy.lower(),  # API requires lowercase: "desktop" or "mobile"
    }
    try:
        async with session.get(
            api_url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=PAGESPEED_TIMEOUT, connect=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                return _parse(url, strategy, data)
            else:
                text = await resp.text()
                logger.warning(f"PageSpeed {strategy} {resp.status}: {text[:200]}")
                return TechnicalResult(
                    url=url, strategy=strategy,
                    performance=None, seo_score=None, accessibility=None,
                    fcp_ms=None, lcp_ms=None, tbt_ms=None,
                    unused_js_kib=None, spa_signal=False,
                    status=resp.status,
                    error=f"HTTP {resp.status}",
                )
    except aiohttp.ServerTimeoutError as e:
        logger.warning(f"PageSpeed {strategy} timeout after {PAGESPEED_TIMEOUT}s: {e}")
        return TechnicalResult(
            url=url, strategy=strategy,
            performance=None, seo_score=None, accessibility=None,
            fcp_ms=None, lcp_ms=None, tbt_ms=None,
            unused_js_kib=None, spa_signal=False,
            status=0, error=f"timeout after {PAGESPEED_TIMEOUT}s",
        )
    except Exception as e:
        logger.error(f"PageSpeed {strategy} exception: {e}")
        return TechnicalResult(
            url=url, strategy=strategy,
            performance=None, seo_score=None, accessibility=None,
            fcp_ms=None, lcp_ms=None, tbt_ms=None,
            unused_js_kib=None, spa_signal=False,
            status=0, error=str(e),
        )


def _parse(url: str, strategy: str, data: dict) -> TechnicalResult:
    """Parse PageSpeed API response into TechnicalResult."""
    cats = data.get("lighthouseResult", {}).get("categories", {})
    audits = data.get("lighthouseResult", {}).get("audits", {})

    def cat_score(key: str) -> Optional[int]:
        s = cats.get(key, {}).get("score")
        return int(round(s * 100)) if s is not None else None

    def audit_ms(key: str) -> Optional[float]:
        v = audits.get(key, {}).get("numericValue")
        return round(float(v), 1) if v is not None else None

    def audit_kib(key: str) -> Optional[float]:
        v = audits.get(key, {}).get("numericValue")
        return round(float(v) / 1024, 1) if v is not None else None

    tbt = audit_ms("total-blocking-time")
    unused_js = audit_kib("unused-javascript")

    spa_signal = bool(
        tbt is not None and tbt > SPA_TBT_THRESHOLD and
        unused_js is not None and unused_js > SPA_UNUSED_JS_THRESHOLD
    )

    return TechnicalResult(
        url=url,
        strategy=strategy,
        performance=cat_score("performance"),
        seo_score=cat_score("seo"),
        accessibility=cat_score("accessibility"),
        fcp_ms=audit_ms("first-contentful-paint"),
        lcp_ms=audit_ms("largest-contentful-paint"),
        tbt_ms=tbt,
        unused_js_kib=unused_js,
        spa_signal=spa_signal,
        status=200,
    )


async def run_desktop(domain: str, settings: Settings) -> TechnicalResult:
    """Run desktop PageSpeed — blocking, called inline."""
    connector = aiohttp.TCPConnector(limit=10, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        return await _fetch_pagespeed(session, domain, "desktop", settings)


async def run_mobile(domain: str, settings: Settings) -> TechnicalResult:
    """Run mobile PageSpeed — called as BackgroundTask in FastAPI."""
    connector = aiohttp.TCPConnector(limit=10, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        return await _fetch_pagespeed(session, domain, "mobile", settings)
