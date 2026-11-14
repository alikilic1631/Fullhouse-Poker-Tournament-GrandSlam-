"""
final_validation.py (Patch 19) — submission-decision phase.

Candidate A = v12 (v9 + hardening), Candidate B = v6 (last pre-v7 stable).
Runs: (19c) multi-version shootout vs 25 opponents; (19d) field-mix on primary
+ llm_heavy; (19e) cross-version round-robin monotonicity; (19i) punt audit;
(19f) decision matrix with (19j) emergency fallback; (19g) SUBMISSION_REPORT.md.

Fast: reuses bench.run_match (in-process, cached warmup) + field_sim.

Usage: python3 sandbox/final_validation.py [--seeds 15] [--tables 40]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import bench
import field_sim
from engine.game import PokerEngine, STARTING_STACK  # noqa

ROOT = Path(__file__).parent.parent
B = lambda p: str(ROOT / p)

CANDIDATES = {"v12": B("bots/v12/bot.py"), "v6": B("bots/v6/bot.py")}

ZOO = ["solver_approximator", "mixed_strategy_pluribus_caricature", "mixed_llm_caricature",
       "tight_value_only", "loose_passive_call_station", "aggressive_3bettor",
       "polarized_bettor", "nit_preflop", "overbet_river_bluffer", "weird_sizing",
       "fit_or_fold", "short_stack_jammer"]
REF = ["template", "aggressor", "mathematician", "shark", "ref_bot_2"]
PARAM = ["param_nit_overfolder", "param_tag_reg", "param_lag_maniac",
         "param_loose_passive_station", "param_modal_llm_chartbot",
         "param_pot_odds_overfolder", "param_weird_sizing_polar",
         "param_multiway_limper_station"]

OPP_PATHS = {}
for z in ZOO:
    OPP_PATHS[z] = B(f"bots/enemy_zoo/{z}.py")
for r in REF:
    OPP_PATHS[r] = B(f"bots/{r}/bot.py")
for p in PARAM:
    OPP_PATHS[p] = B(f"bots/enemy_zoo/{p}.py")

# "weak field" set for farm_score (Patch 18f undefined in spec -> defined here):
# how much we farm the exploitable opponents.
WEAK_SET = ["loose_passive_call_station", "nit_preflop", "fit_or_fold", "always_call_skip",
            "param_nit_overfolder", "param_loose_passive_station",
            "param_pot_odds_overfolder", "param_multiway_limper_station"]

PRIMARY = {
    B("bots/enemy_zoo/solver_approximator.py"): 0.25,
    B("bots/enemy_zoo/mixed_strategy_pluribus_caricature.py"): 0.10,
    B("bots/enemy_zoo/mixed_llm_caricature.py"): 0.15,
    B("bots/enemy_zoo/tight_value_only.py"): 0.08,
    B("bots/enemy_zoo/loose_passive_call_station.py"): 0.08,
    B("bots/enemy_zoo/aggressive_3bettor.py"): 0.05,
    B("bots/enemy_zoo/polarized_bettor.py"): 0.05,
    B("bots/enemy_zoo/short_stack_jammer.py"): 0.04,
    B("bots/enemy_zoo/weird_sizing.py"): 0.05,
    B("bots/enemy_zoo/nit_preflop.py"): 0.03,
    B("bots/enemy_zoo/overbet_river_bluffer.py"): 0.03,
    B("bots/enemy_zoo/fit_or_fold.py"): 0.03,
    B("bots/shark/bot.py"): 0.03,
    B("bots/template/bot.py"): 0.02,
    B("bots/aggressor/bot.py"): 0.01,
}

LLM_HEAVY = {
    B("bots/enemy_zoo/solver_approximator.py"): 0.25,
    B("bots/enemy_zoo/mixed_llm_caricature.py"): 0.25,
    B("bots/enemy_zoo/param_modal_llm_chartbot.py"): 0.20,
    B("bots/enemy_zoo/param_pot_odds_overfolder.py"): 0.15,
    B("bots/enemy_zoo/param_tag_reg.py"): 0.10,
    B("bots/enemy_zoo/mixed_strategy_pluribus_caricature.py"): 0.05,
}


def stats(deltas):
    a = np.array(deltas, dtype=float)
    return {
        "median": float(np.median(a)), "mean": float(a.mean()),
        "p5": float(np.percentile(a, 5)), "p95": float(np.percentile(a, 95)),
        "punts": int((a < -7000).sum()), "n": len(a),
    }


def shootout(cand_path, opp_path, seeds, hands):
    deltas, crashes, timeouts, invalid, times = [], 0, 0, 0, []
    for s in range(seeds):
        r = bench.run_match(cand_path, [opp_path] * 5, s, hands)
        deltas.append(r["delta"])
        m = r["metrics"]
        crashes += m["crashes"]; timeouts += m["timeouts"]; invalid += m["invalid"]
        times += m["times"]
    p99 = float(np.percentile([t * 1000 for t in times], 99)) if times else 0.0
    return deltas, crashes, timeouts, invalid, p99


def run_table(label_paths, seed, hands):
    """Multiway in-process match; returns {label: chip_delta}."""
    labels = list(label_paths.keys())
    mods = {lab: bench._load_module(label_paths[lab]) for lab in labels}
    for lab in labels:
        bench._warmup(mods[lab], label_paths[lab])
    random.seed(seed); np.random.seed(seed % (2**32 - 1))
    stacks = {lab: STARTING_STACK for lab in labels}
    mlog, dealer = [], 0
    for hn in range(hands):
        alive = [lab for lab in labels if stacks[lab] > 0]
        if len(alive) < 2:
            break
        eng = PokerEngine(f"rr_{seed}_h{hn:04d}", alive, dealer % len(alive),
                          {lab: stacks[lab] for lab in alive}, seed=seed * 1000003 + hn)
        st = eng.start_hand()
        if st.get("type") == "action_request":
            st["match_action_log"] = mlog[-200:]
        steps = 0
        while st.get("type") == "action_request" and steps < 1000:
            seat = st["seat_to_act"]; lab = alive[seat]
            try:
                act = mods[lab].decide(st)
            except Exception:
                act = {"action": "fold"}
            mlog.append({"hand_num": hn, "seat": seat, "bot_id": lab,
                         "action": act.get("action"), "amount": act.get("amount")})
            st = eng.apply_action(seat, act or {"action": "fold"})
            if st.get("type") == "action_request":
                st["match_action_log"] = mlog[-200:]
            steps += 1
        for pl in eng.players:
            stacks[pl.bot_id] = pl.stack
        dealer += 1
    return {lab: stacks[lab] - STARTING_STACK for lab in labels}


def evaluate_candidate(name, path, seeds, hands):
    print(f"\n[shootout] {name} vs {len(OPP_PATHS)} opponents x {seeds} seeds ...")
    per_opp, all_deltas = {}, []
    crashes = timeouts = invalid = 0
    p99 = 0.0
    for opp, opath in OPP_PATHS.items():
        d, c, t, i, pp = shootout(path, opath, seeds, hands)
        per_opp[opp] = stats(d)
        all_deltas += d
        crashes += c; timeouts += t; invalid += i; p99 = max(p99, pp)
        print(f"    vs {opp:34s} median={per_opp[opp]['median']:+8.0f} "
              f"p5={per_opp[opp]['p5']:+8.0f} punts={per_opp[opp]['punts']}")
    overall = stats(all_deltas)
    robust = overall["median"] - 0.25 * overall["p5"]
    farm = float(np.mean([per_opp[o]["median"] for o in WEAK_SET if o in per_opp]))
    worst_opp = min(per_opp.items(), key=lambda kv: kv[1]["median"])
    return {
        "per_opp": per_opp, "overall": overall, "robust": robust, "farm": farm,
        "worst_opp": (worst_opp[0], worst_opp[1]["median"]),
        "crashes": crashes, "timeouts": timeouts, "invalid": invalid, "p99_ms": p99,
        "total_matches": overall["n"],
        "punts": sum(s["punts"] for s in per_opp.values()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--tables", type=int, default=40)
    ap.add_argument("--hands", type=int, default=400)
    args = ap.parse_args()
    t0 = time.time()

    results = {}
    for name, path in CANDIDATES.items():
        ev = evaluate_candidate(name, path, args.seeds, args.hands)
        print(f"[field-mix] {name} primary ...")
        ev["field_primary"] = _field_mix(path, PRIMARY, args.tables, args.hands, 2000)
        print(f"[field-mix] {name} llm_heavy ...")
        ev["field_llm"] = _field_mix(path, LLM_HEAVY, args.tables, args.hands, 3000)
        results[name] = ev

    # Cross-version round-robin (19e)
    print("\n[round-robin] v0,v3,v6,v9,v12 + shark ...")
    rr = {v: 0 for v in ["v0", "v3", "v6", "v9", "v12"]}
    rr_paths = {v: B(f"bots/{v}/bot.py") for v in rr}
    rr_paths["filler_shark"] = B("bots/shark/bot.py")
    for s in range(20):
        d = run_table(rr_paths, 5000 + s, args.hands)
        for v in rr:
            rr[v] += d[v]
    rr_order = ["v0", "v3", "v6", "v9", "v12"]
    monotonic = all(rr[rr_order[i]] <= rr[rr_order[i + 1]] for i in range(len(rr_order) - 1))

    report = build_report(results, rr, monotonic, args, time.time() - t0)
    (ROOT.parent / "SUBMISSION_REPORT.md").write_text(report)
    print("\n" + report)


def _field_mix(path, dist, tables, hands, base_seed):
    deltas = []
    for i in range(tables):
        rng = random.Random(base_seed + i)
        bots, w = zip(*dist.items())
        opps = rng.choices(bots, weights=w, k=5)
        r = bench.run_match(path, opps, seed=base_seed + i, n_hands=hands)
        deltas.append(r["delta"])
    a = np.array(deltas, float)
    return {"cumulative": int(a.sum()), "median": float(np.median(a)),
            "p5": float(np.percentile(a, 5)),
            "robust": float(np.median(a) - 0.25 * np.percentile(a, 5)),
            "punts": int((a < -7000).sum()), "positive": int((a > 0).sum()), "n": tables}


def composite(ev):
    pp = ev["total_matches"] + ev["field_primary"]["n"] + ev["field_llm"]["n"]
    punts = ev["punts"] + ev["field_primary"]["punts"] + ev["field_llm"]["punts"]
    norm_punt = punts / (pp * 0.1) if pp else 0.0
    return (0.50 * ev["field_primary"]["robust"] + 0.20 * ev["field_llm"]["robust"]
            + 0.15 * ev["farm"] - 0.15 * norm_punt * 1000.0), norm_punt


def decide_submission(results):
    A, Bc = results["v12"], results["v6"]
    ca, pa = composite(A)
    cb, pb = composite(Bc)
    # Tier 1 hard gates
    a_t1 = A["crashes"] == 0 and A["timeouts"] == 0 and A["invalid"] == 0 and A["p99_ms"] <= 1200
    b_t1 = Bc["crashes"] == 0 and Bc["timeouts"] == 0 and Bc["invalid"] == 0 and Bc["p99_ms"] <= 1200
    reasons = []
    if not a_t1:
        return "v6", ca, cb, "Candidate A failed Tier-1 hard gate -> ship B (Patch 19j)"
    # Patch 19j emergency-style deterministic rule on composites
    if ca - cb > 0.5 * abs(cb if cb else 1):
        pass
    if A["field_primary"]["robust"] > Bc["field_primary"]["robust"] * 1.05:
        return "v12", ca, cb, "A field-mix robust > B by >5% (Patch 19j)"
    if (A["overall"]["p5"] < Bc["overall"]["p5"]) or (A["punts"] > 1.5 * max(Bc["punts"], 1)):
        return "v6", ca, cb, "A has worse p5 / materially more punts -> ship simpler B (Patch 19j)"
    if ca >= cb:
        return "v12", ca, cb, "A composite >= B (Patch 19f)"
    return "v6", ca, cb, "default to simpler stable B under wash (Patch 19j)"


def build_report(results, rr, monotonic, args, secs):
    pick, ca, cb, why = decide_submission(results)
    L = []
    L.append("# SUBMISSION_REPORT.md — Patch 19 final validation\n")
    L.append(f"- Candidate A = v12 (v9 + hardening) · Candidate B = v6 (last pre-v7 stable)")
    L.append(f"- Opponents: {len(OPP_PATHS)} (12 zoo + 5 reference + 8 parametric) × {args.seeds} seeds; "
             f"field-mix {args.tables} tables × 2 distributions; round-robin 20 seeds")
    L.append(f"- Validation wall time: {secs/60:.1f} min\n")
    L.append("## Decision")
    L.append(f"**SHIP: {pick}** — {why}")
    L.append(f"- composite: v12={ca:+.1f}  v6={cb:+.1f}\n")
    L.append("## Per-candidate summary")
    L.append("| metric | v12 | v6 |")
    L.append("|---|---|---|")
    for k, lab in [("overall", "shootout median"), ]:
        L.append(f"| shootout median | {results['v12']['overall']['median']:+.0f} | {results['v6']['overall']['median']:+.0f} |")
    L.append(f"| shootout p5 | {results['v12']['overall']['p5']:+.0f} | {results['v6']['overall']['p5']:+.0f} |")
    L.append(f"| shootout robust | {results['v12']['robust']:+.0f} | {results['v6']['robust']:+.0f} |")
    L.append(f"| farm_score (weak field) | {results['v12']['farm']:+.0f} | {results['v6']['farm']:+.0f} |")
    L.append(f"| field primary robust | {results['v12']['field_primary']['robust']:+.0f} | {results['v6']['field_primary']['robust']:+.0f} |")
    L.append(f"| field primary cumulative | {results['v12']['field_primary']['cumulative']:+d} | {results['v6']['field_primary']['cumulative']:+d} |")
    L.append(f"| field llm_heavy robust | {results['v12']['field_llm']['robust']:+.0f} | {results['v6']['field_llm']['robust']:+.0f} |")
    L.append(f"| total punts (<-7000) | {results['v12']['punts']} | {results['v6']['punts']} |")
    L.append(f"| crashes/timeouts/invalid | {results['v12']['crashes']}/{results['v12']['timeouts']}/{results['v12']['invalid']} | {results['v6']['crashes']}/{results['v6']['timeouts']}/{results['v6']['invalid']} |")
    L.append(f"| p99 decision (ms) | {results['v12']['p99_ms']:.1f} | {results['v6']['p99_ms']:.1f} |")
    L.append("")
    L.append("## Tier-1 hard gates")
    for nm in ("v12", "v6"):
        e = results[nm]
        ok = e["crashes"] == 0 and e["timeouts"] == 0 and e["invalid"] == 0 and e["p99_ms"] <= 1200
        L.append(f"- {nm}: crashes={e['crashes']} timeouts={e['timeouts']} invalid={e['invalid']} "
                 f"p99={e['p99_ms']:.0f}ms -> {'PASS' if ok else 'FAIL'}")
    L.append(f"- cross-version round-robin monotonic (v0<=v3<=v6<=v9<=v12): {'PASS' if monotonic else 'VIOLATION'}")
    L.append(f"  cumulative: " + "  ".join(f"{v}={rr[v]:+d}" for v in ['v0','v3','v6','v9','v12']))
    L.append("")
    L.append("## Worst-case opponents (for qualifier awareness)")
    for nm in ("v12", "v6"):
        e = results[nm]
        L.append(f"- {nm}: worst vs {e['worst_opp'][0]} (median {e['worst_opp'][1]:+.0f})")
        negs = [o for o, s in e["per_opp"].items() if s["median"] < -1500]
        L.append(f"  consistently-negative opponents (median<-1500): {negs if negs else 'none'}")
    L.append("")
    L.append("## Methodology note — v10 (LR) negative result")
    L.append("- v10 (LR confidence-gated bet sizing, Patch 7+17) was built and REJECTED: it did")
    L.append("  not beat v9 (paired held-out -2164; field-mix robust regressed +18968->+16930).")
    L.append("  Root cause: redundant with v4's opponent perturbation. Kept as paper trail in")
    L.append("  bots/v10/ + data/lr_fold_predictor.npz for possible patch-window re-deploy.")
    L.append("- v11 (river LP solver) skipped: 'only if all gates clean' (v10 failed) + same")
    L.append("  redundancy root cause + higher implementation risk.")
    return "\n".join(L)


if __name__ == "__main__":
    main()
