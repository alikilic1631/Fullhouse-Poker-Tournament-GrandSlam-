"""
a3_freq_probe.py (Phase 2) — does A3 (river-HU importance-sampled equity vs an
estimated villain range) have enough firing-rate leverage to justify building it?

Same discipline that correctly evaluated B2: probe BEFORE building. Instruments the
CURRENT submission (v13) and counts, per 400-hand match, river-HU facing-bet spots,
progressively filtered by A3's scope conditions. No behavioral change to the bot.

A3 scope (per spec, adapted to the stats v13 actually tracks):
  river HU facing a bet (hero not aggressor)
   -> opponent has >=30 observed actions (aggression AND bluff_propensity)
   -> bet size > 20% of pot
   -> pot > 1500 chips     (large-pot subset: pot > 3000)

Usage: python3 sandbox/a3_freq_probe.py bots/v13/bot.py --tables 40
"""
import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from engine.game import PokerEngine, STARTING_STACK
from sandbox.bench import _load_module, _warmup, _inject
from sandbox.field_sim import FIELD_DISTRIBUTION, sample_table

C = Counter()
POTS = []


def obs_count(hero, opp_id, stat):
    st = hero.OPPONENT_STATS.get(opp_id)
    if not st or stat not in st:
        return 0
    a, b = st[stat]
    return (a + b) - sum(hero.PRIORS[stat])


def probe_hero_state(hero, state):
    """Count A3-eligible spots; no behavioral effect."""
    if state.get("type") != "action_request":
        return
    if state.get("street") != "river":
        return
    if state.get("can_check") or state.get("amount_owed", 0) <= 0:
        return                                            # not facing a bet
    if hero._n_live_opponents(state) != 1:
        return                                            # HU only
    C["river_hu_facing_bet"] += 1
    opp_id = hero.relevant_opponent_id(state)
    if opp_id is None:
        return
    if obs_count(hero, opp_id, "aggression") >= 30 and \
       obs_count(hero, opp_id, "bluff_propensity") >= 30:
        C["with_obs"] += 1
    else:
        return
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    if owed <= 0.20 * max(pot, 1):
        return
    C["big_bet"] += 1
    if pot > 1500:
        C["large_pot"] += 1
        POTS.append(pot)
        if pot > 3000:
            C["xlarge_pot"] += 1


class _Probe:
    def __init__(self, hero):
        self.hero = hero

    def decide(self, state):
        probe_hero_state(self.hero, state)
        return self.hero.decide(state)


def run(hero, opponents, seed, n_hands):
    ids = ["hero"] + [f"o{i}" for i in range(len(opponents))]
    random.seed(seed); np.random.seed(seed % (2**32 - 1))
    mods = {"hero": _Probe(hero)}
    for i, o in enumerate(opponents):
        m = _load_module(o); _warmup(m, o); mods[f"o{i}"] = m
    stacks = {b: STARTING_STACK for b in ids}; mlog = []; dealer = 0
    for hn in range(n_hands):
        alive = [b for b in ids if stacks[b] > 0]
        if len(alive) < 2 or "hero" not in alive:
            break
        eng = PokerEngine(f"a3_{seed}_h{hn}", alive, dealer % len(alive),
                          {b: stacks[b] for b in alive}, seed=seed * 1000003 + hn)
        st = _inject(eng.start_hand(), mlog); steps = 0
        while st.get("type") == "action_request":
            seat = st["seat_to_act"]; bid = alive[seat]
            try:
                act = mods[bid].decide(st)
            except Exception:
                act = {"action": "fold"}
            mlog.append({"hand_num": hn, "seat": seat, "bot_id": bid,
                         "action": (act or {}).get("action"), "amount": (act or {}).get("amount")})
            st = _inject(eng.apply_action(seat, act or {"action": "fold"}), mlog); steps += 1
            if steps > 1000:
                break
        for b, v in (st.get("final_stacks") or {}).items():
            stacks[b] = v
        dealer += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("--tables", type=int, default=40)
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7000)
    args = ap.parse_args()
    hero = _load_module(args.hero); _warmup(hero, args.hero)
    for i in range(args.tables):
        # reset hero per match (mirror prod: fresh module state per match)
        hero.OPPONENT_STATS.clear()
        if hasattr(hero, "PROCESSED_HANDS"):
            hero.PROCESSED_HANDS.clear()
        rng = random.Random(args.seed + i)
        opps = sample_table(FIELD_DISTRIBUTION, 5, rng)
        run(hero, opps, args.seed + i, args.hands)
    t = args.tables
    print(f"\nA3 FIRING PROBE — {args.hero}  ({t} tables x {args.hands} hands)")
    print(f"  river HU facing bet            : {C['river_hu_facing_bet']}  ({C['river_hu_facing_bet']/t:.2f}/match)")
    print(f"   + opp >=30 obs                : {C['with_obs']}  ({C['with_obs']/t:.2f}/match)")
    print(f"   + bet > 20% pot               : {C['big_bet']}  ({C['big_bet']/t:.2f}/match)")
    print(f"   + pot > 1500 (A3-eligible)    : {C['large_pot']}  ({C['large_pot']/t:.2f}/match)")
    print(f"   + pot > 3000 (large-pot)      : {C['xlarge_pot']}  ({C['xlarge_pot']/t:.2f}/match)")
    if POTS:
        print(f"  A3-eligible pot sizes: min={min(POTS):.0f} median={np.median(POTS):.0f} max={max(POTS):.0f}")
    fires = C['large_pot'] / t
    large = C['xlarge_pot'] / t
    print(f"\n  DECISION: mean A3-eligible fires/match = {fires:.2f}, large-pot/match = {large:.2f}")
    if fires < 2:
        print("  -> DEFER A3 (insufficient firing rate). Skip Phase 3.")
    elif fires <= 5 and large < 1:
        print("  -> DEFER A3 (insufficient leverage). Skip Phase 3.")
    elif fires > 5 and large >= 2:
        print("  -> CONSIDER Phase 3 (firing rate + leverage clear).")
    else:
        print("  -> DEFER A3 (borderline; strong default = defer).")


if __name__ == "__main__":
    main()
