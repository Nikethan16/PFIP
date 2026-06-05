import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";

import { Providers } from "@/components/providers";
import { MobileNav } from "@/components/nav/mobile-nav";
import { Sidebar } from "@/components/nav/sidebar";
import { TopBar } from "@/components/nav/topbar";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PFIP — Solo Financial Intelligence Platform",
  description:
    "Your personal hedge-fund cockpit: dashboard, chat, portfolio, tax, and calibration.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1014" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <Providers>
          <div className="flex min-h-dvh w-full">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <TopBar />
              <main className="flex-1 pb-20 md:pb-0">
                <div className="mx-auto w-full max-w-[1400px] px-3 py-4 sm:px-6 lg:px-8">
                  {children}
                </div>
              </main>
              <MobileNav />
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
