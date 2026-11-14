"""
weakness_discovery.py (D1) — Latin-hypercube parametric weakness search.

Samples ~N opponent configs across a broad parameter space, runs the bot under
test vs 5 copies of each config, ranks by our chip delta (ascending), clusters
the worst, and writes V13_WEAKNESS_CATALOG.md for the D2 patch window. NO
submission change — pure diagnostic.

Uses ParametricOpponent (bots/enemy_zoo/_param_core.py). The hero module is
loaded ONCE (warmup/equity table computed once); per-match opponent memory is
reset so each config is judged fresh.

Usage: python3 sandbox/weakness_discovery.py bots/v13/bot.py --n 80 --seeds 6
"""
import argparse
import importlib.util
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from engine.game import PokerEngine, STARTING_STACK

DIMS = {
    "vpip": (0.10, 0.85), "pfr": (0.05, 0.65), "threebet_freq": (0.02, 0.30),
    "cbet_freq": (0.30, 0.95), "fold_to_cbet": (0.10, 0.95),
    "aggression_factor": (0.3, 5.0), "donk_freq": (0.0, 0.45),
    "trap_freq": (0.0, 0.30), "short_stack_jam_freq": (0.0, 1.0),
    "river_bluff_freq": (0.0, 0.40),
}
SIZINGS = ["standard", "large", "overbet", "min_raise", "tiny_block"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def lhs(n):
    samples = [{} for _ in range(n)]
    for name, (lo, hi) in DIMS.items():
        cuts = np.linspace(0, 1, n + 1)
        pts = [cuts[i] + random.random() * (cuts[i + 1] - cuts[i]) for i in range(n)]
        random.shuffle(pts)
        for i in range(n):
            samples[i][name] = round(lo + pts[i] * (hi - lo), 3)
    for i in range(n):
        samples[i]["pfr"] = round(min(samples[i]["pfr"], samples[i]["vpip"]), 3)
        samples[i]["sizing_profile"] = SIZINGS[i % len(SIZINGS)]
    return samples


def play(hero, opp_decide, seed, hands):
    """v13 (seat rotates) vs 5 copies of one parametric opp. Returns hero delta."""
    ids = ["hero", "o1", "o2", "o3", "o4", "o5"]
    decide = {"hero": hero.decide}
    for o in ids[1:]:
        decide[o] = opp_decide
    hero.OPPONENT_STATS.clear()
    hero.PROCESSED_HANDS.clear()
    random.seed(seed); np.random.seed(seed % (2**32 - 1))
    stacks = {i: STARTING_STACK for i in ids}
    mlog, dealer = [], 0
    for hn in range(hands):
        alive = [i for i in ids if stacks[i] > 0]
        if len(alive) < 2 or "hero" not in alive:
            break
        eng = PokerEngine(f"wd_{seed}_h{hn:04d}", alive, dealer % len(alive),
                          {i: stacks[i] for i in alive}, seed=seed * 1000003 + hn)
        st = eng.start_hand()
        if st.get("type") == "action_request":
            st["match_action_log"] = mlog[-200:]
        steps = 0
        while st.get("type") == "action_request" and steps < 1000:
            seat = st["seat_to_act"]; bid = alive[seat]
            try:
                act = decide[bid](st)
            except Exception:
                act = {"action": "fold"}
            mlog.append({"hand_num": hn, "seat": seat, "bot_id": bid,
                         "action": act.get("action"), "amount": act.get("amount")})
            st = eng.apply_action(seat, act or {"action": "fold"})
            if st.get("type") == "action_request":
                st["match_action_log"] = mlog[-200:]
            steps += 1
        for b, v in st.get("final_stacks", {}).items():
            stacks[b] = v
        dealer += 1
    return stacks["hero"] - STARTING_STACK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--hands", type=int, default=400)
    args = ap.parse_args()

    hero = load(args.hero, "hero_wd")
    try:
        hero.decide({"type": "warmup"})
    except Exception:
        pass
    PC = load(str(ROOT / "bots" / "enemy_zoo" / "_param_core.py"), "pc_wd")

    random.seed(123)
    configs = lhs(args.n)
    results = []
    for ci, cfg in enumerate(configs):
        opp = PC.ParametricOpponent(**cfg)
        deltas = [play(hero, opp.decide, 1000 + ci * 100 + s, args.hands) for s in range(args.seeds)]
        results.append((float(np.mean(deltas)), float(np.median(deltas)), cfg))
        if ci % 10 == 0:
            print(f"  ...{ci}/{args.n}")
    results.sort(key=lambda r: r[0])

    worst = results[:12]
    # dimension signature of worst cluster vs overall
    def dim_mean(rows, d):
        return float(np.mean([r[2][d] for r in rows]))
    overall_dim = {d: dim_mean(results, d) for d in DIMS}
    worst_dim = {d: dim_mean(worst, d) for d in DIMS}
    skew = sorted(DIMS, key=lambda d: abs(worst_dim[d] - overall_dim[d]) /
                  (DIMS[d][1] - DIMS[d][0]), reverse=True)

    L = ["# V13_WEAKNESS_CATALOG.md — parametric weakness discovery (D1)\n",
         f"- Bot: {args.hero} · {args.n} LHS configs × {args.seeds} seeds × {args.hands} hands",
         f"- Overall: median config delta = {np.median([r[1] for r in results]):+.0f}, "
         f"mean = {np.mean([r[0] for r in results]):+.0f}, "
         f"configs where we LOSE (mean<0) = {sum(1 for r in results if r[0] < 0)}/{args.n}\n",
         "## Worst-cluster parameter signature (worst 12 vs overall)",
         "| dim | worst-12 mean | overall mean | range |", "|---|---|---|---|"]
    for d in skew:
        L.append(f"| {d} | {worst_dim[d]:.2f} | {overall_dim[d]:.2f} | {DIMS[d]} |")
    L.append("\n## Top 10 worst configs (patch-window targets)")
    L.append("| rank | mean Δ | median Δ | key params |")
    L.append("|---|---|---|---|")
    for i, (mn, md, cfg) in enumerate(results[:10], 1):
        key = ", ".join(f"{k}={cfg[k]}" for k in ("vpip", "aggression_factor", "fold_to_cbet",
                        "trap_freq", "donk_freq", "short_stack_jam_freq", "sizing_profile"))
        L.append(f"| {i} | {mn:+.0f} | {md:+.0f} | {key} |")
    L.append("\n## Notes")
    L.append("- Counter-strategies are NOT implemented here. On D2, match observed field")
    L.append("  profiles to these clusters; implement a counter ONLY IF the leak is large")
    L.append("  (>3000 mean), the fix is simple (<50 lines / one param), the profile is")
    L.append("  plausible in the real field, and it passes held-out + field-mix gates.")
    L.append("- Note: '5 copies of one config' mono-tables are a stress (5 maniacs/jammers")
    L.append("  at one table = high variance); read mean+median together, not raw worst.")
    report = "\n".join(L)
    (ROOT.parent / "V13_WEAKNESS_CATALOG.md").write_text(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
