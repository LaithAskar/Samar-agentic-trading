"use client";

import { createChart, type IChartApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { EquityPoint } from "@/lib/contracts";

export function EquityChart({
  equity,
  benchmark,
  series,
}: {
  equity: EquityPoint[];
  benchmark: EquityPoint[];
  series?: { name: string; points: EquityPoint[] }[];
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }
    const style = getComputedStyle(document.documentElement);
    const chart: IChartApi = createChart(node, {
      height: 280,
      layout: {
        background: { color: "transparent" },
        textColor: style.getPropertyValue("--muted").trim(),
      },
      grid: {
        vertLines: { color: style.getPropertyValue("--border").trim() },
        horzLines: { color: style.getPropertyValue("--border").trim() },
      },
      rightPriceScale: { borderColor: style.getPropertyValue("--border").trim() },
      timeScale: { borderColor: style.getPropertyValue("--border").trim() },
    });
    const palette = ["--accent", "--gain", "--loss", "--muted"].map((name) => style.getPropertyValue(name).trim());
    const lines = series ?? [
      { name: "strategy", points: equity },
      { name: "benchmark", points: benchmark },
    ];
    lines.forEach((line, index) => {
      const drawn = chart.addLineSeries({
        color: palette[index % palette.length] ?? style.getPropertyValue("--text").trim(),
        lineWidth: index === 0 ? 2 : 1,
      });
      drawn.setData(toLine(line.points));
    });
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: node.clientWidth });
    onResize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [equity, benchmark, series]);

  return <div ref={ref} className="w-full" />;
}

function toLine(points: EquityPoint[]): LineData[] {
  return points.map((point) => ({ time: point.date, value: point.equity }));
}
