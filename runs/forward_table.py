"""Checkpoint (c): the four forward replays, their KPIs, the expectations and the drift items."""
import json
from pathlib import Path

D = Path(__file__).resolve().parent / "forward"
RUN01_MODEL_INVENTORY = 3119651
REPLAYS = [("reference", "Reference (current features and policy)"), ("s1_static", "S1, static horizon"),
           ("s1_pooled", "S1, pooled horizon"), ("s6_pooled", "S6, pooled horizon")]
R = {}
for k, _ in REPLAYS:
    p = D / k
    if (p / "forward_results.json").exists():
        R[k] = {"fr": json.loads((p / "forward_results.json").read_text())["forward"]["1H26"],
                "sig": json.loads((p / "signal_checks.json").read_text()),
                "act": json.loads((p / "active_short.json").read_text()),
                "drift": json.loads((p / "drift_items.json").read_text())}
P = lambda x: f"{x*100:.1f}%"
M = lambda x: f"${x:,.0f}"
out = ["### Forward window, January to June 2026", "",
       "| Replay | Fill | Stockout days | Jobs held | Rush lines | Rush spend | Avg inventory | Days of usage | Service backorders | Active-short item-weeks |",
       "|---|---|---|---|---|---|---|---|---|---|"]
for k, lab in REPLAYS:
    if k not in R:
        continue
    m = R[k]["fr"]["model"]
    out.append(f"| {lab} | {P(m['fill_rate'])} | {m['stockout_days']:,} | {m['jobs_delayed']} | {m['rush_lines']} | {M(m['rush_spend'])} | "
               f"{M(m['avg_inventory_value'])} | {m['days_of_supply']:.0f} | {R[k]['sig']['service_holds']['backorder_forward']:.2f}% | "
               f"{P(R[k]['act']['active_short_share_forward'])} |")
ref = R.get("reference")
if ref:
    r = ref["fr"]["clean_rule"]
    out.append(f"| Rule on corrected masters (same in every replay) | {P(r['fill_rate'])} | {r['stockout_days']:,} | {r['jobs_delayed']} | "
               f"{r['rush_lines']} | {M(r['rush_spend'])} | {M(r['avg_inventory_value'])} | {r['days_of_supply']:.0f} | | |")

out += ["", "### Against the reference and the rule", "",
        "| Replay | Stockout days vs ref | vs rule | Jobs held vs ref | Rush spend vs ref | Avg inventory vs ref | vs rule |", "|---|---|---|---|---|---|---|"]
rel = lambda a, b: f"{(a / b - 1) * 100:+.1f}%" if b else ""
for k, lab in REPLAYS[1:]:
    if k not in R or not ref:
        continue
    m, rf, ru = R[k]["fr"]["model"], ref["fr"]["model"], R[k]["fr"]["clean_rule"]
    out.append(f"| {lab} | {rel(m['stockout_days'], rf['stockout_days'])} | {rel(m['stockout_days'], ru['stockout_days'])} | "
               f"{m['jobs_delayed'] - rf['jobs_delayed']:+d} | {rel(m['rush_spend'], rf['rush_spend'])} | "
               f"{rel(m['avg_inventory_value'], rf['avg_inventory_value'])} | {rel(m['avg_inventory_value'], ru['avg_inventory_value'])} |")

out += ["", "### Expectations (a miss is a finding; nothing is retuned)", "",
        "| Replay | Model inventory vs Run 01 (within ±5%) | Forward service backorders (at most 1.5%) | Active-short item-weeks (at most 1.5%) |",
        "|---|---|---|---|"]
for k, lab in REPLAYS:
    if k not in R:
        continue
    inv = R[k]["fr"]["model"]["avg_inventory_value"] / RUN01_MODEL_INVENTORY - 1
    bo = R[k]["sig"]["service_holds"]["backorder_forward"]; act = R[k]["act"]["active_short_share_forward"] * 100
    v = lambda ok: "met" if ok else "MISS"
    out.append(f"| {lab} | {inv*100:+.1f}% ({v(abs(inv) <= 0.05)}) | {bo:.2f}% ({v(bo <= 1.5)}) | {act:.2f}% ({v(act <= 1.5)}) |")

if "s1_static" in R and "s1_pooled" in R:
    a, b = R["s1_static"]["drift"]["model_total"], R["s1_pooled"]["drift"]["model_total"]
    out += ["", f"### Drift-supplier items ({a['items']} parts), forward window, S1 model", "",
            "| Replay | Stockout days | Avg inventory |", "|---|---|---|",
            f"| S1, static horizon | {a['short_days']:,} | {M(a['avg_inventory_value'])} |",
            f"| S1, pooled horizon | {b['short_days']:,} | {M(b['avg_inventory_value'])} |"]
    if ref:
        c = ref["drift"]["model_total"]; ru = ref["drift"]["rule_total"]
        out += [f"| Reference | {c['short_days']:,} | {M(c['avg_inventory_value'])} |",
                f"| Rule | {ru['short_days']:,} | {M(ru['avg_inventory_value'])} |"]
    out += ["", "| Part | Static: stockout days / avg inventory | Pooled: stockout days / avg inventory |", "|---|---|---|"]
    for n in sorted(R["s1_static"]["drift"]["model"]):
        s, p = R["s1_static"]["drift"]["model"][n], R["s1_pooled"]["drift"]["model"][n]
        out.append(f"| {n} | {s['short_days']} / {M(s['avg_inventory_value'])} | {p['short_days']} / {M(p['avg_inventory_value'])} |")

(D / "forward_table.md").write_text("\n".join(out) + "\n")
print("\n".join(out))
