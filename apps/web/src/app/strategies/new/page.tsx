"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { BacktestView, StrategyView } from "@/lib/contracts";

function Builder() {
  const params = useSearchParams();
  const router = useRouter();
  const templateId = params.get("template") ?? "sma_cross";
  const [spec, setSpec] = useState<StrategyView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api<StrategyView[]>("/strategies/templates")
      .then((rows) => {
        if (current) {
          setSpec(rows.find((row) => row.id === templateId) ?? rows[0] ?? null);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "offline");
        }
      });
    return () => {
      current = false;
    };
  }, [templateId]);

  async function run() {
    if (!spec) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await api<StrategyView>("/strategies", {
        method: "POST",
        body: JSON.stringify({ dsl: spec.dsl }),
      });
      const queued = await api<BacktestView>("/backtests", {
        method: "POST",
        body: JSON.stringify({ strategy_id: saved.id }),
      });
      await api<{ ran: number }>("/jobs/run-once", { method: "POST" });
      router.push(`/backtests/${queued.id}`);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "run failed");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-[28px] font-medium">Rule builder</h1>
        <p className="text-sm text-muted">When the fast average crosses the slow average, buy with cash. When it crosses back, sell the position.</p>
      </header>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      {!spec ? <div className="h-24 animate-pulse rounded-md bg-surface" /> : null}
      {spec ? (
        <section className="space-y-3 rounded-md border border-line bg-surface p-4">
          <p className="text-sm">
            Universe <span className="num">{spec.universe.join(", ")}</span>
          </p>
          <p className="text-sm leading-6">
            When SMA 20 crosses above SMA 50, buy 100% of cash, leaving a 1% buffer so the next open can gap.
            When SMA 20 crosses below SMA 50, sell the position.
          </p>
          <p className="text-xs text-muted">Fills at the next bar open, 5 bps slippage, no commission.</p>
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy}
            className="rounded-md bg-accent px-3 py-2 text-sm text-bg disabled:opacity-50"
          >
            {busy ? "Running" : "Backtest 2020–2024"}
          </button>
        </section>
      ) : null}
    </div>
  );
}

export default function NewStrategyPage() {
  return (
    <Suspense fallback={<div className="h-24 animate-pulse rounded-md bg-surface" />}>
      <Builder />
    </Suspense>
  );
}
