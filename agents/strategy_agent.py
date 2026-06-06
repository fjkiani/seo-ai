"""
agents/strategy_agent.py
Computes ODI-normalised SCI scores for all page nodes.

ODI Normalization (Requirement 2):
  Google competition_index measures PPC ad-spend competition, NOT organic ranking
  difficulty. Raw competition_index overstates organic difficulty for low-budget
  niches and understates it for high-intent commercial terms.

  Normalization formula:
    PageSpeed_Impact_Score (PSI) = 1 - (desktop_performance / 100)
      → 0.0 = perfect site (no technical penalty)
      → 1.0 = completely broken site (maximum technical penalty)
      → Default = 0.30 if PageSpeed unavailable (conservative: assumes moderate debt)

    Estimated_ODI = (competition_index × 0.7) + (PSI × 0.3)
      → 0.7 weight: PPC competition is the primary organic difficulty proxy
      → 0.3 weight: site technical health affects ranking ability
      → ODI floor = 0.01 (avoid division by zero)
      → ODI range: 0.01–1.0 (multiply × 100 for human-readable display)

    SCI = (Volume × Relevance) / (ODI × Competitor_Score)
      → PATH A formula (signed Fahad Kiani 2026-04-28), ODI replaces raw KD

  jedilabs.org example ("enterprise AI solutions"):
    competition_index = 0.15, desktop_perf = 72 → PSI = 0.28
    ODI = (0.15 × 0.7) + (0.28 × 0.3) = 0.105 + 0.084 = 0.189
    SCI = (49,500 × 1.0) / (0.189 × 1.0) = 261,905

  Note: SCI absolute values are larger than KD-based SCI because ODI is 0–1 scale
  vs KD 0–100 scale. sci_normalized (0–100) is the comparable metric across runs.

SCI Formula governance: PATH A — signed by Fahad Kiani 2026-04-28.
"""
from typing import Any, Dict, List, Optional

from core.models import KeywordResult, PageNode, SCINode, StrategyResult

# Default JEDI Labs page inventory (14 core nodes)
DEFAULT_JEDI_PAGES: List[Dict[str, Any]] = [
    {"path": "/", "title": "JEDI Labs Home", "primary_keyword": "AI agents platform", "relevance": 0.9},
    {"path": "/solutions/enterprise-ai", "title": "Enterprise AI Solutions", "primary_keyword": "enterprise AI solutions", "relevance": 1.0},
    {"path": "/solutions/ai-agents", "title": "AI Agents", "primary_keyword": "AI agents platform", "relevance": 1.0},
    {"path": "/solutions/machine-learning", "title": "Machine Learning Platform", "primary_keyword": "machine learning platform", "relevance": 0.9},
    {"path": "/solutions/llm-orchestration", "title": "LLM Orchestration", "primary_keyword": "LLM orchestration", "relevance": 1.0},
    {"path": "/use-cases/enterprise-ai", "title": "Enterprise AI Use Cases", "primary_keyword": "AI solutions for enterprise", "relevance": 0.95},
    {"path": "/use-cases/automation", "title": "AI Automation Use Cases", "primary_keyword": "AI automation platform", "relevance": 0.9},
    {"path": "/use-cases/consulting", "title": "AI Consulting", "primary_keyword": "AI consulting services", "relevance": 0.85},
    {"path": "/technologies/multi-agent", "title": "Multi-Agent Systems", "primary_keyword": "multi-agent AI", "relevance": 1.0},
    {"path": "/technologies/llm", "title": "LLM Technology", "primary_keyword": "LLM orchestration", "relevance": 0.9},
    {"path": "/technologies/agent-framework", "title": "Agent Framework", "primary_keyword": "AI agent framework", "relevance": 1.0},
    {"path": "/about", "title": "About JEDI Labs", "primary_keyword": "AI consulting services", "relevance": 0.5},
    {"path": "/blog", "title": "JEDI Labs Blog", "primary_keyword": "enterprise AI solutions", "relevance": 0.6},
    {"path": "/contact", "title": "Contact", "primary_keyword": "AI consulting services", "relevance": 0.4},
]

PSI_DEFAULT = 0.30   # conservative default when PageSpeed is unavailable
ODI_FLOOR = 0.01     # minimum ODI to avoid division by zero


def _compute_psi(desktop_performance: Optional[int]) -> float:
    """
    PageSpeed Impact Score = 1 - (performance / 100).
    Returns PSI_DEFAULT (0.30) if performance is unavailable.
    """
    if desktop_performance is None:
        return PSI_DEFAULT
    return round(1.0 - (desktop_performance / 100.0), 4)


def _compute_odi(competition_index: float, psi: float) -> float:
    """
    Estimated_ODI = (competition_index × 0.7) + (PSI × 0.3)
    Clipped to [ODI_FLOOR, 1.0].
    """
    raw = (competition_index * 0.7) + (psi * 0.3)
    return round(max(raw, ODI_FLOOR), 4)


def _compute_sci(
    volume: int,
    relevance: float,
    odi: float,
    competitor_score: float,
) -> float:
    """
    SCI = (Volume × Relevance) / (ODI × Competitor_Score)
    PATH A formula — ODI replaces raw KD in denominator.
    """
    comp_safe = max(competitor_score, 1.0)
    return round((volume * relevance) / (odi * comp_safe), 2)


def run(
    keywords: List[KeywordResult],
    pages: List[PageNode],
    competitor_score: float = 1.0,
    desktop_performance: Optional[int] = None,
) -> StrategyResult:
    """
    Compute ODI-normalised SCI for all page nodes and generate strategy.

    Args:
        keywords: from KeywordAgent (includes competition_index)
        pages: page inventory (uses DEFAULT_JEDI_PAGES if empty)
        competitor_score: domain-level competitor pressure (default 1.0)
        desktop_performance: PageSpeed desktop score (0–100); None → PSI default
    """
    # Build keyword lookup: keyword → KeywordResult
    kw_lookup: Dict[str, KeywordResult] = {k.keyword.lower(): k for k in keywords}

    page_nodes = pages if pages else [PageNode(**p) for p in DEFAULT_JEDI_PAGES]

    # Compute PSI once — same site-wide technical debt for all pages
    psi = _compute_psi(desktop_performance)
    psi_source = "PageSpeed desktop" if desktop_performance is not None else f"default ({PSI_DEFAULT})"

    sci_nodes: List[SCINode] = []

    for page in page_nodes:
        kw_lower = page.primary_keyword.lower()
        kw_data = kw_lookup.get(kw_lower)

        if kw_data:
            volume = kw_data.volume
            kd = kw_data.kd
            ci = kw_data.competition_index or 0.0
        else:
            # Conservative defaults for unmapped keywords
            volume = 500
            kd = 10.0
            ci = 0.10

        # ODI normalization
        odi = _compute_odi(ci, psi)
        sci = _compute_sci(volume, page.relevance, odi, competitor_score)

        sci_nodes.append(SCINode(
            path=page.path,
            title=page.title,
            primary_keyword=page.primary_keyword,
            volume=volume,
            kd=kd,
            competition_index=ci,
            pagespeed_impact=psi,
            odi=odi,
            odi_display=round(odi * 100, 1),
            relevance=page.relevance,
            competitor_score=competitor_score,
            sci=sci,
            sci_normalized=0.0,  # filled after sorting
        ))

    # Sort by SCI descending
    sci_nodes.sort(key=lambda x: x.sci, reverse=True)

    # Compute sci_normalized (0–100 relative scale)
    max_sci = sci_nodes[0].sci if sci_nodes else 1.0
    for node in sci_nodes:
        node.sci_normalized = round((node.sci / max_sci) * 100, 1)

    # ── Top opportunities ─────────────────────────────────────────────────────
    top_opportunities = []
    for i, node in enumerate(sci_nodes[:5]):
        top_opportunities.append({
            "rank": i + 1,
            "path": node.path,
            "title": node.title,
            "keyword": node.primary_keyword,
            "volume": node.volume,
            "competition_index": node.competition_index,
            "odi": node.odi,
            "odi_display": node.odi_display,
            "sci": node.sci,
            "sci_normalized": node.sci_normalized,
            "action": _generate_action(node),
        })

    # ── Quick wins: ODI < 0.20 (≈ KD<20 equivalent) and volume > 1000 ────────
    quick_wins = [
        f"{n.path} → '{n.primary_keyword}' "
        f"(vol={n.volume:,}, ODI={n.odi_display}, SCI={n.sci:,.0f}, norm={n.sci_normalized})"
        for n in sci_nodes
        if n.odi < 0.20 and n.volume > 1000
    ]

    # ── 90-day plan ───────────────────────────────────────────────────────────
    top = sci_nodes[0] if sci_nodes else None
    second = sci_nodes[1] if len(sci_nodes) > 1 else None
    third = sci_nodes[2] if len(sci_nodes) > 2 else None

    ninety_day_plan = [
        {
            "phase": "Days 1–30: Fix Crawlability (Priority 0 — blocks everything else)",
            "actions": [
                "Add vike (vite-plugin-ssr) to vite.config.js for build-time SSG",
                "OR add prerender-spa-plugin as immediate bridge solution",
                "PAUSE sitemap submission until SSR is live (currently harmful)",
                "Generate and submit corrected XML sitemap after SSR is in place",
                "Add <meta name=\"description\"> to all page templates",
                "Set up Google Search Console — monitor indexation from day 1",
            ],
            "expected_outcome": "Google begins indexing all 221 pages. Organic keyword count rises from 0.",
        },
        {
            "phase": "Days 31–60: On-Page Optimisation for Top ODI-Normalised SCI Pages",
            "actions": [
                f"Optimise {top.path} for '{top.primary_keyword}' (ODI={top.odi_display}, SCI_norm={top.sci_normalized})" if top else "Optimise top SCI page",
                f"Optimise {second.path} for '{second.primary_keyword}' (ODI={second.odi_display}, SCI_norm={second.sci_normalized})" if second else "Optimise second SCI page",
                f"Optimise {third.path} for '{third.primary_keyword}' (ODI={third.odi_display}, SCI_norm={third.sci_normalized})" if third else "Optimise third SCI page",
                "Add JSON-LD SoftwareApplication schema to all solution + use-case pages",
                "Internal linking: connect all /technology/ pages to /solutions/ pages",
            ],
            "expected_outcome": "Top 3 ODI-normalised SCI pages begin appearing in Google for target keywords.",
        },
        {
            "phase": "Days 61–90: Authority + Content Moat",
            "actions": [
                "Publish 4 long-form blog posts targeting quick-win keywords (ODI<0.20)",
                "Build 10 high-quality backlinks via guest posts on AI/ML publications",
                "Launch TechDemoPanel interactive demos as linkable assets",
                "Create comparison pages: 'JEDI Labs vs [competitor]' for AI agent frameworks",
                "Submit to AI tool directories (Futurepedia, There\'s An AI For That, etc.)",
            ],
            "expected_outcome": "DA rises from 5 to 15+. First page rankings for ODI<0.20 keywords.",
        },
    ]

    odi_formula = (
        f"ODI = (competition_index × 0.7) + (PageSpeed_Impact × 0.3) | "
        f"PSI = 1 - ({desktop_performance}/100) = {psi} [{psi_source}] | "
        f"SCI = (Volume × Relevance) / (ODI × Competitor_Score)"
    )

    return StrategyResult(
        sci_rankings=sci_nodes,
        top_opportunities=top_opportunities,
        quick_wins=quick_wins,
        ninety_day_plan=ninety_day_plan,
        pagespeed_impact_used=psi,
        odi_formula=odi_formula,
    )


def _generate_action(node: SCINode) -> str:
    if node.odi < 0.10:
        urgency = "QUICK WIN"
    elif node.odi < 0.20:
        urgency = "HIGH PRIORITY"
    else:
        urgency = "MEDIUM PRIORITY"
    return (
        f"[{urgency}] H1 + meta targeting '{node.primary_keyword}'. "
        f"Ensure SSR renders full content. Add JSON-LD schema. "
        f"ODI={node.odi_display} (PPC_ci={node.competition_index}, PSI={node.pagespeed_impact})"
    )
