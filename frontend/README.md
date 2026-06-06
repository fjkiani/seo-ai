# open-seo Integration Files

These files wire the `every-app/open-seo` frontend to the `openclaw-api` SEO Intelligence backend.

## Apply to open-seo fork

```bash
# D1 migration
cp 0019_seo_graph_audits.sql ../drizzle/

# Zod schemas
cp seoGraph.ts ../src/types/schemas/

# Server functions
cp seoGraph.ts ../src/serverFunctions/

# UI components
mkdir -p ../src/client/features/seo-graph
cp SeoGraphReport.tsx SeoGraphLauncher.tsx ../src/client/features/seo-graph/

# Routes
cp seo-audit.tsx "../src/routes/_project/p/\$projectId/"
mkdir -p "../src/routes/_project/p/\$projectId/seo-audit"
cp seo-audit.index.tsx "../src/routes/_project/p/\$projectId/seo-audit/index.tsx"

# Apply patches
cd .. && git apply open-seo-integration/navigation.items.patch
git apply open-seo-integration/app.schema.patch
```

## Env vars to add to wrangler.jsonc

```json
{ "name": "OPENCLAW_API_URL", "value": "https://openclaw-api-k30t.onrender.com" },
{ "name": "OPENCLAW_API_KEY", "value": "<your-clerk-token>" }
```

## What this delivers

- `GET /p/$projectId/seo-audit` — new nav item "AI SEO Audit" in Domain group
- Form: domain + GitHub repo + keywords → POST to openclaw-api → renders full result
- D1 table `seo_graph_audits` tracks every audit with full `result_json`
- History panel shows past audits with verdict badges
- Every audit feeds `zie_training_records` + `zie_preference_pairs` on the Render DB
