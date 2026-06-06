/**
 * useAuditGraph.ts — React hook for synchronous openclaw SEO audit
 *
 * Drop into: src/hooks/useAuditGraph.ts
 *
 * One POST to /api/seo/audit-graph → full SeoAuditResult returned.
 * No polling, no run_id, no status endpoint.
 */
'use client';

import { useState, useCallback } from 'react';

export type AuditStatus = 'idle' | 'running' | 'completed' | 'failed';

export interface KeywordInput {
  keyword: string;
  volume: number;
  competition_index: number;
}

export interface SCIRanking {
  keyword: string;
  sci_normalized: number;
  odi_display: number;
  rank: number;
}

export interface ViteAudit {
  is_bare_spa: boolean;
  dynamic_route_count: number;
  repo: string;
  branch: string;
  flags: string[];
}

export interface SeoSynthesis {
  verdict: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  summary: string;
  risk_lines: string[];
  quick_wins: string[];
  traffic_ceiling: string;
}

export interface SeoAuditResult {
  domain: string;
  vite_audit: ViteAudit;
  sci_rankings: SCIRanking[];
  synthesis: SeoSynthesis;
  model_used: string;
  dip_used: number;
  audit_timestamp?: string;
}

export interface AuditSubmitParams {
  domain: string;
  github_owner: string;
  github_repo: string;
  github_branch?: string;
  keywords: KeywordInput[];
  desktop_performance?: number;
}

export interface UseAuditGraphReturn {
  status: AuditStatus;
  result: SeoAuditResult | null;
  error: string | null;
  isLoading: boolean;
  submit: (params: AuditSubmitParams) => Promise<void>;
  reset: () => void;
}

export function useAuditGraph(): UseAuditGraphReturn {
  const [status, setStatus] = useState<AuditStatus>('idle');
  const [result, setResult] = useState<SeoAuditResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async (params: AuditSubmitParams) => {
    setStatus('running');
    setResult(null);
    setError(null);
    try {
      const res = await fetch('/api/seo/audit-graph', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      const data = await res.json() as SeoAuditResult & { error?: string };
      if (!res.ok) throw new Error(data?.error ?? `Audit failed: ${res.status}`);
      setResult(data);
      setStatus('completed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Audit failed');
      setStatus('failed');
    }
  }, []);

  const reset = useCallback(() => {
    setStatus('idle');
    setResult(null);
    setError(null);
  }, []);

  return { status, result, error, isLoading: status === 'running', submit, reset };
}
