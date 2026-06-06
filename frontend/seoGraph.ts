/**
 * seoGraph.ts — SEO Intelligence server functions
 *
 * Wires open-seo's TanStack Start server functions to the openclaw-api
 * SEO Intelligence backend at https://openclaw-api-k30t.onrender.com.
 *
 * Flow:
 *   1. startSeoGraphAudit: inserts D1 row (status=running), POSTs to openclaw-api,
 *      stores full result in result_json, updates status=completed.
 *   2. getSeoGraphAudit: reads D1 row — returns status + parsed result.
 *   3. getSeoGraphAuditHistory: lists all audits for a project.
 *   4. deleteSeoGraphAudit: removes D1 row.
 *
 * No polling, no SSE. The openclaw-api POST is synchronous (~5-30s).
 * The server function awaits the full result before returning.
 */

import { createServerFn } from "@tanstack/react-start";
import { env } from "cloudflare:workers";
import { randomUUID } from "crypto";
import { db } from "@/db";
import { seoGraphAudits } from "@/db/schema";
import { eq, and, desc } from "drizzle-orm";
import { requireProjectContext } from "@/serverFunctions/middleware";
import {
  startSeoGraphAuditSchema,
  getSeoGraphAuditSchema,
  getSeoGraphAuditHistorySchema,
  deleteSeoGraphAuditSchema,
  SeoAuditResultSchema,
  type SeoAuditResult,
} from "@/types/schemas/seoGraph";

// ── Openclaw API base URL ─────────────────────────────────────────────────────
// Set OPENCLAW_API_URL in Cloudflare Worker env vars.
// Default: production Render deployment.
const OPENCLAW_API_URL =
  (env as Record<string, string | undefined>).OPENCLAW_API_URL ??
  "https://openclaw-api-k30t.onrender.com";

// ── startSeoGraphAudit ────────────────────────────────────────────────────────

export const startSeoGraphAudit = createServerFn({ method: "POST" })
  .middleware(requireProjectContext)
  .inputValidator((data: unknown) => startSeoGraphAuditSchema.parse(data))
  .handler(async ({ data, context }) => {
    const auditId = randomUUID();
    const now = new Date().toISOString();

    // Insert D1 tracking row (status=running)
    await db.insert(seoGraphAudits).values({
      id: auditId,
      projectId: context.projectId,
      startedByUserId: context.userId,
      domain: data.domain,
      keywordsJson: JSON.stringify(data.keywords),
      status: "running",
      startedAt: now,
    });

    // POST to openclaw-api — synchronous, awaits full result
    let result: SeoAuditResult;
    try {
      const response = await fetch(`${OPENCLAW_API_URL}/api/v1/seo/audit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // openclaw-api uses Clerk auth in production; Bearer test works in dev
          Authorization: `Bearer ${(env as Record<string, string | undefined>).OPENCLAW_API_KEY ?? "test"}`,
        },
        body: JSON.stringify({
          domain: data.domain,
          github_owner: data.githubOwner,
          github_repo: data.githubRepo,
          github_branch: data.githubBranch ?? "master",
          keywords: data.keywords,
          desktop_performance: data.desktopPerformance,
        }),
        // 60s timeout — Dip 2 can take up to 55s
        signal: AbortSignal.timeout(65_000),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "unknown error");
        throw new Error(`openclaw-api returned ${response.status}: ${errorText}`);
      }

      const raw = await response.json();
      result = SeoAuditResultSchema.parse(raw);
    } catch (err: unknown) {
      // Update D1 row to failed
      await db
        .update(seoGraphAudits)
        .set({
          status: "failed",
          errorMessage: err instanceof Error ? err.message : String(err),
          completedAt: new Date().toISOString(),
        })
        .where(
          and(
            eq(seoGraphAudits.id, auditId),
            eq(seoGraphAudits.projectId, context.projectId),
          ),
        );
      throw err;
    }

    // Update D1 row with full result
    await db
      .update(seoGraphAudits)
      .set({
        status: "completed",
        resultJson: JSON.stringify(result),
        completedAt: new Date().toISOString(),
      })
      .where(
        and(
          eq(seoGraphAudits.id, auditId),
          eq(seoGraphAudits.projectId, context.projectId),
        ),
      );

    return { auditId, result };
  });

// ── getSeoGraphAudit ──────────────────────────────────────────────────────────

export const getSeoGraphAudit = createServerFn({ method: "POST" })
  .middleware(requireProjectContext)
  .inputValidator((data: unknown) => getSeoGraphAuditSchema.parse(data))
  .handler(async ({ data, context }) => {
    const row = await db.query.seoGraphAudits.findFirst({
      where: and(
        eq(seoGraphAudits.id, data.auditId),
        eq(seoGraphAudits.projectId, context.projectId),
      ),
    });

    if (!row) return null;

    return {
      id: row.id,
      domain: row.domain,
      status: row.status,
      result: row.resultJson
        ? (JSON.parse(row.resultJson) as SeoAuditResult)
        : null,
      errorMessage: row.errorMessage ?? null,
      startedAt: row.startedAt,
      completedAt: row.completedAt ?? null,
    };
  });

// ── getSeoGraphAuditHistory ───────────────────────────────────────────────────

export const getSeoGraphAuditHistory = createServerFn({ method: "POST" })
  .middleware(requireProjectContext)
  .inputValidator((data: unknown) => getSeoGraphAuditHistorySchema.parse(data))
  .handler(async ({ context }) => {
    const rows = await db
      .select()
      .from(seoGraphAudits)
      .where(eq(seoGraphAudits.projectId, context.projectId))
      .orderBy(desc(seoGraphAudits.startedAt))
      .limit(50);

    return rows.map((row) => ({
      id: row.id,
      domain: row.domain,
      status: row.status,
      result: row.resultJson
        ? (JSON.parse(row.resultJson) as SeoAuditResult)
        : null,
      errorMessage: row.errorMessage ?? null,
      startedAt: row.startedAt,
      completedAt: row.completedAt ?? null,
    }));
  });

// ── deleteSeoGraphAudit ───────────────────────────────────────────────────────

export const deleteSeoGraphAudit = createServerFn({ method: "POST" })
  .middleware(requireProjectContext)
  .inputValidator((data: unknown) => deleteSeoGraphAuditSchema.parse(data))
  .handler(async ({ data, context }) => {
    await db
      .delete(seoGraphAudits)
      .where(
        and(
          eq(seoGraphAudits.id, data.auditId),
          eq(seoGraphAudits.projectId, context.projectId),
        ),
      );
    return { success: true };
  });
