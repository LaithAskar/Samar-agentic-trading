"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { money, type LiveStatus, type StrategyView } from "@/lib/contracts";

function dayField(value: number | null): string {
  return value === null ? "" : String(value);
}

function dayCap(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "" || trimmed.toLowerCase() === "unlimited") {
    return null;
  }
  return Number(trimmed);
}

const empty = {
  capital_cap: "200",
  max_order_dollars: "200",
  max_orders_per_day: "4",
  max_orders_per_minute: "2",
  daily_loss_stop: "50",
};

export default function LivePage() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");
  const [autoPhrase, setAutoPhrase] = useState("");
  const [limits, setLimits] = useState(empty);
  const [strategies, setStrategies] = useState<StrategyView[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [symbol, setSymbol] = useState("AAPL");
  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("20");
  const [reason, setReason] = useState("One share inside the cap");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const next = await api<LiveStatus>("/live/status");
    setStatus(next);
    setError(null);
    setLimits({
      capital_cap: String(next.capital_cap),
      max_order_dollars: String(next.max_order_dollars),
      max_orders_per_day: dayField(next.max_orders_per_day),
      max_orders_per_minute: String(next.max_orders_per_minute),
      daily_loss_stop: String(next.daily_loss_stop),
    });
    if (next.strategy_id) {
      setStrategyId(next.strategy_id);
    }
    if (next.model_provider) {
      setProvider(next.model_provider);
    }
    if (next.model_name) {
      setModel(next.model_name);
    }
  }

  useEffect(() => {
    let current = true;
    api<LiveStatus>("/live/status")
      .then((next) => {
        if (!current) {
          return;
        }
        setStatus(next);
        setLimits({
          capital_cap: String(next.capital_cap),
          max_order_dollars: String(next.max_order_dollars),
          max_orders_per_day: dayField(next.max_orders_per_day),
          max_orders_per_minute: String(next.max_orders_per_minute),
          daily_loss_stop: String(next.daily_loss_stop),
        });
      })
      .catch((reason: unknown) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "offline");
        }
      });
    api<StrategyView[]>("/strategies")
      .then((rows) => {
        if (current) {
          setStrategies(rows);
        }
      })
      .catch(() => undefined);
    const timer = window.setInterval(() => {
      api<LiveStatus>("/live/status")
        .then((next) => {
          if (current) {
            setStatus(next);
            setError(null);
          }
        })
        .catch((reason: unknown) => {
          if (current) {
            setError(reason instanceof Error ? reason.message : "offline");
          }
        });
    }, 5000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, []);

  async function act(path: string, body?: object) {
    setBusy(true);
    setError(null);
    try {
      await api(path, body ? { method: "POST", body: JSON.stringify(body) } : { method: "POST" });
      await refresh();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "rejected");
    } finally {
      setBusy(false);
    }
  }

  async function saveLimits() {
    setBusy(true);
    setError(null);
    try {
      await api("/live/limits", {
        method: "PUT",
        body: JSON.stringify({
          capital_cap: Number(limits.capital_cap),
          max_order_dollars: Number(limits.max_order_dollars),
          max_orders_per_day: dayCap(limits.max_orders_per_day),
          max_orders_per_minute: Number(limits.max_orders_per_minute),
          daily_loss_stop: Number(limits.daily_loss_stop),
        }),
      });
      await refresh();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "limits rejected");
    } finally {
      setBusy(false);
    }
  }

  async function draftTicket() {
    setBusy(true);
    setError(null);
    try {
      await api("/live/tickets", {
        method: "POST",
        body: JSON.stringify({
          symbol,
          side: "BUY",
          quantity: Number(quantity),
          limit_price: Number(limitPrice),
          reason,
          model: "manual",
        }),
      });
      await refresh();
    } catch (reasonText: unknown) {
      setError(reasonText instanceof Error ? reasonText.message : "ticket rejected");
    } finally {
      setBusy(false);
    }
  }

  async function saveSource(source: "off" | "strategy" | "model") {
    setBusy(true);
    setError(null);
    try {
      await api("/live/source", {
        method: "PUT",
        body: JSON.stringify({
          source,
          strategy_id: strategyId,
          provider,
          model,
        }),
      });
      await refresh();
    } catch (reasonText: unknown) {
      setError(reasonText instanceof Error ? reasonText.message : "source rejected");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4 pb-28">
      <header>
        <h1 className="text-[28px] font-medium">Live</h1>
        <p className="text-sm text-loss">
          Experimental. This can send real orders with real money. You can lose money. Not investment advice.
        </p>
      </header>
      {error ? <p className="text-sm text-loss">{error}</p> : null}
      {status ? (
        <section className="rounded-md border border-line bg-surface p-4">
          <p className="text-xs uppercase tracking-wide text-muted">Status</p>
          <p className={`mt-1 text-2xl font-medium ${status.banner === "paper" ? "text-muted" : "text-loss"}`}>
            {status.banner === "auto" ? "LIVE AUTO" : status.banner === "live" ? "LIVE" : "PAPER"}
          </p>
          <p className="mt-2 text-sm text-muted">
            Permission {status.permission}. Buying power{" "}
            {status.buying_power === null ? "unknown" : money(status.buying_power)}. Streak {status.reject_streak}.
          </p>
          {status.halted_reason ? <p className="mt-2 text-sm text-loss">Halted. {status.halted_reason}</p> : null}
          {status.mode === "auto" && status.source === "off" ? (
            <p className="mt-2 text-sm text-muted">Auto is on and no strategy or model is selected, so the worker places nothing.</p>
          ) : null}
        </section>
      ) : (
        <p className="text-sm text-muted">{error ? "Status unavailable." : "Checking live status"}</p>
      )}

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Turn live on</h2>
        <p className="mt-1 text-sm text-muted">
          Type <span className="text-ink">{status?.enable_phrase ?? "I understand I can lose this money"}</span>. A
          read-only Public key stays read-only.
        </p>
        <input
          value={phrase}
          onChange={(event) => setPhrase(event.target.value)}
          className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-3 text-base"
          aria-label="Live confirmation"
          autoComplete="off"
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => void act("/live/enable", { phrase })}
          className="mt-3 w-full rounded-md bg-accent px-3 py-3 text-sm text-bg"
        >
          Enable approve-each
        </button>
        <p className="mt-4 text-sm text-muted">
          Auto is a second switch. Type{" "}
          <span className="text-ink">{status?.auto_phrase ?? "auto trade while I am away"}</span>. It stays off until
          you do.
        </p>
        <input
          value={autoPhrase}
          onChange={(event) => setAutoPhrase(event.target.value)}
          className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-3 text-base"
          aria-label="Auto confirmation"
          autoComplete="off"
        />
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void act("/live/auto", { phrase: autoPhrase })}
            className="rounded-md border border-line px-3 py-3 text-sm"
          >
            Enable auto
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void act("/live/manual")}
            className="rounded-md border border-line px-3 py-3 text-sm text-muted"
          >
            Back to approve
          </button>
        </div>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Limits</h2>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {(
            [
              ["capital_cap", "Capital cap"],
              ["max_order_dollars", "Per order"],
              ["daily_loss_stop", "Daily loss stop"],
              ["max_orders_per_minute", "Per model / minute"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="text-xs text-muted">
              {label}
              <input
                inputMode="decimal"
                value={limits[key]}
                onChange={(event) => setLimits((current) => ({ ...current, [key]: event.target.value }))}
                className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-3 text-base text-ink"
              />
            </label>
          ))}
        </div>
        <label className="mt-3 block text-xs text-muted">
          Orders / day
          <input
            value={limits.max_orders_per_day}
            onChange={(event) => setLimits((current) => ({ ...current, max_orders_per_day: event.target.value }))}
            placeholder="Unlimited"
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-3 text-base text-ink"
          />
        </label>
        <button
          type="button"
          onClick={() => setLimits((current) => ({ ...current, max_orders_per_day: "" }))}
          className="mt-2 text-sm text-muted"
        >
          Unlimited
        </button>
        <p className="mt-2 text-sm text-muted">
          Blank or Unlimited removes the daily count. The cash-account warning is on Settings.
        </p>
        <button type="button" disabled={busy} onClick={() => void saveLimits()} className="mt-3 text-sm text-accent">
          Save limits
        </button>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">What the worker runs</h2>
        <p className="mt-1 text-sm text-muted">The worker keeps this schedule while the browser is closed.</p>
        <label className="mt-3 block text-xs text-muted">
          Strategy
          <select
            value={strategyId}
            onChange={(event) => setStrategyId(event.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-3 text-base text-ink"
          >
            <option value="">None</option>
            {strategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.name}
              </option>
            ))}
          </select>
        </label>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" disabled={busy} onClick={() => void saveSource("strategy")} className="rounded-md border border-line px-3 py-3 text-sm">
            Use strategy
          </button>
          <button type="button" disabled={busy} onClick={() => void saveSource("off")} className="rounded-md border border-line px-3 py-3 text-sm text-muted">
            Source off
          </button>
        </div>
        <label className="mt-3 block text-xs text-muted">
          Model provider
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-3 text-base text-ink"
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="openrouter">OpenRouter</option>
            <option value="nous">Nous</option>
          </select>
        </label>
        <input
          value={model}
          onChange={(event) => setModel(event.target.value)}
          aria-label="Model id"
          className="mt-3 w-full rounded-md border border-line bg-bg px-3 py-3 text-base"
        />
        <button type="button" disabled={busy} onClick={() => void saveSource("model")} className="mt-3 text-sm text-accent">
          Use this model
        </button>
        <p className="mt-2 text-sm text-muted">Current source {status?.source ?? "off"}.</p>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Draft a ticket</h2>
        <p className="mt-1 text-sm text-muted">Nothing is sent until you approve it. Auto mode sends a ticket that passes the limits.</p>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            aria-label="Symbol"
            className="rounded-md border border-line bg-bg px-3 py-3 text-base"
          />
          <input
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            aria-label="Quantity"
            inputMode="numeric"
            className="rounded-md border border-line bg-bg px-3 py-3 text-base"
          />
          <input
            value={limitPrice}
            onChange={(event) => setLimitPrice(event.target.value)}
            aria-label="Limit price"
            inputMode="decimal"
            className="rounded-md border border-line bg-bg px-3 py-3 text-base"
          />
        </div>
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-label="Reason"
          className="mt-2 w-full rounded-md border border-line bg-bg px-3 py-3 text-base"
        />
        <button type="button" disabled={busy} onClick={() => void draftTicket()} className="mt-3 text-sm text-accent">
          Create ticket
        </button>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Pending tickets</h2>
        {status && status.tickets.length === 0 ? <p className="mt-2 text-sm text-muted">No pending tickets.</p> : null}
        <ul className="mt-2 space-y-3">
          {status?.tickets.map((ticket) => (
            <li key={ticket.id} className="rounded-md border border-line p-3">
              <p className="text-sm">
                {ticket.side} {ticket.quantity} {ticket.symbol} at {money(ticket.limit_price)}
              </p>
              <p className="mt-1 text-sm text-muted">
                Est {money(ticket.est_cost)}. {ticket.reason} ({ticket.model})
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act(`/live/tickets/${ticket.id}/approve`)}
                className="mt-2 text-sm text-accent"
              >
                Approve
              </button>
            </li>
          ))}
        </ul>
        <button type="button" disabled={busy} onClick={() => void act("/live/check")} className="mt-3 text-sm text-muted">
          Run one check now
        </button>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Positions from the last check</h2>
        {status && status.positions.length === 0 ? <p className="mt-2 text-sm text-muted">No positions from the last check.</p> : null}
        <ul className="mt-2 space-y-1 text-sm">
          {status?.positions.map((position) => (
            <li key={position.symbol} className="num">
              {position.symbol} {position.quantity}
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Orders</h2>
        {status && status.orders.length === 0 ? <p className="mt-2 text-sm text-muted">No live orders yet.</p> : null}
        <ul className="mt-2 space-y-1 text-sm">
          {status?.orders.map((order) => (
            <li key={order.id}>
              {order.status} {order.side} {order.quantity} {order.symbol}
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-md border border-line bg-surface p-4">
        <h2 className="text-sm font-medium">Audit</h2>
        {status && status.audit.length === 0 ? <p className="mt-2 text-sm text-muted">No live decisions yet.</p> : null}
        <ul className="mt-2 space-y-2">
          {status?.audit.map((row) => (
            <li key={row.id} className="text-sm">
              <span className="text-muted">{row.action}</span> {row.detail}
            </li>
          ))}
        </ul>
      </section>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-bg p-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => void act("/live/kill")}
          className="w-full rounded-md bg-loss px-4 py-4 text-base font-medium text-bg"
        >
          Kill switch
        </button>
      </div>
    </div>
  );
}
