"""
agents/authority_agent.py
Fetches domain authority metrics from Domain Metrics Check API.

Confirmed response fields (2026-06-04):
  mozDA, mozPA, mozRank, mozTrust, mozSpam, mozLinks
  majesticLinks, majesticRefDomains, majesticCF, majesticTTF0Name/Value
  (No Ahrefs data in this API plan)
"""
import logging

import aiohttp

from core.config import Settings
from core.models import AuthorityResult

logger = logging.getLogger(__name__)


async def run(domain: str, settings: Settings) -> AuthorityResult:
    """
    Fetch domain authority metrics.
    Endpoint: GET /domain-metrics/{domain}/
    """
    url = f"https://{settings.domain_metrics_host}/domain-metrics/{domain}/"
    headers = {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": settings.domain_metrics_host,
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return _parse(domain, data)
                else:
                    text = await resp.text()
                    logger.error(f"AuthorityAgent {resp.status}: {text[:300]}")
                    return _empty(domain)
        except Exception as e:
            logger.error(f"AuthorityAgent exception: {e}")
            return _empty(domain)


def _parse(domain: str, data: dict) -> AuthorityResult:
    """
    Parse Domain Metrics Check response.
    Fields: mozDA, mozPA, mozLinks, majesticLinks, majesticRefDomains, majesticCF
    """
    def safe_int(val, default=0) -> int:
        try:
            return int(float(str(val or default).replace(",", "")))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=0.0) -> float:
        try:
            return float(str(val or default).replace(",", ""))
        except (ValueError, TypeError):
            return default

    return AuthorityResult(
        domain=domain,
        moz_da=safe_int(data.get("mozDA", data.get("moz_da"))),
        moz_pa=safe_int(data.get("mozPA", data.get("moz_pa"))),
        ahrefs_dr=0,  # Not available in this API plan
        majestic_tf=safe_int(data.get("majesticTTF0Value", data.get("majestic_tf"))),
        majestic_cf=safe_int(data.get("majesticCF", data.get("majestic_cf"))),
        backlinks=safe_int(data.get("mozLinks", data.get("majesticLinks"))),
        ref_domains=safe_int(data.get("majesticRefDomains", data.get("ref_domains"))),
        indexed_pages=0,  # Not in Domain Metrics Check — use SimilarWeb or GSC
        organic_keywords=0,  # Not in Domain Metrics Check
    )


def _empty(domain: str) -> AuthorityResult:
    return AuthorityResult(
        domain=domain,
        moz_da=0, moz_pa=0, ahrefs_dr=0,
        majestic_tf=0, majestic_cf=0,
        backlinks=0, ref_domains=0,
        indexed_pages=0, organic_keywords=0,
    )
