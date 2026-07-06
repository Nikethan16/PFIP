import { SectionTabs, RESEARCH_TABS } from "@/components/nav/section-tabs";

/**
 * Research section shell — unifies the two research surfaces (company research
 * `/diligence` and deep research `/research`) under one tab bar. `(research)`
 * is a route group, so the URLs stay `/diligence` and `/research`.
 */
export default function ResearchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <SectionTabs tabs={RESEARCH_TABS} aria-label="Research" />
      {children}
    </div>
  );
}
