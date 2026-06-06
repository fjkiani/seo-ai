"""
agents/keyword_agent.py
Fetches keyword volume + difficulty from SEMrush Keyword Magic Tool.

SEMrush /global-volume response structure (confirmed live 2026-06-04):
  {
    "Keyword Overview": {
      "global": [{"keyword": "...", "searche volume": "2.4k", "Keyword Difficulty %": "67%"}],
      "US": [{"keyword": "...", "searche volume": "170", "Competitive Density Score": 0.15, ...}],
      "UK": [...], "AU": [...], "IN": [...], "CA": [...]
    }
  }

Volume parsing: "2.4k" → 2400, "1.7k" → 1700, "421" → 421.
competition_index: from "Competitive Density Score" in US entry (0–1 scale).
KD: from "Keyword Difficulty %" in US entry (e.g. "67%" → 67.0).
Falls back to global entry if US entry absent.

Google Keyword Insight removed — quota exhausted on BASIC plan.
Rate limit: 1.2s delay between SEMrush requests.
"""
import asyncio
import logging
from typing import List

import aiohttp

from core.config import Settings
from core.models import KeywordResult

logger = logging.getLogger(__name__)

SEMRUSH_DELAY = 1.2  # seconds between requests (rate limit)


def _parse_vol_str(s: str) -> int:
    """Parse SEMrush volume strings: '2.4k' → 2400, '421' → 421."""
    if not s:
        return 0
    s = str(s).strip().lower().replace(",", "")
    if s.endswith("k"):
        try:
            return int(float(s[:-1]) * 1000)
        except ValueError:
            return 0
    if s.endswith("m"):
        try:
            return int(float(s[:-1]) * 1_000_000)
        except ValueError:
            return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _parse_kd_str(s: str) -> float:
    """Parse '67%' → 67.0, '100%' → 100.0."""
    try:
        return float(str(s).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


async def _fetch_semrush(
    session: aiohttp.ClientSession,
    keyword: str,
    settings: Settings,
) -> dict:
    """Fetch keyword data from SEMrush Keyword Magic Tool /global-volume."""
    url = f"https://{settings.semrush_host}/global-volume"
    headers = {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": settings.semrush_host,
        "Content-Type": "application/json",
    }
    params = {"keyword": keyword, "country": "us"}
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                return {"keyword": keyword, "status": 200, "data": data}
            else:
                text = await resp.text()
                logger.warning(f"SEMrush {resp.status} for \'{keyword}\': {text[:200]}")
                return {"keyword": keyword, "status": resp.status, "data": None}
    except Exception as e:
        logger.error(f"SEMrush error for \'{keyword}\': {e}")
        return {"keyword": keyword, "status": 0, "data": None, "error": str(e)}


def _parse_semrush(raw: dict, keyword: str) -> tuple[int, float, float]:
    """
    Parse SEMrush /global-volume response.
    Returns (volume, kd_percent, competition_index).

    Priority: US entry > global entry.
    Volume: "searche volume" field (note API typo).
    KD: "Keyword Difficulty %" → strip "%" → float.
    CI: "Competitive Density Score" (0–1) from US entry.
        Falls back to KD/100 if not present.
    """
    data = raw.get("data")
    if not data or not isinstance(data, dict):
        return 0, 0.0, 0.0

    overview = data.get("Keyword Overview", {})
    if not overview:
        return 0, 0.0, 0.0

    # Try US entry first (most relevant for jedilabs.org target market)
    us_list = overview.get("US", [])
    global_list = overview.get("global", [])

    # Pick best entry: US preferred, fall back to global
    entry = None
    if us_list and isinstance(us_list, list) and us_list:
        entry = us_list[0]
    elif global_list and isinstance(global_list, list) and global_list:
        entry = global_list[0]

    if not entry:
        return 0, 0.0, 0.0

    # Volume
    vol_raw = entry.get("searche volume", entry.get("search volume", "0"))
    volume = _parse_vol_str(str(vol_raw))

    # If US volume is very low, also check global and use whichever is higher
    if us_list and global_list:
        global_entry = global_list[0] if global_list else {}
        global_vol = _parse_vol_str(str(global_entry.get("searche volume", "0")))
        if global_vol > volume:
            volume = global_vol
            # Use global entry for KD/CI too if it has better data
            entry = global_entry

    # KD
    kd = _parse_kd_str(entry.get("Keyword Difficulty %", "0%"))

    # Competition Index: "Competitive Density Score" (0–1) preferred
    ci_raw = entry.get("Competitive Density Score", entry.get("competition_index", None))
    if ci_raw is not None:
        try:
            ci = float(ci_raw)
        except (ValueError, TypeError):
            ci = round(kd / 100.0, 4)
    else:
        # Derive from KD as fallback
        ci = round(kd / 100.0, 4)

    return volume, kd, ci


async def run(keywords: List[str], settings: Settings) -> List[KeywordResult]:
    """
    Main entry point for KeywordAgent.
    SEMrush sequential with 1.2s delay (rate limit constraint).
    """
    results: List[KeywordResult] = []

    async with aiohttp.ClientSession() as session:
        for kw in keywords:
            raw = await _fetch_semrush(session, kw, settings)
            volume, kd, ci = _parse_semrush(raw, kw)

            if volume == 0 and kd == 0.0:
                logger.warning(f"No data from SEMrush for \'{kw}\' — using conservative defaults")
                volume = 500
                kd = 10.0
                ci = 0.10

            results.append(KeywordResult(
                keyword=kw,
                volume=volume,
                kd=kd,
                source="semrush",
                competition_index=ci,
            ))

            await asyncio.sleep(SEMRUSH_DELAY)

    return results
