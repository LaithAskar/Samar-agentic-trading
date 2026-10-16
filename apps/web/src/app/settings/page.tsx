"use client";

import { useEffect, useState } from "react";

import { api, watch } from "@/lib/api";
import type { BrokerSnapshotView, LiveStatus, SecretStatus } from "@/lib/contracts";

const fields = [
  { kind: "anthropic", title: "Anthropic", hint: "Paste an sk-ant- key in this box." },
  { kind: "openrouter", title: "OpenRouter", hint: "Paste an sk-or- key in this box." },
  { kind: "nous", title: "Nous Research", hint: "Paste an sk-nous- key from portal.nousresearch.com in this box." },
  { kind: "openai", title: "OpenAI", hint: "Paste an sk- key in this box." },
  { kind: "public_com", title: "Public.com", hint: "Paste a pub- key in this box. Live trading stays off until you confirm it on Live." },
] as const;

const defaultModels: Record<string, string> = {
  anthropic: "claude-haiku-4-5",
  openrouter: "anthropic/claude-haiku-4.5",
  openai: "gpt-4o-mini",
  nous: "Hermes-4.3-36B",
};

export default function SettingsPage() {
  const [saved, setSaved] = useState<SecretStatus[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const [options, setOptions] = useState<string[]>([]);
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("claude-haiku-4-5");
  const [ordersPerDay, setOrdersPerDay] = useState("4");
  const [ordersPerMinute, setOrdersPerMinute] = useState("2");
  const [pace, setPace] = useState({ capital_cap: 200, max_order_dollars: 200, daily_loss_stop: 50 });

  async function refresh() {
    setSaved(await api<SecretStatus[]>("/settings/keys"));
  }

  useEffect(() => {
    const stopKeys = watch<SecretStatus[]>(
      "/settings/keys",
      (rows) => {
        setSaved(rows);
        setMessage(null);
      },
      setMessage,
    );
    const stopStatus = watch<{ provider: string; model: string; options: string[] }>(
      "/assistant/status",
      (status) => {
        setOptions(status.options);
        if (status.provider !== "scripted") {
          setProvider(status.provider);
          setModel(status.model);
        }
      },
      () => undefined,
    );
    const stopLive = watch<LiveStatus>(
      "/live/status",
      (status) => {
        setOrdersPerDay(status.max_orders_per_day === null ? "" : String(status.max_orders_per_day));
        setOrdersPerMinute(String(status.max_orders_per_minute));
        setPace({
          capital_cap: status.capital_cap,
          max_order_dollars: status.max_order_dollars,
          daily_loss_stop: status.daily_loss_stop,
        });
      },
      () => undefined,
    );
    return () => {
      stopKeys();
      stopStatus();
      stopLive();
    };
  }, []);

  async function save(kind: (typeof fields)[number]["kind"]) {
    setMessage(null);
    try {
      await api(`/settings/keys/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ key: drafts[kind] ?? "" }),
      });
      setDrafts((current) => ({ ...current, [kind]: "" }));
      await refresh();
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : "rejected");
    }
  }

  async function remove(kind: string) {
    await api(`/settings/keys/${kind}`, { method: "DELETE" });
    await refresh();
  }

  async function saveChoice() {
    setMessage(null);
    try {
      const status = await api<{ provider: string; model: string }>("/assistant/choice", {
        method: "PUT",
        body: JSON.stringify({ provider, model }),
      });
      setProvider(status.provider);
      setModel(status.model);
      setSyncNote(`Assistant will call ${status.provider} with ${status.model}.`);
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : "choice rejected");
    }
  }

  async function saveOrderPace() {
    setMessage(null);
    const trimmed = ordersPerDay.trim();
    const perDay = trimmed === "" || trimmed.toLowerCase() === "unlimited" ? null : Number(trimmed);
    try {
      await api("/live/limits", {
        method: "PUT",
        body: JSON.stringify({
          capital_cap: pace.capital_cap,
          max_order_dollars: pace.max_order_dollars,
          daily_loss_stop: pace.daily_loss_stop,
          max_orders_per_day: perDay,
          max_orders_per_minute: Number(ordersPerMinute),
        }),
      });
      setSyncNote(perDay === null ? "Daily order count is unlimited." : `Daily order count is ${perDay}.`);
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : "limits rejected");
    }
  }
  async function syncPortfolio() {
    setMessage(null);
    setSyncNote(null);
    try {
      const snapshot = await api<BrokerSnapshotView>("/broker/sync", { method: "POST" });
      const count = snapshot.positions.length;
      const noun = count === 1 ? "holding" : "holdings";
      setSyncNote(`Synced ${count} ${noun} from ${snapshot.account_id}.`);
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : "sync failed");
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-medium">Settings</h1>
      <p className="max-w-xl text-sm text-muted">
        Bring your own keys. Samar stores ciphertext only and never sends the key back. AI calls bill your
        provider account. Paste the Public.com key here. Live orders stay off until you type the confirmation on
        the Live page.
      </p>
      {message ? <p className="text-sm text-loss">{message}</p> : null}
      {syncNote ? <p className="text-sm text-muted">{syncNote}</p> : null}
      {fields.map((field) => {
        const existing = saved.find((row) => row.kind === field.kind);
        return (
          <section key={field.kind} className="rounded-md border border-line bg-surface p-4">
            <h2 className="text-sm font-medium">{field.title}</h2>
            <p className="mt-1 text-sm text-muted">{field.hint}</p>
            {existing ? (
              <p className="num mt-2 text-sm">
                ••••{existing.last4} · {existing.status}
              </p>
            ) : (
              <p className="mt-2 text-sm text-muted">Not saved.</p>
            )}
            <input
              type="password"
              value={drafts[field.kind] ?? ""}
              onChange={(event) => setDrafts((current) => ({ ...current, [field.kind]: event.target.value }))}
              placeholder="Paste a new key"
              className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
              autoComplete="off"
            />
            <div className="mt-3 flex gap-3 text-sm">
              <button type="button" onClick={() => void save(field.kind)} className="text-accent">
                Save
              </button>
              {existing ? (
                <button type="button" onClick={() => void remove(field.kind)} className="text-muted">
                  Remove
                </button>
              ) : null}
            </div>
          </section>
        );
      })}
      {options.length > 1 ? (
        <section className="rounded-md border border-line bg-surface p-4">
          <h2 className="text-sm font-medium">Assistant model</h2>
          <p className="mt-1 text-sm text-muted">Several model keys are saved. Pick which one the assistant calls.</p>
          <select
            value={provider}
            onChange={(event) => {
              const next = event.target.value;
              setProvider(next);
              setModel(defaultModels[next] ?? "");
            }}
            className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
          >
            {options.map((option) => (
              <option key={option} value={option}>
                {fields.find((field) => field.kind === option)?.title ?? option}
              </option>
            ))}
          </select>
          <input
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
            aria-label="Model id"
          />
          <button type="button" onClick={() => void saveChoice()} className="mt-3 text-sm text-accent">
            Use this model
          </button>
        </section>
      ) : null}
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Orders per day</h2>
        <p className="mt-1 text-sm text-muted">The default is 4. Blank or Unlimited removes only this count.</p>
        <div className="mt-3 flex gap-2">
          <input
            value={ordersPerDay}
            onChange={(event) => setOrdersPerDay(event.target.value)}
            placeholder="Unlimited"
            aria-label="Orders per day"
            className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm"
          />
          <button type="button" onClick={() => setOrdersPerDay("")} className="shrink-0 text-sm text-accent">
            Unlimited
          </button>
        </div>
        <p className="mt-3 text-sm text-muted">
          Unlimited lets a model buy and sell the same day. Public cash accounts settle a stock sale on the next
          business day. Buying with those unsettled proceeds, then selling the new shares before settlement, is a
          good-faith violation. A fourth one in a year limits the account to settled cash. A fifth can make it
          sell-only for 90 days. Samar is cash-only, so a buy cannot spend unsettled sale proceeds. The old $25,000
          pattern-day-trader minimum was a margin-account rule. Public says that designation ended on June 4, 2026,
          and it does not apply here. Unlimited still leaves you exposed to fees, the spread, and losses from
          overtrading. Each model also has a per-minute cap so a loop cannot send an order every second.
        </p>
        <label className="mt-3 block text-xs text-muted">
          Max orders per minute for one model
          <input
            value={ordersPerMinute}
            onChange={(event) => setOrdersPerMinute(event.target.value)}
            inputMode="numeric"
            aria-label="Orders per minute"
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-sm text-ink"
          />
        </label>
        <button type="button" onClick={() => void saveOrderPace()} className="mt-3 text-sm text-accent">
          Save order pace
        </button>
      </section>
      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Brokerage</h2>
        <p className="mt-2 text-sm text-muted">
          Sync reads accounts and positions. Order placement lives on the Live page and is off until you confirm it.
        </p>
        <button
          type="button"
          onClick={() => void syncPortfolio()}
          className="mt-3 rounded-md bg-accent px-3 py-2 text-sm text-bg"
        >
          Sync portfolio
        </button>
      </section>
    </div>
  );
}
