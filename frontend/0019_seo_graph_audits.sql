-- Migration 0019: seo_graph_audits
-- Tracks SEO Intelligence audits dispatched to the openclaw-api backend.
-- Simplified schema: no run_id, no routing_path, no SSE.
-- The full audit result is stored in result_json (synchronous response).

CREATE TABLE `seo_graph_audits` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL REFERENCES `projects`(`id`) ON DELETE CASCADE,
  `started_by_user_id` text NOT NULL,
  `domain` text NOT NULL,
  `keywords_json` text NOT NULL DEFAULT '[]',
  `status` text NOT NULL DEFAULT 'pending',
  `result_json` text,
  `error_message` text,
  `started_at` text NOT NULL DEFAULT (current_timestamp),
  `completed_at` text
);

CREATE INDEX `seo_graph_audits_project_id_idx` ON `seo_graph_audits` (`project_id`);
CREATE INDEX `seo_graph_audits_status_idx` ON `seo_graph_audits` (`status`);
