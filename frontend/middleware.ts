import { withAuth } from "next-auth/middleware";

/**
 * Route guard. Every app route requires an authenticated NextAuth session;
 * unauthenticated requests are redirected to `/login` (matching the
 * `pages.signIn` configured in `lib/auth.ts`). The `matcher` below excludes
 * the login page, NextAuth's own API routes, and Next.js static assets so
 * they remain publicly reachable.
 */
export default withAuth({
  pages: { signIn: "/login" },
});

export const config = {
  // Protect everything EXCEPT:
  //   /login            — the sign-in page itself
  //   /api/auth/*       — NextAuth credential + session endpoints
  //   /_next/*          — Next.js build assets & HMR
  //   /favicon.ico, etc — common public files (any path with a file extension)
  matcher: [
    "/((?!login|api/auth|_next/static|_next/image|favicon.ico|.*\\..*).*)",
  ],
};
