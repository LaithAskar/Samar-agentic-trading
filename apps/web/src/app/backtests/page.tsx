"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { watch } from "@/lib/api";
import { pct, type BacktestView } from "@/lib/contracts";

export default function BacktestsPage() {
  const [rows, setRows] = useState<BacktestView[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      watch<BacktestView[]>(
        "/backtests",
        (next) => {
          setRows(next);
          setError(null);
        },
        setError,
      ),
    [],
  );

  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-medium">Backtests</h1>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      {rows.length === 0 && !error ? <p className="text-sm text-muted">No runs yet.</p> : null}
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.id}>
            <Link href={`/backtests/${row.id}`} className="flex justify-between rounded-md border border-line px-4 py-3 text-sm">
              <span className="num">{row.id}</span>
              <span>{row.status}</span>
              <span className="num">{row.metrics ? pct(row.metrics.total_return_pct) : ""}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
