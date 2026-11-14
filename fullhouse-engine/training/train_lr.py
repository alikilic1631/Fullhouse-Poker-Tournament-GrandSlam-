"""
Offline LR fold-predictor trainer (Patch 8 + 17f/17g context).

Generates (features, opponent_folded) data from in-process matches that MIX
~30% uniform_betting_trainer data (randomized bet sizes -> breaks the
selection-bias confound, Patch 17f) with ~70% selective enemy-zoo data, trains
a sklearn LogisticRegression, and EXTRACTS the coefficients + standardizer to a
pure-numpy .npz. sklearn is used ONLY here, offline. The submitted bot.py loads
the .npz and does inference with numpy (no sklearn import — Patch 8).

Feature vector (kept identical in bots/v10/bot.py::lr_features):
  [0] bet_size_frac (bet / pot_before, capped 3.0)
  [1] is_flop  [2] is_turn  [3] is_river
  [4] paired  [5] monotone  [6] two_tone  [7] connected  [8] a_high  [9] k_high
  [10] spr (capped 10)/10   [11] n_opp/5
  [12] bet_size_frac * is_river        (cross)
  [13] bet_size_frac * wetness         (cross; wetness = paired+monotone+two_tone+connected)

Usage:
  python3 training/train_lr.py --hands 250 --tables 60
"""
import argparse
import os
import sys
import random
import importlib.util
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from engine.game import PokerEngine, STARTING_STACK  # noqa: E402

RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA")}


def board_flags(board):
    if len(board) < 3:
        return [0.0] * 6
    suits = [c[1] for c in board]
    vals = sorted(set(RANK_VAL[c[0]] for c in board))
    sc = {}
    for s in suits:
        sc[s] = sc.get(s, 0) + 1
    maxsuit = max(sc.values())
    paired = 1.0 if len(set(c[0] for c in board)) < len(board) else 0.0
    monotone = 1.0 if maxsuit >= 3 else 0.0
    two_tone = 1.0 if maxsuit == 2 else 0.0
    span = (max(vals) - min(vals)) if len(vals) > 1 else 99
    connected = 1.0 if (span <= 4 and len(vals) >= 3) else 0.0
    top = max(RANK_VAL[c[0]] for c in board)
    a_high = 1.0 if top == RANK_VAL['A'] else 0.0
    k_high = 1.0 if top == RANK_VAL['K'] else 0.0
    return [paired, monotone, two_tone, connected, a_high, k_high]


def lr_features(bet_frac, street, board, spr, n_opp, opp_fold):
    """16 features. opp_fold = the opponent's general fold-to-bet rate (17b-lite),
    giving the model opponent-specificity (the key exploit lever)."""
    bf = min(max(bet_frac, 0.0), 3.0)
    is_flop = 1.0 if street == "flop" else 0.0
    is_turn = 1.0 if street == "turn" else 0.0
    is_river = 1.0 if street == "river" else 0.0
    flags = board_flags(board)
    wetness = flags[0] + flags[1] + flags[2] + flags[3]
    return [
        bf, is_flop, is_turn, is_river,
        flags[0], flags[1], flags[2], flags[3], flags[4], flags[5],
        min(spr, 10.0) / 10.0, min(n_opp, 5) / 5.0,
        bf * is_river, bf * wetness,
        opp_fold,                       # [14] opponent foldiness (17b-lite)
        bf * opp_fold,                  # [15] cross: size x foldiness (17d)
    ]


def load_bot(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def collect(hands, tables):
    """Run mixed 6-bot tables; record (features, folded) for postflop faced-bet
    decisions. ~1/3 of seats are the uniform trainer for causal size data."""
    zoo = ["solver_approximator", "mixed_strategy_pluribus_caricature", "aggressive_3bettor",
           "tight_value_only", "loose_passive_call_station", "polarized_bettor",
           "nit_preflop", "fit_or_fold", "overbet_river_bluffer", "weird_sizing"]
    paths = {f"z_{z}": str(ROOT / "bots" / "enemy_zoo" / f"{z}.py") for z in zoo}
    paths["utrain1"] = str(ROOT / "bots" / "training_only" / "uniform_betting_trainer.py")
    paths["utrain2"] = str(ROOT / "bots" / "training_only" / "uniform_betting_trainer.py")
    paths["shark"] = str(ROOT / "bots" / "shark" / "bot.py")

    X, y = [], []
    fold_stats = {}   # bot_base_name -> [folds, calls] running across all tables (population foldiness)

    def opp_fold_rate(base):
        f, c = fold_stats.get(base, (2.0, 3.0))   # prior ~0.40
        return f / (f + c)

    for t in range(tables):
        rng = random.Random(10_000 + t)
        # 6 seats: 2 uniform trainers + 4 random zoo/ref -> ~33% uniform bet data
        seats = ["utrain1", "utrain2"] + rng.sample([k for k in paths if not k.startswith("utrain")], 4)
        mods = {bid: load_bot(paths[bid], f"{bid}_{t}") for bid in set(seats)}
        for m in mods.values():
            try:
                m.decide({"type": "warmup"})
            except Exception:
                pass
        seat_ids = [f"{s}#{i}" for i, s in enumerate(seats)]
        seat_mod = {seat_ids[i]: mods[seats[i]] for i in range(len(seats))}
        stacks = {sid: STARTING_STACK for sid in seat_ids}
        dealer = 0
        for hn in range(hands):
            alive = [sid for sid in seat_ids if stacks[sid] > 0]
            if len(alive) < 2:
                break
            eng = PokerEngine(f"tr_{t}_h{hn:04d}", alive, dealer % len(alive),
                              {sid: stacks[sid] for sid in alive}, seed=10_000 * t + hn)
            state = eng.start_hand()
            steps = 0
            while state.get("type") == "action_request" and steps < 400:
                seat = state["seat_to_act"]
                sid = alive[seat]
                street = state["street"]
                owed = state["amount_owed"]
                pot = state["pot"]
                # postflop faced-bet decision -> a (features, fold?) sample
                base = sid.split("#")[0]
                rec = None
                if street in ("flop", "turn", "river") and owed > 0 and not state["can_check"]:
                    pot_before = max(pot - owed, 1)
                    bet_frac = owed / pot_before
                    spr = state["your_stack"] / max(pot, 1)
                    n_opp = sum(1 for p in state["players"]
                                if not p["is_folded"] and p["state"] != "busted") - 1
                    rec = lr_features(bet_frac, street, state["community_cards"], spr,
                                      max(n_opp, 1), opp_fold_rate(base))
                try:
                    action = seat_mod[sid].decide(state)
                except Exception:
                    action = {"action": "fold"}
                act = action.get("action")
                # update running foldiness for this bot type (fold vs call when facing a bet)
                if not state["can_check"] and owed > 0:
                    fc = fold_stats.setdefault(base, [2.0, 3.0])
                    if act == "fold":
                        fc[0] += 1
                    elif act == "call":
                        fc[1] += 1
                if rec is not None:
                    X.append(rec)
                    y.append(1 if act == "fold" else 0)
                state = eng.apply_action(seat, action)
                steps += 1
            for p in eng.players:
                stacks[p.bot_id] = p.stack
            dealer += 1
    return np.array(X, dtype=np.float64), np.array(y, dtype=np.int32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=250)
    ap.add_argument("--tables", type=int, default=60)
    args = ap.parse_args()

    print(f"Generating data ({args.tables} tables x {args.hands} hands)...")
    X, y = collect(args.hands, args.tables)
    print(f"  collected {len(y)} faced-bet samples; fold rate = {y.mean():.3f}")

    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    # NO class_weight balancing: we need CALIBRATED fold probabilities for the EV
    # formula (balanced weights inflate P(fold) and bias us toward over-betting).
    clf = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000)
    clf.fit(Xs, y)
    acc = clf.score(Xs, y)
    pred_mean = clf.predict_proba(Xs)[:, 1].mean()
    print(f"  train accuracy = {acc:.3f}  mean P(fold) = {pred_mean:.3f} (true {y.mean():.3f})  "
          f"coef shape {clf.coef_.shape}")

    out_dir = ROOT / "bots" / "v10" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_dir / "lr_fold_predictor.npz",
        coef=clf.coef_[0].astype(np.float32),
        intercept=np.float32(clf.intercept_[0]),
        mean=scaler.mean_.astype(np.float32),
        scale=scaler.scale_.astype(np.float32),
    )
    print(f"  saved -> {out_dir / 'lr_fold_predictor.npz'}")


if __name__ == "__main__":
    main()
