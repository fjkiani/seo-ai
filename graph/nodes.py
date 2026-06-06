"""
graph/nodes.py
--------------
All LangGraph node functions for the SEO audit graph.

Node execution order:
    gather_node
        └─> technical_node
                └─> supervisor_node
                        ├─> crawlability_fix_node  (conditional)
                        ├─> authority_gap_node     (conditional)
                        ├─> content_gap_node       (conditional)
                        └─> strategy_node          (always reachable)
                                └─> synthesis_node
                                        └─> flywheel_persist_node

Model assignments (read from zie_router_policies at runtime):
    supervisor_node        → meta-llama/llama-3.3-70b-instruct  (max_tokens=300)
    crawlability_fix_node  → nvidia/llama-3.3-nemotron-super-49b-v1.5 (max_tokens=3000)
    authority_gap_node     → nvidia/llama-3.3-nemotron-super-49b-v1.5 (max_tokens=3000)
    content_gap_node       → nvidia/llama-3.3-nemotron-super-49b-v1.5 (max_tokens=3000)
    synthesis_node         → meta-llama/llama-3.3-70b-instruct  (max_tokens=2000)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Any

import asyncpg
import httpx

from graph.prompts import (
    SUPERVISOR_PROMPT,
    CRAWLABILITY_FIX_PROMPT,
    AUTHORITY_GAP_PROMPT,
    CONTENT_GAP_PROMPT,
    SYNTHESIS_PROMPT,
)
from graph.state import AuditState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenRouter base URL
# ---------------------------------------------------------------------------
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# Fallback model constants (used when zie_router_policies has no row)
# ---------------------------------------------------------------------------
_DEFAULT_SUPERVISOR_MODEL = "meta-llama/llama-3.3-70b-instruct"
_DEFAULT_FIX_MODEL        = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
_DEFAULT_SYNTHESIS_MODEL  = "meta-llama/llama-3.3-70b-instruct"


# ===========================================================================
# Helpers
# ===========================================================================

async def _get_model_config(
    pool: asyncpg.Pool,
    task_type: str,
    default_model: str,
    default_tokens: int,
    default_timeout_ms: int = 30_000,
) -> tuple[str, int, int]:
    """
    Reads model assignment from zie_router_policies.
    Returns (model_id, max_tokens, timeout_ms).
    Falls back to hardcoded defaults if no row exists — this is the
    hot-swap seam: UPDATE fast_model_id to promote a local SFT model
    without any code changes.
    """
    try:
        row = await pool.fetchrow(
            """
            SELECT fast_model_id, fast_max_tokens, fast_timeout_ms
            FROM zie_router_policies
            WHERE task_type = $1
            """,
            task_type,
        )
        if row and row["fast_model_id"]:
            return row["fast_model_id"], row["fast_max_tokens"], row["fast_timeout_ms"]
    except Exception:  # noqa: BLE001
        logger.warning("_get_model_config: DB read failed, using defaults for %s", task_type)
    return default_model, default_tokens, default_timeout_ms


async def _openrouter_chat(
    model: str,
    messages: list[dict],
    max_tokens: int,
    timeout_s: float,
) -> str:
    """
    Single OpenRouter chat completion call.
    Returns the assistant message content as a string.
    Raises on HTTP error or empty content.
    """
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://jedilabs.org",
        "X-Title": "JediLabs SEO Intelligence",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not content:
            raise ValueError(f"OpenRouter returned empty content for model={model}")
        return content


def _make_flywheel_record(
    task_type: str,
    prompt_json: dict,
    response_json: dict,
) -> dict:
    """
    Builds a flywheel record dict to be accumulated in state["flywheel_records"].
    Hashing is deterministic: sort_keys=True ensures identical prompts always
    produce the same SHA-256 hash regardless of dict insertion order.
    """
    return {
        "task_type": task_type,
        "prompt_json": prompt_json,
        "response_json": response_json,
    }


# ===========================================================================
# Node 1: gather_node
# Calls keyword, authority, traffic, onpage, security agents concurrently.
# ===========================================================================

async def gather_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    """Runs all data-collection agents in parallel via asyncio.gather."""
    from agents.keyword_agent    import run_keyword_research    # noqa: PLC0415
    from agents.authority_agent  import run_authority_check     # noqa: PLC0415
    from agents.traffic_agent    import run_traffic_analysis    # noqa: PLC0415
    from agents.onpage_agent     import run_onpage_audit        # noqa: PLC0415
    from agents.security_agent   import run_security_audit      # noqa: PLC0415

    domain = state["domain"]
    keywords_raw = state.get("keyword_data", {}).get("seed_keywords", [domain])

    results = await asyncio.gather(
        run_keyword_research(domain, keywords_raw),
        run_authority_check(domain),
        run_traffic_analysis(domain),
        run_onpage_audit(domain),
        run_security_audit(domain),
        return_exceptions=True,
    )

    def _safe(r: Any, label: str) -> dict:
        if isinstance(r, Exception):
            logger.warning("gather_node: %s failed: %s", label, r)
            return {"error": str(r)}
        return r or {}

    return {
        **state,
        "keyword_data":   _safe(results[0], "keyword"),
        "authority_data": _safe(results[1], "authority"),
        "traffic_data":   _safe(results[2], "traffic"),
        "onpage_data":    _safe(results[3], "onpage"),
        "security_data":  _safe(results[4], "security"),
    }


# ===========================================================================
# Node 2: technical_node
# Runs technical, pagespeed, and crawlability agents.
# ===========================================================================

async def technical_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    from agents.technical_agent     import run_technical_audit      # noqa: PLC0415
    from agents.crawlability_agent  import run_crawlability_audit   # noqa: PLC0415

    domain = state["domain"]

    results = await asyncio.gather(
        run_technical_audit(domain),
        run_crawlability_audit(domain),
        return_exceptions=True,
    )

    def _safe(r: Any, label: str) -> dict:
        if isinstance(r, Exception):
            logger.warning("technical_node: %s failed: %s", label, r)
            return {"error": str(r)}
        return r or {}

    return {
        **state,
        "technical_data":    _safe(results[0], "technical"),
        "crawlability_data": _safe(results[1], "crawlability"),
    }


# ===========================================================================
# Node 3: supervisor_node
# Llama 3.3 70B reads all agent outputs and emits a routing decision.
# Output: JSON { "decision": "...", "notes": "..." }
# ===========================================================================

async def supervisor_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    model, max_tokens, timeout_ms = await _get_model_config(
        pool, "seo_supervisor", _DEFAULT_SUPERVISOR_MODEL, 300, 5_000
    )

    audit_summary = {
        "domain":           state["domain"],
        "keyword_data":     state["keyword_data"],
        "authority_data":   state["authority_data"],
        "traffic_data":     state["traffic_data"],
        "onpage_data":      state["onpage_data"],
        "security_data":    state["security_data"],
        "technical_data":   state["technical_data"],
        "crawlability_data": state["crawlability_data"],
        "loop_counter":     state["loop_counter"],
    }

    messages = [
        {"role": "system", "content": SUPERVISOR_PROMPT},
        {"role": "user",   "content": json.dumps(audit_summary, default=str)},
    ]

    raw = await _openrouter_chat(model, messages, max_tokens, timeout_ms / 1000)

    # Parse JSON from response — strip markdown fences if present
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    try:
        parsed = json.loads(clean)
        decision = parsed.get("decision", "synthesize")
        notes    = parsed.get("notes", "")
    except json.JSONDecodeError:
        logger.warning("supervisor_node: JSON parse failed, defaulting to synthesize")
        decision = "synthesize"
        notes    = raw[:500]

    # Accumulate flywheel record
    flywheel_records = list(state.get("flywheel_records", []))
    flywheel_records.append(_make_flywheel_record(
        task_type="seo_supervisor",
        prompt_json={"audit_summary": audit_summary},
        response_json={"decision": decision, "notes": notes},
    ))

    return {
        **state,
        "routing_decision": decision,
        "routing_notes":    notes,
        "loop_counter":     state["loop_counter"] + 1,
        "routing_path":     state.get("routing_path", []) + [f"supervisor:{decision}"],
        "flywheel_records": flywheel_records,
    }


# ===========================================================================
# Node 4: crawlability_fix_node
# Nemotron 49B — deep SPA/crawl fix plan.
# ===========================================================================

async def crawlability_fix_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    model, max_tokens, timeout_ms = await _get_model_config(
        pool, "seo_fix_generation", _DEFAULT_FIX_MODEL, 3000, 120_000
    )

    context = {
        "domain":            state["domain"],
        "crawlability_data": state["crawlability_data"],
        "technical_data":    state["technical_data"],
        "onpage_data":       state["onpage_data"],
        "routing_notes":     state["routing_notes"],
    }

    messages = [
        {"role": "system", "content": CRAWLABILITY_FIX_PROMPT},
        {"role": "user",   "content": json.dumps(context, default=str)},
    ]

    fix_plan = await _openrouter_chat(model, messages, max_tokens, timeout_ms / 1000)

    flywheel_records = list(state.get("flywheel_records", []))
    flywheel_records.append(_make_flywheel_record(
        task_type="seo_fix_generation",
        prompt_json={"node": "crawlability_fix", "context": context},
        response_json={"fix_plan": fix_plan},
    ))

    return {
        **state,
        "crawlability_fix": fix_plan,
        "routing_path":     state.get("routing_path", []) + ["crawlability_fix"],
        "flywheel_records": flywheel_records,
    }


# ===========================================================================
# Node 5: authority_gap_node
# Nemotron 49B — link-building + DA gap plan.
# ===========================================================================

async def authority_gap_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    model, max_tokens, timeout_ms = await _get_model_config(
        pool, "seo_fix_generation", _DEFAULT_FIX_MODEL, 3000, 120_000
    )

    context = {
        "domain":         state["domain"],
        "authority_data": state["authority_data"],
        "keyword_data":   state["keyword_data"],
        "routing_notes":  state["routing_notes"],
    }

    messages = [
        {"role": "system", "content": AUTHORITY_GAP_PROMPT},
        {"role": "user",   "content": json.dumps(context, default=str)},
    ]

    fix_plan = await _openrouter_chat(model, messages, max_tokens, timeout_ms / 1000)

    flywheel_records = list(state.get("flywheel_records", []))
    flywheel_records.append(_make_flywheel_record(
        task_type="seo_fix_generation",
        prompt_json={"node": "authority_gap", "context": context},
        response_json={"fix_plan": fix_plan},
    ))

    return {
        **state,
        "authority_fix":  fix_plan,
        "routing_path":   state.get("routing_path", []) + ["authority_gap"],
        "flywheel_records": flywheel_records,
    }


# ===========================================================================
# Node 6: content_gap_node
# Nemotron 49B — content gap + keyword opportunity plan.
# ===========================================================================

async def content_gap_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    model, max_tokens, timeout_ms = await _get_model_config(
        pool, "seo_fix_generation", _DEFAULT_FIX_MODEL, 3000, 120_000
    )

    context = {
        "domain":        state["domain"],
        "keyword_data":  state["keyword_data"],
        "traffic_data":  state["traffic_data"],
        "onpage_data":   state["onpage_data"],
        "routing_notes": state["routing_notes"],
    }

    messages = [
        {"role": "system", "content": CONTENT_GAP_PROMPT},
        {"role": "user",   "content": json.dumps(context, default=str)},
    ]

    fix_plan = await _openrouter_chat(model, messages, max_tokens, timeout_ms / 1000)

    flywheel_records = list(state.get("flywheel_records", []))
    flywheel_records.append(_make_flywheel_record(
        task_type="seo_fix_generation",
        prompt_json={"node": "content_gap", "context": context},
        response_json={"fix_plan": fix_plan},
    ))

    return {
        **state,
        "content_fix":    fix_plan,
        "routing_path":   state.get("routing_path", []) + ["content_gap"],
        "flywheel_records": flywheel_records,
    }


# ===========================================================================
# Node 7: strategy_node
# Pure Python — merges all fix outputs into a prioritized action list.
# No LLM call. Always reachable (hard-gate fallback).
# ===========================================================================

async def strategy_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    actions: list[str] = []

    if state.get("crawlability_fix"):
        actions.append(f"[CRAWLABILITY] {state['crawlability_fix'][:300]}")
    if state.get("authority_fix"):
        actions.append(f"[AUTHORITY] {state['authority_fix'][:300]}")
    if state.get("content_fix"):
        actions.append(f"[CONTENT] {state['content_fix'][:300]}")

    if not actions:
        actions.append("No critical issues detected. Proceed with standard SEO maintenance.")

    summary = "\n\n".join(actions)

    return {
        **state,
        "strategy_summary": summary,
        "routing_path":     state.get("routing_path", []) + ["strategy"],
    }


# ===========================================================================
# Node 8: synthesis_node
# Llama 3.3 70B — writes the client-facing report.
# ===========================================================================

async def synthesis_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    model, max_tokens, timeout_ms = await _get_model_config(
        pool, "seo_synthesis", _DEFAULT_SYNTHESIS_MODEL, 2000, 30_000
    )

    context = {
        "domain":           state["domain"],
        "strategy_summary": state["strategy_summary"],
        "keyword_data":     state["keyword_data"],
        "authority_data":   state["authority_data"],
        "onpage_data":      state["onpage_data"],
        "security_data":    state["security_data"],
        "crawlability_fix": state.get("crawlability_fix", ""),
        "authority_fix":    state.get("authority_fix", ""),
        "content_fix":      state.get("content_fix", ""),
        "routing_path":     state.get("routing_path", []),
    }

    messages = [
        {"role": "system", "content": SYNTHESIS_PROMPT},
        {"role": "user",   "content": json.dumps(context, default=str)},
    ]

    report = await _openrouter_chat(model, messages, max_tokens, timeout_ms / 1000)

    flywheel_records = list(state.get("flywheel_records", []))
    flywheel_records.append(_make_flywheel_record(
        task_type="seo_synthesis",
        prompt_json={"context": context},
        response_json={"client_report": report},
    ))

    return {
        **state,
        "client_report":    report,
        "routing_path":     state.get("routing_path", []) + ["synthesis"],
        "flywheel_records": flywheel_records,
    }


# ===========================================================================
# Node 9: flywheel_persist_node
# Inserts all accumulated flywheel records into zie_training_records.
# ON CONFLICT (prompt_hash) DO NOTHING — safe to re-run on retry.
# ===========================================================================

async def flywheel_persist_node(state: AuditState, pool: asyncpg.Pool) -> AuditState:
    """
    Persists every flywheel record accumulated during this graph run.

    Hashing contract:
        prompt_hash = SHA-256( JSON.dumps(prompt_json, sort_keys=True) )

    sort_keys=True is mandatory — it guarantees that two dicts with the
    same keys/values but different insertion order produce the same hash.
    The UNIQUE constraint on zie_training_records.prompt_hash means
    ON CONFLICT DO NOTHING silently skips exact duplicates (e.g. on retry).
    """
    records: list[dict] = state.get("flywheel_records", [])
    if not records:
        logger.debug("flywheel_persist_node: no records to persist for run_id=%s", state["run_id"])
        return state

    inserted = 0
    skipped  = 0

    for record in records:
        # Deterministic hash — sort_keys ensures dict order independence
        canonical_prompt = json.dumps(record["prompt_json"], sort_keys=True, default=str)
        prompt_hash = hashlib.sha256(canonical_prompt.encode("utf-8")).hexdigest()

        try:
            result = await pool.execute(
                """
                INSERT INTO zie_training_records
                    (task_type,
                     prompt_hash,
                     prompt_json,
                     remote_response_json,
                     quality_score,
                     domain,
                     source_kind,
                     tenant_id,
                     workspace_id,
                     source_run_id)
                VALUES
                    ($1, $2, $3, $4, $5, $6, 'langgraph_node', $7, $8, $9)
                ON CONFLICT (prompt_hash) DO NOTHING
                """,
                record["task_type"],
                prompt_hash,
                json.dumps(record["prompt_json"],  default=str),
                json.dumps(record["response_json"], default=str),
                1.0,                        # quality_score: 1.0 for all live graph outputs
                state["domain"],
                state["tenant_id"],
                state["workspace_id"],
                state["run_id"],
            )
            # asyncpg returns "INSERT 0 N" — N=0 means conflict (skipped)
            n = int(result.split()[-1])
            if n == 1:
                inserted += 1
            else:
                skipped += 1

        except Exception:  # noqa: BLE001
            logger.error(
                "flywheel_persist_node: insert failed for task_type=%s run_id=%s\n%s",
                record["task_type"],
                state["run_id"],
                __import__("traceback").format_exc(),
            )
            # Do not re-raise — a flywheel failure must never abort the audit result

    logger.info(
        "flywheel_persist_node: run_id=%s inserted=%d skipped=%d",
        state["run_id"],
        inserted,
        skipped,
    )
    return state
