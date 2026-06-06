# seo-ai

FastAPI multi-agent SEO intelligence backend + LangGraph audit orchestrator.

## What this is

Two layers:

### Layer 1 — Multi-agent FastAPI (`main.py`)
Stateless REST API. Each request runs all agents concurrently and returns a full audit result.

**Endpoints:**
- `GET /audit/{domain}` — full SEO audit (keyword + authority + traffic + crawlability + strategy + LLM synthesis)
- `GET /audit-v3/{domain}` — v3 adds OnPage + Security agents in Tier 1
- `GET /onpage/{domain}` — on-page SEO: title, meta, H1, canonical, OG tags, JSON-LD, 12-category issue detection
- `GET /security/{domain}` — HTTP security headers audit (7 headers, HTTPS, score 0-100, grade A+→F)
- `GET /content-gap?keyword=...&domain=...` — DuckDuckGo SERP scrape + NLTK keyword extraction
- `GET /vite-audit/{owner}/{repo}` — Vite SPA audit (detects bare SPA, dynamic routes invisible to Googlebot)
- `GET /health` — confirms API keys loaded

**Agents:**
| Agent | What it does |
|---|---|
| `keyword_agent` | Semrush + Google Keyword Insight via RapidAPI, falls back to seed data |
| `authority_agent` | Domain authority, backlink profile |
| `traffic_agent` | Organic traffic estimates |
| `technical_agent` | PageSpeed desktop (inline) + mobile (background task) |
| `crawlability_agent` | Vite SPA detection, ODI normalization, SCI rankings |
| `strategy_agent` | ODI-normalized SCI score, quick wins, content calendar |
| `llm_agent` | OpenRouter synthesis (Llama 3.3 70B) |
| `onpage_agent` | LibreCrawl SEOExtractor, 12-category issue detection |
| `security_agent` | 7 security headers, HTTPS check, grade |
| `content_gap_agent` | SERP scrape, NLTK unigrams/bigrams/trigrams |

### Layer 2 — LangGraph worker (`graph/`)
Async graph execution with Postgres checkpointing. Runs as a background thread alongside FastAPI.

**Graph nodes (9):**
1. `gather_node` — runs all 5 agents concurrently via `asyncio.gather`
2. `technical_node` — desktop + crawlability concurrent
3. `supervisor_node` — Llama 3.3 70B routes to fix node based on worst signal
4. `crawlability_fix_node` — Nemotron 49B generates SPA fix plan
5. `authority_gap_node` — Nemotron 49B generates authority fix plan
6. `content_gap_node` — Nemotron 49B generates content fix plan
7. `strategy_node` — merges all fix plans into strategy summary
8. `synthesis_node` — Llama 3.3 70B writes client-facing report
9. `flywheel_persist_node` — drains `flywheel_records` into `zie_training_records`

**DB tables required:**
- `seo_audit_queue` — job queue (SELECT FOR UPDATE SKIP LOCKED)
- `seo_graph_checkpoints` — AsyncPgCheckpointer backing store
- `zie_training_records` — ZIE flywheel SFT records
- `zie_preference_pairs` — ZIE flywheel DPO pairs
- `zie_router_policies` — dynamic model routing

Run `graph/migrations/001_seo_graph.sql` against your Postgres DB first.

### Layer 3 — Frontend integration (`frontend/`)
TanStack Start server functions for wiring to an open-seo Cloudflare Worker frontend.
Calls `openclaw-api-k30t.onrender.com/api/v1/seo/audit` (the live double-dip ZIE endpoint).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
uvicorn main:app --reload --port 8000
```

## Environment variables

```
RAPIDAPI_KEY=          # Semrush + Google Keyword Insight
OPENROUTER_API_KEY=    # LLM synthesis (Llama 3.3 70B, Nemotron 49B)
PAGESPEED_API_KEY=     # Google PageSpeed Insights
DATABASE_URL=          # Postgres (for LangGraph worker only)
```

## Where the live double-dip ZIE audit runs

`openclaw-api-k30t.onrender.com` — Node.js/Express, deployed on Render.
Source: `fjkiani/openclaw-saas` → `artifacts/api-server/src/routes/seo.ts`
Endpoint: `POST /api/v1/seo/audit`

This Python seo-ai server is the **multi-agent data collection layer**.
The openclaw-saas Node.js server is the **ZIE flywheel + model routing layer**.
They are complementary, not duplicates.
