"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { SessionView } from "@/lib/contracts";

type AuthConfig = { mode: "local" } | { mode: "supabase"; url: string; anon_key: string };

export function SignIn({ onSuccess }: { onSuccess: (email: string) => void }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AuthConfig>("/auth/config")
      .then(setConfig)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "offline"));
  }, []);

  async function submit(path: "/auth/register" | "/auth/login") {
    setError(null);
    try {
      if (config?.mode === "supabase") {
        const response = await fetch(`${config.url}/auth/v1/token?grant_type=password`, {
          method: "POST",
          headers: { apikey: config.anon_key, "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        if (!response.ok) {
          throw new Error("email or password is wrong");
        }
        const body = (await response.json()) as { access_token?: string; user?: { email?: string } };
        if (!body.access_token) {
          throw new Error("email or password is wrong");
        }
        sessionStorage.setItem("samar_token", body.access_token);
        onSuccess(body.user?.email ?? email);
        return;
      }
      const session = await api<SessionView>(path, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      sessionStorage.setItem("samar_token", session.token);
      onSuccess(session.email);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "sign in failed");
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-4 p-8">
      <h1 className="text-[28px] font-medium">Samar</h1>
      <p className="text-sm text-muted">
        {config?.mode === "supabase"
          ? "Sign in with the Supabase project this server is pointed at."
          : "Create an account on this machine. The session token stays in this browser tab."}
      </p>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      <input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="Email"
        className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm"
        autoComplete="username"
      />
      <input
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="Password, at least 10 characters"
        className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm"
        autoComplete="current-password"
      />
      <div className="flex gap-3 text-sm">
        <button type="button" onClick={() => void submit("/auth/login")} className="rounded-md bg-accent px-3 py-2 text-bg">
          Sign in
        </button>
        {config?.mode === "supabase" ? null : (
          <button type="button" onClick={() => void submit("/auth/register")} className="text-accent">
            Create account
          </button>
        )}
      </div>
    </div>
  );
}
