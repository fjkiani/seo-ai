"""
agents/traffic_agent.py
Fetches organic traffic + top keywords from SimilarWeb Insights.
Runs two concurrent requests: /seo and /traffic endpoints.

SimilarWeb returns empty data for low-traffic sites (<5K/mo visits).
All fields gracefully default to 0 / empty list in that case.
"""
import asyncio
import logging
from typing import Any, Dict, List

import aiohttp

from core.config import Settings
from core.models import TrafficResult

logger = logging.getLogger(__name__)


async def _fetch_sw(
    session: aiohttp.ClientSession,
    endpoint: str,
    domain: str,
    settings: Settings,
) -> dict:
    url = f"https://{settings.similarweb_host}/{endpoint}"
    headers = {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": settings.similarweb_host,
        "Content-Type": "application/json",
    }
    params = {"domain": domain}
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                return {"endpoint": endpoint, "status": 200, "data": data}
            else:
                text = await resp.text()
                logger.warning(f"SimilarWeb /{endpoint} {resp.status}: {text[:200]}")
                return {"endpoint": endpoint, "status": resp.status, "data": None}
    except Exception as e:
        logger.error(f"SimilarWeb /{endpoint} exception: {e}")
        return {"endpoint": endpoint, "status": 0, "data": None, "error": str(e)}


async def run(domain: str, settings: Settings) -> TrafficResult:
    """
    Fetch SimilarWeb SEO + traffic data concurrently.
    Gracefully handles empty responses for low-traffic sites.
    """
    async with aiohttp.ClientSession() as session:
        seo_raw, traffic_raw = await asyncio.gather(
            _fetch_sw(session, "seo", domain, settings),
            _fetch_sw(session, "traffic", domain, settings),
        )

    monthly_visits = 0
    top_keywords: List[Dict[str, Any]] = []
    snapshot_date = "unknown"

    # Parse traffic
    if traffic_raw.get("status") == 200 and traffic_raw.get("data"):
        td = traffic_raw["data"]
        monthly_visits = int(td.get("Visits", td.get("visits", td.get("monthly_visits", 0))) or 0)
        snapshot_date = td.get("SnapshotDate", td.get("snapshot_date", "unknown"))

    # Parse SEO keywords — SimilarWeb returns TopKeywords: {} for low-traffic sites
    if seo_raw.get("status") == 200 and seo_raw.get("data"):
        sd = seo_raw["data"]
        snapshot_date = sd.get("SnapshotDate", snapshot_date)
        kws = sd.get("TopKeywords", sd.get("top_keywords", sd.get("keywords", {})))
        # TopKeywords can be a dict {keyword: {volume, share}} or a list
        if isinstance(kws, dict):
            top_keywords = [
                {
                    "keyword": k,
                    "volume": int(v.get("volume", v.get("search_volume", 0)) or 0) if isinstance(v, dict) else 0,
                    "traffic_share": float(v.get("share", v.get("traffic_share", 0)) or 0) if isinstance(v, dict) else 0,
                }
                for k, v in list(kws.items())[:20]
            ]
        elif isinstance(kws, list):
            top_keywords = [
                {
                    "keyword": k.get("keyword", k.get("name", "")),
                    "volume": int(k.get("volume", k.get("search_volume", 0)) or 0),
                    "traffic_share": float(k.get("traffic_share", k.get("share", 0)) or 0),
                }
                for k in kws[:20]
            ]

    return TrafficResult(
        domain=domain,
        monthly_visits=monthly_visits,
        top_keywords=top_keywords,
        snapshot_date=str(snapshot_date),
    )
