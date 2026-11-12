"""SIMULATED price survey: generate example answers, then standardise, validate, weight and
consolidate them with the public Comext unit value.

    python survey/process_survey.py

Everything produced here is labelled SIMULATED. The simulation is calibrated on the public Comext
unit value of hydrofluoric acid so that the consolidation step has something realistic to compare
with; it says nothing about real market prices.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "survey"
SEED = 7
FREIGHT_EUR_KG = 0.08        # documented allowance to move FOB/EXW answers to a delivered basis
PLAUSIBLE = (0.3, 30.0)      # same plausible range as the data dictionary (seeds/materials.csv)

# stratum population (number of companies in the frame) - assumption for the example
POPULATION = {("buyer", "small"): 60, ("buyer", "medium"): 25, ("buyer", "large"): 8,
              ("seller", "small"): 15, ("seller", "medium"): 8, ("seller", "large"): 4}
VOLUME_T = {"small": (20, 120), "medium": (125, 1250), "large": (1300, 6000)}


def public_reference() -> tuple[float, float]:
    """Comext validated HF import unit value for July-September 2026 (EUR/kg) and USD per EUR."""
    m = pd.read_csv(ROOT / "data" / "marts" / "monthly_prices.csv", parse_dates=["period"])
    q = m[(m.material_id == "HF") & (m.period >= "2026-07-01") & (m.period <= "2026-09-01")]
    uv = q.eu_import_value_eur.sum() / q.eu_import_kg.sum()
    return uv, q.usd_per_eur.mean()


def simulate(true_price: float, usd_per_eur: float) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    rid = 0
    for (role, size), pop in POPULATION.items():
        n_invited = pop if size == "large" else max(4, pop // 3)          # take-all for large firms
        for _ in range(n_invited):
            rid += 1
            if rng.random() < 0.30:                                       # 30% non-response
                rows.append({"respondent_id": f"R{rid:03d}", "role": role, "firm_size": size, "responded": False})
                continue
            bias = -0.03 if role == "buyer" else 0.03                     # buyers quote low, sellers high
            size_disc = {"small": 0.04, "medium": 0.0, "large": -0.05}[size]  # volume discounts
            price = true_price * (1 + bias + size_disc) * np.exp(rng.normal(0, 0.06))
            volume = rng.uniform(*VOLUME_T[size])
            currency = "USD" if rng.random() < 0.3 else "EUR"
            unit = "t" if rng.random() < 0.25 else "kg"
            terms = "FOB" if rng.random() < 0.2 else "DAP"
            if terms == "FOB":
                price -= FREIGHT_EUR_KG
            reported = price * (usd_per_eur if currency == "USD" else 1) * (1000 if unit == "t" else 1)
            rows.append({"respondent_id": f"R{rid:03d}", "role": role, "firm_size": size, "responded": True,
                         "price_reported": round(reported, 3), "currency": currency, "unit": unit,
                         "terms": terms, "volume_t": round(volume, 1),
                         "pricing": rng.choice(["contract", "spot", "mix"], p=[0.6, 0.25, 0.15])})
    df = pd.DataFrame(rows)
    # three realistic data-entry errors: a per-tonne price typed in the per-kg field, a typo, a decimal slip
    ok = df[df.responded].index
    df.loc[ok[3], "unit"] = "kg"; df.loc[ok[3], "price_reported"] = round(true_price * 1000, 1)
    df.loc[ok[11], "price_reported"] = round(df.loc[ok[11], "price_reported"] * 10, 3)
    df.loc[ok[20], "price_reported"] = round(df.loc[ok[20], "price_reported"] * 1.9, 3)
    df.insert(0, "data_label", "SIMULATED")
    return df


def process(df: pd.DataFrame, usd_per_eur: float) -> pd.DataFrame:
    d = df[df.responded].copy()
    # 1. standardise to EUR/kg, delivered basis
    d["eur_kg"] = d.price_reported / np.where(d.currency == "USD", usd_per_eur, 1) / np.where(d.unit == "t", 1000, 1)
    d["eur_kg"] += np.where(d.terms == "FOB", FREIGHT_EUR_KG, 0)
    # 2. validate: plausible range, then robust z-score (median / MAD)
    d["status"] = np.where(d.eur_kg.between(*PLAUSIBLE), "ok", "rejected: outside plausible range")
    ok = d.status == "ok"
    med = d.loc[ok, "eur_kg"].median()
    mad = (d.loc[ok, "eur_kg"] - med).abs().median()
    d["robust_z"] = 0.6745 * (d.eur_kg - med) / mad
    d.loc[ok & (d.robust_z.abs() > 3.5), "status"] = "rejected: robust outlier (call back respondent)"
    # 3. weights: design weight x capped volume
    resp = d[d.status == "ok"].groupby(["role", "firm_size"]).size()
    d["design_w"] = [POPULATION[(r, s)] / resp.get((r, s), np.nan) for r, s in zip(d.role, d.firm_size)]
    cap = d.loc[d.status == "ok", "volume_t"].quantile(0.9)
    d["weight"] = d.design_w * d.volume_t.clip(upper=cap)
    return d


def estimate(d: pd.DataFrame) -> dict:
    v = d[d.status == "ok"]
    rng = np.random.default_rng(SEED)

    def wmean(x):
        return np.average(x.eur_kg, weights=x.weight)

    boots = [wmean(v.sample(len(v), replace=True, random_state=int(rng.integers(1e9)))) for _ in range(2000)]
    order = v.sort_values("eur_kg")
    cum = order.weight.cumsum() / order.weight.sum()
    return {"n_invited": None, "n_valid": len(v), "weighted_mean": wmean(v),
            "weighted_median": order.eur_kg[cum >= 0.5].iloc[0], "unweighted_mean": v.eur_kg.mean(),
            "ci90_low": np.percentile(boots, 5), "ci90_high": np.percentile(boots, 95),
            "buyers_mean": v[v.role == "buyer"].eur_kg.mean(), "sellers_mean": v[v.role == "seller"].eur_kg.mean()}


def main() -> None:
    ref, fx = public_reference()
    raw = simulate(true_price=ref * 1.05, usd_per_eur=fx)     # delivered bulk ~5% above border value
    raw.to_csv(OUT / "simulated_responses.csv", index=False)
    d = process(raw, fx)
    d.to_csv(OUT / "simulated_processed.csv", index=False)
    e = estimate(d)
    e["n_invited"] = len(raw)
    e["response_rate"] = raw.responded.mean()
    e["rejected"] = int((d.status != "ok").sum())
    e["comext_q3_2026_eur_kg"] = ref
    e["gap_vs_comext"] = e["weighted_mean"] / ref - 1
    pd.DataFrame([e]).assign(data_label="SIMULATED").to_csv(OUT / "simulated_results.csv", index=False)
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items()})


if __name__ == "__main__":
    main()
