import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

/**
 * NextAuth config for a single-user deployment. We call the FastAPI
 * `/auth/login` endpoint to verify credentials and tuck the backend JWT
 * into the session so API calls can pass it as a Bearer token.
 */

const BACKEND =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    CredentialsProvider({
      name: "PFIP",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials.password) return null;
        try {
          const resp = await fetch(`${BACKEND}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          });
          if (!resp.ok) return null;
          const data = (await resp.json()) as {
            token?: string;
            expiresAt?: string;
          };
          if (!data.token) return null;
          return {
            id: credentials.email,
            email: credentials.email,
            name: credentials.email,
            // Attached to the JWT below.
            backendToken: data.token,
            expiresAt: data.expiresAt,
          } as unknown as import("next-auth").User;
        } catch {
          return null;
        }
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        // Persist backend JWT + expiry on first login.
        const u = user as unknown as {
          backendToken?: string;
          expiresAt?: string;
        };
        if (u.backendToken) token.backendToken = u.backendToken;
        if (u.expiresAt) token.expiresAt = u.expiresAt;
      }
      return token;
    },
    async session({ session, token }) {
      return {
        ...session,
        backendToken: token.backendToken as string | undefined,
        expiresAt: token.expiresAt as string | undefined,
      };
    },
  },
};
