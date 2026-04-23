import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    backendToken?: string;
    expiresAt?: string;
  }

  interface User {
    backendToken?: string;
    expiresAt?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    backendToken?: string;
    expiresAt?: string;
  }
}
