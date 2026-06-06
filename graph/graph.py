"""
graph/graph.py
--------------
Compiles the LangGraph StateGraph for the SEO audit pipeline.

Node wiring:
    gather_node
        └─> technical_node
                └─> supervisor_node
                        ├─> crawlability_fix_node  (route_after_supervisor)
                        ├─> authority_gap_node     (route_after_supervisor)
                        ├─> content_gap_node       (route_after_supervisor)
                        └─> strategy_node          (route_after_supervisor)
                                └─> synthesis_node
                                        └─> flywheel_persist_node
                                                └─> END

All fix nodes (crawlability_fix, authority_gap, content_gap) converge
on strategy_node — they do NOT loop back to supervisor_node.
The hard loop gate in edges.py makes supervisor re-entry impossible
after MAX_SUPERVISOR_LOOPS iterations regardless.

Node functions receive (state, pool) — the asyncpg pool is injected
via functools.partial at graph build time so nodes stay pure functions
with no global state.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

import asyncpg
from langgraph.graph import END, StateGraph

from graph.edges import route_after_supervisor
from graph.nodes import (
    authority_gap_node,
    content_gap_node,
    crawlability_fix_node,
    flywheel_persist_node,
    gather_node,
    strategy_node,
    supervisor_node,
    synthesis_node,
    technical_node,
)
from graph.state import AuditState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


def build_graph(
    checkpointer: "BaseCheckpointSaver",
    pool: asyncpg.Pool | None = None,
) -> "CompiledStateGraph":
    """
    Build and compile the SEO audit StateGraph.

    Args:
        checkpointer: AsyncPgCheckpointer instance (from worker's event loop)
        pool: asyncpg.Pool for node DB access (flywheel inserts, model routing)
              If None, nodes that need DB access will skip DB operations gracefully.

    Returns:
        Compiled LangGraph graph ready for ainvoke().
    """

    # ── Bind pool to all nodes that need DB access ────────────────────────────
    # functools.partial injects `pool` as the second positional argument.
    # Node signature: async def node_name(state: AuditState, pool: asyncpg.Pool)
    # LangGraph calls nodes with (state,) — partial fills in pool.

    def _bind(fn):
        """Bind pool to a node function. If pool is None, bind a sentinel."""
        return functools.partial(fn, pool=pool)

    # ── Build graph ───────────────────────────────────────────────────────────
    builder = StateGraph(AuditState)

    # Register nodes
    builder.add_node("gather_node",            _bind(gather_node))
    builder.add_node("technical_node",         _bind(technical_node))
    builder.add_node("supervisor_node",        _bind(supervisor_node))
    builder.add_node("crawlability_fix_node",  _bind(crawlability_fix_node))
    builder.add_node("authority_gap_node",     _bind(authority_gap_node))
    builder.add_node("content_gap_node",       _bind(content_gap_node))
    builder.add_node("strategy_node",          _bind(strategy_node))
    builder.add_node("synthesis_node",         _bind(synthesis_node))
    builder.add_node("flywheel_persist_node",  _bind(flywheel_persist_node))

    # ── Entry point ───────────────────────────────────────────────────────────
    builder.set_entry_point("gather_node")

    # ── Linear edges ─────────────────────────────────────────────────────────
    builder.add_edge("gather_node",           "technical_node")
    builder.add_edge("technical_node",        "supervisor_node")

    # Fix nodes all converge on strategy_node (no loop-back to supervisor)
    builder.add_edge("crawlability_fix_node", "strategy_node")
    builder.add_edge("authority_gap_node",    "strategy_node")
    builder.add_edge("content_gap_node",      "strategy_node")

    builder.add_edge("strategy_node",         "synthesis_node")
    builder.add_edge("synthesis_node",        "flywheel_persist_node")
    builder.add_edge("flywheel_persist_node", END)

    # ── Conditional edge: supervisor → fix node | strategy ────────────────────
    # route_after_supervisor reads state["loop_counter"] and state["routing_decision"]
    # The hard gate (loop_counter >= MAX_SUPERVISOR_LOOPS) is enforced inside
    # route_after_supervisor — no LLM involvement.
    builder.add_conditional_edges(
        "supervisor_node",
        route_after_supervisor,
        {
            "crawlability_fix_node": "crawlability_fix_node",
            "authority_gap_node":    "authority_gap_node",
            "content_gap_node":      "content_gap_node",
            "strategy_node":         "strategy_node",
        },
    )

    # ── Compile ───────────────────────────────────────────────────────────────
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("SEO audit graph compiled successfully")
    return graph
