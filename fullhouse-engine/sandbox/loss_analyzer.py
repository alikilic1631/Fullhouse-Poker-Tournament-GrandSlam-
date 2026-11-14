"""
loss_analyzer.py — per-hand loss-by-spot analysis (Phase 1 failure-mode discovery).

Runs the bot under test (seat 0) vs an opponent set in-process, captures each
hand's rich result, and assigns the hand to ONE spot bucket from the hero's
perspective. Tracks NET chip delta + count per bucket: a bucket that's strongly
net-negative is a real leak (not just variance). Also runs the Patch 19i punt
audit. Reuses bench._load_module / _warmup.

Buckets:
  preflop_fold        hand ended preflop, hero folded (blind/limp surrender)
  preflop_allin       hand ended preflop with an all-in (3bet/4bet/jam spots)
  preflop_other       other preflop-ending hands
  multiway_pot        3+ players saw the flop, hero in postflop
  hu_aggressor        HU postflop, hero was the last aggressor (our bet/raise)
  hu_caller           HU postflop, hero was NOT the aggressor (we called/check-called)
For postflop showdown losses we also note street reached + biggest bet hero called.

Usage:
  python3 sandbox/loss_analyzer.py bots/v12/bot.py --opp enemy_zoo/solver_approximator --copies 5 --seeds 20
"""
import argparse
import sys
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import bench
from engine.game import PokerEngine, STARTING_STACK

ROOT = Path(__file__).parent.parent


def classify(hero_seat, result, start_stack, end_stack):
    delta = end_stack - start_stack
    events = result.get("events", []) or []
    board = result.get("community_cards", []) or []
    street_reached = len(board)  # 0 pf, 3 flop, 4 turn, 5 river
    showdown = result.get("showdown", False)

    # players who had NOT folded by the time the flop started
    folded_before_flop = set()
    saw_flop = None
    hero_actions = []
    last_aggressor = None
    hero_biggest_call = 0
    seen_flop_marker = False
    for e in events:
        et = e.get("type")
        if et == "street_start" and e.get("street") == "flop":
            seen_flop_marker = True
            saw_flop = [s for s in range(9) if s not in folded_before_flop]
        if et == "action":
            seat = e.get("seat"); act = e.get("action"); amt = e.get("amount", 0)
            if act == "fold" and not seen_flop_marker:
                folded_before_flop.add(seat)
            if act in ("raise", "all_in"):
                last_aggressor = seat
            if seat == hero_seat:
                hero_actions.append(act)
                if act == "call" and amt and amt > hero_biggest_call:
                    hero_biggest_call = amt

    # count players who saw the flop (= total minus folded-before-flop), approx
    n_players = len({e.get("seat") for e in events if e.get("type") in ("action", "blind")})
    n_saw_flop = max(n_players - len(folded_before_flop), 0)

    if street_reached == 0:
        if "all_in" in hero_actions or any(e.get("action") == "all_in" for e in events):
            bucket = "preflop_allin"
        elif hero_actions and hero_actions[-1] == "fold":
            bucket = "preflop_fold"
        else:
            bucket = "preflop_other"
    elif n_saw_flop >= 3:
        bucket = "multiway_pot"
    else:
        if last_aggressor == hero_seat:
            bucket = "hu_aggressor"
        else:
            bucket = "hu_caller"
    return bucket, delta, street_reached, showdown, hero_biggest_call


def run(hero_path, opp_paths, seeds, hands):
    ids = ["hero"] + [f"o{i}" for i in range(len(opp_paths))]
    paths = [hero_path] + list(opp_paths)
    net = defaultdict(float)
    cnt = defaultdict(int)
    loss_in = defaultdict(float)          # chips lost in losing hands per bucket
    street_pay = defaultdict(float)       # hu_caller showdown loss by street
    deltas_match = []
    punts = 0
    for s in range(seeds):
        mods = {bid: bench._load_module(p) for bid, p in zip(ids, paths)}
        for bid, p in zip(ids, paths):
            bench._warmup(mods[bid], p)
        random.seed(s); np.random.seed(s)
        stacks = {bid: STARTING_STACK for bid in ids}
        mlog, dealer = [], 0
        for hn in range(hands):
            alive = [bid for bid in ids if stacks[bid] > 0]
            if len(alive) < 2:
                break
            if "hero" not in alive:
                break
            start = {bid: stacks[bid] for bid in alive}
            eng = PokerEngine(f"an_{s}_h{hn:04d}", alive, dealer % len(alive), start,
                              seed=s * 1000003 + hn)
            hero_seat = alive.index("hero")
            st = eng.start_hand()
            if st.get("type") == "action_request":
                st["match_action_log"] = mlog[-200:]
            steps = 0
            result = None
            while st.get("type") == "action_request" and steps < 1000:
                seat = st["seat_to_act"]; bid = alive[seat]
                try:
                    act = mods[bid].decide(st)
                except Exception:
                    act = {"action": "fold"}
                mlog.append({"hand_num": hn, "seat": seat, "bot_id": bid,
                             "action": act.get("action"), "amount": act.get("amount")})
                st = eng.apply_action(seat, act or {"action": "fold"})
                if st.get("type") == "action_request":
                    st["match_action_log"] = mlog[-200:]
                steps += 1
            result = st
            new = result.get("final_stacks", {})
            for bid, v in new.items():
                stacks[bid] = v
            hd = stacks["hero"] - start["hero"]
            bucket, delta, street, sd, big = classify(hero_seat, result, start["hero"], stacks["hero"])
            net[bucket] += delta
            cnt[bucket] += 1
            if delta < 0:
                loss_in[bucket] += -delta
            if bucket == "hu_caller" and sd and delta < 0:
                street_pay[{3: "flop", 4: "turn", 5: "river"}.get(street, "pf")] += -delta
            dealer += 1
        deltas_match.append(stacks["hero"] - STARTING_STACK)
        if (stacks["hero"] - STARTING_STACK) < -7000:
            punts += 1
    return net, cnt, loss_in, street_pay, deltas_match, punts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hero")
    ap.add_argument("--opp", required=True, help="opponent path stem under bots/, e.g. enemy_zoo/solver_approximator")
    ap.add_argument("--copies", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--hands", type=int, default=400)
    args = ap.parse_args()
    opp = str(ROOT / "bots" / (args.opp + ".py"))
    net, cnt, loss_in, street_pay, dm, punts = run(args.hero, [opp] * args.copies, args.seeds, args.hands)
    label = f"{'HU' if args.copies==1 else str(args.copies+1)+'-bot'} vs {args.opp.split('/')[-1]}"
    print(f"\n=== {args.hero} | {label} | {args.seeds} seeds x {args.hands} hands ===")
    print(f"  match delta: median={np.median(dm):+.0f} mean={np.mean(dm):+.0f} punts(<-7000)={punts}/{args.seeds}")
    print(f"  {'bucket':16s} {'net':>10s} {'count':>6s} {'net/hand':>9s} {'lost_in_losers':>14s}")
    for b in sorted(net, key=lambda k: net[k]):
        print(f"  {b:16s} {net[b]:+10.0f} {cnt[b]:6d} {net[b]/max(cnt[b],1):+9.0f} {loss_in[b]:14.0f}")
    if street_pay:
        print("  hu_caller showdown losses by street:", {k: int(v) for k, v in street_pay.items()})


if __name__ == "__main__":
    main()
