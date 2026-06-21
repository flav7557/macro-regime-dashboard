"""Utility helpers shared across the pipeline.

Pure functions only (formatting, labels, comparisons) so that the data,
feature, engine and HTML layers can all import from here without cycles.
"""
from __future__ import annotations

import math
import operator
import sys

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def log(msg: str) -> None:
    """Print with flush so logs show up in real time in CI."""
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

_OPS = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
}


def compare(a, op: str, b) -> bool:
    fn = _OPS.get(op)
    if fn is None:
        raise ValueError(f"Unknown operator: {op!r}")
    return bool(fn(a, b))


# --------------------------------------------------------------------------- #
# Score labels (aggregate macro blocks)
# --------------------------------------------------------------------------- #

SCORE_LABELS = {
    "equity_risk": "Equity Risk Score",
    "growth_defensive": "Growth vs Defensive Score",
    "credit_risk": "Credit Risk Score",
    "rates_pressure": "Rates Pressure Score",
    "dollar_stress": "Dollar Stress Score",
    "commodity_inflation": "Commodity Inflation Score",
    "volatility_stress": "Volatility Stress Score",
    "safe_haven": "Safe Haven Score",
    "tech_speculation": "Tech Speculation Score",
    "em_stress": "EM Stress Score",
}

# Order used in the dashboard "Aggregate scores" table.
SCORE_ORDER = [
    "equity_risk",
    "growth_defensive",
    "credit_risk",
    "rates_pressure",
    "dollar_stress",
    "commodity_inflation",
    "volatility_stress",
    "safe_haven",
    "tech_speculation",
    "em_stress",
]

METRIC_LABELS = {
    "last": "price",
    "return_1d": "1D return",
    "return_5d": "5D return",
    "return_20d": "20D return",
    "zscore_1d": "1D z-score",
    "zscore_5d": "5D z-score",
    "zlevel": "level z-score",
    "realized_vol_20d": "20D realized vol",
    "dist_high_20d": "dist. to 20D high",
    "dist_low_20d": "dist. to 20D low",
    "level": "level",
    "change_1d_bps": "1D change",
    "change_5d_bps": "5D change",
    "change_20d_bps": "20D change",
}


# --------------------------------------------------------------------------- #
# Feature key helpers
# --------------------------------------------------------------------------- #


def entity_of(key: str) -> str:
    """Return the entity portion of a feature key.

    ``score.equity_risk`` -> ``score:equity_risk`` (so it is easy to filter
    out scores), otherwise the part before the last dot (handles ratios that
    contain a slash, e.g. ``HYG/LQD.return_1d`` -> ``HYG/LQD``).
    """
    if key.startswith("score."):
        return "score:" + key.split(".", 1)[1]
    return key.rsplit(".", 1)[0]


def metric_of(key: str) -> str:
    if key.startswith("score."):
        return key.split(".", 1)[1]
    return key.rsplit(".", 1)[1]


def describe_feature(key: str, ctx: dict):
    """Return (entity_label, metric_label, unit, signed) for a feature key."""
    if key.startswith("score."):
        name = key.split(".", 1)[1]
        return SCORE_LABELS.get(name, name.replace("_", " ").title() + " Score"), "", "", True

    entity, metric = key.rsplit(".", 1)
    yield_aliases = ctx["yield_aliases"]
    if entity in yield_aliases:
        elabel = ctx["asset_labels"].get(entity, entity)
    elif "/" in entity:
        elabel = entity + " ratio"
    elif entity == "USD":
        elabel = "US Dollar (DXY/UUP)"
    else:
        elabel = ctx["asset_labels"].get(entity, entity)

    mlabel = METRIC_LABELS.get(metric, metric.replace("_", " "))
    unit, signed = _unit_for(entity, metric, ctx)
    return elabel, mlabel, unit, signed


def _unit_for(entity: str, metric: str, ctx: dict):
    yield_aliases = ctx["yield_aliases"]
    if metric.endswith("_bps"):
        return " bps", True
    if metric == "level":
        return ("%", False) if entity in yield_aliases else ("", False)
    if metric.startswith("return"):
        return "%", True
    if metric.startswith("realized_vol"):
        return "%", False
    if metric.startswith("dist"):
        return "%", True
    if metric.startswith("zscore") or metric == "zlevel":
        return "\u03c3", True   # sigma
    if metric == "last":
        return "", False
    return "", True


# --------------------------------------------------------------------------- #
# Number formatting
# --------------------------------------------------------------------------- #


def _is_num(v) -> bool:
    return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def format_observed(key: str, v, ctx: dict) -> str:
    if not _is_num(v):
        return "n/a"
    if key.startswith("score."):
        return f"{v:+.0f}"
    _, _, unit, signed = describe_feature(key, ctx)
    return _fmt_num(v, unit, signed)


def _fmt_num(v: float, unit: str, signed: bool) -> str:
    if unit == " bps":
        return f"{v:+.1f} bps" if signed else f"{v:.1f} bps"
    if unit == "%":
        return f"{v:+.2f}%" if signed else f"{v:.2f}%"
    if unit == "\u03c3":
        return f"{v:+.2f}\u03c3"
    # plain number: price / level
    if signed:
        return f"{v:+.2f}"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def format_threshold(key: str, t, ctx: dict) -> str:
    if t is None:
        return ""
    if key.startswith("score."):
        return f"{_g(t)}"
    _, _, unit, _ = describe_feature(key, ctx)
    if unit == " bps":
        return f"{_g(t)} bps"
    if unit == "%":
        return f"{_g(t)}%"
    if unit == "\u03c3":
        return f"{_g(t)}\u03c3"
    return f"{_g(t)}"


def _g(t) -> str:
    """Format a threshold like %g but tidy for integers."""
    if isinstance(t, (int,)) or (isinstance(t, float) and t == int(t)):
        return str(int(t))
    return f"{t:g}"


def join_human(items) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def html_escape(s) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
