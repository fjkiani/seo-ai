/**
 * SeoGraphReport.tsx
 *
 * Renders the full SEO Intelligence audit result returned by openclaw-api.
 * Displays: verdict badge, SCI rankings table, ViteSPA audit flags,
 * synthesis summary, risk lines, quick wins, and traffic ceiling.
 *
 * Uses DaisyUI classes throughout — no custom CSS.
 */

import { AlertTriangle, CheckCircle, TrendingUp, Download } from "lucide-react";
import type { SeoAuditResult, SciNode } from "@/types/schemas/seoGraph";

const VERDICT_BADGE: Record<string, string> = {
  CRITICAL: "badge-error",
  HIGH: "badge-warning",
  MEDIUM: "badge-info",
  LOW: "badge-success",
};

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: "badge-error",
  WARNING: "badge-warning",
  OK: "badge-success",
};

function downloadReport(result: SeoAuditResult) {
  const lines = [
    `# SEO Intelligence Audit — ${result.domain}`,
    `**Verdict**: ${result.synthesis.verdict}`,
    `**Model**: ${result.model_used} (Dip ${result.dip_used})`,
    "",
    "## Summary",
    result.synthesis.summary,
    "",
    "## Risk Lines",
    ...result.synthesis.risk_lines.map((r) => `- ${r}`),
    "",
    "## Quick Wins",
    ...result.synthesis.quick_wins.map((q) => `- ${q}`),
    "",
    `## Estimated Traffic Ceiling`,
    `${result.synthesis.estimated_traffic_ceiling.toLocaleString()} monthly visits`,
    "",
    "## SCI Rankings",
    "| Rank | Path | Keyword | Volume | ODI | SCI (norm) |",
    "|------|------|---------|--------|-----|------------|",
    ...result.sci_rankings.map(
      (r) =>
        `| ${r.rank} | ${r.path} | ${r.keyword} | ${r.volume.toLocaleString()} | ${r.odi_display} | ${r.sci_normalized.toFixed(1)} |`,
    ),
    "",
    "## ViteSPA Audit",
    `- Routing: ${result.vite_audit.routing_type}`,
    `- Pre-rendering: ${result.vite_audit.pre_rendering_detected ? "Yes" : "No"}`,
    `- Sitemap harmful: ${result.vite_audit.sitemap_harmful ? "Yes" : "No"}`,
    `- Severity: ${result.vite_audit.severity}`,
  ];

  const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `seo-audit-${result.domain}-${new Date().toISOString().slice(0, 10)}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function SciTable({ rankings }: { rankings: SciNode[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="table table-sm">
        <thead>
          <tr>
            <th>#</th>
            <th>Path</th>
            <th>Keyword</th>
            <th className="text-right">Volume</th>
            <th className="text-right">ODI</th>
            <th className="text-right">SCI</th>
          </tr>
        </thead>
        <tbody>
          {rankings.map((r) => (
            <tr key={r.rank} className={r.rank === 1 ? "bg-primary/5 font-medium" : ""}>
              <td className="text-base-content/50">{r.rank}</td>
              <td className="font-mono text-xs">{r.path}</td>
              <td>{r.keyword}</td>
              <td className="text-right tabular-nums">{r.volume.toLocaleString()}</td>
              <td className="text-right tabular-nums">
                <span
                  className={`badge badge-sm ${r.odi_display < 15 ? "badge-success" : r.odi_display < 30 ? "badge-warning" : "badge-error"}`}
                >
                  {r.odi_display}
                </span>
              </td>
              <td className="text-right tabular-nums">{r.sci_normalized.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SeoGraphReport({ result }: { result: SeoAuditResult }) {
  const { synthesis, vite_audit, sci_rankings } = result;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold">AI SEO Audit</h2>
          <span className={`badge ${VERDICT_BADGE[synthesis.verdict] ?? "badge-ghost"}`}>
            {synthesis.verdict}
          </span>
          <span className="text-sm text-base-content/50">
            {result.model_used.split("/").pop()} · Dip {result.dip_used}
          </span>
        </div>
        <button
          className="btn btn-ghost btn-sm gap-2"
          onClick={() => downloadReport(result)}
        >
          <Download className="size-4" />
          Download
        </button>
      </div>

      {/* Summary */}
      <div className="card bg-base-100 border border-base-300">
        <div className="card-body gap-3">
          <h3 className="font-medium">Summary</h3>
          <p className="text-sm text-base-content/80 leading-relaxed">{synthesis.summary}</p>
          <div className="flex items-center gap-2 text-sm text-base-content/60">
            <TrendingUp className="size-4" />
            <span>
              Estimated traffic ceiling:{" "}
              <strong className="text-base-content">
                {synthesis.estimated_traffic_ceiling.toLocaleString()}
              </strong>{" "}
              monthly visits
            </span>
          </div>
        </div>
      </div>

      {/* SCI Rankings */}
      <div className="card bg-base-100 border border-base-300">
        <div className="card-body gap-3">
          <h3 className="font-medium">SCI Keyword Rankings</h3>
          <p className="text-xs text-base-content/50">
            Lower ODI = less competition. Higher SCI = more opportunity.
          </p>
          <SciTable rankings={sci_rankings} />
        </div>
      </div>

      {/* ViteSPA Audit */}
      <div className="card bg-base-100 border border-base-300">
        <div className="card-body gap-3">
          <div className="flex items-center gap-2">
            <h3 className="font-medium">ViteSPA Crawlability</h3>
            <span
              className={`badge badge-sm ${SEVERITY_BADGE[vite_audit.severity] ?? "badge-ghost"}`}
            >
              {vite_audit.severity}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            {[
              { label: "Routing", value: vite_audit.routing_type },
              {
                label: "Pre-rendering",
                value: vite_audit.pre_rendering_detected ? "Yes" : "No",
                ok: vite_audit.pre_rendering_detected,
              },
              {
                label: "Sitemap harmful",
                value: vite_audit.sitemap_harmful ? "Yes" : "No",
                ok: !vite_audit.sitemap_harmful,
              },
              {
                label: "Client-side fetch",
                value: vite_audit.client_side_fetch_detected ? "Yes" : "No",
              },
            ].map(({ label, value, ok }) => (
              <div key={label} className="rounded bg-base-200 p-2">
                <p className="text-xs text-base-content/50">{label}</p>
                <p
                  className={`font-medium ${ok === true ? "text-success" : ok === false ? "text-error" : ""}`}
                >
                  {value}
                </p>
              </div>
            ))}
          </div>
          {vite_audit.dynamic_routes.length > 0 && (
            <div>
              <p className="text-xs text-base-content/50 mb-1">
                Dynamic routes ({vite_audit.dynamic_routes.length})
              </p>
              <div className="flex flex-wrap gap-1">
                {vite_audit.dynamic_routes.slice(0, 8).map((r) => (
                  <span key={r} className="badge badge-ghost badge-sm font-mono">
                    {r}
                  </span>
                ))}
                {vite_audit.dynamic_routes.length > 8 && (
                  <span className="badge badge-ghost badge-sm">
                    +{vite_audit.dynamic_routes.length - 8} more
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Risk Lines */}
      {synthesis.risk_lines.length > 0 && (
        <div className="card bg-base-100 border border-base-300">
          <div className="card-body gap-3">
            <h3 className="font-medium flex items-center gap-2">
              <AlertTriangle className="size-4 text-warning" />
              Risk Lines
            </h3>
            <ul className="space-y-2">
              {synthesis.risk_lines.map((line, i) => (
                <li key={i} className="flex gap-2 text-sm">
                  <span className="text-warning mt-0.5 shrink-0">▸</span>
                  <span className="text-base-content/80">{line}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Quick Wins */}
      {synthesis.quick_wins.length > 0 && (
        <div className="card bg-base-100 border border-base-300">
          <div className="card-body gap-3">
            <h3 className="font-medium flex items-center gap-2">
              <CheckCircle className="size-4 text-success" />
              Quick Wins
            </h3>
            <ul className="space-y-2">
              {synthesis.quick_wins.map((win, i) => (
                <li key={i} className="flex gap-2 text-sm">
                  <span className="text-success mt-0.5 shrink-0">✓</span>
                  <span className="text-base-content/80">{win}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
