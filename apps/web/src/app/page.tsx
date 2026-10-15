"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { watch } from "@/lib/api";
import { money, pct, type BrokerSnapshotView, type PaperAccountView } from "@/lib/contracts";

export default function DashboardPage() {
  const [account, setAccount] = useState<PaperAccountView | null>(null);
  const [broker, setBroker] = useState<BrokerSnapshotView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stopPaper = watch<PaperAccountView>(
      "/paper",
      (row) => {
        setAccount(row);
        setError(null);
      },
      setError,
    );
    const stopBroker = watch<BrokerSnapshotView | null>(
      "/broker/snapshot",
      (row) => setBroker(row),
      setError,
    );
    return () => {
      stopPaper();
      stopBroker();
    };
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-[28px] font-medium">Paper account</h1>
        <p className="text-sm text-muted">$100,000 simulated cash. Fills use the next bar&apos;s open.</p>
      </header>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      {!account && !error ? <div className="h-24 animate-pulse rounded-md bg-surface" /> : null}
      {account ? (
        <section className="grid gap-3 md:grid-cols-3">
          <Stat label="Equity" value={money(account.equity)} />
          <Stat label="Cash" value={money(account.cash)} />
          <Stat
            label="P&L"
            value={money(account.pnl)}
            tone={account.pnl >= 0 ? "gain" : "loss"}
          />
        </section>
      ) : null}
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">Positions</h2>
        {account && account.positions.length === 0 ? (
          <p className="text-sm text-muted">No simulated positions yet.</p>
        ) : null}
        {account && account.positions.length > 0 ? (
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-2 font-normal">Ticker</th>
                <th className="py-2 font-normal">Shares</th>
                <th className="py-2 font-normal">Value</th>
              </tr>
            </thead>
            <tbody>
              {account.positions.map((position) => (
                <tr key={position.ticker} className="border-t border-line">
                  <td className="py-2">{position.ticker}</td>
                  <td className="num py-2">{position.quantity}</td>
                  <td className="num py-2">{money(position.market_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">REAL ACCOUNT · read-only</h2>
        {broker && broker.positions.length > 0 ? (
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-2 font-normal">Ticker</th>
                <th className="py-2 font-normal">Shares</th>
                <th className="py-2 font-normal">Value</th>
              </tr>
            </thead>
            <tbody>
              {broker.positions.map((position) => (
                <tr key={position.symbol} className="border-t border-line">
                  <td className="py-2">{position.symbol}</td>
                  <td className="num py-2">{position.quantity}</td>
                  <td className="num py-2">{money(position.market_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted">No synced holdings. Sync from Settings. Samar cannot place orders.</p>
        )}
      </section>
      <Link href="/strategies" className="inline-block text-sm text-accent">
        Build a strategy
      </Link>
      <p className="text-xs text-muted">{account ? `${account.orders.length} paper fills` : ""}</p>
      <p className="hidden">{account ? pct(account.pnl) : ""}</p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "gain" | "loss" }) {
  const color = tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : "text-ink";
  return (
    <div className="rounded-md border border-line bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`num mt-2 text-[20px] ${color}`}>{value}</p>
    </div>
  );
}
