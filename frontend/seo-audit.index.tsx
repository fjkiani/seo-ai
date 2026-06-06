import { createFileRoute } from "@tanstack/react-router";
import { SeoGraphLauncher } from "@/client/features/seo-graph/SeoGraphLauncher";

export const Route = createFileRoute("/_project/p/$projectId/seo-audit/")({
  component: SeoAuditPage,
});

function SeoAuditPage() {
  const { projectId } = Route.useParams();

  return (
    <div className="px-4 py-4 md:px-6 md:py-6 pb-24 md:pb-8 overflow-auto">
      <div className="mx-auto max-w-5xl space-y-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">AI SEO Audit</h1>
          <p className="text-sm text-base-content/60">
            Every audit feeds the ZIE data flywheel — making future audits smarter.
          </p>
        </div>
        <SeoGraphLauncher projectId={projectId} />
      </div>
    </div>
  );
}
