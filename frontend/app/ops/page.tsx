import { redirect } from "next/navigation";

/**
 * `/ops` has no page of its own — it's the parent of the Operations section
 * (sources / schedules / models). Redirect it to the first child so the section
 * URL (and any breadcrumb/prefetch that targets `/ops`) resolves instead of 404ing.
 */
export default function OpsIndex() {
  redirect("/ops/sources");
}
