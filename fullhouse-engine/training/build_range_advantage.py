"""
build_range_advantage.py (v15.8) — range/nut advantage table.

For each (preflop_bucket, board_texture, hero_position) cell, computes:
  [0] hero_eq_vs_villain_range: hero's mean equity vs villain's calling range
                                 on a representative board of the texture
  [1] hero_nut_share: hero's range fraction with top-10% strength on board
                       MINUS villain's fraction
  [2] aggression_multiplier: derived from (hero_eq, nut_share) per spec table

Preflop bucket = (pos_group 0..3, action_pattern 0..3). 16 buckets.
  pos_group: 0=EP, 1=MP, 2=LP, 3=Blinds
  action_pattern: 0=open-called, 1=open-3bet-called, 2=cold-called, 3=limped

Output: submission/data/range_advantage.npz (~60 KB).
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

BOARD_TEXTURES = [
    "draw_completed", "monotone", "paired", "broadway_connected",
    "low_connected", "connected", "two_tone", "A_high_dry",
    "K_high_dry", "disconnected_low",
]
TEX_IDX = {t: i for i, t in enumerate(BOARD_TEXTURES)}
POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]   # 6
POS_GROUPS = {"UTG": 0, "HJ": 0, "CO": 1, "BTN": 2, "SB": 3, "BB": 3}
ACTION_PATTERNS = ["open_called", "open_3bet_called", "cold_called", "limped"]

# Range definitions per (pos_group, action_pattern).
# Format: list of hand-class strings (e.g., "AKs", "QQ", "T9o").
# Built from canonical poker preflop charts — conservative, position-aware.

def _all_pairs():
    return [r + r for r in RANKS]

def _suited(top_pct_top_high):
    # Suited combos by simple ranking: high+low+s
    out = []
    for i in range(13):
        for j in range(i):
            hi = RANKS[12 - j]; lo = RANKS[12 - i]
            out.append(hi + lo + "s")
    return out  # 78 suited

def _offsuit():
    out = []
    for i in range(13):
        for j in range(i):
            hi = RANKS[12 - j]; lo = RANKS[12 - i]
            out.append(hi + lo + "o")
    return out  # 78 offsuit


# Strength-ordered list of all 169 (broad heuristic ranking)
def _hand_score(cls):
    if len(cls) == 2:                 # pair
        return 140 + RV[cls[0]] * 10
    hi, lo, t = cls[0], cls[1], cls[2]
    s = RV[hi] * 5 + RV[lo] * 3
    gap = RV[hi] - RV[lo]
    if gap == 1: s += 6
    elif gap == 2: s += 3
    if t == "s": s += 8
    return s


HAND_RANK_ORDER = sorted([r + r for r in RANKS] + _suited([]) + _offsuit(),
                          key=lambda c: -_hand_score(c))
N_HANDS = len(HAND_RANK_ORDER)
assert N_HANDS == 169


def top_frac(frac):
    k = max(1, min(N_HANDS, int(round(N_HANDS * frac))))
    return HAND_RANK_ORDER[:k]


# Range widths per (pos_group, action_pattern). Hand-authored estimates.
HERO_RANGE_PCT = {
    # (pos_group, pattern): fraction
    (0, 0): 0.13,   # EP open-called: tight raise range
    (0, 1): 0.06,   # EP open-3bet-called: very tight (KK+, AK)
    (0, 2): 0.10,   # EP cold-called: rare, mostly pairs+broadways
    (0, 3): 0.20,   # EP limped: weak limpers, wider weak holdings

    (1, 0): 0.20,   # MP open-called
    (1, 1): 0.08,
    (1, 2): 0.15,
    (1, 3): 0.25,

    (2, 0): 0.30,   # LP (BTN) open-called: wider open range
    (2, 1): 0.10,
    (2, 2): 0.22,
    (2, 3): 0.35,   # BTN over-limp / iso

    (3, 0): 0.18,   # Blinds open-called (SB raised, BB called)
    (3, 1): 0.07,
    (3, 2): 0.25,   # BB defending wide vs late open
    (3, 3): 0.30,   # BB option after limps
}
# Villain ranges per same cells (villain = the caller / continuing player).
VILL_RANGE_PCT = {
    (0, 0): 0.18,   # vs EP open: villain calls top 18% (BB defend tight)
    (0, 1): 0.04,   # vs EP 4bet continue: QQ+/AK very tight
    (0, 2): 0.18,
    (0, 3): 0.30,

    (1, 0): 0.25,   # vs MP open
    (1, 1): 0.05,
    (1, 2): 0.22,
    (1, 3): 0.32,

    (2, 0): 0.35,   # vs LP open: defenders go wider
    (2, 1): 0.07,
    (2, 2): 0.28,
    (2, 3): 0.40,

    (3, 0): 0.25,   # vs blind raise: caller's range
    (3, 1): 0.05,
    (3, 2): 0.30,
    (3, 3): 0.35,
}


def class_combos(cls):
    if len(cls) == 2:                          # pair
        r = cls[0]
        return [(r + a, r + b) for i, a in enumerate(SUITS) for j, b in enumerate(SUITS) if i < j]
    hi, lo, t = cls[0], cls[1], cls[2]
    if t == "s":
        return [(hi + s, lo + s) for s in SUITS]
    return [(hi + a, lo + b) for a in SUITS for b in SUITS if a != b]


def range_combos(range_classes):
    out = []
    for cls in range_classes:
        out.extend(class_combos(cls))
    return out


def _vals(board):
    return [RV[c[0]] for c in board]


def _has_straight(vset):
    if not vset: return False
    sv = sorted(vset)
    for i in range(len(sv) - 4):
        if sv[i + 4] - sv[i] == 4: return True
    if {12, 0, 1, 2, 3}.issubset(vset): return True
    return False


def board_texture_bucket(board):
    if not board: return "disconnected_low"
    vals = _vals(board)
    distinct = sorted(set(vals))
    top = max(vals)
    sc = {}
    for c in board: sc[c[1]] = sc.get(c[1], 0) + 1
    maxsuit = max(sc.values())
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


def synth_board(target_tex, n_cards=5, rng=None, max_tries=200000):
    rng = rng or random.Random()
    for _ in range(max_tries):
        bd = rng.sample(FULL_DECK, n_cards)
        if board_texture_bucket(bd) == target_tex:
            return bd
    return None


def hand_strength_on_board(hole, board):
    """Return eval7 score (higher = stronger)."""
    return eval7.evaluate([CARDS[c] for c in list(hole) + list(board)])


def cell_eq_and_nut(pg, pattern, position, board, n_samples=300, rng=None):
    """Compute hero_eq, hero_nut_share for one cell."""
    rng = rng or random.Random()
    hero_r = top_frac(HERO_RANGE_PCT[(pg, pattern)])
    vill_r = top_frac(VILL_RANGE_PCT[(pg, pattern)])
    hero_combos = range_combos(hero_r)
    vill_combos = range_combos(vill_r)
    if not hero_combos or not vill_combos:
        return 0.5, 0.0
    # Equity via MC
    wins = ties = total = 0
    bd_set = set(board)
    board_cards = [CARDS[c] for c in board]
    for _ in range(n_samples):
        for _retry in range(8):
            hh = rng.choice(hero_combos)
            if hh[0] in bd_set or hh[1] in bd_set:
                continue
            vh = rng.choice(vill_combos)
            if vh[0] in bd_set or vh[1] in bd_set: continue
            if vh[0] in hh or vh[1] in hh: continue
            break
        else:
            continue
        hs = eval7.evaluate([CARDS[c] for c in hh] + board_cards)
        vs = eval7.evaluate([CARDS[c] for c in vh] + board_cards)
        if hs > vs: wins += 1
        elif hs < vs: pass
        else: ties += 1
        total += 1
    hero_eq = (wins + 0.5 * ties) / max(total, 1)

    # Nut share: fraction of each range with eval7 score in top-10% of all
    # legal combos on this board.
    def _score_range(combos):
        scores = []
        for h in combos:
            if h[0] in bd_set or h[1] in bd_set: continue
            scores.append(eval7.evaluate([CARDS[c] for c in h] + board_cards))
        return scores
    hero_scores = _score_range(hero_combos)
    vill_scores = _score_range(vill_combos)
    if not hero_scores or not vill_scores:
        return hero_eq, 0.0
    all_scores = sorted(hero_scores + vill_scores)
    if not all_scores:
        return hero_eq, 0.0
    threshold = all_scores[int(len(all_scores) * 0.90)]
    hero_nut = sum(1 for s in hero_scores if s >= threshold) / len(hero_scores)
    vill_nut = sum(1 for s in vill_scores if s >= threshold) / len(vill_scores)
    return hero_eq, hero_nut - vill_nut


def compute_multiplier(hero_eq, nut_share):
    if hero_eq > 0.55 and nut_share > 0.05: return 1.30
    if hero_eq > 0.55:                       return 1.15
    if hero_eq < 0.45 and nut_share < -0.05: return 0.55
    if hero_eq < 0.45:                       return 0.70
    return 1.00


def main():
    out_dir = Path(__file__).resolve().parent.parent.parent / "submission" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "range_advantage.npz"
    rng = random.Random(20260608)

    # Shape: (16 pf_buckets, 50 board_textures, 6 positions, 3)
    table = np.zeros((16, 50, 6, 3), dtype=np.float32)
    filled = np.zeros((16, 10, 6), dtype=np.int8)

    # Sample one representative board per texture (re-used across cells). Try
    # 3-card flops first (best texture differentiation; 5-card has too many
    # overlapping features and earliest classifier wins). Fall back to 4/5.
    sample_boards = {}
    for tex in BOARD_TEXTURES:
        bd = None
        for sz in (3, 4, 5):
            bd = synth_board(tex, sz, rng, max_tries=80000)
            if bd: break
        if bd: sample_boards[tex] = bd
    print(f"[v15.8] sampled {len(sample_boards)}/{len(BOARD_TEXTURES)} representative boards")
    print(f"  textures captured: {sorted(sample_boards.keys())}")

    n_cells = 16 * 10 * 6                   # active cells; 50 dim has 40 unused
    done = 0
    t0 = time.time()
    print(f"[v15.8] computing {n_cells} cells, 300 samples each...")
    for pg in range(4):
        for pat in range(4):
            pf_idx = pg * 4 + pat            # 0..15
            for tex in BOARD_TEXTURES:
                bd = sample_boards.get(tex)
                if not bd:
                    continue
                t_idx = TEX_IDX[tex]
                for pos in range(6):
                    done += 1
                    he, nut = cell_eq_and_nut(pg, pat, pos, bd, n_samples=300, rng=rng)
                    mult = compute_multiplier(he, nut)
                    table[pf_idx, t_idx, pos, 0] = he
                    table[pf_idx, t_idx, pos, 1] = nut
                    table[pf_idx, t_idx, pos, 2] = mult
                    filled[pf_idx, t_idx, pos] = 1
        print(f"  pos_group {pg}/4 done at {time.time()-t0:.1f}s")
    dt = time.time() - t0
    print(f"[v15.8] done in {dt:.1f}s")
    np.savez_compressed(out_path,
                         range_adv=table, filled=filled,
                         action_patterns=np.array(ACTION_PATTERNS, dtype="U24"),
                         board_textures=np.array(BOARD_TEXTURES, dtype="U24"),
                         positions=np.array(POSITIONS, dtype="U4"))
    sz = out_path.stat().st_size
    nz = int((table != 0).sum())
    # variance: nonzero std on multiplier dim
    mults = table[..., 2][table[..., 2] != 0]
    print(f"saved -> {out_path} ({sz:,} bytes)")
    print(f"non-zero entries: {nz}, multiplier range: "
          f"{mults.min():.2f} .. {mults.max():.2f}, std: {mults.std():.3f}")


if __name__ == "__main__":
    main()
