"""
pushfold_freq_probe.py — how often does the short-stack (<=15bb) push/fold
branch actually fire for the hero, under a realistic field?

Fixed blinds (SB50/BB100, no escalation, 100bb start) mean push/fold territory
is only reached after big losses. This measures the realized frequency to size
the ceiling of any push/fold (B2) improvement BEFORE building it.

Counts, per hero preflop decision:
  - total preflop decisions
  - short-stack (eff_bb <= 15) preflop decisions  [the JAM_FIRST_IN / HU jam branch]
  - facing-all-in preflop decisions               [the equity-call branch]
  - heads-up (n==2) short-stack decisions

Usage: python3 sandbox/pushfold_freq_probe.py bots/v13/bot.py --tables 40
"""
import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from engine.game import PokerEngine, STARTING_STACK, BIG_BLIND
from sandbox.bench import _load_module, _warmup, _inject
from sandbox.field_sim import FIELD_DISTRIBUTION, sample_table

C = Counter()


def _is_preflop(state):
    return (state.get("street") in (None, "preflop")) and not state.get("community_cards")


def probe_decide(real_decide, state):
    if state.get("type") == "action_request" and _is_preflop_state(state):
        C["preflop"] += 1
        stack = _hero_stack(state)
        bb = BIG_BLIND
        eff_bb = stack / bb if bb else 100
        n = len(state.get("players", []) or [])
        facing_allin = any(
            pl.get("is_all_in") and pl.get("seat") != state.get("seat_to_act")
            for pl in (state.get("players") or [])
        ) and state.get("amount_owed", 0) > 0
        if facing_allin:
            C["facing_allin"] += 1
        if eff_bb <= 15:
            C["shortstack"] += 1
            if n == 2:
                C["shortstack_hu"] += 1
    return real_decide(state)


def _is_preflop_state(state):
    cc = state.get("community_cards") or state.get("board") or []
    return len(cc) == 0


def _hero_stack(state):
    seat = state.get("seat_to_act")
    for pl in state.get("players", []) or []:
        if pl.get("seat") == seat:
            return pl.get("stack", STARTING_STACK)
    return state.get("your_stack", STARTING_STACK)


def run(hero_path, opponents, seed, n_hands, hero_mod):
    paths = [hero_path] + list(opponents)
    bot_ids = ["hero"] + [f"opp_{i}" for i in range(len(opponents))]
    random.seed(seed); np.random.seed(seed % (2**32 - 1))
    modules = {bid: (hero_mod if bid == "hero" else _load_module(p))
               for bid, p in zip(bot_ids, paths)}
    for bid, m in modules.items():
        _warmup(m, paths[bot_ids.index(bid)])
    real = hero_mod.decide
    modules["hero"] = _Wrap(real)
    stacks = {bid: STARTING_STACK for bid in bot_ids}
    match_log, dealer = [], 0
    for hand_num in range(n_hands):
        alive = [bid for bid in bot_ids if stacks[bid] > 0]
        if len(alive) < 2:
            break
        eng = PokerEngine(f"probe_{seed}_h{hand_num}", alive, dealer % len(alive),
                          {bid: stacks[bid] for bid in alive}, seed=seed * 1000003 + hand_num)
        state = _inject(eng.start_hand(), match_log)
        steps = 0
        while state.get("type") == "action_request":
            seat = state["seat_to_act"]; bid = alive[seat]
            try:
                action = modules[bid].decide(state)
            except Exception:
                action = {"action": "fold"}
            match_log.append({"hand_num": hand_num, "seat": seat, "bot_id": bid,
                              "action": (action or {}).get("action"),
                              "amount": (action or {}).get("amount")})
            state = _inject(eng.apply_action(seat, action or {"action": "fold"}), match_log)
            steps += 1
            if steps > 1000:
                break
        for b, v in eng_final(state).items():
            stacks[b] = v
        dealer += 1


class _Wrap:
    def __init__(self, real):
        self.real = real

    def decide(self, state):
        return probe_decide(self.real, state)


def eng_final(state):
    return state.get("final_stacks", {}) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("--tables", type=int, default=40)
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--seed", type=int, default=5000)
    args = ap.parse_args()
    hero_mod = _load_module(args.hero)
    _warmup(hero_mod, args.hero)
    for i in range(args.tables):
        rng = random.Random(args.seed + i)
        opps = sample_table(FIELD_DISTRIBUTION, 5, rng)
        run(args.hero, opps, args.seed + i, args.hands, hero_mod)
    pf = C["preflop"] or 1
    print(f"\nPUSH/FOLD FREQUENCY PROBE — {args.hero}  ({args.tables} tables x {args.hands} hands)")
    print(f"  total hero preflop decisions : {C['preflop']}")
    print(f"  short-stack (<=15bb)         : {C['shortstack']}  ({100*C['shortstack']/pf:.2f}%)")
    print(f"    of which heads-up          : {C['shortstack_hu']}")
    print(f"  facing preflop all-in        : {C['facing_allin']}  ({100*C['facing_allin']/pf:.2f}%)")


if __name__ == "__main__":
    main()
