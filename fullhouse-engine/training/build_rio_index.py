"""
build_rio_index.py (v15.6) — Reverse-Implied-Odds index.

For each (hand_strength, board_texture, street, SPR, [rio_score|cap_adj|buf_adj])
cell, computes the fraction of villain's plausible continuing range that
DOMINATES us (villain score > hero score by > MARGIN). Feeds upstream of
nut_danger_score as an additive amplifier; high RIO -> governor more likely
to veto stack-off -> Patch K's commit gate doesn't fire.

Speedup: rio_score depends only on (texture, strength, street). SPR is applied
as a multiplier at lookup time (deeper SPR -> RIO matters more). So we compute
12*10*3 = 360 unique cells and replicate across the 5 SPR buckets.

Output: submission/data/rio_index.npz  (~108 KB).
Usage: python3 training/build_rio_index.py
"""
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import eval7

RANKS = "23456789TJQKA"
SUITS = "shdc"
RV = {r: i for i, r in enumerate(RANKS)}
FULL_DECK = [r + s for r in RANKS for s in SUITS]
CARDS = {c: eval7.Card(c) for c in FULL_DECK}

# Buckets must match v15.5 exactly (lookup keys at runtime).
HAND_STRENGTHS = [
    "full_house_or_better", "flush", "straight", "set_or_trips", "two_pair",
    "overpair", "strong_top_pair", "weak_top_pair", "second_pair",
    "third_pair_or_underpair", "weak_showdown", "air",
]
BOARD_TEXTURES = [
    "draw_completed", "monotone", "paired", "broadway_connected",
    "low_connected", "connected", "two_tone", "A_high_dry",
    "K_high_dry", "disconnected_low",
]
STREETS = ["flop", "turn", "river"]  # 3 / 4 / 5 cards
SPR_BUCKETS = ["<1", "1-3", "3-6", "6-10", ">=10"]      # 5
HS_IDX = {h: i for i, h in enumerate(HAND_STRENGTHS)}
TEX_IDX = {t: i for i, t in enumerate(BOARD_TEXTURES)}
ST_IDX = {s: i for i, s in enumerate(STREETS)}

DOMINATION_MARGIN = 1000   # eval7 score margin: villain - hero > this -> dominated
TOP_CONTINUING_FRAC = 0.33 # villain continues with top 33% of hands by current strength

# Replicated shape from spec.
TABLE_SHAPE = (12, 50, 3, 5, 3)


# Bucket helpers — replicas of v15.5 logic, kept inline so this script is
# self-contained and the buckets match at runtime by string -> index mapping.
def _vals(board):
    return [RV[c[0]] for c in board]


def _has_straight(vset):
    if not vset:
        return False
    sv = sorted(vset)
    for i in range(len(sv) - 4):
        if sv[i + 4] - sv[i] == 4:
            return True
    if {12, 0, 1, 2, 3}.issubset(vset):
        return True
    return False


def board_texture_bucket(board):
    if not board:
        return "disconnected_low"
    vals = _vals(board)
    distinct = sorted(set(vals))
    top = max(vals)
    suit_counts = {}
    for c in board:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    maxsuit = max(suit_counts.values())
    has_pair = len(vals) != len(set(vals))
    if len(board) >= 4 and _has_straight(set(vals)):
        return "draw_completed"
    if maxsuit >= 3:
        return "monotone"
    if has_pair:
        return "paired"
    span = max(distinct) - min(distinct) if len(distinct) > 1 else 0
    connected = span <= 4 and len(distinct) >= 3
    allbroadway = all(v >= RV["T"] for v in vals)
    if allbroadway and connected:
        return "broadway_connected"
    if connected and top <= RV["9"]:
        return "low_connected"
    if connected:
        return "connected"
    if maxsuit == 2:
        return "two_tone"
    if top == RV["A"]:
        return "A_high_dry"
    if top == RV["K"]:
        return "K_high_dry"
    return "disconnected_low"


def hand_strength_bucket(hole, board):
    score = eval7.evaluate([CARDS[c] for c in list(hole) + list(board)])
    ht = str(eval7.handtype(score))
    if ht in ("Full House", "Quads", "Straight Flush"):
        return "full_house_or_better"
    if ht == "Flush":
        return "flush"
    if ht == "Straight":
        return "straight"
    if ht == "Trips":
        return "set_or_trips"
    if ht == "Two Pair":
        return "two_pair"
    if ht == "Pair":
        board_vals = sorted(set(_vals(board)), reverse=True)
        h0, h1 = hole[0][0], hole[1][0]
        v0, v1 = RV[h0], RV[h1]
        top = board_vals[0]
        if h0 == h1:
            return "overpair" if v0 > top else "third_pair_or_underpair"
        paired_val = v0 if v0 in _vals(board) else (v1 if v1 in _vals(board) else None)
        kicker_val = v1 if paired_val == v0 else v0
        if paired_val is None:
            return "weak_showdown"
        rank_idx = board_vals.index(paired_val) if paired_val in board_vals else 99
        if rank_idx == 0:
            return "strong_top_pair" if kicker_val >= RV["T"] else "weak_top_pair"
        if rank_idx == 1:
            return "second_pair"
        return "third_pair_or_underpair"
    board_top = max(_vals(board))
    overcards = sum(1 for c in hole if RV[c[0]] > board_top)
    if overcards >= 2 or any(c[0] == "A" for c in hole):
        return "weak_showdown"
    return "air"


def synth_hole_board(target_tex, target_hs, street_size, rng, max_tries=2000):
    """Rejection-sample (hole, board) matching (texture, strength)."""
    for _ in range(max_tries):
        sample = rng.sample(FULL_DECK, street_size + 2)
        board = sample[:street_size]
        hole = sample[street_size:street_size + 2]
        if board_texture_bucket(board) != target_tex:
            continue
        if hand_strength_bucket(hole, board) != target_hs:
            continue
        return hole, board
    return None, None


def rio_score_cell(hole, board, rng):
    """Compute rio_score for ONE concrete (hole, board)."""
    dead = set(hole) | set(board)
    candidates = [c for c in FULL_DECK if c not in dead]
    n_cand = len(candidates)
    # Enumerate all villain 2-card combos
    villain_combos = []
    for i in range(n_cand):
        for j in range(i + 1, n_cand):
            villain_combos.append((candidates[i], candidates[j]))
    # Score each on this board
    board_cards = [CARDS[c] for c in board]
    hero_score = eval7.evaluate([CARDS[c] for c in hole] + board_cards)
    scored = []
    for vh in villain_combos:
        vs = eval7.evaluate([CARDS[vh[0]], CARDS[vh[1]]] + board_cards)
        scored.append((vs, vh))
    if not scored:
        return 0.0
    # Continuing range = top 33% by strength
    scored.sort(key=lambda x: -x[0])
    cut = max(1, int(len(scored) * TOP_CONTINUING_FRAC))
    continuing = scored[:cut]
    # Fraction dominated
    dominated = sum(1 for vs, _ in continuing if vs - hero_score > DOMINATION_MARGIN)
    return dominated / len(continuing)


# SPR multiplier: deeper SPR -> RIO matters more (more chips at risk).
SPR_MULTIPLIER = np.array([0.7, 0.85, 1.0, 1.15, 1.30], dtype=np.float32)


def main():
    out_dir = Path(__file__).resolve().parent.parent.parent / "submission" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "rio_index.npz"
    rng = random.Random(20260606)

    rio = np.zeros(TABLE_SHAPE, dtype=np.float32)
    filled = np.zeros((12, 50, 3), dtype=np.int8)

    n_unique = 12 * 10 * 3              # 360 unique compute cells
    done = 0
    t0 = time.time()
    # Per cell, average rio_score over up to N_SAMPLES distinct (hole, board)
    # synths. One sample is too noisy (card-specific). N_SAMPLES=30 typically
    # gets us SE ~ sqrt(p*(1-p)/30) ~ 0.09pp on rio_score, plenty stable.
    N_SAMPLES = 30
    MIN_SAMPLES_TO_FILL = 5
    print(f"[rio] computing {n_unique} unique cells, "
          f"averaging up to {N_SAMPLES} samples/cell for stability...")
    for hs in HAND_STRENGTHS:
        for tex in BOARD_TEXTURES:
            for street in STREETS:
                street_size = {"flop": 3, "turn": 4, "river": 5}[street]
                hs_i, tex_i, st_i = HS_IDX[hs], TEX_IDX[tex], ST_IDX[street]
                done += 1
                rio_samples = []
                used_combos = set()
                for _ in range(N_SAMPLES):
                    hole, board = synth_hole_board(tex, hs, street_size, rng,
                                                    max_tries=4000)
                    if hole is None:
                        break  # cell unsynthesizable
                    key = (tuple(hole), tuple(board))
                    if key in used_combos:
                        continue
                    used_combos.add(key)
                    rio_samples.append(rio_score_cell(hole, board, rng))
                if len(rio_samples) < MIN_SAMPLES_TO_FILL:
                    continue
                rs = float(np.mean(rio_samples))
                cap_adj = -0.05 if rs > 0.5 else 0.0
                buf_adj = +0.03 if rs > 0.3 else 0.0
                for spr_i in range(5):
                    mult = float(SPR_MULTIPLIER[spr_i])
                    rio[hs_i, tex_i, st_i, spr_i, 0] = rs * mult
                    rio[hs_i, tex_i, st_i, spr_i, 1] = cap_adj
                    rio[hs_i, tex_i, st_i, spr_i, 2] = buf_adj
                filled[hs_i, tex_i, st_i] = len(rio_samples)
                if done % 40 == 0:
                    dt = time.time() - t0
                    print(f"  {done}/{n_unique} cells  ({dt:.1f}s elapsed)")
    dt = time.time() - t0
    print(f"[rio] done in {dt:.1f}s; filled {int(filled.sum())}/{12*10*3} "
          f"(texture x strength x street) cells")

    # Quick spot-checks
    print("\n[spot checks]")
    pairs = [
        ("weak_top_pair", "paired", "river", 2),
        ("two_pair", "paired", "river", 2),
        ("set_or_trips", "paired", "turn", 2),
        ("flush", "monotone", "river", 2),
        ("air", "K_high_dry", "flop", 2),
        ("overpair", "low_connected", "turn", 2),
    ]
    for hs, tex, st, spr_i in pairs:
        v = rio[HS_IDX[hs], TEX_IDX[tex], ST_IDX[st], spr_i, 0]
        print(f"  rio({hs:<22s}, {tex:<22s}, {st:<5s}, spr_i={spr_i}) = {v:.3f}")

    np.savez_compressed(out_path, rio_index=rio, filled=filled,
                         hand_strengths=np.array(HAND_STRENGTHS, dtype="U24"),
                         board_textures=np.array(BOARD_TEXTURES, dtype="U24"),
                         streets=np.array(STREETS, dtype="U6"),
                         spr_buckets=np.array(SPR_BUCKETS, dtype="U6"))
    print(f"\nSaved {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
