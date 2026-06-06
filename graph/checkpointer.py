"""
graph/checkpointer.py
---------------------
AsyncPgCheckpointer — LangGraph BaseCheckpointSaver backed by asyncpg.

Why asyncpg and not psycopg2:
  - This runs inside the worker thread's own asyncio event loop
  - psycopg2 is synchronous and would block the event loop
  - asyncpg is a pure-async Postgres driver with zero blocking calls

LangGraph checkpoint contract (BaseCheckpointSaver interface):
  aget_tuple(config)          → CheckpointTuple | None
  aput(config, checkpoint, metadata, new_versions) → RunnableConfig
  alist(config, *, filter, before, limit) → AsyncIterator[CheckpointTuple]

Backing table: seo_graph_checkpoints (created by 001_seo_graph.sql)
  thread_id     TEXT NOT NULL
  checkpoint_id TEXT NOT NULL
  parent_id     TEXT
  checkpoint    JSONB NOT NULL
  metadata      JSONB NOT NULL DEFAULT '{}'
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
  PRIMARY KEY (thread_id, checkpoint_id)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    RunnableConfig,
)

logger = logging.getLogger(__name__)


class AsyncPgCheckpointer(BaseCheckpointSaver):
    """
    LangGraph checkpoint saver using asyncpg.

    Pass an asyncpg.Pool created in the worker's own event loop.
    Never share this pool with the FastAPI event loop.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        super().__init__()
        self.pool = pool

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_tuple(row: asyncpg.Record) -> CheckpointTuple:
        config: RunnableConfig = {
            "configurable": {
                "thread_id":     row["thread_id"],
                "checkpoint_id": row["checkpoint_id"],
            }
        }
        parent_config: RunnableConfig | None = None
        if row["parent_id"]:
            parent_config = {
                "configurable": {
                    "thread_id":     row["thread_id"],
                    "checkpoint_id": row["parent_id"],
                }
            }
        checkpoint: Checkpoint = json.loads(row["checkpoint"])
        metadata: CheckpointMetadata = json.loads(row["metadata"])
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
        )

    # ── BaseCheckpointSaver interface ─────────────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """
        Fetch the most recent checkpoint for a thread, or a specific
        checkpoint_id if provided in config["configurable"].
        """
        cfg = config.get("configurable", {})
        thread_id: str | None = cfg.get("thread_id")
        checkpoint_id: str | None = cfg.get("checkpoint_id")

        if not thread_id:
            return None

        try:
            async with self.pool.acquire() as conn:
                if checkpoint_id:
                    row = await conn.fetchrow(
                        """
                        SELECT thread_id, checkpoint_id, parent_id,
                               checkpoint, metadata
                        FROM seo_graph_checkpoints
                        WHERE thread_id = $1 AND checkpoint_id = $2
                        """,
                        thread_id,
                        checkpoint_id,
                    )
                else:
                    # Most recent checkpoint for this thread
                    row = await conn.fetchrow(
                        """
                        SELECT thread_id, checkpoint_id, parent_id,
                               checkpoint, metadata
                        FROM seo_graph_checkpoints
                        WHERE thread_id = $1
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        thread_id,
                    )

                if row is None:
                    return None
                return self._row_to_tuple(row)

        except Exception:
            logger.exception(
                "AsyncPgCheckpointer.aget_tuple failed thread_id=%s", thread_id
            )
            return None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any = None,  # noqa: ANN401 — LangGraph passes this
    ) -> RunnableConfig:
        """
        Persist a checkpoint. Returns the config that can be used to
        retrieve this exact checkpoint later.
        """
        cfg = config.get("configurable", {})
        thread_id: str = cfg["thread_id"]
        checkpoint_id: str = checkpoint["id"]
        parent_id: str | None = cfg.get("checkpoint_id")

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO seo_graph_checkpoints
                        (thread_id, checkpoint_id, parent_id, checkpoint, metadata)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                    ON CONFLICT (thread_id, checkpoint_id)
                    DO UPDATE SET
                        checkpoint = EXCLUDED.checkpoint,
                        metadata   = EXCLUDED.metadata
                    """,
                    thread_id,
                    checkpoint_id,
                    parent_id,
                    json.dumps(checkpoint),
                    json.dumps(metadata),
                )
        except Exception:
            logger.exception(
                "AsyncPgCheckpointer.aput failed thread_id=%s checkpoint_id=%s",
                thread_id,
                checkpoint_id,
            )
            raise

        return {
            "configurable": {
                "thread_id":     thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def alist(
        self,
        config: RunnableConfig,
        *,
        filter: dict | None = None,       # noqa: A002 — LangGraph API
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        List checkpoints for a thread in reverse chronological order.
        Supports optional `before` cursor and `limit`.
        """
        cfg = config.get("configurable", {})
        thread_id: str | None = cfg.get("thread_id")

        if not thread_id:
            return

        before_id: str | None = None
        if before:
            before_id = before.get("configurable", {}).get("checkpoint_id")

        try:
            async with self.pool.acquire() as conn:
                if before_id:
                    rows = await conn.fetch(
                        """
                        SELECT thread_id, checkpoint_id, parent_id,
                               checkpoint, metadata
                        FROM seo_graph_checkpoints
                        WHERE thread_id = $1
                          AND created_at < (
                              SELECT created_at FROM seo_graph_checkpoints
                              WHERE thread_id = $1 AND checkpoint_id = $2
                          )
                        ORDER BY created_at DESC
                        LIMIT $3
                        """,
                        thread_id,
                        before_id,
                        limit or 100,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT thread_id, checkpoint_id, parent_id,
                               checkpoint, metadata
                        FROM seo_graph_checkpoints
                        WHERE thread_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        thread_id,
                        limit or 100,
                    )

                for row in rows:
                    yield self._row_to_tuple(row)

        except Exception:
            logger.exception(
                "AsyncPgCheckpointer.alist failed thread_id=%s", thread_id
            )
            return

    # ── Synchronous stubs (required by BaseCheckpointSaver ABC) ──────────────
    # The worker runs fully async — these should never be called.
    # Raise explicitly so any accidental sync call surfaces immediately.

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError(
            "AsyncPgCheckpointer is async-only. Use aget_tuple()."
        )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any = None,
    ) -> RunnableConfig:
        raise NotImplementedError(
            "AsyncPgCheckpointer is async-only. Use aput()."
        )

    def list(
        self,
        config: RunnableConfig,
        *,
        filter: dict | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        raise NotImplementedError(
            "AsyncPgCheckpointer is async-only. Use alist()."
        )
