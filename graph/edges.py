"""
graph/edges.py
--------------
Conditional edge functions for the LangGraph StateGraph.

route_after_supervisor is the ONLY place routing decisions are made.
The hard gate at loop_counter >= MAX_SUPERVISOR_LOOPS is enforced in
pure Python — no LLM call, no prompt, no way to loop forever.

Billing safety proof:
  - Nemotron fix nodes cost ~$0.04 per call at 3000 tokens
  - MAX_SUPERVISOR_LOOPS = 2 → maximum 2 fix node calls per audit
  - Even if the supervisor hallucinates "spa_critical" twice, the gate
    forces "strategy" on the third pass — total max cost is bounded
"""

from __future__ import annotations

from graph.state import AuditState

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_SUPERVISOR_LOOPS: int = 2

# Valid routing decisions emitted by supervisor_node
VALID_DECISIONS = frozenset(
    {"spa_critical", "low_authority", "content_gap", "synthesize"}
)


# ── Edge functions ────────────────────────────────────────────────────────────

def route_after_supervisor(state: AuditState) -> str:
    """
    Conditional edge: supervisor_node → fix node | strategy.

    Hard gate: if loop_counter >= MAX_SUPERVISOR_LOOPS, always go to
    "strategy" regardless of what the LLM decided. This is a Python
    conditional — the LLM cannot override it.

    Decision map:
        "spa_critical"  → crawlability_fix_node  (Nemotron 49B)
        "low_authority" → authority_gap_node      (Nemotron 49B)
        "content_gap"   → content_gap_node        (Nemotron 49B)
        "synthesize"    → strategy_node           (pure Python)
        <anything else> → strategy_node           (safe fallback)
    """
    # ── HARD GATE — billing-safe, Python-enforced ─────────────────────────
    if state["loop_counter"] >= MAX_SUPERVISOR_LOOPS:
        return "strategy_node"

    decision = state.get("routing_decision", "synthesize")

    # Sanitise: if the LLM returned something unexpected, go to strategy
    if decision not in VALID_DECISIONS:
        return "strategy_node"

    # ── Route to fix nodes (only on first pass through supervisor) ────────
    # loop_counter is incremented BEFORE this edge is evaluated, so:
    #   first supervisor call  → loop_counter == 1 → fix nodes allowed
    #   second supervisor call → loop_counter == 2 → hard gate fires above
    if decision == "spa_critical":
        return "crawlability_fix_node"
    if decision == "low_authority":
        return "authority_gap_node"
    if decision == "content_gap":
        return "content_gap_node"

    # "synthesize" or any other valid decision → skip fix nodes
    return "strategy_node"
