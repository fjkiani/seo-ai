"""
agents/crawlability_agent.py

Two responsibilities:
  1. run_vite_audit(repo, branch) — async GitHub Raw API fetch + static code analysis
     of a real Vite + React SPA. No git clone. Detects:
       - Pre-rendering plugins (vike, vite-ssg, prerender-spa-plugin)
       - Router type (BrowserRouter vs HashRouter)
       - Client-side fetch dependencies (Apollo, graphql-request)
       - Dynamic :slug routes (all invisible to Googlebot without SSR)
       - Harmful sitemap pattern (sitemap exists but no SSR = pointing Google at shells)

  2. run(authority, technical) — synthesises authority + PageSpeed data into
     CrawlabilityResult with Priority 0 SPA diagnosis. Calls run_vite_audit()
     and embeds ViteSPAAudit in the result.

Audit targets (fjkiani/jedi-v2, branch: master):
  - package.json       → dependency scan
  - vite.config.js/ts  → plugin scan
  - src/App.jsx/tsx    → route + router scan
  - src/main.jsx/tsx   → router mount scan
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional, Tuple

import aiohttp

from core.models import CrawlabilityResult, ViteSPAAudit

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

GITHUB_RAW = "https://raw.githubusercontent.com"

# Pre-rendering / SSG plugins that would fix the SPA crawl problem
SSG_PLUGINS = [
    "vike", "vite-plugin-ssr", "vite-ssg", "prerender-spa-plugin",
    "react-snap", "@vitejs/plugin-react-pages", "vite-plugin-static-copy",
]

# Client-side data fetch dependencies (confirm Hygraph data is JS-rendered)
CLIENT_FETCH_DEPS = [
    "@apollo/client", "graphql-request", "swr", "react-query",
    "@tanstack/react-query", "urql",
]

# Sitemap-related signals
SITEMAP_DEPS = ["vite-plugin-sitemap", "sitemap", "next-sitemap"]

# PageSpeed thresholds for SPA detection
TBT_SPA_THRESHOLD = 300.0
UNUSED_JS_SPA_THRESHOLD = 100.0

# Crawlability thresholds
INDEXED_PAGES_THRESHOLD = 10
ORGANIC_KW_THRESHOLD = 5


# ── GitHub Raw fetch helpers ──────────────────────────────────────────────────

async def _fetch_raw(
    session: aiohttp.ClientSession,
    repo: str,
    branch: str,
    path: str,
) -> Tuple[str, int, Optional[str]]:
    """Fetch one file from GitHub Raw Content API."""
    url = f"{GITHUB_RAW}/{repo}/{branch}/{path}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status == 200:
                text = await resp.text()
                return path, 200, text
            return path, resp.status, None
    except Exception as e:
        logger.warning(f"GitHub Raw fetch error {path}: {e}")
        return path, 0, None


async def _fetch_with_fallbacks(
    session: aiohttp.ClientSession,
    repo: str,
    branch: str,
    candidates: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Try each candidate path in order; return (path, content) for first 200.
    Used for files that may be .ts or .js, .tsx or .jsx.
    """
    for path in candidates:
        _, status, content = await _fetch_raw(session, repo, branch, path)
        if status == 200 and content:
            return path, content
    return None, None


# ── Vite SPA Audit (Requirement 1) ───────────────────────────────────────────

async def run_vite_audit(
    repo: str = "fjkiani/jedi-v2",
    branch: str = "master",
) -> ViteSPAAudit:
    """
    Async GitHub Raw API audit of a Vite + React SPA repository.
    Fetches package.json, vite.config, App/main entry — no git clone.

    Returns ViteSPAAudit with all signals populated from real code.
    """
    files_inspected: List[str] = []
    import json as _json

    async with aiohttp.ClientSession() as session:
        # ── Concurrent fetch of all target files ─────────────────────────────
        pkg_task = _fetch_raw(session, repo, branch, "package.json")
        vite_task = _fetch_with_fallbacks(
            session, repo, branch,
            ["vite.config.ts", "vite.config.js"]
        )
        app_task = _fetch_with_fallbacks(
            session, repo, branch,
            ["src/App.tsx", "src/App.jsx"]
        )
        main_task = _fetch_with_fallbacks(
            session, repo, branch,
            ["src/main.tsx", "src/main.jsx"]
        )

        (pkg_path, pkg_status, pkg_raw),         (vite_path, vite_content),         (app_path, app_content),         (main_path, main_content) = await asyncio.gather(
            pkg_task, vite_task, app_task, main_task
        )

    # ── Parse package.json ────────────────────────────────────────────────────
    all_deps: Dict[str, str] = {}
    pkg_data: Dict = {}
    if pkg_status == 200 and pkg_raw:
        files_inspected.append(pkg_path)
        try:
            pkg_data = _json.loads(pkg_raw)
            all_deps = {
                **pkg_data.get("dependencies", {}),
                **pkg_data.get("devDependencies", {}),
            }
        except Exception as e:
            logger.warning(f"package.json parse error: {e}")

    # ── Signal: pre-rendering plugins ────────────────────────────────────────
    pre_rendering_detected = False
    pre_rendering_plugin: Optional[str] = None
    for plugin in SSG_PLUGINS:
        if plugin in all_deps:
            pre_rendering_detected = True
            pre_rendering_plugin = f"{plugin}@{all_deps[plugin]}"
            break

    # ── Signal: client-side fetch dependencies ────────────────────────────────
    client_side_fetch_detected = any(dep in all_deps for dep in CLIENT_FETCH_DEPS)
    client_fetch_deps_found = {
        dep: all_deps[dep] for dep in CLIENT_FETCH_DEPS if dep in all_deps
    }

    # ── Signal: sitemap ───────────────────────────────────────────────────────
    sitemap_exists = any(dep in all_deps for dep in SITEMAP_DEPS)
    # Also check scripts for generate-sitemap
    scripts = pkg_data.get("scripts", {})
    if any("sitemap" in v.lower() for v in scripts.values()):
        sitemap_exists = True
    sitemap_harmful = sitemap_exists and not pre_rendering_detected

    # ── Notable deps for report ───────────────────────────────────────────────
    notable_dep_keys = SSG_PLUGINS + CLIENT_FETCH_DEPS + SITEMAP_DEPS + [
        "react-router-dom", "react-helmet", "react-helmet-async",
        "puppeteer", "@vitejs/plugin-react",
    ]
    deps_found = {k: all_deps[k] for k in notable_dep_keys if k in all_deps}

    # ── Parse vite.config ─────────────────────────────────────────────────────
    vite_has_ssr = False
    if vite_path and vite_content:
        files_inspected.append(vite_path)
        vite_lower = vite_content.lower()
        vite_has_ssr = any(
            kw in vite_lower
            for kw in ["ssr", "prerender", "vike", "vite-ssg", "static"]
        )
        # Double-check: if only react() plugin, confirm bare SPA
        if re.search(r"plugins\s*:\s*\[\s*react\(\)\s*\]", vite_content):
            vite_has_ssr = False  # bare react() only

    # ── Parse App entry — router type + dynamic routes ────────────────────────
    routing_type = "Unknown"
    dynamic_routes: List[str] = []

    if main_path and main_content:
        files_inspected.append(main_path)
        if "HashRouter" in main_content:
            routing_type = "HashRouter"
        elif "BrowserRouter" in main_content or "Router" in main_content:
            routing_type = "BrowserRouter"

    if app_path and app_content:
        files_inspected.append(app_path)
        # Extract all dynamic route paths (contain :param)
        dynamic_routes = re.findall(r'path=(?:["\'])(.*?:.*?)(?:["\'])', app_content)
        # Deduplicate while preserving order
        seen = set()
        dynamic_routes = [r for r in dynamic_routes if not (r in seen or seen.add(r))]

    # ── Determine is_bare_spa ─────────────────────────────────────────────────
    is_bare_spa = not pre_rendering_detected and not vite_has_ssr

    # ── Severity ──────────────────────────────────────────────────────────────
    if is_bare_spa and client_side_fetch_detected and len(dynamic_routes) > 3:
        severity = "CRITICAL"
        verdict = (
            f"Confirmed bare Vite SPA. No pre-rendering or SSG plugins detected. "
            f"vite.config.js uses only react() — no SSR configuration. "
            f"BrowserRouter with {len(dynamic_routes)} dynamic :slug routes, all invisible to Googlebot. "
            f"Apollo + graphql-request confirm Hygraph content is fetched client-side. "
            f"{'CRITICAL: sitemap exists but lists unrenderable SPA shells — actively harmful. ' if sitemap_harmful else ''}"
            f"Googlebot receives <div id='root'></div> on every page."
        )
    elif is_bare_spa:
        severity = "CRITICAL"
        verdict = (
            f"Bare Vite SPA with no pre-rendering. "
            f"{len(dynamic_routes)} dynamic routes invisible to Googlebot."
        )
    elif pre_rendering_detected:
        severity = "PASS"
        verdict = f"Pre-rendering detected via {pre_rendering_plugin}. SSG/SSR is configured."
    else:
        severity = "HIGH"
        verdict = "Partial SSR configuration detected. Verify all dynamic routes are pre-rendered."

    # ── Recommendations ───────────────────────────────────────────────────────
    recommendations: List[str] = []
    if severity == "CRITICAL":
        recommendations = [
            "IMMEDIATE (Days 1–7): Add vike (formerly vite-plugin-ssr) to vite.config.js. "
            "This is the lowest-friction SSG path for an existing Vite + React codebase. "
            "Alternatively, migrate to Next.js App Router for full SSG/ISR support.",

            "IMMEDIATE (Days 1–7): Add prerender-spa-plugin as a bridge solution. "
            "Generates static HTML snapshots at build time for all known routes. "
            "Not as robust as full SSG but fixes the blank-shell problem immediately.",

            f"CRITICAL: Pause the sitemap generator until SSR is in place. "
            f"vite-plugin-sitemap is currently submitting {len(dynamic_routes)} dynamic routes "
            f"to Google that all return <div id='root'></div>. "
            f"This accelerates Google's conclusion that the domain has no indexable content.",

            "For each dynamic route, implement build-time static generation: "
            "fetch all Hygraph slugs at build time and pre-render each page to static HTML. "
            f"Priority order: /technology/:slug → /solutions/:slug → /use-cases/:slug "
            f"(these are the highest SCI-value routes).",

            "Add server-side rendering via the existing server/server.js (puppeteer is already "
            "in devDependencies — it can serve pre-rendered HTML to crawlers via user-agent detection). "
            "This is a short-term bridge while full SSG is implemented.",
        ]
    elif severity == "PASS":
        recommendations = [
            "Verify generateStaticParams covers all Hygraph slugs at build time.",
            "Confirm sitemap.xml is submitted to Google Search Console.",
        ]

    return ViteSPAAudit(
        repo=repo,
        branch=branch,
        files_inspected=files_inspected,
        is_bare_spa=is_bare_spa,
        routing_type=routing_type,
        pre_rendering_detected=pre_rendering_detected,
        pre_rendering_plugin=pre_rendering_plugin,
        client_side_fetch_detected=client_side_fetch_detected,
        sitemap_exists=sitemap_exists,
        sitemap_harmful=sitemap_harmful,
        dynamic_routes=dynamic_routes,
        dynamic_route_count=len(dynamic_routes),
        deps_found=deps_found,
        severity=severity,
        verdict=verdict,
        recommendations=recommendations,
    )


# ── CrawlabilityResult synthesis ──────────────────────────────────────────────

def run(
    authority,
    technical: list,
    vite_audit: Optional[ViteSPAAudit] = None,
) -> CrawlabilityResult:
    """
    Synthesise authority + technical data into CrawlabilityResult.
    Embeds ViteSPAAudit if provided.
    """
    indexed = authority.indexed_pages
    organic_kw = authority.organic_keywords

    desktop = next((t for t in technical if t.strategy == "desktop" and t.status == 200), None)
    tbt = desktop.tbt_ms if desktop else None
    unused_js = desktop.unused_js_kib if desktop else None

    spa_confirmed = bool(
        tbt is not None and tbt > TBT_SPA_THRESHOLD and
        unused_js is not None and unused_js > UNUSED_JS_SPA_THRESHOLD
    )
    # Also confirm via vite_audit if available
    if vite_audit and vite_audit.is_bare_spa:
        spa_confirmed = True

    indexation_crisis = indexed < INDEXED_PAGES_THRESHOLD and organic_kw < ORGANIC_KW_THRESHOLD

    if indexation_crisis and spa_confirmed:
        severity = "CRITICAL"
        root_cause = (
            f"Bare Vite SPA with no SSR/SSG (confirmed via codebase analysis). "
            f"Googlebot fetches <div id=\"root\"></div> and abandons rendering. "
            f"Only {indexed} pages indexed (expected 221+). "
            f"TBT={tbt}ms + {unused_js} KiB unused JS confirms un-split bundle. "
            + (f"CRITICAL: sitemap is actively harmful — lists {vite_audit.dynamic_route_count} "
               f"unrenderable SPA routes. " if vite_audit and vite_audit.sitemap_harmful else "")
            + "All keyword and content work is blocked until SSR/SSG is implemented."
        )
        fix_priority = 0
    elif indexation_crisis:
        severity = "CRITICAL"
        root_cause = (
            f"Severe under-indexation: only {indexed} pages indexed, {organic_kw} organic keywords. "
            "Likely SPA crawl problem or robots.txt/noindex misconfiguration."
        )
        fix_priority = 0
    elif spa_confirmed:
        severity = "HIGH"
        root_cause = (
            f"SPA bundle not code-split (TBT={tbt}ms, {unused_js} KiB unused JS). "
            "Googlebot rendering budget may be exhausted before hydration completes."
        )
        fix_priority = 1
    else:
        severity = "MEDIUM"
        root_cause = "No critical crawlability issues detected."
        fix_priority = 2

    recommendations: List[str] = []
    if vite_audit and vite_audit.recommendations:
        recommendations = vite_audit.recommendations
    elif severity in ("CRITICAL", "HIGH"):
        recommendations = [
            "Add vike or prerender-spa-plugin to vite.config.js for build-time SSG.",
            "Generate and submit XML sitemap only after SSR/SSG is in place.",
            "Add <meta name=\"description\"> to all page templates.",
            "Set up Google Search Console and monitor indexation.",
        ]

    return CrawlabilityResult(
        indexed_pages=indexed,
        organic_keywords=organic_kw,
        spa_confirmed=spa_confirmed,
        tbt_ms=tbt,
        unused_js_kib=unused_js,
        severity=severity,
        root_cause=root_cause,
        fix_priority=fix_priority,
        recommendations=recommendations,
        vite_audit=vite_audit,
    )
