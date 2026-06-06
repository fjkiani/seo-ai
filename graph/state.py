"""
graph/state.py
--------------
AuditState TypedDict — the single source of truth flowing through every
LangGraph node. All fields are explicitly typed; no Any, no dict[str, Any].

loop_counter is a plain int incremented in Python inside supervisor_node.
It is NEVER modified by an LLM. route_after_supervisor reads it directly
to enforce the MAX_SUPERVISOR_LOOPS hard gate.
"""

from __future__ import annotations

from typing import TypedDict


class AuditState(TypedDict):
    # ── Identity (injected from request body / JWT — never hardcoded) ────────
    run_id:       str
    tenant_id:    str
    workspace_id: str
    domain:       str

    # ── Agent data payloads ───────────────────────────────────────────────────
    keyword_data:      dict
    authority_data:    dict
    traffic_data:      dict
    onpage_data:       dict
    security_data:     dict
    technical_data:    dict
    crawlability_data: dict

    # ── Supervisor output ─────────────────────────────────────────────────────
    # routing_decision: one of "spa_critical" | "low_authority" |
    #                          "content_gap"  | "synthesize"
    routing_decision: str
    routing_notes:    str

    # Hard gate counter — incremented in Python, never by LLM
    loop_counter: int

    # Ordered list of nodes visited — written to seo_audit_queue.routing_path
    routing_path: list[str]

    # ── Fix node outputs ──────────────────────────────────────────────────────
    crawlability_fix: str
    authority_fix:    str
    content_fix:      str

    # ── Final outputs ─────────────────────────────────────────────────────────
    strategy_summary: str
    client_report:    str

    # ── ZIE flywheel accumulator ──────────────────────────────────────────────
    # Each node appends a dict: { task_type, prompt_json, response_json }
    # flywheel_persist_node drains this list into zie_training_records.
    flywheel_records: list[dict]
