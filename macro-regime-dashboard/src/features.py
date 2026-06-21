"""Feature engineering.

Turns a dict of {alias: price Series} into a flat feature dictionary keyed by
dotted strings (e.g. ``SPY.return_1d``, ``HYG/LQD.return_1d``,
``US10Y.change_1d_bps``, ``score.equity_risk``) that the regime engine reads.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Per-series feature blocks
# --------------------------------------------------------------------------- #


def returns_block(close: pd.Series) -> dict:
    """Return/volatility features for a price-like series (returns in %)."""
    s = close.dropna().astype(float)
    out: dict = {}
    if len(s) < 2:
        return out

    last = float(s.iloc[-1])
    out["last"] = last

    def ret(n):
        if len(s) >= n + 1:
            base = float(s.iloc[-(n + 1)])
            if base != 0:
                return (last / base - 1.0) * 100.0
        return None

    out["return_1d"] = ret(1)
    out["return_5d"] = ret(5)
    out["return_20d"] = ret(20)

    daily = s.pct_change().dropna() * 100.0
    win = daily.tail(TRADING_DAYS)
    if out["return_1d"] is not None and len(win) >= 20 and win.std(ddof=0) > 0:
        out["zscore_1d"] = (out["return_1d"] - win.mean()) / win.std(ddof=0)

    r5 = (s / s.shift(5) - 1.0).dropna() * 100.0
    win5 = r5.tail(TRADING_DAYS)
    if out.get("return_5d") is not None and len(win5) >= 20 and win5.std(ddof=0) > 0:
        out["zscore_5d"] = (out["return_5d"] - win5.mean()) / win5.std(ddof=0)

    dec = s.pct_change().dropna()
    if len(dec) >= 20:
        out["realized_vol_20d"] = float(dec.tail(20).std(ddof=0) * math.sqrt(TRADING_DAYS) * 100.0)

    if len(s) >= 20:
        hi = float(s.tail(20).max())
        lo = float(s.tail(20).min())
        if hi:
            out["dist_high_20d"] = (last / hi - 1.0) * 100.0
        if lo:
            out["dist_low_20d"] = (last / lo - 1.0) * 100.0

    lvl = s.tail(TRADING_DAYS)
    if len(lvl) >= 20 and lvl.std(ddof=0) > 0:
        out["zlevel"] = (last - lvl.mean()) / lvl.std(ddof=0)

    return _clean(out)


def yield_block(close: pd.Series) -> dict:
    """Yield features. Cleans Yahoo's occasional x10 scaling, returns bps changes."""
    s = close.dropna().astype(float)
    out: dict = {}
    if len(s) < 2:
        return out

    # Yahoo sometimes quotes ^TNX etc. as 10x the yield. Normalise.
    if float(s.median()) > 20:
        s = s / 10.0

    last = float(s.iloc[-1])
    out["level"] = last

    def bps(n):
        if len(s) >= n + 1:
            return (last - float(s.iloc[-(n + 1)])) * 100.0
        return None

    out["change_1d_bps"] = bps(1)
    out["change_5d_bps"] = bps(5)
    out["change_20d_bps"] = bps(20)

    dchg = s.diff().dropna() * 100.0
    win = dchg.tail(TRADING_DAYS)
    if out["change_1d_bps"] is not None and len(win) >= 20 and win.std(ddof=0) > 0:
        out["zscore_1d"] = (out["change_1d_bps"] - win.mean()) / win.std(ddof=0)

    return _clean(out)


def ratio_series(a: pd.Series, b: pd.Series):
    df = pd.concat([a.dropna(), b.dropna()], axis=1).dropna()
    if df.empty:
        return None
    denom = df.iloc[:, 1]
    if (denom == 0).any():
        denom = denom.replace(0, np.nan)
    out = df.iloc[:, 0] / denom
    return out.dropna()


def _clean(d: dict) -> dict:
    res = {}
    for k, v in d.items():
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            continue
        res[k] = fv
    return res


# --------------------------------------------------------------------------- #
# Aggregate macro scores
# --------------------------------------------------------------------------- #

_AGG_SCALE = 30.0  # a ~1 sigma average maps to ~30 points; clipped to [-100, 100]


def _score_specs() -> dict:
    """name -> list of (feature_key, sign)."""

    def z(alias):  # 1D z-score key
        return f"{alias}.zscore_1d"

    return {
        "equity_risk": [(z("SPY"), 1), (z("QQQ"), 1), (z("IWM"), 1), (z("ACWI"), 1), (z("EEM"), 1)],
        "growth_defensive": [
            (z("QQQ/SPY"), 1), (z("IWM/SPY"), 1), (z("XLY/XLP"), 1),
            (z("XLI/XLU"), 1), (z("SMH/SPY"), 1),
        ],
        "credit_risk": [(z("HYG/LQD"), 1), (z("HYG/IEF"), 1), (z("HYG"), 1)],
        "rates_pressure": [(z("US10Y"), 1), (z("US5Y"), 1), (z("TLT"), -1), (z("IEF"), -1)],
        "dollar_stress": [(z("USD"), 1), (z("EURUSD"), -1), (z("AUDUSD"), -1), (z("EEM/SPY"), -1)],
        "commodity_inflation": [(z("OIL"), 1), (z("COPPER"), 1), (z("DBC"), 1), (z("XLE/SPY"), 1)],
        "volatility_stress": [(z("VIX"), 1), ("VIX.zlevel", 1)],
        "safe_haven": [(z("GOLD"), 1), (z("TLT"), 1), (z("USDJPY"), -1), (z("VIX"), 1)],
        "tech_speculation": [(z("QQQ/SPY"), 1), (z("SMH/SPY"), 1), (z("XLK/SPY"), 1), (z("BTC"), 1)],
        "em_stress": [(z("EEM"), -1), (z("EEM/SPY"), -1), (z("USD"), 1), (z("AUDUSD"), -1), (z("COPPER"), -1)],
    }


def _agg(feat: dict, comps) -> float | None:
    vals = []
    for key, sign in comps:
        v = feat.get(key)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            vals.append(sign * v)
    if not vals:
        return None
    m = sum(vals) / len(vals)
    return float(round(max(-100.0, min(100.0, m * _AGG_SCALE)), 0))


# --------------------------------------------------------------------------- #
# Top-level builder
# --------------------------------------------------------------------------- #


def build_features(prices: dict, ratios: list, yield_aliases: set) -> dict:
    feat: dict = {}

    for alias, series in prices.items():
        blk = yield_block(series) if alias in yield_aliases else returns_block(series)
        for k, v in blk.items():
            feat[f"{alias}.{k}"] = v

    for r in ratios:
        if "/" not in r:
            continue
        a, b = r.split("/", 1)
        if a in prices and b in prices:
            rs = ratio_series(prices[a], prices[b])
            if rs is not None and len(rs) >= 2:
                for k, v in returns_block(rs).items():
                    feat[f"{r}.{k}"] = v

    for name, comps in _score_specs().items():
        val = _agg(feat, comps)
        if val is not None:
            feat[f"score.{name}"] = val

    return feat
