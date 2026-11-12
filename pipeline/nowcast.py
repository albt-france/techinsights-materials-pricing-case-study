"""Step 5 - estimate the months Comext has not published yet, with honest intervals.

Comext arrives about two months after the end of the month, while exchange prices (World Bank)
are available for the previous month. For each material we nowcast the validated EU import unit
value for the missing months with three simple, explainable methods:

  naive  : last observed value (the baseline any method must beat)
  ets    : exponential smoothing with a damped additive trend on log(unit value), the Python
           counterpart of Excel's FORECAST.ETS (no seasonality)
  signal : for exchange-traded metals only, log(unit value) regressed on log(World Bank price in EUR)
           over the last 36 months; the World Bank price of the missing month is already known

Back-test ("if I had estimated N months ago, how wrong would I have been?"): rolling origins over
the last 24 months, horizons 1-6. The method with the lowest error at horizons 1-2 is selected
per material, and its 80% interval is the 10th-90th percentile of its own past errors.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .config import MARTS

warnings.filterwarnings("ignore")          # statsmodels convergence chatter on short series
SIGNAL = {"CU": "wb_price_eur_kg", "SN": "wb_price_eur_kg", "AL": "wb_price_eur_kg"}
BACKTEST_ORIGINS = 24
HORIZONS = range(1, 7)


def _prepare(m: pd.DataFrame) -> pd.Series:
    """Monthly validated unit value; outlier / thin-trade / missing months are interpolated in logs."""
    s = m.set_index("period")["eu_import_uv_clean_eur_kg"].astype(float)
    s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))
    return np.exp(np.log(s).interpolate(limit_direction="both"))


def _ets(y: pd.Series, h: int) -> np.ndarray:
    fit = ExponentialSmoothing(np.log(y.values), trend="add", damped_trend=True,
                               initialization_method="estimated").fit()
    return np.exp(fit.forecast(h))


def _signal(y: pd.Series, x: pd.Series, h: int) -> np.ndarray | None:
    """log(y) = a + b*log(x) on the last 36 months; x must be known for the forecast months."""
    xy = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    xy = xy[xy.index <= y.index.max()].tail(36)
    future = x[x.index > y.index.max()].head(h)
    if len(xy) < 12 or len(future) < h:
        return None
    b, a = np.polyfit(np.log(xy.x), np.log(xy.y), 1)
    return np.exp(a + b * np.log(future.values))


def _forecast(method: str, y: pd.Series, x: pd.Series | None, h: int) -> np.ndarray | None:
    if method == "naive":
        return np.repeat(y.iloc[-1], h)
    if method == "ets":
        return _ets(y, h)
    return _signal(y, x, h) if x is not None else None


def run(con) -> None:
    monthly = con.sql("SELECT * FROM mart_monthly_prices ORDER BY material_id, period").df()
    monthly["period"] = pd.to_datetime(monthly.period)
    # fast signal: World Bank price converted with the ECB rate, available one month after month end
    wb = con.sql("""SELECT o.period, o.material_id, o.price_eur_kg FROM observations o
                    WHERE o.source = 'WORLDBANK'""").df()
    wb["period"] = pd.to_datetime(wb.period)
    last_comext = monthly.period.max()
    last_signal = wb.dropna().period.max()
    gap = (last_signal.year - last_comext.year) * 12 + last_signal.month - last_comext.month
    n_missing = max(gap, 2)                      # always nowcast at least two months
    print(f"  nowcast: last Comext month {last_comext:%Y-%m}, nowcasting {n_missing} month(s)")

    bt_rows, nc_rows = [], []
    for mat, m in monthly.groupby("material_id"):
        y = _prepare(m)
        x = None
        if mat in SIGNAL:
            x = wb[wb.material_id == mat].set_index("period")["price_eur_kg"].astype(float)
        methods = ["naive", "ets"] + (["signal"] if x is not None else [])
        # ---- back-test on rolling origins -------------------------------------------
        for k in range(BACKTEST_ORIGINS + max(HORIZONS) - 1, max(HORIZONS) - 1, -1):
            origin = len(y) - k
            train, test = y.iloc[:origin], y.iloc[origin:origin + max(HORIZONS)]
            for meth in methods:
                xf = x[x.index <= test.index.max()] if x is not None else None
                f = _forecast(meth, train, xf, len(test))
                if f is None:
                    continue
                for h, (actual, pred) in enumerate(zip(test.values, f), start=1):
                    bt_rows.append({"material_id": mat, "method": meth, "origin": train.index.max().date(),
                                    "horizon": h, "actual": actual, "forecast": pred,
                                    "log_error": np.log(actual / pred)})
        bt = pd.DataFrame([r for r in bt_rows if r["material_id"] == mat])
        score = bt[bt.horizon <= 2].groupby("method").log_error.apply(lambda e: np.mean(np.abs(np.exp(e) - 1)))
        best = score.idxmin()
        # ---- nowcast of the missing months ------------------------------------------
        for meth in methods:
            f = _forecast(meth, y, x, n_missing)
            if f is None:
                continue
            for h, val in enumerate(f, start=1):
                e = bt[(bt.method == meth) & (bt.horizon == h)].log_error
                lo, hi = (val * np.exp(e.quantile(0.10)), val * np.exp(e.quantile(0.90))) if len(e) >= 8 else (np.nan, np.nan)
                nc_rows.append({"material_id": mat, "period": (y.index.max() + pd.DateOffset(months=h)).date(),
                                "horizon": h, "method": meth, "selected": int(meth == best),
                                "nowcast_eur_kg": val, "lo80_eur_kg": lo, "hi80_eur_kg": hi,
                                "last_actual_eur_kg": y.iloc[-1]})

    bt = pd.DataFrame(bt_rows)
    bt["abs_pct_error"] = np.abs(bt.actual / bt.forecast - 1)
    summary = bt.groupby(["material_id", "method", "horizon"]).agg(
        mape=("abs_pct_error", "mean"), median_ape=("abs_pct_error", "median"), n=("abs_pct_error", "size")).reset_index()
    # 80% interval coverage check on the back-test itself (should be close to 80%)
    nc = pd.DataFrame(nc_rows)
    bt.to_csv(MARTS / "nowcast_backtest_detail.csv", index=False)
    summary.to_csv(MARTS / "nowcast_backtest.csv", index=False)
    nc.to_csv(MARTS / "nowcast.csv", index=False)
    sel = nc[nc.selected & (nc.horizon == 1)]
    print(f"  nowcast: {nc.material_id.nunique()} materials, selected methods: "
          + ", ".join(f"{r.material_id}={r.method}" for r in sel.itertuples()))
