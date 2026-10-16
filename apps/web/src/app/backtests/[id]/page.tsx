"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { EquityChart } from "@/components/equity-chart";
import { api, watch } from "@/lib/api";
import { money, pct, type BacktestView } from "@/lib/contracts";

export default function BacktestResultPage() {
  const params = useParams<{ id: string }>();
  const [row, setRow] = useState<BacktestView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(
    () =>
      watch<BacktestView>(
        `/backtests/${params.id}`,
        (next) => {
          setRow(next);
          setError(null);
        },
        setError,
      ),
    [params.id],
  );

  async function paper() {
    if (!row) {
      return;
    }
    await api("/paper/deploy", {
      method: "POST",
      body: JSON.stringify({ strategy_id: row.strategy_id, started_on: "2020-01-02" }),
    });
    const inserted = await api<{ inserted: number }>("/paper/eval", {
      method: "POST",
      body: JSON.stringify({ as_of: "2024-12-31" }),
    });
    setNote(`Paper eval inserted ${inserted.inserted} fills. The same day will not insert them again.`);
  }

  if (error) {
    return <p className="text-sm text-loss">{error}</p>;
  }
  if (!row) {
    return <div className="h-40 animate-pulse rounded-md bg-surface" />;
  }
  if (!row.metrics || !row.skepticism) {
    return (
      <div className="space-y-3">
        <h1 className="text-[28px] font-medium">Backtest</h1>
        <p className="text-sm font-medium">{row.data_label}</p>
        <p className="text-sm text-muted">Status {row.status}.</p>
        {row.error ? <p className="text-sm text-loss">{row.error}</p> : null}
      </div>
    );
  }
  const metrics = row.metrics;
  const skepticism = row.skepticism;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-[28px] font-medium">Backtest</h1>
        <p className="text-sm font-medium">{row.data_label}</p>
        <p className="text-sm text-muted">Next-bar open fills. 5 bps slippage. Marked at the close.</p>
      </header>
      <EquityChart equity={row.equity} benchmark={row.benchmark_equity} />
      <p className="text-xs text-muted">Violet is the strategy. Gray is SPY buy-and-hold.</p>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Return" value={pct(metrics.total_return_pct)} />
        <Metric label="CAGR" value={pct(metrics.cagr_pct)} />
        <Metric label="Sharpe" value={`${metrics.sharpe.toFixed(2)} ± ${metrics.sharpe_se.toFixed(2)}`} />
        <Metric label="Max drawdown" value={pct(metrics.max_drawdown_pct)} />
        <Metric label="Win rate" value={`${metrics.win_rate_pct.toFixed(1)}%`} />
        <Metric label="Round trips" value={String(metrics.num_round_trips)} />
        <Metric label="Exposure" value={`${metrics.exposure_pct.toFixed(1)}%`} />
        <Metric label="Ending equity" value={money(metrics.ending_equity)} />
      </section>
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Why to be skeptical</h2>
        <p className="mt-2 text-sm">
          Holding the same ticker returned {pct(skepticism.benchmark_return_pct)}. The strategy returned{" "}
          {pct(skepticism.strategy_return_pct)}. Sharpe p-value {skepticism.sharpe_p_value.toFixed(4)}.
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
          {skepticism.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </section>
      <button type="button" onClick={() => void paper()} className="rounded-md bg-accent px-3 py-2 text-sm text-bg">
        Paper trade this
      </button>
      {note ? <p className="text-sm text-muted">{note}</p> : null}
      <section>
        <h2 className="mb-2 text-sm text-muted">Trades</h2>
        <table className="w-full text-left text-sm">
          <tbody>
            {row.trades.slice(0, 12).map((trade) => (
              <tr key={`${trade.date}-${trade.side}`} className="border-t border-line">
                <td className="num py-2">{trade.date}</td>
                <td className={trade.side === "BUY" ? "text-gain" : "text-loss"}>{trade.side}</td>
                <td className="num">{trade.quantity}</td>
                <td className="num">{trade.price.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="num mt-1 text-sm">{value}</p>
    </div>
  );
}
