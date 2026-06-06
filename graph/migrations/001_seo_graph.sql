-- =============================================================================
-- Migration: 001_seo_graph.sql
-- Purpose:   Extend seo_audit_queue for LangGraph worker handoff,
--            create seo_graph_checkpoints for AsyncPgCheckpointer,
--            seed zie_router_policies for dynamic model routing.
-- Run once against Railway Postgres (idempotent via IF NOT EXISTS / ON CONFLICT).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Extend seo_audit_queue
-- -----------------------------------------------------------------------------
ALTER TABLE seo_audit_queue
    ADD COLUMN IF NOT EXISTS run_id              TEXT,
    ADD COLUMN IF NOT EXISTS loop_counter        INT          NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS routing_path        TEXT[]       NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS result_json         JSONB,
    ADD COLUMN IF NOT EXISTS client_report       TEXT,
    ADD COLUMN IF NOT EXISTS graph_state_json    JSONB,
    ADD COLUMN IF NOT EXISTS worker_claimed_at   TIMESTAMPTZ;

-- Unique index on run_id so the status/stream endpoints can look up by it
CREATE UNIQUE INDEX IF NOT EXISTS idx_seo_audit_queue_run_id
    ON seo_audit_queue (run_id)
    WHERE run_id IS NOT NULL;

-- Index to speed up the worker's SELECT FOR UPDATE SKIP LOCKED poll
CREATE INDEX IF NOT EXISTS idx_seo_audit_queue_pending
    ON seo_audit_queue (created_at ASC)
    WHERE status = 'pending';

-- -----------------------------------------------------------------------------
-- 2. Create seo_graph_checkpoints (AsyncPgCheckpointer backing store)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seo_graph_checkpoints (
    thread_id       TEXT        NOT NULL,
    checkpoint_id   TEXT        NOT NULL,
    parent_id       TEXT,
    checkpoint      JSONB       NOT NULL,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_seo_graph_checkpoints_thread
    ON seo_graph_checkpoints (thread_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- 3. Seed zie_router_policies for SEO graph nodes
--    fast_model_id starts as the remote OpenRouter model.
--    After SFT promotion, UPDATE fast_model_id to the local model ID —
--    the graph reads this at node execution time (zero code changes needed).
-- -----------------------------------------------------------------------------
INSERT INTO zie_router_policies
    (task_type, fast_model_id, fast_provider, fast_api_key_env, fast_max_tokens, fast_timeout_ms)
VALUES
    (
        'seo_supervisor',
        'meta-llama/llama-3.3-70b-instruct',
        'openrouter',
        'OPENROUTER_API_KEY',
        300,
        5000
    ),
    (
        'seo_fix_generation',
        'nvidia/llama-3.3-nemotron-super-49b-v1.5',
        'openrouter',
        'OPENROUTER_API_KEY',
        3000,
        120000
    ),
    (
        'seo_synthesis',
        'meta-llama/llama-3.3-70b-instruct',
        'openrouter',
        'OPENROUTER_API_KEY',
        2000,
        30000
    )
ON CONFLICT DO NOTHING;
