#!/usr/bin/env python3
"""Build the macro regime dashboard.

Usage:
    python run.py                 # live data from Yahoo Finance
    python run.py --source synthetic   # offline demo / test
    python run.py --period 5y

Outputs:
    output/index.html                     (GitHub Pages entry point)
    output/macro_regime_dashboard.html    (same content, convenience copy)
    data/regime_history.csv               (one appended row per run)
    data/processed/last_run.json
    data/raw/close_prices.csv             (tail of close prices)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "src"))

import data_loader          # noqa: E402
import features as F        # noqa: E402
import html_report as H     # noqa: E402
import regime_engine as E   # noqa: E402
from utils import SCORE_LABELS, log  # noqa: E402


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_ctx(assets_cfg: dict) -> tuple[dict, dict]:
    asset_meta, asset_labels, asset_categories, yield_aliases = {}, {}, {}, set()
    for alias, m in assets_cfg["assets"].items():
        asset_meta[alias] = {
            "ticker": m["ticker"],
            "label": m.get("label", alias),
            "category": m.get("category", ""),
            "yield": bool(m.get("yield", False)),
        }
        asset_labels[alias] = m.get("label", alias)
        asset_categories[alias] = m.get("category", "")
        if m.get("yield"):
            yield_aliases.add(alias)
    ctx = {
        "asset_labels": asset_labels,
        "asset_categories": asset_categories,
        "yield_aliases": yield_aliases,
        "score_labels": SCORE_LABELS,
    }
    return asset_meta, ctx


def _add_derived(prices: dict) -> None:
    if "USD" not in prices:
        if "DXY" in prices:
            prices["USD"] = prices["DXY"]
        elif "UUP" in prices:
            prices["USD"] = prices["UUP"]
    if "VIX" not in prices and "VXX" in prices:
        prices["VIX"] = prices["VXX"]


def _history_columns(regimes_cfg: list) -> list:
    keys = [r["key"] for r in regimes_cfg]
    return ["run_date", "data_date", "primary_regime", "primary_score"] + [f"{k}_score" for k in keys]


def _write_history(path: Path, columns: list, row: dict, keep_rows: int) -> list:
    new_df = pd.DataFrame([row]).reindex(columns=columns)
    if path.exists():
        try:
            old = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001
            log(f"[warn] could not read existing history ({exc}); starting fresh.")
            old = pd.DataFrame(columns=columns)
        old = old[old.get("run_date") != row["run_date"]] if "run_date" in old.columns else old
        df = pd.concat([old, new_df], ignore_index=True)
    else:
        df = new_df
    df = df.reindex(columns=columns)
    if "run_date" in df.columns:
        df = df.sort_values("run_date").reset_index(drop=True)
    df.to_csv(path, index=False)
    tail = df.tail(keep_rows).iloc[::-1]
    return tail.to_dict("records")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the macro regime dashboard.")
    ap.add_argument("--source", choices=["live", "synthetic"], default="live")
    ap.add_argument("--period", default="3y", help="history length, e.g. 1y, 3y, 5y")
    args = ap.parse_args()

    cfg_dir = BASE / "config"
    assets_cfg = _load_yaml(cfg_dir / "assets.yml")
    regimes_doc = _load_yaml(cfg_dir / "regimes.yml")
    settings = regimes_doc["settings"]
    regimes_cfg = regimes_doc["regimes"]

    asset_meta, ctx = _build_ctx(assets_cfg)
    ratios = assets_cfg.get("ratios", [])

    # 1) data ---------------------------------------------------------------
    prices, source = data_loader.load_prices(asset_meta, period=args.period, source=args.source)
    _add_derived(prices)

    # 2) features -----------------------------------------------------------
    feat = F.build_features(prices, ratios, ctx["yield_aliases"])
    log(f"[info] built {len(feat)} features.")

    # 3) regimes ------------------------------------------------------------
    results = E.evaluate_all(regimes_cfg, feat, settings, ctx)
    primary, mode, ordered = E.finalize(results, settings)
    log(f"[info] primary regime: {results[primary]['name']} "
        f"({results[primary]['score']}%, mode={mode}).")

    # 4) dates + table records ---------------------------------------------
    today = datetime.now(timezone.utc).date().isoformat()
    last_dates = [s.index[-1] for s in prices.values() if len(s)]
    data_date = max(last_dates).date().isoformat() if last_dates else today

    market_recs = H.market_records(feat, ctx, assets_cfg.get("market_table", []))
    yield_recs = H.yield_records(feat, ctx, assets_cfg.get("yields_table", []))
    score_recs = H.score_records(feat)

    analysis = {
        "analysis_date": today,
        "data_date": data_date,
        "source": source,
        "primary_key": primary,
        "primary_regime": results[primary]["name"],
        "primary_score": results[primary]["score"],
        "mode": mode,
        "ordered": ordered,
        "n_series": len(prices),
        "market_recs": market_recs,
        "yield_recs": yield_recs,
        "score_recs": score_recs,
    }

    # 5) history ------------------------------------------------------------
    data_dir = BASE / "data"
    (data_dir / "processed").mkdir(parents=True, exist_ok=True)
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)
    columns = _history_columns(regimes_cfg)
    hist_row = {
        "run_date": today,
        "data_date": data_date,
        "primary_regime": results[primary]["name"],
        "primary_score": results[primary]["score"],
    }
    for r in regimes_cfg:
        hist_row[f"{r['key']}_score"] = results[r["key"]]["score"]
    history_rows = _write_history(data_dir / "regime_history.csv", columns, hist_row,
                                  int(settings.get("history_table_rows", 10)))

    # 6) render -------------------------------------------------------------
    template = (BASE / "templates" / "dashboard_template.html").read_text(encoding="utf-8")
    html = H.build_html(analysis, results, feat, ctx, history_rows, template)

    out_dir = BASE / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "macro_regime_dashboard.html").write_text(html, encoding="utf-8")

    # 7) side artifacts -----------------------------------------------------
    last_run = {
        "analysis_date": today, "data_date": data_date, "source": source,
        "primary_key": primary, "primary_regime": results[primary]["name"],
        "primary_score": results[primary]["score"], "mode": mode, "n_series": len(prices),
        "ranking": [{"key": k, "name": results[k]["name"], "score": results[k]["score"]}
                    for k in ordered],
    }
    (data_dir / "processed" / "last_run.json").write_text(
        json.dumps(last_run, indent=2), encoding="utf-8")

    try:
        price_aliases = [a for a in asset_meta if a in prices]
        frame = pd.DataFrame({a: prices[a] for a in price_aliases})
        frame.tail(60).to_csv(data_dir / "raw" / "close_prices.csv")
    except Exception as exc:  # noqa: BLE001
        log(f"[warn] could not write close_prices.csv: {exc}")

    # 8) console summary ----------------------------------------------------
    log("")
    log(f"  Macro regime dashboard  |  data {data_date}  |  source {source}")
    log(f"  PRIMARY: {results[primary]['name']}  ({results[primary]['score']}%)  [{mode}]")
    log("  Ranked match scores:")
    for k in ordered:
        marker = " <-- primary" if k == primary else ""
        log(f"    {results[k]['score']:5.1f}%  {results[k]['name']}{marker}")
    log("")
    log(f"  Wrote: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
