/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
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
