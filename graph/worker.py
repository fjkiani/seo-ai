"""
graph/worker.py
---------------
GraphWorker — non-daemon thread with its own asyncio event loop.

Design guarantees:
  - Never shares the FastAPI event loop (no cross-loop task injection).
  - Semaphore gate checked BEFORE any Postgres transaction to prevent
    SELECT FOR UPDATE SKIP LOCKED row accumulation when all slots are full.
  - stop_flag (threading.Event) + thread.join(timeout=30) for graceful
    shutdown on Railway/Render SIGTERM — active LangGraph node finishes
    and saves its checkpoint before the process exits.
  - daemon=False: OS will not kill this thread mid-execution on scale events.
  - Failures update seo_audit_queue.status = 'failed' without crashing the loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import traceback
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from graph.graph import CompiledGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CONCURRENT_JOBS: int = 3
POLL_INTERVAL_SECONDS: float = 2.0


# ---------------------------------------------------------------------------
# Job executor (runs as an asyncio Task inside the worker loop)
# ---------------------------------------------------------------------------
async def _execute_job(
    pool: asyncpg.Pool,
    graph: "CompiledGraph",
    row: asyncpg.Record,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Acquires a semaphore slot, runs the LangGraph graph for one audit job,
    and writes the result (or failure) back to seo_audit_queue.

    The semaphore is acquired HERE (inside the task), not in the poll loop,
    so the poll loop is never blocked waiting for a slot.
    """
    run_id: str = row["run_id"]
    queue_id: str = str(row["id"])
    domain: str = row["domain"]

    async with semaphore:
        try:
            logger.info("worker: starting job run_id=%s domain=%s", run_id, domain)

            initial_state = {
                "run_id": run_id,
                "tenant_id": row["tenant_id"],
                "workspace_id": row["workspace_id"],
                "domain": domain,
                "keyword_data": {},
                "authority_data": {},
                "traffic_data": {},
                "onpage_data": {},
                "security_data": {},
                "technical_data": {},
                "crawlability_data": {},
                "routing_decision": "",
                "routing_notes": "",
                "loop_counter": 0,
                "crawlability_fix": "",
                "authority_fix": "",
                "content_fix": "",
                "strategy_summary": "",
                "client_report": "",
                "flywheel_records": [],
            }

            config = {"configurable": {"thread_id": run_id}}
            final_state = await graph.ainvoke(initial_state, config=config)

            # Persist result back to queue row
            await pool.execute(
                """
                UPDATE seo_audit_queue
                SET
                    status            = 'completed',
                    client_report     = $1,
                    result_json       = $2,
                    routing_path      = $3,
                    loop_counter      = $4,
                    completed_at      = NOW(),
                    updated_at        = NOW()
                WHERE id = $5
                """,
                final_state.get("client_report", ""),
                json.dumps(final_state.get("result_json", {})),
                final_state.get("routing_path", []),
                final_state.get("loop_counter", 0),
                queue_id,
            )
            logger.info("worker: completed run_id=%s", run_id)

        except Exception:  # noqa: BLE001
            err = traceback.format_exc()
            logger.error("worker: job failed run_id=%s\n%s", run_id, err)
            # Update status to 'failed' — never re-raise so the worker loop survives
            try:
                await pool.execute(
                    """
                    UPDATE seo_audit_queue
                    SET
                        status        = 'failed',
                        error_message = $1,
                        updated_at    = NOW()
                    WHERE id = $2
                    """,
                    err[:4000],   # Postgres TEXT column — truncate to be safe
                    queue_id,
                )
            except Exception:  # noqa: BLE001
                # DB write for failure also failed — log and move on
                logger.error(
                    "worker: could not write failure status for run_id=%s\n%s",
                    run_id,
                    traceback.format_exc(),
                )


# ---------------------------------------------------------------------------
# GraphWorker
# ---------------------------------------------------------------------------
class GraphWorker:
    """
    Runs a persistent poll loop in a dedicated non-daemon thread.

    Usage (FastAPI lifespan):

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            worker = GraphWorker(db_url=settings.DATABASE_URL)
            worker.start()
            yield
            worker.stop(timeout=30)   # waits for active node to finish
    """

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self.stop_flag = threading.Event()
        # daemon=False: Railway/Render SIGTERM will not kill this thread
        # mid-execution; lifespan cleanup calls stop() which joins it cleanly.
        self.thread = threading.Thread(
            target=self._run_loop,
            name="seo-graph-worker",
            daemon=False,
        )
        self._graph: "CompiledGraph | None" = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        logger.info("worker: starting thread")
        self.thread.start()

    def stop(self, timeout: int = 30) -> None:
        """
        Signal the worker to stop and wait up to `timeout` seconds for it
        to finish the current job and save its checkpoint.
        """
        logger.info("worker: stop requested, joining thread (timeout=%ds)", timeout)
        self.stop_flag.set()
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            logger.warning(
                "worker: thread did not stop within %ds — "
                "checkpoint may be incomplete",
                timeout,
            )

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """
        Creates a fresh asyncio event loop isolated from FastAPI's loop.
        This is the only correct pattern for running async code in a
        non-async thread — asyncio.run() would also work but
        new_event_loop() gives us explicit control over loop lifetime.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_loop())
        finally:
            loop.close()
            logger.info("worker: event loop closed")

    # ------------------------------------------------------------------
    # Async poll loop (runs inside the worker thread's event loop)
    # ------------------------------------------------------------------

    async def _async_loop(self) -> None:
        # Import here to avoid circular imports at module load time
        from graph.checkpointer import AsyncPgCheckpointer  # noqa: PLC0415
        from graph.graph import build_graph                  # noqa: PLC0415

        pool: asyncpg.Pool = await asyncpg.create_pool(
            self.db_url,
            min_size=2,
            max_size=MAX_CONCURRENT_JOBS + 2,  # headroom for result writes
        )
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        checkpointer = AsyncPgCheckpointer(pool)
        graph = build_graph(checkpointer)

        logger.info(
            "worker: poll loop started (max_concurrent=%d, interval=%.1fs)",
            MAX_CONCURRENT_JOBS,
            POLL_INTERVAL_SECONDS,
        )

        try:
            while not self.stop_flag.is_set():
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

                # -------------------------------------------------------
                # SEMAPHORE GATE — checked BEFORE touching Postgres.
                # If all slots are taken, skip the DB query entirely.
                # This prevents SELECT FOR UPDATE SKIP LOCKED from
                # accumulating locked rows that block other workers.
                # -------------------------------------------------------
                if semaphore.locked():
                    logger.debug("worker: semaphore full, skipping poll")
                    continue

                # -------------------------------------------------------
                # Claim one pending row atomically.
                # SELECT FOR UPDATE SKIP LOCKED: if another worker (or
                # another pod on Railway) already holds the row lock,
                # we skip it rather than blocking.
                # -------------------------------------------------------
                row: asyncpg.Record | None = None
                try:
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            row = await conn.fetchrow(
                                """
                                SELECT
                                    id,
                                    run_id,
                                    domain,
                                    tenant_id,
                                    workspace_id,
                                    keywords_json
                                FROM seo_audit_queue
                                WHERE status = 'pending'
                                ORDER BY created_at ASC
                                LIMIT 1
                                FOR UPDATE SKIP LOCKED
                                """
                            )
                            if row is None:
                                continue  # nothing pending

                            await conn.execute(
                                """
                                UPDATE seo_audit_queue
                                SET
                                    status             = 'running',
                                    worker_claimed_at  = NOW(),
                                    updated_at         = NOW()
                                WHERE id = $1
                                """,
                                row["id"],
                            )

                except Exception:  # noqa: BLE001
                    logger.error(
                        "worker: DB claim error\n%s", traceback.format_exc()
                    )
                    continue

                if row is None:
                    continue

                # -------------------------------------------------------
                # Dispatch job as a non-blocking asyncio Task.
                # The semaphore is acquired inside _execute_job so this
                # create_task call returns immediately and the poll loop
                # continues without waiting.
                # -------------------------------------------------------
                asyncio.create_task(
                    _execute_job(pool, graph, row, semaphore),
                    name=f"seo-job-{row['run_id']}",
                )

        finally:
            await pool.close()
            logger.info("worker: asyncpg pool closed")
