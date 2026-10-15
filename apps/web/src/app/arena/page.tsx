"use client";

import { useMemo, useState } from "react";

import { EquityChart } from "@/components/equity-chart";
import { api } from "@/lib/api";
import type { ArenaRunView } from "@/lib/contracts";

const choices = [
  { provider: "random", title: "Random search", model: "random-search" },
  { provider: "anthropic", title: "Anthropic", model: "claude-haiku-4-5" },
  { provider: "openrouter", title: "OpenRouter", model: "anthropic/claude-haiku-4.5" },
  { provider: "openai", title: "OpenAI", model: "gpt-4o-mini" },
  { provider: "nous", title: "Nous Research", model: "Hermes-4.3-36B" },
] as const;

export default function ArenaPage() {
  const [picked, setPicked] = useState<Record<string, boolean>>({ random: true });
  const [models, setModels] = useState<Record<string, string>>({});
  const [run, setRun] = useState<ArenaRunView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const series = useMemo(
    () =>
      run?.entries
        .filter((entry) => entry.equity.length > 0)
        .map((entry) => ({ name: `${entry.contestant} ${entry.model}`, points: entry.equity })) ?? [],
    [run],
  );

  function toggle(provider: string) {
    setPicked((current) => ({ ...current, [provider]: !current[provider] }));
  }

  async function start() {
    setError(null);
    setBusy(true);
    try {
      const contestants = choices
        .filter((choice) => picked[choice.provider])
        .map((choice) => ({ provider: choice.provider, model: models[choice.provider] || choice.model }));
      const created = await api<ArenaRunView>("/arena/runs", {
        method: "POST",
        body: JSON.stringify({ contestants, budget_proposals: 3, token_cap: 8000 }),
      });
      if (created.status === "queued") {
        await api("/jobs/run-once", { method: "POST" });
      }
      setRun(await api<ArenaRunView>(`/arena/runs/${created.id}`));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "arena failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-medium">Arena</h1>
      <p className="max-w-xl text-sm text-muted">
        Each contestant gets the same frozen AAPL file, the same train window, and the same number of proposals.
        Rank uses the held-out window after a haircut for how many trials were tried. Train Sharpe is not the rank.
        These are historical backtests on a small sample. A higher rank is not a prediction. Not investment advice.
        Paper only. Public.com stays read-only.
      </p>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Contestants</h2>
        <ul className="mt-3 space-y-3">
          {choices.map((choice) => (
            <li key={choice.provider} className="grid gap-2 md:grid-cols-[12rem_1fr] md:items-center">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(picked[choice.provider])}
                  onChange={() => toggle(choice.provider)}
                />
                {choice.title}
              </label>
              <input
                value={models[choice.provider] ?? choice.model}
                onChange={(event) => setModels((current) => ({ ...current, [choice.provider]: event.target.value }))}
                aria-label={`${choice.title} model`}
                className="rounded-md border border-line bg-bg px-3 py-2 text-sm"
                disabled={choice.provider === "random"}
              />
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          className="mt-4 rounded-md bg-accent px-3 py-2 text-sm text-bg"
        >
          {busy ? "Running" : "Run arena"}
        </button>
      </section>
      {run ? (
        <section className="space-y-4">
          <p className="text-sm text-muted">
            Train {run.train_start} to {run.train_end}. Held-out {run.test_start} to {run.test_end}. Budget{" "}
            {run.budget_proposals} proposals. Status {run.status}.
          </p>
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-left text-sm">
              <thead className="text-muted">
                <tr>
                  <th className="p-3">Rank</th>
                  <th className="p-3">Contestant</th>
                  <th className="p-3">Held-out Sharpe</th>
                  <th className="p-3">SE</th>
                  <th className="p-3">Deflated</th>
                  <th className="p-3">Drawdown</th>
                  <th className="p-3">Turnover</th>
                  <th className="p-3">Trials</th>
                  <th className="p-3">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {run.entries.map((entry) => (
                  <tr key={`${entry.contestant}-${entry.model}`} className="border-t border-line">
                    <td className="num p-3">{entry.rank}</td>
                    <td className="p-3">
                      {entry.contestant} · {entry.model}
                    </td>
                    <td className="num p-3">{entry.test_sharpe?.toFixed(3) ?? "n/a"}</td>
                    <td className="num p-3">{entry.test_sharpe_se?.toFixed(3) ?? "n/a"}</td>
                    <td className="num p-3">{entry.deflated_sharpe?.toFixed(3) ?? "n/a"}</td>
                    <td className="num p-3">{entry.test_max_drawdown_pct?.toFixed(2) ?? "n/a"}</td>
                    <td className="num p-3">{entry.turnover ?? "n/a"}</td>
                    <td className="num p-3">
                      {entry.n_trials} / {entry.n_failures} failed
                    </td>
                    <td className="num p-3">
                      {entry.tokens_in}+{entry.tokens_out}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {series.length > 0 ? <EquityChart equity={[]} benchmark={[]} series={series} /> : null}
          {run.entries.map((entry) => (
            <article key={`${entry.contestant}-detail`} className="rounded-md border border-line bg-surface p-4">
              <h2 className="text-sm font-medium">
                {entry.contestant} · {entry.model}
              </h2>
              {entry.fold_sharpes.length > 0 ? (
                <p className="num mt-2 text-sm text-muted">
                  Walk-forward Sharpes {entry.fold_sharpes.map((value) => value.toFixed(3)).join(", ")}
                </p>
              ) : null}
              <ul className="mt-2 space-y-1 text-sm text-muted">
                {(entry.skepticism?.warnings ?? ["No held-out score. Every proposal failed."]).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
              <ol className="mt-3 space-y-1 text-sm">
                {entry.proposals.map((proposal) => (
                  <li key={proposal.index}>
                    {proposal.ok
                      ? `Trial ${proposal.index + 1}. ${proposal.spec_name}. Train Sharpe ${proposal.train_sharpe?.toFixed(3)}.`
                      : `Trial ${proposal.index + 1} failed. ${proposal.error}`}
                  </li>
                ))}
              </ol>
            </article>
          ))}
        </section>
      ) : (
        <p className="text-sm text-muted">No arena run yet.</p>
      )}
    </div>
  );
}
