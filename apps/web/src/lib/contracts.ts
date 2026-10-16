export type StrategyView = {
  id: string;
  name: string;
  universe: string[];
  dsl: Record<string, unknown>;
};

export type EquityPoint = { date: string; equity: number };

export type TradeView = {
  date: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
};

export type MetricsView = {
  total_return_pct: number;
  cagr_pct: number;
  sharpe: number;
  sharpe_se: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  exposure_pct: number;
  num_round_trips: number;
  ending_equity: number;
};

export type SkepticismView = {
  beat_benchmark: boolean;
  benchmark_name: string;
  strategy_return_pct: number;
  benchmark_return_pct: number;
  sharpe: number;
  sharpe_se: number;
  sharpe_p_value: number;
  num_round_trips: number;
  sample_days: number;
  warnings: string[];
};

export type BacktestView = {
  id: string;
  strategy_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  metrics: MetricsView | null;
  skepticism: SkepticismView | null;
  equity: EquityPoint[];
  benchmark_equity: EquityPoint[];
  trades: TradeView[];
  error: string | null;
  data_label: "REAL DATA" | "SYNTHETIC DATA";
};

export type SecretStatus = {
  kind: "anthropic" | "openrouter" | "openai" | "nous" | "public_com";
  last4: string;
  status: "valid" | "invalid" | "revoked";
  validated_at: string;
};

export type PaperAccountView = {
  cash: number;
  equity: number;
  starting_cash: number;
  pnl: number;
  positions: {
    ticker: string;
    quantity: number;
    avg_price: number;
    last_price: number;
    market_value: number;
  }[];
  orders: TradeView[];
};

export type ProposalView = {
  id: string;
  kind: "create_strategy" | "run_backtest";
  status: "pending" | "approved" | "rejected";
  payload: Record<string, string>;
};

export type BrokerSnapshotView = {
  label: "REAL ACCOUNT · read-only";
  account_id: string;
  equity: number;
  cash: number;
  positions: { symbol: string; quantity: number; market_value: number }[];
  synced_at: string;
};

export type ArenaProposalView = {
  index: number;
  ok: boolean;
  error: string | null;
  train_sharpe: number | null;
  spec_name: string | null;
};

export type ArenaEntryView = {
  contestant: string;
  model: string;
  status: string;
  n_trials: number;
  n_failures: number;
  tokens_in: number;
  tokens_out: number;
  rank: number | null;
  deflated_sharpe: number | null;
  test_sharpe: number | null;
  test_sharpe_se: number | null;
  test_max_drawdown_pct: number | null;
  turnover: number | null;
  fold_sharpes: number[];
  skepticism: SkepticismView | null;
  equity: EquityPoint[];
  proposals: ArenaProposalView[];
};

export type ArenaRunView = {
  id: string;
  status: string;
  ticker: string;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  budget_proposals: number;
  token_cap: number;
  entries: ArenaEntryView[];
  error: string | null;
  data_label: "REAL DATA" | "SYNTHETIC DATA";
};

export type SessionView = {
  token: string;
  user_id: string;
  email: string;
};

export type LiveTicket = {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  limit_price: number;
  est_cost: number;
  reason: string;
  model: string;
  status: string;
  expires_at: string;
};

export type LiveOrder = {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  limit_price: number;
  status: string;
};

export type LiveAudit = {
  id: string;
  at: string;
  action: string;
  detail: string;
};

export type LivePosition = {
  symbol: string;
  quantity: number;
  instrument_type: string;
};

export type LiveStatus = {
  enabled: boolean;
  mode: "approve" | "auto";
  banner: "paper" | "live" | "auto";
  permission: string;
  capital_cap: number;
  max_order_dollars: number;
  max_orders_per_day: number | null;
  max_orders_per_minute: number;
  daily_loss_stop: number;
  source: "off" | "strategy" | "model";
  strategy_id: string;
  model_provider: string;
  model_name: string;
  buying_power: number | null;
  positions: LivePosition[];
  tickets: LiveTicket[];
  orders: LiveOrder[];
  audit: LiveAudit[];
  halted_reason: string;
  reject_streak: number;
  enable_phrase: string;
  auto_phrase: string;
};

export function money(value: number): string {
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function pct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}
