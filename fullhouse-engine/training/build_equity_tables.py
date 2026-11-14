"""
build_equity_tables.py (v15 Patch J) — offline equity table generation.

Run once before submission to populate `submission/data/equity_tables.npz`.
Saves incrementally after each table so partial results are never lost.

Tables produced (in priority order):
  T1  preflop hand-vs-hand 169x169 (~228 KB)
  T2  preflop vs 1..5 random opponents 169x5 (~3.4 KB)
  T3  postflop {board-texture x hand-strength-bucket x n_opp} (~few KB)
  T4  range-vs-range hot spots (~tens of KB; optional)

Hand-class naming matches v14's `hand_class()` (e.g. AA / AKs / AKo) so the
runtime lookup can use the same string keys without translation.

Usage:
  python3 training/build_equity_tables.py
  python3 training/build_equity_tables.py --t1-iters 8000 --t2-iters 20000
  python3 training/build_equity_tables.py --skip-t4
"""
import argparse
import itertools
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


# -- 169 hand classes (must match v14's hand_class()) -----------------------
def build_hand_classes():
    out = []
    for i in range(13):
        for j in range(13):
            if i == j:
                out.append(RANKS[i] + RANKS[i])
            elif i > j:
                out.append(RANKS[i] + RANKS[j] + "s")
                out.append(RANKS[i] + RANKS[j] + "o")
    return out


HAND_CLASSES = build_hand_classes()
assert len(HAND_CLASSES) == 169, len(HAND_CLASSES)
CIDX = {c: i for i, c in enumerate(HAND_CLASSES)}


def class_combos(cls):
    """Return list of (card1, card2) tuples (eval7-friendly strings)."""
    if len(cls) == 2:                     # pair
        r = cls[0]
        return [(r + a, r + b) for a, b in itertools.combinations(SUITS, 2)]
    hi, lo, t = cls[0], cls[1], cls[2]
    if t == "s":
        return [(hi + s, lo + s) for s in SUITS]
    return [(hi + a, lo + b) for a in SUITS for b in SUITS if a != b]


COMBOS = {c: class_combos(c) for c in HAND_CLASSES}


def combo_count(cls):
    return 6 if len(cls) == 2 else (4 if cls.endswith("s") else 12)


WEIGHT = np.array([combo_count(c) for c in HAND_CLASSES], dtype=np.float32)


# -- Board / hand-strength buckets matching v14 -----------------------------
BOARD_TEXTURES = [
    "draw_completed", "monotone", "paired", "broadway_connected",
    "low_connected", "connected", "two_tone", "A_high_dry",
    "K_high_dry", "disconnected_low",
]
HAND_STRENGTHS = [
    "full_house_or_better", "flush", "straight", "set_or_trips", "two_pair",
    "overpair", "strong_top_pair", "weak_top_pair", "second_pair",
    "third_pair_or_underpair", "weak_showdown", "air",
]
TEX_IDX = {t: i for i, t in enumerate(BOARD_TEXTURES)}
HS_IDX = {h: i for i, h in enumerate(HAND_STRENGTHS)}


def _vals(board):
    return [RV[c[0]] for c in board]


def _has_straight(vset):
    if not vset:
        return False
    sv = sorted(vset)
    for i in range(len(sv) - 4):
        if sv[i + 4] - sv[i] == 4:
            return True
    if {12, 0, 1, 2, 3}.issubset(vset):           # wheel
        return True
    return False


def board_texture_bucket(board):
    """Replicates v14's logic so cells line up at runtime."""
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
    """Replicates v14's logic."""
    score = eval7.evaluate([eval7.Card(c) for c in hole + board])
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


# -- Equity helpers ---------------------------------------------------------
_FULL_DECK = [r + s for r in RANKS for s in SUITS]
_CARDS = {c: eval7.Card(c) for c in _FULL_DECK}


def hh_equity(c1_combos, c2_combos, n_iter, rng):
    """MC equity of class 1 vs class 2. Fast: rejection-sample boards from the
    full deck instead of building a filtered deck + shuffling per iter."""
    wins = ties = total = 0
    randrange = rng.randrange
    choice = rng.choice
    DECK = _FULL_DECK
    CARDS = _CARDS
    for _ in range(n_iter):
        h1 = choice(c1_combos)
        h2 = choice(c2_combos)
        if h1[0] in h2 or h1[1] in h2:
            continue
        a, b, c, d = h1[0], h1[1], h2[0], h2[1]
        b0 = b1 = b2 = b3 = b4 = None
        slots = [b0, b1, b2, b3, b4]
        # rejection sample 5 distinct non-dead cards
        filled = 0
        while filled < 5:
            x = DECK[randrange(52)]
            if x == a or x == b or x == c or x == d:
                continue
            dup = False
            for k in range(filled):
                if slots[k] == x:
                    dup = True; break
            if dup:
                continue
            slots[filled] = x
            filled += 1
        s1 = eval7.evaluate([CARDS[a], CARDS[b], CARDS[slots[0]], CARDS[slots[1]],
                              CARDS[slots[2]], CARDS[slots[3]], CARDS[slots[4]]])
        s2 = eval7.evaluate([CARDS[c], CARDS[d], CARDS[slots[0]], CARDS[slots[1]],
                              CARDS[slots[2]], CARDS[slots[3]], CARDS[slots[4]]])
        if s1 > s2:   wins += 1
        elif s1 < s2: pass
        else:         ties += 1
        total += 1
    if total == 0:
        return 0.5
    return (wins + 0.5 * ties) / total


def hand_vs_n_random(hole, n_opp, n_iter, rng):
    """MC equity of a fixed hand vs n_opp uniform-random opponents (pre-board).
    Fast: sample (n_opp*2 + 5) cards from the prefiltered deck via random.sample."""
    wins = ties = total = 0
    dead0 = set(hole)
    base_deck = [c for c in _FULL_DECK if c not in dead0]
    CARDS = _CARDS
    take = n_opp * 2 + 5
    for _ in range(n_iter):
        deck = random.sample(base_deck, take)
        opp_holes = [(deck[2 * i], deck[2 * i + 1]) for i in range(n_opp)]
        board = deck[n_opp * 2:n_opp * 2 + 5]
        hv = eval7.evaluate([CARDS[hole[0]], CARDS[hole[1]],
                              CARDS[board[0]], CARDS[board[1]],
                              CARDS[board[2]], CARDS[board[3]], CARDS[board[4]]])
        best = -1
        for oh in opp_holes:
            ov = eval7.evaluate([CARDS[oh[0]], CARDS[oh[1]],
                                  CARDS[board[0]], CARDS[board[1]],
                                  CARDS[board[2]], CARDS[board[3]], CARDS[board[4]]])
            if ov > best:
                best = ov
        if hv > best:   wins += 1
        elif hv < best: pass
        else:           ties += 1
        total += 1
    if total == 0:
        return 0.5
    return (wins + 0.5 * ties) / total


def equity_with_board(hole, board, n_opp, n_iter, rng):
    """MC equity of a hand on a partial board vs n_opp random opponents."""
    dead0 = set(hole) | set(board)
    base_deck = [c for c in _FULL_DECK if c not in dead0]
    need = 5 - len(board)
    take = n_opp * 2 + need
    if take > len(base_deck) or need < 0:
        return 0.5
    wins = ties = total = 0
    for _ in range(n_iter):
        rng.shuffle(base_deck)
        full_board = board + (base_deck[n_opp * 2:n_opp * 2 + need] if need > 0 else [])
        hv = eval7.evaluate([_CARDS[c] for c in list(hole) + full_board])
        best = -1
        for o in range(n_opp):
            ov = eval7.evaluate([_CARDS[c]
                                  for c in [base_deck[2 * o], base_deck[2 * o + 1]] + full_board])
            if ov > best:
                best = ov
        if hv > best:   wins += 1
        elif hv < best: pass
        else:           ties += 1
        total += 1
    if total == 0:
        return 0.5
    return (wins + 0.5 * ties) / total


def synth_board_hand_for_cell(tex, hs, rng, max_tries=2000):
    """Search for (board, hole) matching (texture, hand_strength)."""
    for _ in range(max_tries):
        deck = list(_FULL_DECK)
        rng.shuffle(deck)
        board = deck[:5]
        hole = deck[5:7]
        if board_texture_bucket(board) != tex:
            continue
        if hand_strength_bucket(hole, board) != hs:
            continue
        return tuple(hole), tuple(board)
    return None, None


# -- Range definitions for Table 4 (a small curated set) --------------------
RANGES = {
    "UTG_open":    ["AA","KK","QQ","JJ","TT","99","88","77","66","55","44","33","22",
                    "AKs","AQs","AJs","ATs","KQs","KJs","KTs","QJs","QTs","JTs","T9s",
                    "AKo","AQo","AJo","KQo"],
    "BTN_open":    ["AA","KK","QQ","JJ","TT","99","88","77","66","55","44","33","22",
                    "AKs","AQs","AJs","ATs","A9s","A8s","A7s","A6s","A5s","A4s","A3s","A2s",
                    "KQs","KJs","KTs","K9s","K8s","K7s","K6s","K5s",
                    "QJs","QTs","Q9s","Q8s","JTs","J9s","J8s","T9s","T8s","98s","97s","87s","76s","65s","54s",
                    "AKo","AQo","AJo","ATo","KQo","KJo","KTo","QJo","QTo","JTo","T9o"],
    "BB_defend":   ["AA","KK","QQ","JJ","TT","99","88","77","66","55","44","33","22",
                    "AKs","AQs","AJs","ATs","A9s","A8s","A7s","A5s","A4s","A3s","A2s",
                    "KQs","KJs","KTs","K9s","K8s","Q9s","QJs","QTs","JTs","T9s","98s","87s","76s","65s","54s",
                    "AKo","AQo","AJo","ATo","KQo","KJo","KTo","QJo","JTo"],
    "SB_3bet":     ["AA","KK","QQ","JJ","TT","AKs","AKo","AQs","AQo","A5s","A4s","KQs"],
    "value_4bet":  ["AA","KK","QQ","AKs","AKo"],
}
RANGES_KEYS = list(RANGES.keys())


def range_to_combos(range_classes):
    out = []
    for cls in range_classes:
        out.extend(COMBOS.get(cls, []))
    return out


def range_vs_range_equity(r1_combos, r2_combos, board, n_iter, rng):
    """MC equity of range1 vs range2 on a fixed board (or random board if []).
    Resamples conflicting card draws."""
    wins = ties = total = 0
    skip_cap = n_iter * 10
    tries = 0
    while total < n_iter and tries < skip_cap:
        tries += 1
        h1 = rng.choice(r1_combos)
        h2 = rng.choice(r2_combos)
        dead = set(h1) | set(h2)
        if set(board) & dead:
            continue
        if len(dead) < 4:
            continue
        deck = [c for c in _FULL_DECK if c not in dead and c not in board]
        need = 5 - len(board)
        if need < 0 or need > len(deck):
            continue
        rng.shuffle(deck)
        full_board = board + deck[:need] if need > 0 else list(board)
        s1 = eval7.evaluate([_CARDS[c] for c in list(h1) + full_board])
        s2 = eval7.evaluate([_CARDS[c] for c in list(h2) + full_board])
        if s1 > s2:   wins += 1
        elif s1 < s2: pass
        else:         ties += 1
        total += 1
    if total == 0:
        return 0.5
    return (wins + 0.5 * ties) / total


# -- Main driver ------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="submission/data/equity_tables.npz")
    ap.add_argument("--t1-iters", type=int, default=6000,
                    help="MC iters per cell for Table 1 (preflop H-vs-H)")
    ap.add_argument("--t2-iters", type=int, default=30000,
                    help="MC iters per cell for Table 2 (vs N random)")
    ap.add_argument("--t3-iters", type=int, default=15000,
                    help="MC iters per cell for Table 3 (postflop class)")
    ap.add_argument("--t4-iters", type=int, default=4000,
                    help="MC iters per cell for Table 4 (range vs range)")
    ap.add_argument("--skip-t3", action="store_true")
    ap.add_argument("--skip-t4", action="store_true")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260604)
    arrays = {
        "hand_classes": np.array(HAND_CLASSES, dtype="U4"),
        "board_textures": np.array(BOARD_TEXTURES, dtype="U24"),
        "hand_strengths": np.array(HAND_STRENGTHS, dtype="U24"),
    }

    # ---- Table 1: preflop hand-vs-hand (169 x 169) ------------------------
    print(f"[T1] preflop H-vs-H 169x169 ({args.t1_iters} iters/cell)...")
    t0 = time.time()
    T1 = np.zeros((169, 169), dtype=np.float32)
    for i in range(169):
        ci = COMBOS[HAND_CLASSES[i]]
        for j in range(i, 169):
            if i == j:
                T1[i, j] = 0.5
                continue
            cj = COMBOS[HAND_CLASSES[j]]
            eq = hh_equity(ci, cj, args.t1_iters, rng)
            T1[i, j] = eq
            T1[j, i] = 1.0 - eq
        if i % 20 == 0:
            dt = time.time() - t0
            print(f"   row {i}/169  ({dt:.1f}s elapsed)")
    arrays["preflop_hand_vs_hand"] = T1
    np.savez_compressed(out_path, **arrays)
    print(f"   T1 done in {time.time()-t0:.1f}s; size={out_path.stat().st_size//1024} KB")

    # spot checks
    print(f"   spot-check: AA vs 72o = {T1[CIDX['AA'], CIDX['72o']]:.3f} (expect ~0.87)")
    print(f"               AKs vs QQ = {T1[CIDX['AKs'], CIDX['QQ']]:.3f} (expect ~0.46)")
    print(f"               AKo vs AKs = {T1[CIDX['AKo'], CIDX['AKs']]:.3f} (expect ~0.5)")

    # ---- Table 2: preflop vs N random (169 x 5) ---------------------------
    print(f"\n[T2] preflop vs N random ({args.t2_iters} iters/cell)...")
    t0 = time.time()
    T2 = np.zeros((169, 5), dtype=np.float32)
    for i in range(169):
        cls = HAND_CLASSES[i]
        hole = COMBOS[cls][0]
        for n in range(1, 6):
            T2[i, n - 1] = hand_vs_n_random(hole, n, args.t2_iters, rng)
        if i % 20 == 0:
            print(f"   class {i}/169  ({time.time()-t0:.1f}s)")
    arrays["preflop_vs_random"] = T2
    np.savez_compressed(out_path, **arrays)
    print(f"   T2 done in {time.time()-t0:.1f}s; size={out_path.stat().st_size//1024} KB")
    print(f"   spot-check: AA vs 1 random = {T2[CIDX['AA'], 0]:.3f} (expect ~0.85)")
    print(f"               AKs vs 1 random = {T2[CIDX['AKs'], 0]:.3f} (expect ~0.67)")
    print(f"               72o vs 1 random = {T2[CIDX['72o'], 0]:.3f} (expect ~0.36)")
    print(f"               AKs vs 5 random = {T2[CIDX['AKs'], 4]:.3f} (expect ~0.28)")

    # ---- Table 3: postflop {texture x strength x n_opp} -------------------
    if not args.skip_t3:
        print(f"\n[T3] postflop class table ({args.t3_iters} iters/cell)...")
        t0 = time.time()
        nT, nH = len(BOARD_TEXTURES), len(HAND_STRENGTHS)
        T3 = np.zeros((nT, nH, 5), dtype=np.float32)
        T3_filled = np.zeros((nT, nH), dtype=np.int8)
        for ti, tex in enumerate(BOARD_TEXTURES):
            for hi, hs in enumerate(HAND_STRENGTHS):
                hole, board = synth_board_hand_for_cell(tex, hs, rng)
                if hole is None:
                    continue
                T3_filled[ti, hi] = 1
                for n in range(1, 6):
                    T3[ti, hi, n - 1] = equity_with_board(
                        list(hole), list(board), n, args.t3_iters, rng)
            print(f"   tex {ti+1}/{nT} '{tex}'  ({time.time()-t0:.1f}s)")
        arrays["postflop_class_n_opp"] = T3
        arrays["postflop_class_filled"] = T3_filled
        np.savez_compressed(out_path, **arrays)
        n_filled = int(T3_filled.sum())
        print(f"   T3 done in {time.time()-t0:.1f}s; filled {n_filled}/{nT*nH} cells")

    # ---- Table 4: range-vs-range hot spots --------------------------------
    if not args.skip_t4:
        print(f"\n[T4] range vs range ({args.t4_iters} iters/cell)...")
        t0 = time.time()
        # Curated hot-spot list (ranges 1 vs ranges 2 at each common street).
        matchups = [
            ("UTG_open", "BB_defend"), ("BTN_open", "BB_defend"),
            ("BTN_open", "SB_3bet"),   ("UTG_open", "SB_3bet"),
            ("SB_3bet", "value_4bet"), ("UTG_open", "value_4bet"),
        ]
        nM = len(matchups)
        nT = len(BOARD_TEXTURES)
        # streets: 0=preflop (empty), 1=flop, 2=turn, 3=river
        T4 = np.zeros((nM, nT, 4), dtype=np.float32)
        T4_filled = np.zeros((nM, nT, 4), dtype=np.int8)
        for mi, (a, b) in enumerate(matchups):
            ca = range_to_combos(RANGES[a])
            cb = range_to_combos(RANGES[b])
            # preflop
            T4[mi, 0, 0] = range_vs_range_equity(ca, cb, [], args.t4_iters, rng)
            T4_filled[mi, 0, 0] = 1
            # postflop: sample a representative board per texture
            for ti, tex in enumerate(BOARD_TEXTURES):
                for street, sz in [(1, 3), (2, 4), (3, 5)]:
                    # synthesize a board of size sz with target texture
                    found = None
                    for _ in range(800):
                        deck = list(_FULL_DECK); rng.shuffle(deck)
                        bd = deck[:sz]
                        if board_texture_bucket(bd) == tex:
                            found = bd; break
                    if found is None:
                        continue
                    T4[mi, ti, street] = range_vs_range_equity(
                        ca, cb, found, args.t4_iters, rng)
                    T4_filled[mi, ti, street] = 1
            print(f"   matchup {mi+1}/{nM} {a} vs {b}  ({time.time()-t0:.1f}s)")
        arrays["matchup_names"] = np.array([f"{a}__vs__{b}" for a, b in matchups],
                                            dtype="U48")
        arrays["range_vs_range"] = T4
        arrays["range_vs_range_filled"] = T4_filled
        np.savez_compressed(out_path, **arrays)
        print(f"   T4 done in {time.time()-t0:.1f}s")

    final = out_path.stat().st_size
    print(f"\nDone. Saved {out_path} ({final:,} bytes = {final/1024:.1f} KB)")
    print(f"Keys: {sorted(arrays.keys())}")


if __name__ == "__main__":
    main()
