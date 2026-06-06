"""
main.py — JEDI Labs SEO Intelligence API
FastAPI multi-agent orchestrator for SEO auditing.

Architecture:
  Tier 1 (asyncio.gather): KeywordAgent + AuthorityAgent + TrafficAgent + ViteAudit — concurrent
  Tier 2 (inline):         TechnicalAgent desktop (blocking, primary signal)
  Tier 3 (BackgroundTask): TechnicalAgent mobile (non-blocking, rate-limit safe)
  Tier 4 (compute):        CrawlabilityAgent (embeds ViteSPAAudit) + StrategyAgent (ODI-normalised SCI)
  Tier 5 (inline):         LLMAgent (OpenRouter synthesis, optional)

New agents (v3):
  OnPageAgent    — LibreCrawl SEOExtractor + IssueDetector (12 check categories)
  SecurityAgent  — HTTP security headers audit (7 headers, HTTPS, score/grade)
  ContentGapAgent — DuckDuckGo SERP + async scrape + NLTK keyword extraction

Usage:
  uvicorn main:app --reload --port 8000
  curl http://localhost:8000/audit/jedilabs.org
  curl http://localhost:8000/onpage/jedilabs.org
  curl http://localhost:8000/security/jedilabs.org
  curl http://localhost:8000/content-gap?keyword=enterprise+AI+solutions&domain=jedilabs.org
  curl http://localhost:8000/health
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents import (
    authority_agent,
    crawlability_agent,
    keyword_agent,
    llm_agent,
    strategy_agent,
    technical_agent,
    traffic_agent,
)
from agents.onpage_agent import run_onpage_audit
from agents.security_agent import run_security_audit
from agents.content_gap_agent import run_content_gap_analysis
from core.config import get_settings
from core.models import AuditRequest, AuditResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="JEDI Labs SEO Intelligence API",
    description=(
        "Multi-agent SEO audit framework. "
        "Tier 1: concurrent keyword+authority+traffic+ViteAudit. "
        "Tier 2: PageSpeed desktop. Tier 3: PageSpeed mobile (background). "
        "Tier 4: CrawlabilityAgent (ViteSPAAudit) + StrategyAgent (ODI-normalised SCI). "
        "Tier 5: OpenRouter LLM synthesis. "
        "v3: OnPageAgent + SecurityAgent + ContentGapAgent."
    ),
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for background mobile PageSpeed results
_mobile_results: dict = {}


# ── Background worker: mobile PageSpeed ───────────────────────────────────────
async def _run_mobile_pagespeed(domain: str) -> None:
    """Non-blocking background task for mobile PageSpeed."""
    try:
        settings = get_settings()
        result = await technical_agent.run_mobile(domain, settings)
        _mobile_results[domain] = result.model_dump()
        logger.info(f"Mobile PageSpeed complete for {domain}: perf={result.performance}")
    except Exception as e:
        logger.error(f"Mobile PageSpeed background error for {domain}: {e}")
        _mobile_results[domain] = {"error": str(e), "strategy": "mobile", "status": 0}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — confirms API key is loaded."""
    try:
        settings = get_settings()
        return {
            "status": "ok",
            "rapidapi_key_set": bool(settings.rapidapi_key),
            "openrouter_key_set": bool(settings.openrouter_key),
            "version": "3.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── NEW: OnPage Audit ─────────────────────────────────────────────────────────

@app.get("/onpage/{domain}")
async def onpage_audit(domain: str):
    """
    On-page SEO audit for a domain.
    Fetches homepage HTML, extracts SEO signals, runs 12-category issue detection.

    GET /onpage/jedilabs.org

    Returns:
      - page_data: title, meta, h1/h2/h3, word_count, canonical, og_tags, twitter_tags,
                   json_ld, analytics, images, internal/external links, hreflang, schema_org
      - issues: list of {type, category, issue, details}
      - summary: {total, errors, warnings, infos, is_spa}
    """
    logger.info(f"OnPage audit: {domain}")
    result = await run_onpage_audit(domain)
    if "error" in result and result["error"]:
        logger.warning(f"OnPage audit error for {domain}: {result['error']}")
    return result


# ── NEW: Security Headers Audit ───────────────────────────────────────────────

@app.get("/security/{domain}")
async def security_audit(domain: str):
    """
    HTTP security headers audit for a domain.
    Checks 7 security headers + HTTPS + HTTP→HTTPS redirect.

    GET /security/jedilabs.org

    Returns:
      - headers_present: dict of security headers found
      - headers_missing: list of {header, severity, description, recommendation}
      - info_headers: {server, x-powered-by, ...} (fingerprinting signals)
      - https: bool
      - redirects_to_https: bool
      - score: 0-100
      - grade: A+/A/B/C/D/F
      - issues: sorted by severity (critical → high → medium → low)
    """
    logger.info(f"Security audit: {domain}")
    result = await run_security_audit(domain)
    return result


# ── NEW: Content Gap Analysis ─────────────────────────────────────────────────

@app.get("/content-gap")
async def content_gap(
    keyword: str = Query(..., description="Search keyword to analyze"),
    domain: Optional[str] = Query(None, description="Target domain to check SERP position"),
):
    """
    Content gap analysis for a keyword.
    Scrapes top DuckDuckGo SERP results, extracts headings + keywords via NLTK.

    GET /content-gap?keyword=enterprise+AI+solutions&domain=jedilabs.org

    Returns:
      - serp_urls: top URLs found
      - content_info: per-article {url, title, total_words, headings, keywords}
      - top_keywords: aggregated top 15 keywords across all results
      - average_words: average word count
      - target_in_serp: bool (if domain provided)
      - target_serp_position: int or None
      - content_gap: keywords in top results not in target domain
    """
    logger.info(f"Content gap: keyword='{keyword}' domain={domain}")
    result = await run_content_gap_analysis(keyword, target_domain=domain)
    return result


# ── NEW: Full Audit v3 (adds onpage + security in Tier 1) ────────────────────

@app.get("/audit-v3/{domain}")
async def run_audit_v3(
    background_tasks: BackgroundTasks,
    domain: str = "jedilabs.org",
    vite_repo: str = "fjkiani/jedi-v2",
    vite_branch: str = "master",
):
    """
    Full SEO audit v3 — adds OnPage + Security to Tier 1 concurrent gather.

    GET /audit-v3/jedilabs.org

    Tier 1 (concurrent): Keyword + Authority + Traffic + ViteAudit + OnPage + Security
    Tier 2 (inline):     Desktop PageSpeed
    Tier 3 (background): Mobile PageSpeed
    Tier 4 (compute):    Crawlability + Strategy (ODI SCI)
    Tier 5 (optional):   LLM synthesis
    """
    settings = get_settings()
    keywords = AuditRequest.__fields__["keywords"].default
    pages = []

    logger.info(f"Starting audit-v3 for {domain}")
    audit_start = datetime.now(timezone.utc)

    # Tier 1: All concurrent agents
    logger.info("Tier 1: keyword + authority + traffic + ViteAudit + OnPage + Security (concurrent)")
    (
        keyword_results,
        authority_result,
        traffic_result,
        vite_audit,
        onpage_result,
        security_result,
    ) = await asyncio.gather(
        keyword_agent.run(keywords, settings),
        authority_agent.run(domain, settings),
        traffic_agent.run(domain, settings),
        crawlability_agent.run_vite_audit(repo=vite_repo, branch=vite_branch),
        run_onpage_audit(domain),
        run_security_audit(domain),
    )

    # Tier 2: Desktop PageSpeed
    logger.info("Tier 2: Desktop PageSpeed")
    desktop_result = await technical_agent.run_desktop(domain, settings)

    # Tier 3: Mobile PageSpeed (background)
    background_tasks.add_task(_run_mobile_pagespeed, domain)
    technical_results = [desktop_result]

    # Tier 4: Crawlability + Strategy
    crawlability_result = crawlability_agent.run(
        authority_result, technical_results, vite_audit=vite_audit,
    )
    strategy_result = strategy_agent.run(
        keyword_results, pages,
        competitor_score=1.0,
        desktop_performance=desktop_result.performance,
    )

    # Tier 5: LLM synthesis
    synthesis = await llm_agent.run(
        domain, authority_result, traffic_result,
        crawlability_result, keyword_results, strategy_result, settings,
    )

    # Build response
    data_quality_notes = []
    if vite_audit.is_bare_spa:
        data_quality_notes.append(
            f"ViteSPAAudit [{vite_repo}@{vite_branch}]: BARE SPA confirmed. "
            f"{vite_audit.dynamic_route_count} dynamic routes invisible to Googlebot."
        )
    if onpage_result.get("summary", {}).get("is_spa"):
        data_quality_notes.append(
            f"OnPage: SPA confirmed — only {onpage_result['page_data'].get('word_count', 0)} words in HTML shell."
        )
    if security_result.get("grade") in ("D", "F"):
        data_quality_notes.append(
            f"Security: Grade {security_result.get('grade')} — {len(security_result.get('headers_missing', []))} security headers missing."
        )

    return {
        "domain": domain,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "keywords": [k.model_dump() for k in keyword_results],
        "authority": authority_result.model_dump(),
        "traffic": traffic_result.model_dump(),
        "technical": [t.model_dump() for t in technical_results],
        "crawlability": crawlability_result.model_dump(),
        "strategy": strategy_result.model_dump(),
        "onpage": onpage_result,
        "security": security_result,
        "synthesis": synthesis,
        "data_quality_notes": data_quality_notes,
    }


# ── Original /audit endpoint (unchanged) ─────────────────────────────────────

@app.get("/vite-audit/{owner}/{repo}")
async def vite_audit_endpoint(owner: str, repo: str, branch: str = "master"):
    """Standalone Vite SPA audit endpoint."""
    full_repo = f"{owner}/{repo}"
    logger.info(f"Running ViteSPAAudit for {full_repo}@{branch}")
    audit = await crawlability_agent.run_vite_audit(repo=full_repo, branch=branch)
    return audit.model_dump()


@app.post("/audit", response_model=AuditResponse)
@app.get("/audit/{domain}", response_model=AuditResponse)
async def run_audit(
    background_tasks: BackgroundTasks,
    domain: str = "jedilabs.org",
    body: Optional[AuditRequest] = None,
    vite_repo: str = "fjkiani/jedi-v2",
    vite_branch: str = "master",
) -> AuditResponse:
    """Run full SEO audit (v2 — original endpoint, unchanged)."""
    settings = get_settings()

    if body:
        domain = body.domain
        keywords = body.keywords
        pages = body.pages
    else:
        keywords = AuditRequest.__fields__["keywords"].default
        pages = []

    logger.info(f"Starting audit for {domain} | vite_repo={vite_repo}@{vite_branch}")

    (
        keyword_results,
        authority_result,
        traffic_result,
        vite_audit,
    ) = await asyncio.gather(
        keyword_agent.run(keywords, settings),
        authority_agent.run(domain, settings),
        traffic_agent.run(domain, settings),
        crawlability_agent.run_vite_audit(repo=vite_repo, branch=vite_branch),
    )

    desktop_result = await technical_agent.run_desktop(domain, settings)
    background_tasks.add_task(_run_mobile_pagespeed, domain)
    technical_results = [desktop_result]

    crawlability_result = crawlability_agent.run(
        authority_result, technical_results, vite_audit=vite_audit,
    )
    strategy_result = strategy_agent.run(
        keyword_results, pages,
        competitor_score=1.0,
        desktop_performance=desktop_result.performance,
    )

    synthesis = await llm_agent.run(
        domain, authority_result, traffic_result,
        crawlability_result, keyword_results, strategy_result, settings,
    )

    data_quality_notes = []
    if vite_audit.is_bare_spa:
        data_quality_notes.append(
            f"ViteSPAAudit [{vite_repo}@{vite_branch}]: BARE SPA confirmed. "
            f"No pre-rendering plugins. {vite_audit.dynamic_route_count} dynamic routes invisible to Googlebot."
        )
    if vite_audit.sitemap_harmful:
        data_quality_notes.append(
            "HARMFUL SITEMAP: vite-plugin-sitemap is submitting unrenderable SPA routes to Google."
        )
    if traffic_result.monthly_visits == 0:
        data_quality_notes.append("Similarweb: 0 monthly visits — site below 5K/mo measurement threshold.")
    if authority_result.indexed_pages < 10:
        data_quality_notes.append(f"Only {authority_result.indexed_pages} pages indexed. SPA crawl problem confirmed.")
    kd_zero = [k for k in keyword_results if k.kd == 0.0]
    if kd_zero:
        data_quality_notes.append(f"Semrush KD=0 for {len(kd_zero)} keywords — unreliable.")
    data_quality_notes.append(f"ODI formula: {strategy_result.odi_formula}")

    return AuditResponse(
        domain=domain,
        audit_timestamp=datetime.now(timezone.utc).isoformat(),
        keywords=keyword_results,
        authority=authority_result,
        traffic=traffic_result,
        technical=technical_results,
        crawlability=crawlability_result,
        strategy=strategy_result,
        synthesis=synthesis,
        data_quality_notes=data_quality_notes,
    )


@app.get("/mobile-result/{domain}")
async def get_mobile_result(domain: str):
    """Poll for background mobile PageSpeed result."""
    result = _mobile_results.get(domain)
    if result is None:
        return JSONResponse(
            status_code=202,
            content={"status": "pending", "message": "Mobile PageSpeed still running"},
        )
    return result


@app.get("/sci/{domain}")
async def get_sci_rankings(domain: str = "jedilabs.org", desktop_performance: Optional[int] = None):
    """Quick ODI-normalised SCI ranking endpoint."""
    settings = get_settings()
    keywords_list = [
        "enterprise AI solutions", "AI agents platform", "AI agent framework",
        "AI automation platform", "AI consulting services", "LLM orchestration",
        "multi-agent AI", "AI solutions for enterprise",
    ]
    kw_results = await keyword_agent.run(keywords_list, settings)
    strategy = strategy_agent.run(kw_results, [], desktop_performance=desktop_performance)
    return {
        "domain": domain,
        "odi_formula": strategy.odi_formula,
        "pagespeed_impact_used": strategy.pagespeed_impact_used,
        "sci_rankings": [n.model_dump() for n in strategy.sci_rankings],
        "top_opportunities": strategy.top_opportunities,
        "quick_wins": strategy.quick_wins,
    }


# =============================================================================
# LangGraph Async Audit Endpoints (v4)
# =============================================================================
# Architecture:
#   POST /api/v1/audit-graph        → INSERT seo_audit_queue (pending) → {run_id}
#   GET  /api/v1/audit-graph/{run_id}/status → SELECT status + routing_path
#   GET  /api/v1/audit-graph/{run_id}/stream → SSE: node events + thinking tokens
#
# The GraphWorker (graph/worker.py) polls seo_audit_queue independently.
# These endpoints are pure DB reads/writes — they never touch the graph directly.
# =============================================================================

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from graph.worker import GraphWorker

# ── DB pool for FastAPI endpoints (separate from worker pool) ─────────────────
# This pool lives in the FastAPI event loop. The worker has its own pool
# in its own event loop. They never share a pool.
_api_pool: asyncpg.Pool | None = None
_graph_worker: GraphWorker | None = None


async def _get_api_pool() -> asyncpg.Pool:
    global _api_pool
    if _api_pool is None:
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable not set")
        _api_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    return _api_pool


# ── Lifespan: start/stop GraphWorker ─────────────────────────────────────────
# Replace the existing app = FastAPI(...) startup with lifespan context manager.
# We patch the existing app's lifespan here rather than rewriting the whole file.

@asynccontextmanager
async def _graph_lifespan(app):
    """Start GraphWorker on startup, stop it gracefully on shutdown."""
    global _graph_worker
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        _graph_worker = GraphWorker(db_url=database_url)
        _graph_worker.start()
        logger.info("GraphWorker started")
    else:
        logger.warning("DATABASE_URL not set — GraphWorker not started")
    yield
    if _graph_worker is not None:
        logger.info("Stopping GraphWorker (timeout=30s)...")
        _graph_worker.stop(timeout=30)
        logger.info("GraphWorker stopped")
    if _api_pool is not None:
        await _api_pool.close()


# Attach lifespan to the existing app
app.router.lifespan_context = _graph_lifespan


# ── Request / Response models ─────────────────────────────────────────────────

class AuditGraphRequest(BaseModel):
    domain: str
    keywords: list[str] = []
    tenant_id: str = "default"
    workspace_id: str = "default"


class AuditGraphSubmitResponse(BaseModel):
    run_id: str
    status: str = "pending"


class AuditGraphStatusResponse(BaseModel):
    run_id: str
    status: str
    routing_path: list[str]
    loop_counter: int
    client_report: str | None
    error_message: str | None


# ── POST /api/v1/audit-graph ──────────────────────────────────────────────────

@app.post("/api/v1/audit-graph", response_model=AuditGraphSubmitResponse)
async def submit_audit_graph(body: AuditGraphRequest):
    """
    Submit a new LangGraph SEO audit job.

    Inserts a row into seo_audit_queue with status='pending'.
    The GraphWorker picks it up within POLL_INTERVAL_SECONDS (2s).
    Returns run_id immediately — no blocking, no 60s timeout risk.
    """
    run_id = str(uuid.uuid4())
    pool = await _get_api_pool()

    await pool.execute(
        """
        INSERT INTO seo_audit_queue
            (run_id, domain, tenant_id, workspace_id, keywords_json, status, created_at, updated_at)
        VALUES
            ($1, $2, $3, $4, $5, 'pending', NOW(), NOW())
        """,
        run_id,
        body.domain,
        body.tenant_id,
        body.workspace_id,
        json.dumps(body.keywords),
    )

    logger.info("audit-graph submitted run_id=%s domain=%s", run_id, body.domain)
    return AuditGraphSubmitResponse(run_id=run_id)


# ── GET /api/v1/audit-graph/{run_id}/status ───────────────────────────────────

@app.get("/api/v1/audit-graph/{run_id}/status", response_model=AuditGraphStatusResponse)
async def get_audit_graph_status(run_id: str):
    """
    Poll the status of a LangGraph audit job.

    The React frontend calls this every 2s via useAuditGraph's refetchInterval.
    Returns routing_path[] so the UI can render the live node feed.
    """
    pool = await _get_api_pool()

    row = await pool.fetchrow(
        """
        SELECT run_id, status, routing_path, loop_counter,
               client_report, error_message
        FROM seo_audit_queue
        WHERE run_id = $1
        """,
        run_id,
    )

    if row is None:
        raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

    return AuditGraphStatusResponse(
        run_id=row["run_id"],
        status=row["status"],
        routing_path=list(row["routing_path"] or []),
        loop_counter=row["loop_counter"] or 0,
        client_report=row["client_report"],
        error_message=row["error_message"],
    )


# ── GET /api/v1/audit-graph/{run_id}/stream ───────────────────────────────────
# SSE stream: emits node lifecycle events and Nemotron thinking tokens.
# The React AuditStream component subscribes to this via native EventSource.
#
# Event types:
#   node_start    { node, timestamp }
#   thinking      { node, text }        ← incremental Nemotron tokens
#   node_complete { node, timestamp }
#   done          { client_report }
#   error         { message }
#
# Implementation: polls seo_audit_queue + seo_graph_checkpoints every 1.5s.
# The checkpoint JSONB contains the latest AuditState — we diff it against
# the previous state to emit node_start / node_complete events.
# Nemotron thinking tokens are stored in checkpoint metadata as they stream.

@app.get("/api/v1/audit-graph/{run_id}/stream")
async def stream_audit_graph(run_id: str, request: Request):
    """
    SSE stream for a LangGraph audit run.
    Connects the Nemotron thinking panel in the React frontend.
    """
    pool = await _get_api_pool()

    async def event_generator():
        prev_routing_path: list[str] = []
        prev_thinking: dict[str, str] = {}  # node → accumulated text
        poll_interval = 1.5
        max_polls = 240  # 6 minutes max stream duration

        for _ in range(max_polls):
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                row = await pool.fetchrow(
                    """
                    SELECT status, routing_path, loop_counter,
                           client_report, error_message, graph_state_json
                    FROM seo_audit_queue
                    WHERE run_id = $1
                    """,
                    run_id,
                )
            except Exception as e:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": str(e)}),
                }
                return

            if row is None:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": f"run_id {run_id} not found"}),
                }
                return

            current_path: list[str] = list(row["routing_path"] or [])
            status: str = row["status"]

            # ── Emit node_start / node_complete for new path entries ──────────
            new_nodes = current_path[len(prev_routing_path):]
            for node in new_nodes:
                # The previous last node just completed
                if prev_routing_path:
                    yield {
                        "event": "node_complete",
                        "data": json.dumps({
                            "node": prev_routing_path[-1],
                            "timestamp": _now_iso(),
                        }),
                    }
                # New node starting
                yield {
                    "event": "node_start",
                    "data": json.dumps({
                        "node": node,
                        "timestamp": _now_iso(),
                    }),
                }
            prev_routing_path = current_path

            # ── Emit thinking tokens from graph_state_json ────────────────────
            # The worker writes incremental Nemotron output to graph_state_json
            # as nodes execute. We diff against prev_thinking to emit only new text.
            if row["graph_state_json"]:
                try:
                    state_json = row["graph_state_json"]
                    if isinstance(state_json, str):
                        state_json = json.loads(state_json)

                    # thinking_stream: { node_name: accumulated_text }
                    thinking_stream: dict = state_json.get("thinking_stream", {})
                    for node, full_text in thinking_stream.items():
                        already_sent = prev_thinking.get(node, "")
                        new_text = full_text[len(already_sent):]
                        if new_text:
                            yield {
                                "event": "thinking",
                                "data": json.dumps({
                                    "node": node,
                                    "text": new_text,
                                }),
                            }
                            prev_thinking[node] = full_text
                except Exception:
                    pass  # Don't crash the stream on state parse errors

            # ── Terminal states ───────────────────────────────────────────────
            if status == "completed":
                # Complete the last node
                if current_path:
                    yield {
                        "event": "node_complete",
                        "data": json.dumps({
                            "node": current_path[-1],
                            "timestamp": _now_iso(),
                        }),
                    }
                yield {
                    "event": "done",
                    "data": json.dumps({
                        "client_report": row["client_report"] or "",
                    }),
                }
                return

            if status == "failed":
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": row["error_message"] or "Audit failed",
                    }),
                }
                return

            await asyncio.sleep(poll_interval)

        # Timeout
        yield {
            "event": "error",
            "data": json.dumps({"message": "Stream timeout — poll /status for final result"}),
        }

    return EventSourceResponse(event_generator())


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
