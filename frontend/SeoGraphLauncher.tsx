/**
 * SeoGraphLauncher.tsx
 *
 * Launch form + history for the SEO Intelligence audit.
 * Calls startSeoGraphAudit server function → awaits full result → renders SeoGraphReport.
 *
 * No polling, no SSE. The server function is synchronous (awaits openclaw-api POST).
 * Loading state is shown while the server function is in-flight (~5-30s).
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, ExternalLink, Brain } from "lucide-react";
import {
  startSeoGraphAudit,
  getSeoGraphAuditHistory,
  deleteSeoGraphAudit,
} from "@/serverFunctions/seoGraph";
import { SeoGraphReport } from "./SeoGraphReport";
import type { SeoAuditResult } from "@/types/schemas/seoGraph";

// ── Default keywords for quick-start ─────────────────────────────────────────
const DEFAULT_KEYWORDS = [
  { keyword: "enterprise AI solutions", volume: 49500, competition_index: 0.15 },
];

// ── Verdict color map ─────────────────────────────────────────────────────────
const VERDICT_BADGE: Record<string, string> = {
  CRITICAL: "badge-error",
  HIGH: "badge-warning",
  MEDIUM: "badge-info",
  LOW: "badge-success",
};

// ── History row ───────────────────────────────────────────────────────────────
function HistoryRow({
  audit,
  onSelect,
  onDelete,
}: {
  audit: {
    id: string;
    domain: string;
    status: string;
    result: SeoAuditResult | null;
    startedAt: string;
  };
  onSelect: () => void;
  onDelete: () => void;
}) {
  const verdict = audit.result?.synthesis.verdict;
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2 rounded hover:bg-base-200 transition-colors">
      <button className="flex items-center gap-3 flex-1 text-left" onClick={onSelect}>
        <span className="font-medium text-sm">{audit.domain}</span>
        {verdict && (
          <span className={`badge badge-sm ${VERDICT_BADGE[verdict] ?? "badge-ghost"}`}>
            {verdict}
          </span>
        )}
        {audit.status === "failed" && (
          <span className="badge badge-sm badge-error">Failed</span>
        )}
        <span className="text-xs text-base-content/40 ml-auto">
          {new Date(audit.startedAt).toLocaleDateString()}
        </span>
      </button>
      <button
        className="btn btn-ghost btn-xs text-base-content/40 hover:text-error"
        onClick={onDelete}
        title="Delete audit"
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function SeoGraphLauncher({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();

  // Form state
  const [domain, setDomain] = useState("");
  const [githubOwner, setGithubOwner] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubBranch, setGithubBranch] = useState("master");
  const [keywordsRaw, setKeywordsRaw] = useState(
    DEFAULT_KEYWORDS.map((k) => k.keyword).join("\n"),
  );
  const [desktopPerf, setDesktopPerf] = useState<string>("72");

  // Active result (from new audit or history selection)
  const [activeResult, setActiveResult] = useState<SeoAuditResult | null>(null);
  const [activeDomain, setActiveDomain] = useState<string>("");

  // History
  const historyQuery = useQuery({
    queryKey: ["seo-graph-history", projectId],
    queryFn: () => getSeoGraphAuditHistory({ data: { projectId } }),
  });

  // Run audit mutation
  const auditMutation = useMutation({
    mutationFn: () => {
      const keywords = keywordsRaw
        .split("\n")
        .map((k) => k.trim())
        .filter(Boolean)
        .map((keyword, i) => ({
          keyword,
          volume: DEFAULT_KEYWORDS[i]?.volume ?? 10000,
          competition_index: DEFAULT_KEYWORDS[i]?.competition_index ?? 0.5,
        }));

      return startSeoGraphAudit({
        data: {
          projectId,
          domain: domain.trim(),
          githubOwner: githubOwner.trim(),
          githubRepo: githubRepo.trim(),
          githubBranch: githubBranch.trim() || "master",
          keywords,
          desktopPerformance: desktopPerf ? parseFloat(desktopPerf) : undefined,
        },
      });
    },
    onSuccess: ({ result }) => {
      setActiveResult(result);
      setActiveDomain(domain.trim());
      void queryClient.invalidateQueries({ queryKey: ["seo-graph-history", projectId] });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (auditId: string) =>
      deleteSeoGraphAudit({ data: { projectId, auditId } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["seo-graph-history", projectId] });
    },
  });

  const isRunning = auditMutation.isPending;

  return (
    <div className="space-y-4">
      {/* Launch form */}
      <div className="card bg-base-100 border border-base-300">
        <div className="card-body gap-4">
          <div className="flex items-center gap-2">
            <Brain className="size-5 text-primary" />
            <h2 className="card-title text-base">AI SEO Audit</h2>
            <span className="badge badge-ghost badge-sm">Powered by openclaw-api</span>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {/* Domain */}
            <label className="form-control">
              <div className="label">
                <span className="label-text text-xs">Domain</span>
              </div>
              <input
                className="input input-bordered input-sm"
                placeholder="jedilabs.org"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                disabled={isRunning}
              />
            </label>

            {/* Desktop Performance */}
            <label className="form-control">
              <div className="label">
                <span className="label-text text-xs">Desktop Performance Score (0-100)</span>
              </div>
              <input
                className="input input-bordered input-sm"
                type="number"
                min={0}
                max={100}
                placeholder="72"
                value={desktopPerf}
                onChange={(e) => setDesktopPerf(e.target.value)}
                disabled={isRunning}
              />
            </label>

            {/* GitHub Owner */}
            <label className="form-control">
              <div className="label">
                <span className="label-text text-xs">GitHub Owner</span>
              </div>
              <input
                className="input input-bordered input-sm"
                placeholder="fjkiani"
                value={githubOwner}
                onChange={(e) => setGithubOwner(e.target.value)}
                disabled={isRunning}
              />
            </label>

            {/* GitHub Repo */}
            <label className="form-control">
              <div className="label">
                <span className="label-text text-xs">GitHub Repo</span>
              </div>
              <input
                className="input input-bordered input-sm"
                placeholder="jedi-v2"
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
                disabled={isRunning}
              />
            </label>
          </div>

          {/* Keywords */}
          <label className="form-control">
            <div className="label">
              <span className="label-text text-xs">Keywords (one per line)</span>
            </div>
            <textarea
              className="textarea textarea-bordered textarea-sm h-20 font-mono text-xs"
              placeholder={"enterprise AI solutions\nAI consulting\nmachine learning services"}
              value={keywordsRaw}
              onChange={(e) => setKeywordsRaw(e.target.value)}
              disabled={isRunning}
            />
          </label>

          {/* Error */}
          {auditMutation.isError && (
            <div className="alert alert-error text-sm">
              {auditMutation.error instanceof Error
                ? auditMutation.error.message
                : "Audit failed. Please try again."}
            </div>
          )}

          {/* Submit */}
          <button
            className="btn btn-primary btn-sm"
            disabled={isRunning || !domain.trim() || !githubOwner.trim() || !githubRepo.trim()}
            onClick={() => auditMutation.mutate()}
          >
            {isRunning ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Running AI audit… (~15-30s)
              </>
            ) : (
              "Run AI SEO Audit"
            )}
          </button>

          {isRunning && (
            <p className="text-xs text-base-content/50 text-center">
              Analyzing ViteSPA structure, computing ODI/SCI rankings, and running
              double-dip LLM synthesis. This feeds the data flywheel.
            </p>
          )}
        </div>
      </div>

      {/* Active result */}
      {activeResult && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h3 className="font-medium text-sm text-base-content/70">
              Result — {activeDomain}
            </h3>
          </div>
          <SeoGraphReport result={activeResult} />
        </div>
      )}

      {/* History */}
      {(historyQuery.data?.length ?? 0) > 0 && (
        <div className="card bg-base-100 border border-base-300">
          <div className="card-body gap-2 p-4">
            <h3 className="text-sm font-medium text-base-content/70">
              Audit History ({historyQuery.data?.length ?? 0})
            </h3>
            <div className="space-y-0.5">
              {historyQuery.data?.map((audit) => (
                <HistoryRow
                  key={audit.id}
                  audit={audit}
                  onSelect={() => {
                    if (audit.result) {
                      setActiveResult(audit.result);
                      setActiveDomain(audit.domain);
                    }
                  }}
                  onDelete={() => deleteMutation.mutate(audit.id)}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
