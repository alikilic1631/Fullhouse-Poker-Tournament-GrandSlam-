"""
bench.py — paired-seed differential testing harness.

The ONLY honest way to know if a change helped: compare two bot versions on
identical seeds. This runs the engine IN-PROCESS (no subprocess/JSON overhead)
and seeds all RNG before every match so opponent behaviour is identical across
the paired runs — the cards are the same and the opponents play the same way,
so the only difference between run A and run B is the bot under test. That
maximises pairing and minimises noise.

For each seed s:
  run A = [botA as "hero"] + opponents, seeded with s
  run B = [botB as "hero"] + opponents, seeded with s
The hero occupies the same seat with the same bot_id ("hero") in both runs, so
opponents that model by bot_id treat botA and botB identically.

Robustness/sandbox fidelity (the 2s hard timeout, crash isolation, AST checks)
is covered by validator.py and fuzz.py — bench measures EV and flags timing.

Usage:
  python3 sandbox/bench.py bots/v1/bot.py bots/v0/bot.py \
      --opponents bots/template/bot.py,bots/aggressor/bot.py,bots/mathematician/bot.py,bots/shark/bot.py,bots/ref_bot_2/bot.py \
      --seeds 30 --hands 400
"""
import argparse
import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.game import PokerEngine, STARTING_STACK

try:
    from scipy import stats as _scipy_stats
except Exception:
    _scipy_stats = None

MATCH_LOG_MAX = 200
VALID_ACTIONS = {"fold", "check", "call", "raise", "all_in"}

DEFAULT_OPPONENTS = [
    "bots/template/bot.py",
    "bots/aggressor/bot.py",
    "bots/mathematician/bot.py",
    "bots/shark/bot.py",
    "bots/ref_bot_2/bot.py",
]

_load_counter = 0


def _load_module(path):
    """Load a fresh module instance so module globals reset per match
    (mirrors the prod model: one fresh subprocess per match)."""
    global _load_counter
    _load_counter += 1
    spec = importlib.util.spec_from_file_location(f"benchbot_{_load_counter}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not hasattr(m, "decide"):
        raise AttributeError(f"{path} has no decide()")
    return m


def _inject(state, match_log):
    if state.get("type") == "action_request":
        state["match_action_log"] = match_log[-MATCH_LOG_MAX:]
    return state


def _is_legal(action, state):
    if not isinstance(action, dict):
        return False
    a = action.get("action")
    if a not in VALID_ACTIONS:
        return False
    if a == "check" and not state.get("can_check"):
        return False
    if a == "raise":
        if "amount" not in action:
            return False
        try:
            int(action["amount"])
        except (TypeError, ValueError):
            return False
    return True


# Cache of match-independent warmup state (e.g. a bot's precomputed equity
# table) keyed by bot path. bench reloads each bot fresh per match to reset
# per-match memory, but recomputing a heavy equity table every match dominates
# runtime — so we warm up each unique path ONCE and reuse its table. Production
# fidelity is preserved (the table is present); only the redundant recompute is
# skipped. Production warmup itself is validated separately (validator + real
# subprocess matches).
_WARMUP_EQ_CACHE = {}


def _warmup(module, path):
    cached = _WARMUP_EQ_CACHE.get(path)
    if cached is not None and hasattr(module, "PREFLOP_EQ"):
        try:
            module.PREFLOP_EQ.update(cached)   # reuse precomputed table; skip recompute
            return
        except Exception:
            pass
    try:
        module.decide({"type": "warmup"})
    except Exception:
        pass
    eq = getattr(module, "PREFLOP_EQ", None)
    if isinstance(eq, dict) and eq:
        _WARMUP_EQ_CACHE[path] = dict(eq)


def run_match(hero_path, opp_paths, seed, n_hands, hero_id="hero"):
    """Run one in-process match. Returns hero chip delta + hero metrics."""
    paths = [hero_path] + list(opp_paths)
    bot_ids = [hero_id] + [f"opp_{i}" for i in range(len(opp_paths))]

    # Seed everything that bots might use. Deck is seeded separately per hand
    # by the engine, so this only affects bot-side randomness.
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))

    modules = {bid: _load_module(p) for bid, p in zip(bot_ids, paths)}

    for bid, m in modules.items():
        _warmup(m, paths[bot_ids.index(bid)])

    stacks = {bid: STARTING_STACK for bid in bot_ids}
    match_log = []
    dealer = 0
    metrics = {"times": [], "crashes": 0, "timeouts": 0, "invalid": 0}

    for hand_num in range(n_hands):
        alive = [bid for bid in bot_ids if stacks[bid] > 0]
        if len(alive) < 2:
            break
        hand_seed = seed * 1000003 + hand_num
        engine = PokerEngine(
            hand_id=f"bench_{seed}_h{hand_num}",
            bot_ids=alive,
            dealer_seat=dealer % len(alive),
            starting_stacks={bid: stacks[bid] for bid in alive},
            seed=hand_seed,
        )
        state = _inject(engine.start_hand(), match_log)
        steps = 0
        while state.get("type") == "action_request":
            seat = state["seat_to_act"]
            bid = alive[seat]
            t0 = time.perf_counter()
            try:
                action = modules[bid].decide(state)
                dt = time.perf_counter() - t0
            except Exception:
                dt = time.perf_counter() - t0
                action = {"action": "fold"}
                if bid == hero_id:
                    metrics["crashes"] += 1
            if bid == hero_id:
                metrics["times"].append(dt)
                if dt > 2.0:
                    metrics["timeouts"] += 1
                if not _is_legal(action, state):
                    metrics["invalid"] += 1
            match_log.append({
                "hand_num": hand_num, "seat": seat, "bot_id": bid,
                "action": (action or {}).get("action"),
                "amount": (action or {}).get("amount"),
            })
            state = _inject(engine.apply_action(seat, action or {"action": "fold"}), match_log)
            steps += 1
            if steps > 1000:
                break
        for bid, s in state.get("final_stacks", {}).items():
            stacks[bid] = s
        dealer += 1

    return {
        "delta": stacks[hero_id] - STARTING_STACK,
        "metrics": metrics,
    }


def _pct(arr, q):
    return float(np.percentile(arr, q)) if len(arr) else 0.0


def _summarize_metrics(metric_list):
    times = [t for m in metric_list for t in m["times"]]
    times_ms = [t * 1000 for t in times]
    return {
        "crashes": sum(m["crashes"] for m in metric_list),
        "timeouts": sum(m["timeouts"] for m in metric_list),
        "invalid": sum(m["invalid"] for m in metric_list),
        "mean_ms": round(float(np.mean(times_ms)), 2) if times_ms else 0.0,
        "p99_ms": round(_pct(times_ms, 99), 2),
        "max_ms": round(max(times_ms), 2) if times_ms else 0.0,
        "decisions": len(times_ms),
    }


def compare(botA, botB, opponents, seeds, n_hands):
    a_deltas, b_deltas = [], []
    a_metrics, b_metrics = [], []
    per_seed = []

    for s in range(seeds):
        ra = run_match(botA, opponents, s, n_hands)
        rb = run_match(botB, opponents, s, n_hands)
        a_deltas.append(ra["delta"])
        b_deltas.append(rb["delta"])
        a_metrics.append(ra["metrics"])
        b_metrics.append(rb["metrics"])
        per_seed.append({"seed": s, "A": ra["delta"], "B": rb["delta"],
                         "diff": rb["delta"] - ra["delta"]})

    a_arr = np.array(a_deltas, dtype=float)
    b_arr = np.array(b_deltas, dtype=float)
    diff = b_arr - a_arr

    pval = None
    if _scipy_stats is not None and seeds >= 2 and np.std(diff) > 0:
        try:
            pval = float(_scipy_stats.ttest_rel(b_arr, a_arr).pvalue)
        except Exception:
            pval = None

    return {
        "botA": botA, "botB": botB,
        "opponents": opponents,
        "seeds": seeds, "n_hands": n_hands,
        "A": {"median": float(np.median(a_arr)), "mean": float(np.mean(a_arr)),
              "p5": _pct(a_arr, 5), "p95": _pct(a_arr, 95),
              **_summarize_metrics(a_metrics)},
        "B": {"median": float(np.median(b_arr)), "mean": float(np.mean(b_arr)),
              "p5": _pct(b_arr, 5), "p95": _pct(b_arr, 95),
              **_summarize_metrics(b_metrics)},
        "diff": {"median": float(np.median(diff)), "mean": float(np.mean(diff)),
                 "p5": _pct(diff, 5), "p95": _pct(diff, 95),
                 "wins": int(np.sum(diff > 0)), "losses": int(np.sum(diff < 0))},
        "p_value": pval,
        "per_seed": per_seed,
    }


def _print_report(r):
    print("\n" + "=" * 64)
    print(f"PAIRED BENCH  —  {r['seeds']} seeds x {r['n_hands']} hands")
    print(f"  B (new) : {r['botB']}")
    print(f"  A (base): {r['botA']}")
    print(f"  opponents: {len(r['opponents'])} -> " + ", ".join(Path(p).parent.name or Path(p).stem for p in r['opponents']))
    print("=" * 64)

    def row(label, d):
        print(f"  {label:8s} median={d['median']:+9.1f}  mean={d['mean']:+9.1f}  "
              f"p5={d['p5']:+9.1f}  p95={d['p95']:+9.1f}")

    print("Per-seed chip delta vs opponents:")
    row("A base", r["A"])
    row("B new", r["B"])
    print("Paired difference (B - A), per seed:")
    row("B - A", r["diff"])
    print(f"  B wins {r['diff']['wins']}/{r['seeds']} seeds,  loses {r['diff']['losses']}/{r['seeds']}")
    pv = r["p_value"]
    print(f"  paired t-test p-value: {pv:.4g}" if pv is not None else "  paired t-test p-value: n/a")
    robust = r["B"]["median"] - 0.25 * r["B"]["p5"]
    print(f"  robust score (B): median - 0.25*p5 = {robust:+.1f}")

    print("\nRobustness (hero bot only):")
    for label, d in (("A base", r["A"]), ("B new", r["B"])):
        print(f"  {label:8s} crashes={d['crashes']}  timeouts={d['timeouts']}  "
              f"invalid={d['invalid']}  mean={d['mean_ms']}ms  p99={d['p99_ms']}ms  "
              f"max={d['max_ms']}ms  ({d['decisions']} decisions)")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="Paired-seed differential bench. Reports B - A, so pass "
                    "the baseline first and the new bot second.")
    ap.add_argument("botA", help="Baseline bot, listed first (reported as A)")
    ap.add_argument("botB", help="New bot under test, listed second (reported as B)")
    ap.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS),
                    help="Comma-separated opponent bot paths")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    opponents = [p.strip() for p in args.opponents.split(",") if p.strip()]
    if not (2 <= 1 + len(opponents) <= 9):
        print(f"ERROR: hero + {len(opponents)} opponents must total 2..9 players", file=sys.stderr)
        sys.exit(2)

    t0 = time.time()
    r = compare(args.botA, args.botB, opponents, args.seeds, args.hands)
    r["wall_s"] = round(time.time() - t0, 1)

    if args.json:
        print(json.dumps(r, indent=2))
    else:
        _print_report(r)
        print(f"  wall time: {r['wall_s']}s")


if __name__ == "__main__":
    main()
