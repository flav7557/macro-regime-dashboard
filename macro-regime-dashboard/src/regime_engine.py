"""Rule-based regime scoring engine.

For each regime we evaluate confirming and contradicting rules against the flat
feature dict, then compute an interpretable match score in [0, 100].
"""
from __future__ import annotations

from utils import (
    compare,
    describe_feature,
    entity_of,
    format_observed,
    format_threshold,
    join_human,
)


# --------------------------------------------------------------------------- #
# Rule entries
# --------------------------------------------------------------------------- #


def _rule_entry(rule: dict, ctx: dict, status: str, lhs, rhs) -> dict:
    f = rule["f"]
    op = rule["op"]
    elabel, mlabel, _, _ = describe_feature(f, ctx)

    if "cf" in rule:
        cel, cml, _, _ = describe_feature(rule["cf"], ctx)
        thr_text = f"{cel} {cml}".strip()
        obs = format_observed(f, lhs, ctx)
        if rhs is not None:
            obs += f" vs {format_observed(rule['cf'], rhs, ctx)}"
    else:
        thr_text = format_threshold(f, rule.get("t"), ctx)
        obs = format_observed(f, lhs, ctx)

    cond = " ".join(p for p in [elabel, mlabel, op, thr_text] if p).strip()
    name = rule.get("n") or f"{elabel} {mlabel}".strip()
    kind = rule.get("k", "c")

    return {
        "name": name,
        "condition": cond,
        "observed": obs,
        "threshold": thr_text,
        "weight": rule.get("w", 1),
        "status": status,
        "kind": kind,
        "explanation": _explain(rule, status, elabel, mlabel, obs, op, thr_text),
    }


def _explain(rule, status, elabel, mlabel, obs, op, thr):
    why = rule.get("why")
    base = f"{elabel} {mlabel}".strip()
    head = f"{base} = {obs}" if obs and obs != "n/a" else base
    kind = rule.get("k", "c")

    if status == "missing":
        return f"{base}: data unavailable, this signal is ignored."
    if kind == "x":
        if status == "triggered":
            return f"{head} ({op} {thr}): contradicts this regime."
        return f"{head}: no contradiction ({op} {thr} is not met)."
    # confirming rule
    if status == "triggered":
        return f"{head} ({op} {thr}): {why}." if why else f"{head}: confirms this regime."
    if why:
        return f"{head}: the condition {op} {thr} is not met, so '{why}' is not confirmed."
    return f"{head}: the condition {op} {thr} is not met."


# --------------------------------------------------------------------------- #
# Per-regime evaluation
# --------------------------------------------------------------------------- #


def evaluate_regime(reg: dict, feat: dict, settings: dict, ctx: dict) -> dict:
    triggered, not_triggered, missing, contradictions = [], [], [], []
    c_obtained = c_possible = 0.0
    x_obtained = x_possible = 0.0
    n_missing = 0
    n_total = 0
    entities = set()

    for rule in reg.get("rules", []):
        n_total += 1
        f = rule["f"]
        op = rule["op"]
        w = float(rule.get("w", 1))
        kind = rule.get("k", "c")

        lhs = feat.get(f)
        if "cf" in rule:
            rhs = feat.get(rule["cf"])
            rhs_missing = rhs is None
        else:
            rhs = rule.get("t")
            rhs_missing = rhs is None

        if lhs is None or rhs_missing:
            status = "missing"
        elif compare(lhs, op, rhs):
            status = "triggered"
        else:
            status = "not"

        entry = _rule_entry(rule, ctx, status, lhs, rhs)
        entities.add(entity_of(f))
        if "cf" in rule:
            entities.add(entity_of(rule["cf"]))

        if kind == "x":
            if status == "missing":
                n_missing += 1
                missing.append(entry)
            else:
                x_possible += w
                if status == "triggered":
                    x_obtained += w
                    contradictions.append(entry)
        else:
            if status == "missing":
                n_missing += 1
                missing.append(entry)
            elif status == "triggered":
                c_possible += w
                c_obtained += w
                triggered.append(entry)
            else:
                c_possible += w
                not_triggered.append(entry)

    raw = (c_obtained / c_possible * 100.0) if c_possible > 0 else 0.0
    x_ratio = (x_obtained / x_possible) if x_possible > 0 else 0.0
    m_ratio = (n_missing / n_total) if n_total else 0.0

    score = raw * (1.0 - settings["contradiction_penalty"] * x_ratio)
    score = score * (1.0 - settings["missing_penalty"] * m_ratio)
    score = round(max(0.0, min(100.0, score)), 1)

    summary = _summary(reg, score, round(raw, 1), triggered, not_triggered, contradictions, n_missing)

    return {
        "key": reg["key"],
        "name": reg["name"],
        "tone": reg.get("tone", "gray"),
        "definition": " ".join((reg.get("definition") or "").split()),
        "score": score,
        "raw": round(raw, 1),
        "triggered_rules": triggered,
        "not_triggered_rules": not_triggered,
        "missing_rules": missing,
        "contradictions": contradictions,
        "n_triggered": len(triggered),
        "n_possible": len(triggered) + len(not_triggered),
        "n_missing": n_missing,
        "entities": sorted(e for e in entities if not e.startswith("score:")),
        "summary": summary,
    }


def _summary(reg, score, raw, triggered, not_triggered, contradictions, n_missing):
    parts = [f"{reg['name']} matches current conditions at {score}% (raw {raw}%)."]
    if triggered:
        parts.append("Confirmed mainly by " + join_human([t["name"] for t in triggered[:4]]) + ".")
    else:
        parts.append("No confirming signal is currently active.")
    if contradictions:
        parts.append("Contradicted by " + join_human([c["name"] for c in contradictions[:3]]) + ".")
    if not_triggered:
        n = len(not_triggered)
        parts.append(f"{n} expected signal{'s' if n != 1 else ''} not confirmed.")
    if n_missing:
        parts.append(f"{n_missing} signal{'s' if n_missing != 1 else ''} unavailable (missing data).")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Full pass + neutral / primary selection
# --------------------------------------------------------------------------- #


def evaluate_all(regimes_cfg: list, feat: dict, settings: dict, ctx: dict) -> dict:
    return {reg["key"]: evaluate_regime(reg, feat, settings, ctx) for reg in regimes_cfg}


def finalize(results: dict, settings: dict):
    """Compute the Neutral/Mixed score and pick the primary regime.

    Returns (primary_key, mode, ordered_keys_by_score).
    mode in {"clear", "mixed_bias", "neutral"}.
    """
    real = [k for k in results if k != "neutral_mixed"]
    ranked_real = sorted(real, key=lambda k: results[k]["score"], reverse=True)

    best_key = ranked_real[0]
    best = results[best_key]["score"]
    second_key = ranked_real[1] if len(ranked_real) > 1 else None
    second = results[second_key]["score"] if second_key else 0.0
    gap = best - second
    close = best < settings["mixed_ceiling"] and gap < settings["mixed_gap"]

    neutral_score = round(max(0.0, 100.0 - best), 1)
    if close:
        neutral_score = max(neutral_score, round(best + 0.5, 1))

    if "neutral_mixed" in results:
        nm = results["neutral_mixed"]
        nm["score"] = neutral_score
        nm["raw"] = neutral_score
        nm["summary"] = _neutral_summary(neutral_score, results[best_key],
                                          results[second_key] if second_key else None,
                                          close, settings)

    if best < settings["neutral_threshold"]:
        primary, mode = "neutral_mixed", "neutral"
    elif close:
        primary, mode = "neutral_mixed", "mixed_bias"
        if "neutral_mixed" in results:
            results["neutral_mixed"]["bias"] = results[best_key]["name"]
    else:
        primary, mode = best_key, "clear"

    ordered = sorted(results.keys(), key=lambda k: results[k]["score"], reverse=True)
    return primary, mode, ordered


def _neutral_summary(score, best, second, close, settings):
    bits = [f"Neutral / Mixed matches at {score}%."]
    if best["score"] < settings["neutral_threshold"]:
        bits.append(
            f"The strongest regime, {best['name']}, only reaches {best['score']}% "
            f"(below the {settings['neutral_threshold']}% conviction threshold), "
            "so no regime dominates."
        )
    elif close and second is not None:
        bits.append(
            f"{best['name']} ({best['score']}%) and {second['name']} ({second['score']}%) "
            f"are within {settings['mixed_gap']} points, so the read is mixed with a bias "
            f"toward {best['name']}."
        )
    else:
        bits.append("Signals across equities, rates, FX, credit and commodities are not aligned.")
    return " ".join(bits)
