"""
field_analysis.py — D2 patch-window field profiler.

Reads hand-history records and profiles the opponent field so we can (a) re-tune
field_sim's FIELD_DISTRIBUTION and (b) pick a pre-built patch adjustment. Works on
the engine's hand-result schema (the reference); on D1 the portal JSON is mapped to
this schema by `normalize_record()` (one place to adjust once we see the real format).

Per opponent bot_id it computes: bet-size histogram (+ round-number 33/50/66/100%%
usage -> modal-LLM detector), VPIP, fold-to-bet, aggression factor. Outputs field
flags that drive the PATCH_WINDOW.md decision tree.

Usage:
  python3 analytics/field_analysis.py --selftest          # rehearse on synthetic data
  python3 analytics/field_analysis.py --input d1_hands.jsonl
"""
import argparse
import json
import sys
import random
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.game import PokerEngine, STARTING_STACK


def normalize_record(raw):
    """Map a raw hand-history record to our schema: a list of action dicts with
    keys {bot_id, action, amount, pot}. The engine result already provides this
    via its 'events' (type=='action'). ADAPT HERE for the real D1 portal JSON."""
    actions = []
    for e in raw.get("events", []):
        if e.get("type") == "action":
            actions.append({"bot_id": e.get("bot_id"), "action": e.get("action"),
                            "amount": e.get("amount", 0), "pot": e.get("pot", 0)})
    return actions


def analyze(records):
    by = defaultdict(lambda: {"bets": [], "fold": 0, "call": 0, "raise": 0,
                              "allin": 0, "check": 0, "round_bets": 0, "n_bets": 0})
    for rec in records:
        for a in normalize_record(rec):
            bid, act, amt, pot = a["bot_id"], a["action"], a["amount"] or 0, a["pot"] or 0
            if bid is None:
                continue
            s = by[bid]
            if act == "fold":
                s["fold"] += 1
            elif act == "call":
                s["call"] += 1
            elif act == "check":
                s["check"] += 1
            elif act in ("raise", "all_in"):
                s["raise" if act == "raise" else "allin"] += 1
                pot_before = max(pot - amt, 1)
                frac = amt / pot_before if pot_before > 0 else 0
                if 0 < frac < 4:
                    s["bets"].append(frac)
                    s["n_bets"] += 1
                    if any(abs(frac - r) < 0.06 for r in (0.33, 0.5, 0.66, 1.0)):
                        s["round_bets"] += 1
    out = {}
    for bid, s in by.items():
        faced = s["fold"] + s["call"]
        agg_acts = s["raise"] + s["allin"]
        out[bid] = {
            "fold_to_bet": round(s["fold"] / faced, 3) if faced else None,
            "aggression": round(agg_acts / max(agg_acts + s["call"] + s["check"], 1), 3),
            "shove_rate": round(s["allin"] / max(agg_acts + s["call"] + s["check"] + s["fold"], 1), 3),
            "round_bet_pct": round(s["round_bets"] / s["n_bets"], 3) if s["n_bets"] else None,
            "n_bets": s["n_bets"], "n_actions": faced + agg_acts + s["check"],
        }
    return out


def field_flags(profiles):
    vals = [p for p in profiles.values() if p["n_actions"] >= 20]
    if not vals:
        return {"note": "insufficient data"}
    rb = [p["round_bet_pct"] for p in vals if p["round_bet_pct"] is not None]
    return {
        "n_opponents_profiled": len(vals),
        "pct_using_round_sizing(>60%)": round(sum(1 for x in rb if x > 0.6) / max(len(rb), 1), 2),
        "mean_fold_to_bet": round(sum(p["fold_to_bet"] for p in vals if p["fold_to_bet"] is not None)
                                  / max(sum(1 for p in vals if p["fold_to_bet"] is not None), 1), 3),
        "mean_aggression": round(sum(p["aggression"] for p in vals) / len(vals), 3),
        "high_shove_share": round(sum(1 for p in vals if p["shove_rate"] > 0.08) / len(vals), 2),
    }


def generate_synthetic(n_hands=300):
    ROOT = Path(__file__).parent.parent
    specs = [("solver", "enemy_zoo/solver_approximator"),
             ("chartbot", "enemy_zoo/param_modal_llm_chartbot"),
             ("aggr3b", "enemy_zoo/aggressive_3bettor"),
             ("station", "enemy_zoo/loose_passive_call_station"),
             ("nit", "enemy_zoo/nit_preflop"),
             ("v13", "v13/bot")]
    import importlib.util
    modmap = {}
    for bid, rel in specs:
        p = str(ROOT / "bots" / (rel + ".py"))
        spec = importlib.util.spec_from_file_location(bid, p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        try:
            m.decide({"type": "warmup"})
        except Exception:
            pass
        modmap[bid] = m
    ids = [bid for bid, _ in specs]
    random.seed(7)
    stacks = {i: STARTING_STACK for i in ids}
    recs, dealer, mlog = [], 0, []
    for hn in range(n_hands):
        alive = [i for i in ids if stacks[i] > 0]
        if len(alive) < 2:
            break
        eng = PokerEngine(f"syn_h{hn:04d}", alive, dealer % len(alive),
                          {i: stacks[i] for i in alive}, seed=hn)
        st = eng.start_hand()
        if st.get("type") == "action_request":
            st["match_action_log"] = mlog[-200:]
        steps = 0
        while st.get("type") == "action_request" and steps < 500:
            seat = st["seat_to_act"]; bid = alive[seat]
            try:
                act = modmap[bid].decide(st)
            except Exception:
                act = {"action": "fold"}
            mlog.append({"hand_num": hn, "seat": seat, "bot_id": bid,
                         "action": act.get("action"), "amount": act.get("amount")})
            st = eng.apply_action(seat, act or {"action": "fold"})
            if st.get("type") == "action_request":
                st["match_action_log"] = mlog[-200:]
            steps += 1
        recs.append(st)          # hand_complete dict (has 'events')
        for b, v in st.get("final_stacks", {}).items():
            stacks[b] = v
        dealer += 1
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        recs = generate_synthetic(300)
        print(f"[selftest] generated {len(recs)} synthetic hands")
    else:
        recs = [json.loads(l) for l in open(args.input) if l.strip()]
        print(f"[input] read {len(recs)} hands from {args.input}")
    profiles = analyze(recs)
    print("\nPer-opponent profile:")
    for bid, p in sorted(profiles.items()):
        print(f"  {bid:34s} f2b={p['fold_to_bet']} agg={p['aggression']} "
              f"shove={p['shove_rate']} round_bet%={p['round_bet_pct']} (n={p['n_actions']})")
    print("\nField flags:", json.dumps(field_flags(profiles), indent=2))


if __name__ == "__main__":
    main()
