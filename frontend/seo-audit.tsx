import { Outlet, createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_project/p/$projectId/seo-audit")({
  component: () => <Outlet />,
});
