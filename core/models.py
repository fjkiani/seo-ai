"""
core/models.py — Pydantic models for all agent inputs/outputs.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    domain: str = Field(..., example="jedilabs.org")
    keywords: List[str] = Field(
        default=[
            "enterprise AI solutions",
            "AI agents platform",
            "AI agent framework",
            "AI automation platform",
            "AI consulting services",
            "LLM orchestration",
            "multi-agent AI",
            "AI solutions for enterprise",
        ]
    )
    pages: List[PageNode] = Field(default_factory=list)


class PageNode(BaseModel):
    path: str
    title: str
    primary_keyword: str
    relevance: float = 0.8


# ── Vite SPA Audit (Requirement 1) ───────────────────────────────────────────

class ViteSPAAudit(BaseModel):
    """
    Static code analysis of a Vite + React SPA repository.
    Fetched asynchronously from GitHub Raw Content API — no git clone.
    """
    repo: str
    branch: str
    files_inspected: List[str]

    # Core signals
    is_bare_spa: bool               # True if no pre-rendering plugins found
    routing_type: str               # "BrowserRouter" | "HashRouter" | "Unknown"
    pre_rendering_detected: bool    # True if vike/vite-ssg/prerender found
    pre_rendering_plugin: Optional[str]  # Name of plugin if found
    client_side_fetch_detected: bool     # Apollo/graphql-request/useQuery in deps
    sitemap_exists: bool            # vite-plugin-sitemap or generate-sitemap script
    sitemap_harmful: bool           # sitemap exists but no SSR = pointing Google at shells

    # Dynamic routes found (all invisible to Googlebot without SSR)
    dynamic_routes: List[str]       # e.g. ["/technology/:slug", "/solutions/:slug"]
    dynamic_route_count: int

    # Dependency signals
    deps_found: Dict[str, str]      # {dep_name: version} for notable deps

    # Verdict
    severity: str                   # "PASS" | "CRITICAL" | "HIGH" | "WARNING"
    verdict: str                    # human-readable diagnosis
    recommendations: List[str]


# ── Agent outputs ─────────────────────────────────────────────────────────────

class KeywordResult(BaseModel):
    keyword: str
    volume: int
    kd: float
    source: str
    competition_index: Optional[float] = None


class AuthorityResult(BaseModel):
    domain: str
    moz_da: int
    moz_pa: int
    ahrefs_dr: int
    majestic_tf: int
    majestic_cf: int
    backlinks: int
    ref_domains: int
    indexed_pages: int
    organic_keywords: int


class TrafficResult(BaseModel):
    domain: str
    monthly_visits: int
    top_keywords: List[Dict[str, Any]]
    snapshot_date: str


class TechnicalResult(BaseModel):
    url: str
    strategy: str
    performance: Optional[int]
    seo_score: Optional[int]
    accessibility: Optional[int]
    fcp_ms: Optional[float]
    lcp_ms: Optional[float]
    tbt_ms: Optional[float]
    unused_js_kib: Optional[float]
    spa_signal: bool
    status: int
    error: Optional[str] = None


class CrawlabilityResult(BaseModel):
    indexed_pages: int
    organic_keywords: int
    spa_confirmed: bool
    tbt_ms: Optional[float]
    unused_js_kib: Optional[float]
    severity: str               # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    root_cause: str
    fix_priority: int           # 0 = must fix before anything else
    recommendations: List[str]
    vite_audit: Optional[ViteSPAAudit] = None   # Req 1: real codebase analysis


class SCINode(BaseModel):
    path: str
    title: str
    primary_keyword: str
    volume: int
    kd: float                   # raw KD (kept for reference)
    competition_index: float    # Google PPC competition_index (0.0–1.0)
    pagespeed_impact: float     # 1 - (desktop_perf / 100); 0.3 default if unavailable
    odi: float                  # Estimated_ODI = (ci * 0.7) + (psi * 0.3)
    odi_display: float          # odi * 100 for human-readable scale
    relevance: float
    competitor_score: float
    sci: float                  # (Volume * Relevance) / (ODI * Competitor_Score)
    sci_normalized: float       # sci / max_sci * 100 — 0–100 relative scale


class StrategyResult(BaseModel):
    sci_rankings: List[SCINode]
    top_opportunities: List[Dict[str, Any]]
    quick_wins: List[str]
    ninety_day_plan: List[Dict[str, Any]]
    pagespeed_impact_used: float    # the PSI value used in ODI calculation
    odi_formula: str                # human-readable formula string


class LLMSynthesis(BaseModel):
    executive_summary: str
    critical_blockers: List[str]
    top_3_actions: List[str]
    page_briefs: List[Dict[str, Any]]
    model_used: str


# ── Full audit response ───────────────────────────────────────────────────────

class AuditResponse(BaseModel):
    domain: str
    audit_timestamp: str
    keywords: List[KeywordResult]
    authority: AuthorityResult
    traffic: TrafficResult
    technical: List[TechnicalResult]
    crawlability: CrawlabilityResult
    strategy: StrategyResult
    synthesis: Optional[LLMSynthesis] = None
    data_quality_notes: List[str] = Field(default_factory=list)
