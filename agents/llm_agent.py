"""
agents/llm_agent.py
OpenRouter LLM synthesis — generates executive summary, critical blockers,
top 3 actions, and per-page optimisation briefs.
Falls back gracefully if OPENROUTER_API_KEY is not set.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from core.config import Settings
from core.models import (
    AuthorityResult,
    CrawlabilityResult,
    KeywordResult,
    LLMSynthesis,
    StrategyResult,
    TrafficResult,
)

logger = logging.getLogger(__name__)


def _build_prompt(
    domain: str,
    authority: AuthorityResult,
    traffic: TrafficResult,
    crawlability: CrawlabilityResult,
    keywords: List[KeywordResult],
    strategy: StrategyResult,
) -> str:
    """Build the synthesis prompt from all agent outputs."""
    top_kws = sorted(keywords, key=lambda k: k.volume, reverse=True)[:5]
    top_pages = strategy.sci_rankings[:5]

    kw_lines = "\n".join(
        f"  - {k.keyword}: vol={k.volume:,}/mo, KD={k.kd}" for k in top_kws
    )
    page_lines = "\n".join(
        f"  - {p.path} → '{p.primary_keyword}' (SCI={p.sci:,.0f}, vol={p.volume:,}, KD={p.kd})"
        for p in top_pages
    )

    return f"""You are an expert SEO strategist. Analyse this SEO audit data for {domain} and provide actionable recommendations.

## Domain Authority
- Moz DA: {authority.moz_da}/100, Ahrefs DR: {authority.ahrefs_dr}/100
- Majestic TF: {authority.majestic_tf}, CF: {authority.majestic_cf}
- Backlinks: {authority.backlinks:,}, Referring Domains: {authority.ref_domains:,}
- Indexed Pages: {authority.indexed_pages} (CRITICAL: expected 221+)
- Organic Keywords: {authority.organic_keywords}

## Traffic
- Monthly Visits: {traffic.monthly_visits:,} (Similarweb)
- Top Keywords: {len(traffic.top_keywords)} tracked

## Crawlability — Severity: {crawlability.severity}
- SPA Confirmed: {crawlability.spa_confirmed}
- TBT: {crawlability.tbt_ms}ms, Unused JS: {crawlability.unused_js_kib} KiB
- Root Cause: {crawlability.root_cause}

## Top Keywords by Volume
{kw_lines}

## Top SCI-Ranked Pages
{page_lines}

## Quick Wins (KD<20, vol>1000)
{chr(10).join(f"  - {w}" for w in strategy.quick_wins[:5])}

Respond in this exact JSON format:
{{
  "executive_summary": "2-3 sentence summary of the site\'s SEO situation and biggest opportunity",
  "critical_blockers": ["blocker 1", "blocker 2", "blocker 3"],
  "top_3_actions": ["action 1 with specific detail", "action 2 with specific detail", "action 3 with specific detail"],
  "page_briefs": [
    {{
      "path": "/path",
      "keyword": "target keyword",
      "h1_suggestion": "Suggested H1 tag",
      "meta_description": "Suggested meta description (150-160 chars)",
      "content_angle": "What unique angle this page should take"
    }}
  ]
}}

Include page_briefs for the top 3 SCI pages only. Be specific and actionable."""


async def run(
    domain: str,
    authority: AuthorityResult,
    traffic: TrafficResult,
    crawlability: CrawlabilityResult,
    keywords: List[KeywordResult],
    strategy: StrategyResult,
    settings: Settings,
) -> Optional[LLMSynthesis]:
    """
    Call OpenRouter to synthesise all agent outputs into actionable briefs.
    Returns None if OPENROUTER_API_KEY is not set.
    """
    if not settings.openrouter_key:
        logger.warning("OPENROUTER_API_KEY not set — skipping LLM synthesis")
        return None

    prompt = _build_prompt(domain, authority, traffic, crawlability, keywords, strategy)

    headers = {
        "Authorization": f"Bearer {settings.openrouter_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": f"https://{domain}",
        "X-Title": "JEDI Labs SEO Audit",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{settings.openrouter_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    # Strip markdown code fences if present
                    content = content.strip()
                    if content.startswith("```"):
                        content = content.split("```")[1]
                        if content.startswith("json"):
                            content = content[4:]
                    parsed = json.loads(content.strip())
                    return LLMSynthesis(
                        executive_summary=parsed.get("executive_summary", ""),
                        critical_blockers=parsed.get("critical_blockers", []),
                        top_3_actions=parsed.get("top_3_actions", []),
                        page_briefs=parsed.get("page_briefs", []),
                        model_used=settings.openrouter_model,
                    )
                else:
                    text = await resp.text()
                    logger.error(f"OpenRouter {resp.status}: {text[:300]}")
                    return None
    except Exception as e:
        logger.error(f"LLM synthesis exception: {e}")
        return None
