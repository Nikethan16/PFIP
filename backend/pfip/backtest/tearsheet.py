"""QuantStats-style HTML tearsheet generator.

Tries `quantstats` first (full Pyfolio-style HTML). Falls back to a small
self-contained HTML report when quantstats isn't installed so the rest of the
pipeline still produces something useful.

Inputs:
    * ``returns`` — pd.Series of strategy returns (indexed by datetime).
    * ``benchmark`` — optional pd.Series of a benchmark's returns (e.g.
      buy-and-hold) for the same period.
    * ``metadata`` — free-form dict that we render as a header table.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import (
    _calmar,
    _cagr,
    _hit_rate,
    _max_drawdown,
    _sharpe,
    _sortino,
)

log = logging.getLogger(__name__)

try:  # pragma: no cover — optional
    import quantstats as qs  # type: ignore[import-untyped]

    _HAS_QS = True
except Exception:  # pragma: no cover
    qs = None  # type: ignore[assignment]
    _HAS_QS = False


def monthly_returns_table(returns: pd.Series) -> pd.DataFrame:
    """Pivot a daily-return series into the classic year×month grid used by
    QuantStats. The returned DataFrame has years as the index and months
    Jan..Dec as columns, plus a 'YTD' total column. Months with no data
    are NaN.

    Inputs are compounded within the month: ``(1+r).prod() - 1``.
    """
    r = returns.dropna()
    if r.empty:
        return pd.DataFrame(
            columns=[
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
                "YTD",
            ]
        )
    idx = pd.to_datetime(r.index)
    df = pd.DataFrame({"ret": r.values, "y": idx.year, "m": idx.month})
    monthly = df.groupby(["y", "m"])["ret"].apply(lambda s: (1.0 + s).prod() - 1.0)
    grid = monthly.unstack("m")
    grid.columns = [
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][
            c - 1
        ]
        for c in grid.columns
    ]
    # Reindex to ensure all 12 months present.
    for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
        if m not in grid.columns:
            grid[m] = pd.NA
    grid = grid[
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ]
    grid["YTD"] = grid.apply(
        lambda row: (1.0 + row.dropna()).prod() - 1.0 if row.notna().any() else pd.NA,
        axis=1,
    )
    return grid


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Per-bar drawdown vs the running peak of the cumulative equity curve.

    All values are <= 0; 0 means at a new high. Useful for plotting the
    underwater chart and for halt-threshold monitoring.
    """
    r = returns.fillna(0.0)
    if r.empty:
        return pd.Series(dtype=float)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    return eq / peak - 1.0


def _summary_stats(returns: pd.Series) -> dict[str, float]:
    """Stripped-down headline stats — used for both the QS and fallback paths."""
    r = returns.dropna()
    return {
        "sharpe": _sharpe(r),
        "sortino": _sortino(r),
        "calmar": _calmar(r),
        "max_drawdown": _max_drawdown(r),
        "cagr": _cagr(r),
        "hit_rate": _hit_rate(r),
        "total_return": float((1.0 + r).prod() - 1.0) if not r.empty else 0.0,
        "n_obs": int(len(r)),
    }


def _build_html_table(rows: Mapping[str, Any]) -> str:
    body = []
    for k, v in rows.items():
        if isinstance(v, float):
            cell = f"{v:.4f}"
        else:
            cell = html.escape(str(v))
        body.append(f"<tr><th>{html.escape(str(k))}</th><td>{cell}</td></tr>")
    return "<table>" + "".join(body) + "</table>"


def generate_tearsheet(
    returns: pd.Series,
    *,
    output_path: str | Path,
    benchmark: pd.Series | None = None,
    title: str = "PFIP Backtest Tearsheet",
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write a tearsheet HTML file and return its ``Path``.

    Uses quantstats if available; otherwise emits a small but valid HTML
    report with stats + an equity curve embedded as base64 PNG (if matplotlib
    is available) or the JSON of equity per timestamp.
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if _HAS_QS:  # pragma: no cover — only with optional dep
        try:
            qs.reports.html(
                returns,
                benchmark=benchmark,
                output=str(out_path),
                title=title,
            )
            return out_path
        except Exception as exc:
            log.warning("quantstats failed (%s); using fallback", exc)

    return _fallback_html(
        returns,
        output_path=out_path,
        benchmark=benchmark,
        title=title,
        metadata=metadata or {},
    )


def _fallback_html(
    returns: pd.Series,
    *,
    output_path: Path,
    benchmark: pd.Series | None,
    title: str,
    metadata: Mapping[str, Any],
) -> Path:
    stats = _summary_stats(returns)
    bench_stats = _summary_stats(benchmark) if benchmark is not None else {}

    equity = (1.0 + returns.fillna(0.0)).cumprod()
    equity_pairs = [
        {"t": str(t), "equity": float(v)}
        for t, v in equity.tail(500).items()
    ]

    meta_block = _build_html_table(
        {
            "Generated at": datetime.now(tz=timezone.utc).isoformat(),
            **metadata,
        }
    )
    stats_block = _build_html_table(stats)
    bench_block = _build_html_table(bench_stats) if bench_stats else ""

    html_str = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 920px; color: #222; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 0.5rem; }}
    h2 {{ font-size: 1.1rem; margin-top: 1.4rem; }}
    table {{ border-collapse: collapse; margin-bottom: 1rem; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 14px; }}
    th {{ background: #f5f5f5; }}
    pre {{ background: #f9f9f9; padding: 10px; overflow-x: auto; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p><em>QuantStats not installed — using built-in fallback report.</em></p>

  <h2>Run metadata</h2>
  {meta_block}

  <h2>Strategy stats</h2>
  {stats_block}

  {"<h2>Benchmark stats</h2>" + bench_block if bench_block else ""}

  <h2>Equity curve (last 500 bars)</h2>
  <pre>{html.escape(str(equity_pairs))}</pre>
</body>
</html>
"""
    output_path.write_text(html_str, encoding="utf-8")
    return output_path
