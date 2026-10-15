const terms = [
  {
    name: "Lookahead bias",
    body: "A backtest that fills at the same close that generated the signal is using information you would not have had. Samar fills at the next bar's open.",
  },
  {
    name: "Sharpe ratio",
    body: "Annualized mean daily return divided by the sample standard deviation, times the square root of 252. The ± figure is the Mertens/Lo standard error.",
  },
  {
    name: "Drawdown",
    body: "The drop from a peak in the equity curve to a later trough. Shown as a negative percent.",
  },
  {
    name: "Slippage",
    body: "Buys fill a little above the open and sells a little below. The default is 5 basis points each way.",
  },
];

export default function LearnPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-medium">Learn</h1>
      <p className="text-sm text-muted">The numbers on a backtest are measurements, not instructions.</p>
      <div className="grid gap-3 md:grid-cols-2">
        {terms.map((term) => (
          <article key={term.name} className="rounded-md border border-line bg-surface p-4">
            <h2 className="text-sm font-medium">{term.name}</h2>
            <p className="mt-2 text-sm text-muted">{term.body}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
