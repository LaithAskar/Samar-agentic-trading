"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { StrategyView } from "@/lib/contracts";

export default function StrategiesPage() {
  const [templates, setTemplates] = useState<StrategyView[]>([]);
  const [mine, setMine] = useState<StrategyView[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    Promise.all([api<StrategyView[]>("/strategies/templates"), api<StrategyView[]>("/strategies")])
      .then(([library, saved]) => {
        if (!current) {
          return;
        }
        setTemplates(library);
        setMine(saved);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "offline");
        }
      });
    return () => {
      current = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-[28px] font-medium">Strategies</h1>
          <p className="text-sm text-muted">Rules are a typed spec. The backtester is the only interpreter.</p>
        </div>
        <Link href="/strategies/new" className="rounded-md bg-accent px-3 py-2 text-sm text-bg">
          New rule
        </Link>
      </header>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      <section>
        <h2 className="mb-2 text-sm text-muted">Library</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {templates.map((template) => (
            <Link
              key={template.id}
              href={`/strategies/new?template=${template.id}`}
              className="rounded-md border border-line bg-surface p-4"
            >
              <p className="font-medium">{template.name}</p>
              <p className="mt-1 text-sm text-muted">{template.universe.join(", ")}</p>
            </Link>
          ))}
        </div>
      </section>
      <section>
        <h2 className="mb-2 text-sm text-muted">Yours</h2>
        {mine.length === 0 ? <p className="text-sm text-muted">Nothing saved yet.</p> : null}
        <ul className="space-y-2">
          {mine.map((strategy) => (
            <li key={strategy.id} className="rounded-md border border-line px-4 py-3 text-sm">
              {strategy.name}
              <span className="num ml-2 text-muted">{strategy.id}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
