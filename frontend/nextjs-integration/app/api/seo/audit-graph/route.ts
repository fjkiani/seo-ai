/**
 * /api/seo/audit-graph — Next.js proxy route to openclaw-api (synchronous)
 *
 * Drop this file into your Next.js app at:
 *   src/app/api/seo/audit-graph/route.ts
 *
 * Calls: POST https://openclaw-api-k30t.onrender.com/api/v1/seo/audit
 * Synchronous — awaits full result (5–55s). No polling needed.
 *
 * Env vars required:
 *   SEO_API_URL      (default: https://openclaw-api-k30t.onrender.com)
 *   OPENCLAW_API_KEY (default: test)
 */
import { NextRequest, NextResponse } from 'next/server';

const OPENCLAW_API_URL =
  process.env.SEO_API_URL ?? 'https://openclaw-api-k30t.onrender.com';

const TIMEOUT_MS = 65_000;

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(`${OPENCLAW_API_URL}/api/v1/seo/audit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${process.env.OPENCLAW_API_KEY ?? 'test'}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    clearTimeout(timer);
    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: (data as { error?: string })?.error ?? `openclaw-api returned ${res.status}` },
        { status: res.status },
      );
    }

    return NextResponse.json(data);
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof Error && err.name === 'AbortError') {
      return NextResponse.json({ error: 'Audit timed out after 65s' }, { status: 504 });
    }
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Internal error' },
      { status: 500 },
    );
  }
}
