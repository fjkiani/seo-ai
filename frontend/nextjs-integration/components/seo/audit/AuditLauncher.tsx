'use client';

/**
 * AuditLauncher.tsx — Next.js component for openclaw SEO audit
 *
 * Drop into: src/components/seo/audit/AuditLauncher.tsx
 *
 * Requires:
 *   - hooks/useAuditGraph.ts (in this folder)
 *   - app/api/seo/audit-graph/route.ts (in this folder)
 *   - lucide-react in package.json
 *
 * Calls openclaw-api-k30t.onrender.com/api/v1/seo/audit via the proxy route.
 * Renders: VerdictBadge, SCITable, ViteAuditFlags, risk_lines, quick_wins.
 */

import { useState, type FormEvent } from 'react';
import {
  Loader2, ScanSearch, CheckCircle, AlertCircle,
  Zap, Shield, TrendingUp, AlertTriangle,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import {
  useAuditGraph,
  type AuditSubmitParams,
  type SeoAuditResult,
  type SeoSynthesis,
  type SCIRanking,
  type ViteAudit,
} from '@/hooks/useAuditGraph';

const VERDICT_STYLES: Record<SeoSynthesis['verdict'], string> = {
  CRITICAL: 'bg-red-900/30 border-red-700/40 text-red-400',
  HIGH:     'bg-orange-900/30 border-orange-700/40 text-orange-400',
  MEDIUM:   'bg-yellow-900/30 border-yellow-700/40 text-yellow-400',
  LOW:      'bg-green-900/30 border-green-700/40 text-green-400',
};

function VerdictBadge({ verdict }: { verdict: SeoSynthesis['verdict'] }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-bold px-3 py-1 rounded-full border ${VERDICT_STYLES[verdict]}`}>
      {verdict === 'CRITICAL' && <AlertTriangle className="size-3.5" />}
      {verdict === 'HIGH' && <AlertCircle className="size-3.5" />}
      {verdict === 'MEDIUM' && <Shield className="size-3.5" />}
      {verdict === 'LOW' && <CheckCircle className="size-3.5" />}
      {verdict}
    </span>
  );
}

function SCITable({ rankings }: { rankings: SCIRanking[] }) {
  if (!rankings.length) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-800/60">
          <tr>
            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">#</th>
            <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Keyword</th>
            <th className="px-4 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase tracking-wider">SCI</th>
            <th className="px-4 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase tracking-wider">ODI</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {rankings.map((r) => {
            const odiColor = r.odi_display < 15 ? 'text-green-400' : r.odi_display < 30 ? 'text-yellow-400' : 'text-red-400';
            return (
              <tr key={r.keyword} className="hover:bg-gray-800/30 transition-colors">
                <td className="px-4 py-2.5 text-gray-500 text-xs">{r.rank}</td>
                <td className="px-4 py-2.5 text-gray-200">{r.keyword}</td>
                <td className="px-4 py-2.5 text-right text-white font-mono">{r.sci_normalized}</td>
                <td className={`px-4 py-2.5 text-right font-mono ${odiColor}`}>{r.odi_display}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ViteAuditFlags({ audit }: { audit: ViteAudit }) {
  if (!audit.is_bare_spa && !audit.flags.length) return null;
  return (
    <div className="bg-orange-950/20 border border-orange-800/30 rounded-lg p-4 space-y-2">
      <p className="text-orange-400 text-xs font-semibold uppercase tracking-wider">
        Vite SPA — {audit.repo}@{audit.branch}
      </p>
      {audit.is_bare_spa && (
        <p className="text-orange-300 text-sm">
          Bare SPA — {audit.dynamic_route_count} dynamic routes invisible to Googlebot
        </p>
      )}
      {audit.flags.map((flag, i) => (
        <p key={i} className="text-orange-200/70 text-xs font-mono">{flag}</p>
      ))}
    </div>
  );
}

function AuditResultCard({ result, domain }: { result: SeoAuditResult; domain: string }) {
  const [showRisk, setShowRisk] = useState(true);
  return (
    <div className="space-y-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-white font-semibold text-lg">{domain}</h3>
            <p className="text-gray-500 text-xs mt-1">
              {result.model_used} · Dip {result.dip_used}
              {result.audit_timestamp && ` · ${new Date(result.audit_timestamp).toLocaleString()}`}
            </p>
          </div>
          <VerdictBadge verdict={result.synthesis.verdict} />
        </div>
        <p className="text-gray-300 text-sm leading-relaxed">{result.synthesis.summary}</p>
      </div>

      {result.sci_rankings.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-3">
          <h4 className="text-white text-sm font-semibold flex items-center gap-2">
            <TrendingUp className="size-4 text-yellow-400" /> SCI Rankings
          </h4>
          <SCITable rankings={result.sci_rankings} />
        </div>
      )}

      {result.vite_audit && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <ViteAuditFlags audit={result.vite_audit} />
        </div>
      )}

      {result.synthesis.risk_lines.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-3">
          <button onClick={() => setShowRisk(v => !v)} className="flex items-center justify-between w-full text-left">
            <h4 className="text-white text-sm font-semibold flex items-center gap-2">
              <AlertTriangle className="size-4 text-red-400" />
              Risk Lines ({result.synthesis.risk_lines.length})
            </h4>
            {showRisk ? <ChevronUp className="size-4 text-gray-500" /> : <ChevronDown className="size-4 text-gray-500" />}
          </button>
          {showRisk && (
            <ul className="space-y-2">
              {result.synthesis.risk_lines.map((line, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                  <span className="text-red-400 shrink-0 mt-0.5">•</span>{line}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {result.synthesis.quick_wins.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-3">
          <h4 className="text-white text-sm font-semibold flex items-center gap-2">
            <CheckCircle className="size-4 text-green-400" /> Quick Wins
          </h4>
          <ul className="space-y-2">
            {result.synthesis.quick_wins.map((win, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                <span className="text-green-400 shrink-0 mt-0.5">✓</span>{win}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.synthesis.traffic_ceiling && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-1">Traffic Ceiling</p>
          <p className="text-gray-200 text-sm">{result.synthesis.traffic_ceiling}</p>
        </div>
      )}
    </div>
  );
}

const DEFAULT_KEYWORDS = [{ keyword: 'enterprise AI solutions', volume: 49500, competition_index: 0.15 }];

export function AuditLauncher({ defaultDomain = '' }: { defaultDomain?: string }) {
  const [domain, setDomain] = useState(defaultDomain);
  const [githubOwner, setGithubOwner] = useState('fjkiani');
  const [githubRepo, setGithubRepo] = useState('jedi-v2');
  const [githubBranch, setGithubBranch] = useState('master');
  const [keywordsRaw, setKeywordsRaw] = useState('enterprise AI solutions');
  const [desktopPerf, setDesktopPerf] = useState('90');
  const audit = useAuditGraph();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!domain.trim()) return;
    const keywords = keywordsRaw.split(',').map(k => k.trim()).filter(Boolean)
      .map(k => ({ keyword: k, volume: 1000, competition_index: 0.5 }));
    const params: AuditSubmitParams = {
      domain: domain.trim(),
      github_owner: githubOwner.trim() || 'fjkiani',
      github_repo: githubRepo.trim() || 'jedi-v2',
      github_branch: githubBranch.trim() || 'master',
      keywords: keywords.length ? keywords : DEFAULT_KEYWORDS,
      desktop_performance: Number(desktopPerf) || 90,
    };
    void audit.submit(params);
  }

  return (
    <div className="space-y-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <Zap className="size-4 text-yellow-400" /> AI SEO Audit
          </h2>
          {audit.status === 'running' && (
            <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-blue-900/30 border border-blue-700/40 text-blue-400">
              <Loader2 className="size-3 animate-spin" /> Running…
            </span>
          )}
          {audit.status === 'completed' && (
            <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-green-900/20 border border-green-700/30 text-green-400">
              <CheckCircle className="size-3" /> Complete
            </span>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            <input type="text" placeholder="Domain (e.g. jedilabs.org)" value={domain}
              onChange={e => setDomain(e.target.value)} disabled={audit.isLoading}
              className="lg:col-span-8 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
            <input type="number" placeholder="Desktop perf" value={desktopPerf}
              onChange={e => setDesktopPerf(e.target.value)} disabled={audit.isLoading} min={0} max={100}
              className="lg:col-span-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            <input type="text" placeholder="GitHub owner" value={githubOwner}
              onChange={e => setGithubOwner(e.target.value)} disabled={audit.isLoading}
              className="lg:col-span-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
            <input type="text" placeholder="GitHub repo" value={githubRepo}
              onChange={e => setGithubRepo(e.target.value)} disabled={audit.isLoading}
              className="lg:col-span-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
            <input type="text" placeholder="Branch" value={githubBranch}
              onChange={e => setGithubBranch(e.target.value)} disabled={audit.isLoading}
              className="lg:col-span-4 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            <input type="text" placeholder="Keywords (comma-separated)" value={keywordsRaw}
              onChange={e => setKeywordsRaw(e.target.value)} disabled={audit.isLoading}
              className="lg:col-span-10 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-yellow-500 disabled:opacity-50" />
            <button type="submit" disabled={audit.isLoading || !domain.trim()}
              className="lg:col-span-2 bg-yellow-500 hover:bg-yellow-400 disabled:bg-gray-700 disabled:text-gray-500 text-black font-semibold text-sm px-4 py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2">
              {audit.isLoading ? <><Loader2 className="size-4 animate-spin" /> Running</> : <><ScanSearch className="size-4" /> Run Audit</>}
            </button>
          </div>
        </form>

        {audit.isLoading && (
          <div className="mt-4 flex items-center gap-3 bg-blue-950/20 border border-blue-800/30 rounded-lg px-4 py-3">
            <Loader2 className="size-4 text-blue-400 animate-spin shrink-0" />
            <div>
              <p className="text-blue-300 text-sm font-medium">Double-dip audit running</p>
              <p className="text-blue-400/60 text-xs mt-0.5">Dip 1 (gpt-oss-20b) → confidence check → Dip 2 (gpt-oss-120b) if needed. 5–55s.</p>
            </div>
          </div>
        )}

        {audit.status === 'failed' && audit.error && (
          <div className="mt-3 flex items-start gap-2 bg-red-950/30 border border-red-800/40 rounded-lg px-4 py-3">
            <AlertCircle className="size-4 text-red-400 shrink-0 mt-0.5" />
            <p className="text-red-400 text-sm">{audit.error}</p>
          </div>
        )}

        {(audit.status === 'completed' || audit.status === 'failed') && (
          <button onClick={audit.reset} className="mt-3 text-xs text-gray-500 hover:text-gray-300 transition-colors">
            ← Run another audit
          </button>
        )}
      </div>

      {audit.status === 'completed' && audit.result && (
        <AuditResultCard result={audit.result} domain={domain} />
      )}
    </div>
  );
}
