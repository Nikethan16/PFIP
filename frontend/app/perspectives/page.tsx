import { redirect } from "next/navigation";

/**
 * Perspectives is now a mode inside Chat (C4). Keep this route as a permanent
 * redirect so old links/bookmarks land on the panel.
 */
export default function PerspectivesPage() {
  redirect("/chat?mode=panel");
}
