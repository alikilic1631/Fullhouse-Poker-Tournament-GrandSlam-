"""
precision_audit.py — instrumentation pass to FIRM UP the B2/A3 rejection rationale
with precise numbers (per the GPT critique). One-pass over the same 40 field-mix
tables x 400 hands; no behavioral change.

B2 audit (per hero preflop decision):
  - effective_bb = hero stack / BB
  - first-in flag (no prior preflop raises this hand)
  Reports distribution + counts at <20bb / <15bb / first-in<15bb.

A3 audit (per hero river HU facing-bet decision, bet>20%pot AND pot>1500):
  - For the relevant opponent at decision time, count
      cbet_obs   = #(prior hands where opp was preflop aggressor AND flop reached)
      bluff_obs  = v13's bluff_propensity observation count (alpha+beta - prior sum)
  Reports counts at relaxed (>=5 cbet) / mid (>=15 cbet) / strict (>=30 cbet AND
  >=30 bluff_obs) gates -> separates "rare spot" from "rare-due-to-strict-gate".

cbet_freq isn't tracked by v13, so the cbet_obs counter is BUILT here from the
hand events (the OPPORTUNITY count, irrespective of what v13 stores).

Usage: python3 sandbox/precision_audit.py bots/v13/bot.py --tables 40
"""
import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from engine.game import PokerEngine, STARTING_STACK, BIG_BLIND
from sandbox.bench import _load_module, _warmup, _inject
from sandbox.field_sim import FIELD_DISTRIBUTION, sample_table


# ---------------------------------------------------------------------------
# State
EFF_BBS = []           # hero preflop eff_bb at every hero preflop decision
PRE_CNT = Counter()    # B2 buckets
A3 = []                # list of (cbet_obs, bluff_obs, pot, owed_frac) per A3-spot
A3_TOTAL = Counter()   # A3 unfiltered counts


def _bluff_obs(hero, opp_id):
    st = hero.OPPONENT_STATS.get(opp_id)
    if not st or "bluff_propensity" not in st:
        return 0
    a, b = st["bluff_propensity"]
    return (a + b) - sum(hero.PRIORS["bluff_propensity"])


def _hero_stack(state):
    seat = state.get("seat_to_act")
    for pl in state.get("players", []) or []:
        if pl.get("seat") == seat:
            return pl.get("stack", STARTING_STACK)
    return state.get("your_stack", STARTING_STACK)


class _Probe:
    """Wraps hero.decide; also maintains per-opponent cbet-opportunity counts
    that we update at each hand boundary."""

    def __init__(self, hero):
        self.hero = hero
        self.cbet_obs = defaultdict(int)            # opp_id -> opportunity count

    def decide(self, state):
        if state.get("type") == "action_request":
            self._record(state)
        return self.hero.decide(state)

    def _record(self, state):
        # B2: hero preflop decisions
        cc = state.get("community_cards") or []
        if len(cc) == 0:
            eff_bb = _hero_stack(state) / (BIG_BLIND or 100)
            EFF_BBS.append(eff_bb)
            raises = sum(1 for e in (state.get("action_log") or [])
                         if e.get("action") in ("raise", "all_in"))
            first_in = raises == 0
            if eff_bb < 20:
                PRE_CNT["lt20"] += 1
            if eff_bb < 15:
                PRE_CNT["lt15"] += 1
                if first_in:
                    PRE_CNT["lt15_firstin"] += 1
            PRE_CNT["total"] += 1
            return

        # A3: river HU facing a bet
        if state.get("street") != "river":
            return
        if state.get("can_check") or state.get("amount_owed", 0) <= 0:
            return
        if self.hero._n_live_opponents(state) != 1:
            return
        pot = state.get("pot", 0); owed = state.get("amount_owed", 0)
        A3_TOTAL["river_hu_facing_bet"] += 1
        if owed <= 0.20 * max(pot, 1) or pot <= 1500:
            return
        A3_TOTAL["bet20_pot1500"] += 1
        opp_id = self.hero.relevant_opponent_id(state)
        if opp_id is None:
            return
        A3.append((self.cbet_obs.get(opp_id, 0), _bluff_obs(self.hero, opp_id),
                   pot, owed / max(pot, 1)))

    def post_hand(self, hand_result):
        """Update cbet-opportunity counts from completed-hand events.
        cbet opportunity = opponent was the preflop aggressor AND flop reached."""
        events = hand_result.get("events") or []
        # find preflop raisers (last is the PFR)
        pfr = None
        flop_reached = False
        for e in events:
            t = e.get("type")
            if t == "street_start" and e.get("street") in ("flop", "turn", "river"):
                flop_reached = True
            if t == "action" and e.get("street", "preflop") == "preflop" and \
               e.get("action") in ("raise", "all_in"):
                pfr = e.get("bot_id")
        if pfr is not None and pfr != "hero" and flop_reached:
            self.cbet_obs[pfr] += 1


def run(hero, opponents, seed, n_hands, probe):
    ids = ["hero"] + [f"o{i}" for i in range(len(opponents))]
    random.seed(seed); np.random.seed(seed % (2**32 - 1))
    mods = {"hero": probe}
    for i, o in enumerate(opponents):
        m = _load_module(o); _warmup(m, o); mods[f"o{i}"] = m
    stacks = {b: STARTING_STACK for b in ids}; mlog = []; dealer = 0
    for hn in range(n_hands):
        alive = [b for b in ids if stacks[b] > 0]
        if len(alive) < 2 or "hero" not in alive:
            break
        eng = PokerEngine(f"aud_{seed}_h{hn}", alive, dealer % len(alive),
                          {b: stacks[b] for b in alive}, seed=seed * 1000003 + hn)
        st = _inject(eng.start_hand(), mlog); steps = 0
        while st.get("type") == "action_request":
            seat = st["seat_to_act"]; bid = alive[seat]
            try:
                act = mods[bid].decide(st)
            except Exception:
                act = {"action": "fold"}
            mlog.append({"hand_num": hn, "seat": seat, "bot_id": bid,
                         "action": (act or {}).get("action"),
                         "amount": (act or {}).get("amount")})
            st = _inject(eng.apply_action(seat, act or {"action": "fold"}), mlog)
            steps += 1
            if steps > 1000:
                break
        probe.post_hand(st if isinstance(st, dict) else {})
        for b, v in (st.get("final_stacks") or {}).items():
            stacks[b] = v
        dealer += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("--tables", type=int, default=40)
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11000)
    args = ap.parse_args()
    hero = _load_module(args.hero); _warmup(hero, args.hero)
    for i in range(args.tables):
        # reset per-match (matches prod model: fresh subprocess per match)
        hero.OPPONENT_STATS.clear()
        if hasattr(hero, "PROCESSED_HANDS"):
            hero.PROCESSED_HANDS.clear()
        probe = _Probe(hero)
        rng = random.Random(args.seed + i)
        opps = sample_table(FIELD_DISTRIBUTION, 5, rng)
        run(hero, opps, args.seed + i, args.hands, probe)

    t = args.tables
    print(f"\nPRECISION AUDIT — {args.hero}  ({t} tables x {args.hands} hands)")
    print("\n=== B2 audit (hero preflop eff_bb distribution) ===")
    arr = np.array(EFF_BBS)
    print(f"  total hero preflop decisions   : {len(arr)}  ({len(arr)/t:.0f}/match)")
    if len(arr):
        for q in (1, 5, 25, 50, 95):
            print(f"    eff_bb p{q:>2}                  : {np.percentile(arr, q):.1f}")
        print(f"    min/max                       : {arr.min():.1f} / {arr.max():.1f}")
    pf = PRE_CNT.get("total", 1)
    print(f"  preflop <20bb                  : {PRE_CNT['lt20']}  ({100*PRE_CNT['lt20']/pf:.2f}%, {PRE_CNT['lt20']/t:.2f}/match)")
    print(f"  preflop <15bb (B2 trigger)     : {PRE_CNT['lt15']}  ({100*PRE_CNT['lt15']/pf:.2f}%, {PRE_CNT['lt15']/t:.2f}/match)")
    print(f"  preflop <15bb FIRST-IN (B2 fires) : {PRE_CNT['lt15_firstin']}  "
          f"({100*PRE_CNT['lt15_firstin']/pf:.3f}%, {PRE_CNT['lt15_firstin']/t:.3f}/match)")

    print("\n=== A3 audit (river HU facing-bet, by observation gate) ===")
    print(f"  river HU facing bet (total)         : {A3_TOTAL['river_hu_facing_bet']}  ({A3_TOTAL['river_hu_facing_bet']/t:.2f}/match)")
    print(f"  + bet>20%pot AND pot>1500 (spot)    : {A3_TOTAL['bet20_pot1500']}  ({A3_TOTAL['bet20_pot1500']/t:.2f}/match)")
    if A3:
        cbets = np.array([x[0] for x in A3])
        bluffs = np.array([x[1] for x in A3])
        for gate in (5, 15, 30):
            n = int((cbets >= gate).sum())
            print(f"   + cbet_obs >= {gate:>2}                  : {n}  ({n/t:.2f}/match)")
        strict = int(((cbets >= 30) & (bluffs >= 30)).sum())
        print(f"   + cbet_obs>=30 AND bluff_obs>=30 (STRICT A3 gate): {strict}  ({strict/t:.2f}/match)")
        print(f"  cbet_obs distribution at A3-eligible spots: "
              f"p5={np.percentile(cbets,5):.0f} p50={np.percentile(cbets,50):.0f} "
              f"p95={np.percentile(cbets,95):.0f} max={cbets.max()}")
        print(f"  bluff_obs distribution: p5={np.percentile(bluffs,5):.0f} "
              f"p50={np.percentile(bluffs,50):.0f} p95={np.percentile(bluffs,95):.0f} "
              f"max={bluffs.max()}")
    print("\nBottleneck diagnosis:")
    eligible = A3_TOTAL.get("bet20_pot1500", 0)
    if eligible == 0:
        print("  spot itself never occurs -> SPOT-frequency bottleneck.")
    else:
        cbets = np.array([x[0] for x in A3]) if A3 else np.array([])
        relaxed_5 = int((cbets >= 5).sum()) if len(cbets) else 0
        strict = int(((np.array([x[0] for x in A3]) >= 30) &
                      (np.array([x[1] for x in A3]) >= 30)).sum()) if A3 else 0
        ratio = strict / max(eligible, 1)
        print(f"  spot rate {eligible/t:.2f}/match; strict-gate yield {ratio:.0%} "
              f"of eligible spots; relaxed (cbet>=5) yield "
              f"{relaxed_5/max(eligible,1):.0%}.")
        if eligible / t < 1:
            print("  -> SPOT-frequency dominates (eligible spot itself <1/match).")
        elif ratio < 0.25:
            print("  -> OBSERVATION GATE dominates (spot common, but gate filters most).")
        else:
            print("  -> Spot AND gate both contribute meaningfully.")


if __name__ == "__main__":
    main()
