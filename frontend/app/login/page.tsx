"use client";

import * as React from "react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Lock, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { toast } from "@/components/ui/toast";

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const callbackUrl = search.get("callbackUrl") ?? "/";

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });
      if (!res || res.error) {
        toast.error("Invalid email or password");
        return;
      }
      router.push(callbackUrl);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative -mx-3 -my-4 flex min-h-[80vh] items-center justify-center overflow-hidden px-4 sm:-mx-6 lg:-mx-8">
      {/* Ambient gradient background */}
      <div
        className="pointer-events-none absolute inset-0 opacity-80"
        aria-hidden
      >
        <div className="absolute -top-32 left-1/2 h-[40rem] w-[40rem] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl" />
        <div className="absolute bottom-0 right-1/3 h-[24rem] w-[24rem] rounded-full bg-fuchsia-500/10 blur-3xl" />
      </div>

      <div className="relative z-10 w-full max-w-sm space-y-6">
        {/* Brand */}
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="relative flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-primary to-primary/60 text-primary-foreground shadow-lg shadow-primary/20">
            <span className="relative z-10 text-base font-bold">PF</span>
            <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.4),transparent_60%)]" />
          </div>
          <div>
            <div className="text-base font-semibold tracking-tight">PFIP</div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Solo Financial Intelligence Platform
            </div>
          </div>
        </div>

        <Card className="border-border/60 shadow-xl shadow-black/5 backdrop-blur supports-[backdrop-filter]:bg-card/80">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Sign in</CardTitle>
            <CardDescription className="text-xs">
              Use the single-user credentials configured in your{" "}
              <code className="font-mono">.env</code>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-3">
              <div>
                <Label htmlFor="email" className="text-xs">
                  Email
                </Label>
                <div className="relative mt-1">
                  <Mail className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="pl-8"
                    placeholder="you@example.com"
                  />
                </div>
              </div>
              <div>
                <div className="flex items-baseline justify-between">
                  <Label htmlFor="password" className="text-xs">
                    Password
                  </Label>
                </div>
                <div className="relative mt-1">
                  <Lock className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="pl-8"
                  />
                </div>
              </div>
              <Button
                type="submit"
                className="w-full gap-2"
                disabled={loading}
              >
                {loading ? "Signing in…" : "Sign in"}
                {!loading ? <ArrowRight className="h-3.5 w-3.5" /> : null}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-[11px] text-muted-foreground">
          PFIP is a personal tool. No data leaves your infrastructure unless
          you explicitly opt in to external LLM providers in{" "}
          <Link href={"/settings" as never} className="underline hover:text-foreground">
            settings
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
