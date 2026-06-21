"""Data loading.

Primary source is Yahoo Finance via yfinance (free). A synthetic generator is
provided so the full pipeline can be exercised offline / in tests with
``--source synthetic``.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from utils import log


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def load_prices(asset_meta: dict, period: str = "3y", source: str = "live") -> tuple[dict, str]:
    """Return ({alias: price Series}, source_used)."""
    if source == "synthetic":
        log("[info] using synthetic data (offline mode).")
        return synthetic_prices(asset_meta), "synthetic"

    prices = _download_live(asset_meta, period)
    if not prices:
        log("[error] no live data could be downloaded from Yahoo Finance.")
    return prices, "live"


# --------------------------------------------------------------------------- #
# Live download (yfinance)
# --------------------------------------------------------------------------- #


def _download_live(asset_meta: dict, period: str) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        log("[error] yfinance is not installed; run `pip install -r requirements.txt`.")
        return {}

    tickers = [m["ticker"] for m in asset_meta.values()]
    prices: dict = {}

    data = None
    for attempt in range(1, 4):
        try:
            data = yf.download(
                tickers,
                period=period,
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if data is not None and len(data):
                break
        except Exception as exc:  # noqa: BLE001
            log(f"[warn] batch download attempt {attempt} failed: {exc}")
            time.sleep(2)

    if data is not None and len(data):
        for alias, meta in asset_meta.items():
            s = _extract_close(data, meta["ticker"])
            if s is not None and s.dropna().shape[0] >= 2:
                prices[alias] = s.dropna()

    missing = [a for a in asset_meta if a not in prices]
    if missing:
        log(f"[info] retrying {len(missing)} ticker(s) individually: {', '.join(missing)}")
    for alias in missing:
        s = _download_single(yf, asset_meta[alias]["ticker"], period)
        if s is not None and s.dropna().shape[0] >= 2:
            prices[alias] = s.dropna()
        else:
            log(f"[warn] no data for {alias} ({asset_meta[alias]['ticker']}); "
                "rules using it will be marked missing.")

    log(f"[info] loaded {len(prices)}/{len(asset_meta)} series from Yahoo Finance.")
    return prices


def _extract_close(data: pd.DataFrame, ticker: str):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            level0 = data.columns.get_level_values(0)
            if ticker in set(level0):
                sub = data[ticker]
                for col in ("Close", "Adj Close"):
                    if col in sub.columns:
                        return sub[col]
            return None
        for col in ("Close", "Adj Close"):
            if col in data.columns:
                return data[col]
        return None
    except Exception:  # noqa: BLE001
        return None


def _download_single(yf, ticker: str, period: str):
    for attempt in range(1, 3):
        try:
            df = yf.download(ticker, period=period, interval="1d",
                             auto_adjust=True, progress=False)
            if df is not None and len(df):
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                for col in ("Close", "Adj Close"):
                    if col in df.columns:
                        return df[col]
        except Exception as exc:  # noqa: BLE001
            log(f"[warn] single download {ticker} attempt {attempt} failed: {exc}")
            time.sleep(1)
    return None


# --------------------------------------------------------------------------- #
# Synthetic generator (offline testing / demo)
# --------------------------------------------------------------------------- #


def synthetic_prices(asset_meta: dict, days: int = 760, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    idx = pd.bdate_range(end=end, periods=days)
    n = len(idx)  # pandas can return periods-1 at some boundaries; trust the index
    prices: dict = {}

    for alias, meta in asset_meta.items():
        if meta.get("yield"):
            base = rng.uniform(3.6, 4.8)
            steps = rng.normal(0.0, 0.03, n).cumsum()
            level = np.clip(base + steps, 0.2, 8.0)
            # emulate Yahoo's occasional x10 scaling to exercise the cleaner
            prices[alias] = pd.Series(level * 10.0, index=idx)
            continue

        vol, start = _synth_params(alias, meta.get("category", ""), rng)
        drift = rng.normal(0.0002, 0.00015)
        rets = rng.normal(drift, vol, n)
        path = start * np.exp(np.cumsum(rets))
        prices[alias] = pd.Series(path, index=idx)

    return prices


def _synth_params(alias: str, category: str, rng) -> tuple[float, float]:
    if alias in ("VIX", "VXX"):
        return 0.06, rng.uniform(13.0, 20.0)
    if category == "Crypto":
        return 0.035, rng.uniform(20000.0, 60000.0)
    if category == "Commodity":
        return 0.015, rng.uniform(20.0, 120.0)
    if category == "FX":
        return 0.005, rng.uniform(0.9, 1.3)
    if category in ("Rates/Credit",):
        return 0.006, rng.uniform(80.0, 110.0)
    # equities / sectors / global
    return 0.011, rng.uniform(30.0, 500.0)
