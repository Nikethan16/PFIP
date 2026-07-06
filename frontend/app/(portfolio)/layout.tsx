import { SectionTabs, PORTFOLIO_TABS } from "@/components/nav/section-tabs";

/**
 * Portfolio section shell. Groups holdings, the analytics surfaces
 * (net-worth / benchmark / what-if / stress / shadow) and tax under a single
 * tab bar. Routes are unchanged — `(portfolio)` is a route group, so URLs stay
 * `/portfolio`, `/net-worth`, `/tax`, etc.
 */
export default function PortfolioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <SectionTabs tabs={PORTFOLIO_TABS} aria-label="Portfolio" />
      {children}
    </div>
  );
}
