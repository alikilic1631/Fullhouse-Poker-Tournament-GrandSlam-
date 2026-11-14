"""
field_sim.py (Patch 16b) — realistic field-mix tournament simulation.

Draws 5 opponents per 6-bot table from a weighted FIELD_DISTRIBUTION and runs
the bot under test across many tables. This is the single best local predictor
of qualifier finish — it tests the bot against the kind of mix it will actually
face, not a single bot type. Reports cumulative delta, median, p5, robust_score
and the Patch 19i punt audit (catastrophic-loss counts).

Uses the in-process run_match from bench.py (fast; warmup tables cached).

Usage:
  python3 sandbox/field_sim.py bots/v9/bot.py --tables 60
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench import run_match  # noqa: E402

# Pre-tournament best-guess field. Paths match this repo's flat enemy_zoo layout.
# Re-tune from D1 hand histories during the patch window.
FIELD_DISTRIBUTION = {
    "bots/enemy_zoo/solver_approximator.py":               0.25,
    "bots/enemy_zoo/mixed_strategy_pluribus_caricature.py": 0.10,
    "bots/enemy_zoo/mixed_llm_caricature.py":              0.15,
    "bots/enemy_zoo/tight_value_only.py":                  0.08,
    "bots/enemy_zoo/loose_passive_call_station.py":        0.08,
    "bots/enemy_zoo/aggressive_3bettor.py":                0.05,
    "bots/enemy_zoo/polarized_bettor.py":                  0.05,
    "bots/enemy_zoo/short_stack_jammer.py":                0.04,
    "bots/enemy_zoo/weird_sizing.py":                      0.05,
    "bots/enemy_zoo/nit_preflop.py":                       0.03,
    "bots/enemy_zoo/overbet_river_bluffer.py":             0.03,
    "bots/enemy_zoo/fit_or_fold.py":                       0.03,
    "bots/shark/bot.py":                                   0.03,
    "bots/template/bot.py":                                0.02,
    "bots/aggressor/bot.py":                               0.01,
}


def sample_table(distribution, n_opponents, rng):
    bots, weights = zip(*distribution.items())
    return rng.choices(bots, weights=weights, k=n_opponents)


def run_field_simulation(bot_under_test, n_tables=60, hands=400, base_seed=2000):
    deltas = []
    for i in range(n_tables):
        rng = random.Random(base_seed + i)
        opponents = sample_table(FIELD_DISTRIBUTION, 5, rng)
        r = run_match(bot_under_test, opponents, seed=base_seed + i, n_hands=hands)
        deltas.append(r["delta"])
    arr = np.array(deltas, dtype=float)
    return {
        "n_tables": n_tables,
        "cumulative_delta": int(arr.sum()),
        "mean_per_table": float(arr.mean()),
        "median_per_table": float(np.median(arr)),
        "p5_per_table": float(np.percentile(arr, 5)),
        "p95_per_table": float(np.percentile(arr, 95)),
        "std_per_table": float(arr.std()),
        "robust_score": float(np.median(arr) - 0.25 * np.percentile(arr, 5)),
        "tables_with_positive_delta": int((arr > 0).sum()),
        # Patch 19i punt audit
        "punt_tables": int((arr < -7000).sum()),
        "near_punt_tables": int(((arr >= -7000) & (arr < -4000)).sum()),
        "worst_table_delta": int(arr.min()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_path")
    ap.add_argument("--tables", type=int, default=60)
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = run_field_simulation(args.bot_path, args.tables, args.hands, args.seed)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"\nFIELD-MIX SIM — {args.bot_path}  ({r['n_tables']} tables x {args.hands} hands)")
        print(f"  cumulative delta : {r['cumulative_delta']:+d}")
        print(f"  per-table        : median={r['median_per_table']:+.0f} mean={r['mean_per_table']:+.0f} "
              f"p5={r['p5_per_table']:+.0f} p95={r['p95_per_table']:+.0f}")
        print(f"  robust_score     : {r['robust_score']:+.0f}")
        print(f"  positive tables  : {r['tables_with_positive_delta']}/{r['n_tables']}")
        print(f"  punts (<-7000)   : {r['punt_tables']}   near-punts: {r['near_punt_tables']}   "
              f"worst: {r['worst_table_delta']:+d}")


if __name__ == "__main__":
    main()
