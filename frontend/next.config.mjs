/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  // Defense-in-depth security headers applied to every response. The CSP is
  // intentionally permissive for a Next.js app (it needs inline/eval scripts
  // for the dev runtime and hydration) while still constraining framing,
  // object embedding, and the set of hosts the app may talk to (self +
  // the localhost FastAPI backend). `connect-src` allows ws: for HMR in dev.
  async headers() {
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      "connect-src 'self' http://localhost:8000 ws: wss:",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ");
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          { key: "Content-Security-Policy", value: csp },
        ],
      },
    ];
  },
  // In dev we proxy any `/backend/*` request straight through to FastAPI.
  // Client code should prefer `NEXT_PUBLIC_API_URL` directly; this rewrite
  // exists so server components can call `/backend/...` without CORS.
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
