"""HTML rendering.

Builds the self-contained dashboard (cards + expandable detail panels + tables)
by injecting pre-rendered HTML fragments into ``templates/dashboard_template.html``.
All detail is rendered server-side and hidden with CSS; a tiny bit of JS only
toggles panels, so the page works by double-clicking the file (no server).
"""
from __future__ import annotations

from utils import SCORE_LABELS, SCORE_ORDER, html_escape as esc


ICON = {"triggered": "\u2705", "not": "\u274c", "missing": "\u26a0\ufe0f", "contra": "\U0001f53b"}


# --------------------------------------------------------------------------- #
# Table record builders
# --------------------------------------------------------------------------- #


def market_records(feat: dict, ctx: dict, aliases: list) -> list:
    recs = []
    for a in aliases:
        if f"{a}.return_1d" not in feat and f"{a}.last" not in feat:
            continue
        recs.append({
            "alias": a,
            "label": ctx["asset_labels"].get(a, a),
            "last": feat.get(f"{a}.last"),
            "r1": feat.get(f"{a}.return_1d"),
            "r5": feat.get(f"{a}.return_5d"),
            "r20": feat.get(f"{a}.return_20d"),
        })
    return recs


def yield_records(feat: dict, ctx: dict, aliases: list) -> list:
    recs = []
    for a in aliases:
        if f"{a}.level" not in feat:
            continue
        recs.append({
            "alias": a,
            "label": ctx["asset_labels"].get(a, a),
            "level": feat.get(f"{a}.level"),
            "b1": feat.get(f"{a}.change_1d_bps"),
            "b5": feat.get(f"{a}.change_5d_bps"),
            "b20": feat.get(f"{a}.change_20d_bps"),
        })
    return recs


def score_records(feat: dict) -> list:
    return [{"name": SCORE_LABELS[n], "key": n, "value": feat.get(f"score.{n}")} for n in SCORE_ORDER]


# --------------------------------------------------------------------------- #
# Small cell helpers
# --------------------------------------------------------------------------- #


def _ret(v):
    if v is None:
        return "<span class='muted'>n/a</span>"
    cls = "pos" if v > 0 else "neg" if v < 0 else "zero"
    return f"<span class='{cls}'>{v:+.2f}%</span>"


def _bps(v):
    if v is None:
        return "<span class='muted'>n/a</span>"
    cls = "pos" if v > 0 else "neg" if v < 0 else "zero"
    return f"<span class='{cls}'>{v:+.1f}</span>"


def _price(v):
    if v is None:
        return "<span class='muted'>n/a</span>"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def _market_table(recs: list) -> str:
    head = ("<thead><tr><th>Ticker</th><th>Asset</th><th class='num'>Price</th>"
            "<th class='num'>1D</th><th class='num'>5D</th><th class='num'>20D</th></tr></thead>")
    rows = "".join(
        f"<tr><td class='tk'>{esc(r['alias'])}</td><td>{esc(r['label'])}</td>"
        f"<td class='num'>{_price(r['last'])}</td><td class='num'>{_ret(r['r1'])}</td>"
        f"<td class='num'>{_ret(r['r5'])}</td><td class='num'>{_ret(r['r20'])}</td></tr>"
        for r in recs
    )
    if not rows:
        return "<p class='muted'>No market data available.</p>"
    return f"<div class='tbl-wrap'><table class='tbl'>{head}<tbody>{rows}</tbody></table></div>"


def _yields_table(recs: list) -> str:
    head = ("<thead><tr><th>Series</th><th class='num'>Level</th>"
            "<th class='num'>1D (bps)</th><th class='num'>5D (bps)</th>"
            "<th class='num'>20D (bps)</th></tr></thead>")
    rows = "".join(
        f"<tr><td>{esc(r['label'])}</td><td class='num'>{('%.2f%%' % r['level']) if r['level'] is not None else 'n/a'}</td>"
        f"<td class='num'>{_bps(r['b1'])}</td><td class='num'>{_bps(r['b5'])}</td>"
        f"<td class='num'>{_bps(r['b20'])}</td></tr>"
        for r in recs
    )
    if not rows:
        return "<p class='muted'>No yield data available.</p>"
    return f"<div class='tbl-wrap'><table class='tbl'>{head}<tbody>{rows}</tbody></table></div>"


def _scores_table(recs: list) -> str:
    rows = ""
    for r in recs:
        v = r["value"]
        if v is None:
            bar = "<span class='muted'>n/a</span>"
            val = "<span class='muted'>n/a</span>"
        else:
            half = abs(v) / 2.0
            if v >= 0:
                style = f"left:50%;width:{half}%"
                cls = "pos"
            else:
                style = f"left:{50 - half}%;width:{half}%"
                cls = "neg"
            bar = (f"<div class='sbar'><div class='sline'></div>"
                   f"<div class='sfill {cls}' style='{style}'></div></div>")
            val = f"<span class='{cls}'>{v:+.0f}</span>"
        rows += (f"<tr><td>{esc(r['name'])}</td><td class='sbarcell'>{bar}</td>"
                 f"<td class='num scoreval'>{val}</td></tr>")
    return f"<div class='tbl-wrap'><table class='tbl scores'><tbody>{rows}</tbody></table></div>"


def _history_table(rows: list) -> str:
    if not rows:
        return "<p class='muted'>No history yet \u2014 this is the first run.</p>"
    cols = [
        ("run_date", "Run"), ("data_date", "Data"), ("primary_regime", "Primary regime"),
        ("primary_score", "Score"), ("risk_on_score", "Risk-On"), ("risk_off_score", "Risk-Off"),
        ("recession_scare_score", "Recession"), ("inflation_shock_score", "Inflation"),
        ("rates_shock_score", "Rates"),
    ]
    head = "<thead><tr>" + "".join(
        f"<th class='{'num' if c not in ('run_date', 'data_date', 'primary_regime') else ''}'>{esc(t)}</th>"
        for c, t in cols
    ) + "</tr></thead>"

    body = ""
    for row in rows:
        tds = ""
        for c, _ in cols:
            val = row.get(c, "")
            if c == "primary_score":
                try:
                    tds += f"<td class='num'><span class='chip'>{float(val):.0f}%</span></td>"
                except (TypeError, ValueError):
                    tds += f"<td class='num'>{esc(val)}</td>"
            elif c.endswith("_score"):
                try:
                    tds += f"<td class='num'>{float(val):.0f}</td>"
                except (TypeError, ValueError):
                    tds += f"<td class='num'>{esc(val)}</td>"
            elif c == "primary_regime":
                tds += f"<td>{esc(val)}</td>"
            else:
                tds += f"<td>{esc(val)}</td>"
        body += f"<tr>{tds}</tr>"
    return f"<div class='tbl-wrap'><table class='tbl'>{head}<tbody>{body}</tbody></table></div>"


# --------------------------------------------------------------------------- #
# Regime cards + detail panels
# --------------------------------------------------------------------------- #


def _rules_block(title: str, items: list, icon: str) -> str:
    if not items:
        return ""
    lis = ""
    for e in items:
        lis += (
            f"<li class='rule rule-{e['status']} kind-{e['kind']}'>"
            f"<div class='rule-top'><span class='rule-ic'>{icon}</span>"
            f"<span class='rule-name'>{esc(e['name'])}</span>"
            f"<span class='rule-w'>w{e['weight']}</span></div>"
            f"<div class='rule-cond'>{esc(e['condition'])} &middot; observed <b>{esc(e['observed'])}</b></div>"
            f"<div class='rule-expl'>{esc(e['explanation'])}</div>"
            f"</li>"
        )
    return f"<div class='rblock'><div class='rblock-h'>{esc(title)} <span class='rcount'>{len(items)}</span></div><ul class='rlist'>{lis}</ul></div>"


def _used_block(entities: list, feat: dict, ctx: dict) -> str:
    rows = ""
    for e in entities:
        if e.startswith("score:"):
            continue
        if e in ctx["yield_aliases"]:
            lvl = feat.get(f"{e}.level")
            if lvl is None:
                continue
            label = ctx["asset_labels"].get(e, e)
            rows += (f"<tr><td>{esc(label)}</td><td class='num'>{lvl:.2f}%</td>"
                     f"<td class='num'>{_bps(feat.get(f'{e}.change_1d_bps'))} bps</td><td></td></tr>")
        elif "/" in e:
            r1 = feat.get(f"{e}.return_1d")
            r5 = feat.get(f"{e}.return_5d")
            if r1 is None and r5 is None:
                continue
            rows += (f"<tr><td>{esc(e)} ratio</td><td class='num'>{_ret(r1)}</td>"
                     f"<td class='num'>{_ret(r5)}</td><td></td></tr>")
        else:
            last = feat.get(f"{e}.last")
            r1 = feat.get(f"{e}.return_1d")
            if last is None and r1 is None:
                continue
            label = "US Dollar (DXY/UUP)" if e == "USD" else ctx["asset_labels"].get(e, e)
            rows += (f"<tr><td>{esc(label)}</td><td class='num'>{_price(last)}</td>"
                     f"<td class='num'>{_ret(r1)}</td><td class='num'>{_ret(feat.get(f'{e}.return_5d'))}</td></tr>")
    if not rows:
        return ""
    return (f"<div class='rblock used'><div class='rblock-h'>Market data used</div>"
            f"<div class='tbl-wrap'><table class='tbl mini'><tbody>{rows}</tbody></table></div></div>")


def _card(reg: dict, feat: dict, ctx: dict) -> str:
    score = reg["score"]
    meta = f"{reg['n_triggered']}/{reg['n_possible']} rules"
    if reg["n_missing"]:
        meta += f" \u00b7 {reg['n_missing']} missing"

    detail = (
        f"<p class='def'>{esc(reg['definition'])}</p>"
        f"<p class='sum'>{esc(reg['summary'])}</p>"
        + _rules_block("Triggered rules", reg["triggered_rules"], ICON["triggered"])
        + _rules_block("Not triggered", reg["not_triggered_rules"], ICON["not"])
        + _rules_block("Contradictions", reg["contradictions"], ICON["contra"])
        + _rules_block("Missing data", reg["missing_rules"], ICON["missing"])
        + _used_block(reg["entities"], feat, ctx)
    )

    return (
        f"<div class='card tone-{esc(reg['tone'])}' data-key='{esc(reg['key'])}'>"
        f"<button class='card-head' type='button' onclick='toggleCard(this)' aria-expanded='false'>"
        f"<span class='swatch' aria-hidden='true'></span>"
        f"<span class='card-name'>{esc(reg['name'])}</span>"
        f"<span class='card-meta'>{esc(meta)}</span>"
        f"<span class='card-score'>{score:.0f}<span class='pct'>%</span></span>"
        f"<span class='chev' aria-hidden='true'>&rsaquo;</span>"
        f"</button>"
        f"<div class='bar'><div class='bar-fill' style='width:{score}%'></div></div>"
        f"<div class='detail'>{detail}</div>"
        f"</div>"
    )


def _primary_block(analysis: dict, results: dict) -> str:
    reg = results[analysis["primary_key"]]
    mode = analysis["mode"]
    score = reg["score"]
    if mode == "neutral":
        note = "No single regime reaches the conviction threshold \u2014 the tape is mixed."
    elif mode == "mixed_bias":
        bias = results.get("neutral_mixed", {}).get("bias", "")
        note = f"Mixed read, with a bias toward {esc(bias)}." if bias else "Mixed read."
    else:
        note = "Clear regime read."
    return (
        f"<section class='primary tone-{esc(reg['tone'])}'>"
        f"<div class='primary-eyebrow'>Primary regime</div>"
        f"<h2 class='primary-name'>{esc(reg['name'])}</h2>"
        f"<div class='conf'><div class='conf-track'><div class='conf-fill' style='width:{score}%'></div></div>"
        f"<div class='conf-val'>{score:.0f}<span class='pct'>%</span></div></div>"
        f"<div class='primary-note'>{note}</div>"
        f"</section>"
    )


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #


def build_html(analysis: dict, results: dict, feat: dict, ctx: dict,
               history_rows: list, template: str) -> str:
    cards = "".join(_card(results[k], feat, ctx) for k in analysis["ordered"])
    tokens = {
        "{{DATA_DATE}}": esc(analysis["data_date"]),
        "{{ANALYSIS_DATE}}": esc(analysis["analysis_date"]),
        "{{SOURCE}}": esc(analysis["source"]),
        "{{N_REGIMES}}": str(len([k for k in results if k != "neutral_mixed"])),
        "{{N_SERIES}}": str(analysis.get("n_series", "")),
        "{{PRIMARY_BLOCK}}": _primary_block(analysis, results),
        "{{REGIME_CARDS}}": cards,
        "{{MARKET_TABLE}}": _market_table(analysis["market_recs"]),
        "{{YIELDS_TABLE}}": _yields_table(analysis["yield_recs"]),
        "{{SCORES_TABLE}}": _scores_table(analysis["score_recs"]),
        "{{HISTORY_TABLE}}": _history_table(history_rows),
    }
    out = template
    for k, v in tokens.items():
        out = out.replace(k, v)
    return out
