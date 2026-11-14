"""
solve_push_fold.py (B2) — offline chip-EV Nash push/fold solver.

Computes first-in JAM ranges for a chip-EV (no-ICM) game — which is exactly our
scoring model (cumulative chip delta). Output is a compact Python constant block
(hand-class frozensets keyed by (position, effective-BB)) that is pasted into the
bot. NO numpy/npz/zip is shipped — the submission stays a single self-contained
bot.py. This script only RUNS offline.

Model (per first-in spot): hero has s BB effective, k opponents left to act behind,
each calls independently with its chip-EV-Nash calling range (heads-up-when-called
approximation; for k>=2 a small positive EV margin tightens jams conservatively to
account for multiway equity loss). Fixed blinds SB=0.5 / BB=1.0, no antes.

Heads-up SB (k=1) reduces to the canonical 2-player jam/call Nash equilibrium.

Validation: the solved table is checked against published push/fold sanity points
(premiums always jam; trash never jams from non-blind at 10bb; all pairs jam short;
short-stack SB jams very wide). If >5% of sanity points fail, the solver is wrong.

Usage:
  python3 training/solve_push_fold.py            # solve + print table + chart check
  python3 training/solve_push_fold.py --rebuild  # force-rebuild equity matrix cache
"""
import argparse
import itertools
import os
import random
import sys
from pathlib import Path

import numpy as np
import eval7

RANKS = "23456789TJQKA"
RV = {r: i for i, r in enumerate(RANKS)}
SUITS = "shdc"
CACHE = Path(__file__).parent / "_pf_equity_matrix.npz"


# ---- 169 hand classes (bot-compatible naming) -----------------------------
def build_classes():
    classes = []
    for i in range(13):
        for j in range(13):
            hi, lo = RANKS[12 - i], RANKS[12 - j]
            if i == j:
                classes.append(hi + hi)          # pair "AA"
            elif i < j:
                classes.append(hi + lo + "s")     # suited (i is higher)
            else:
                classes.append(RANKS[12 - j] + RANKS[12 - i] + "o")
    # de-dup while preserving a stable order
    seen, out = set(), []
    for c in classes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


CLASSES = build_classes()
CIDX = {c: i for i, c in enumerate(CLASSES)}
N = len(CLASSES)
assert N == 169, N


def class_combos(cls):
    """All concrete 2-card combos (as ('As','Kd') tuples) for a hand class."""
    if len(cls) == 2:                                    # pair
        r = cls[0]
        return [(r + a, r + b) for a, b in itertools.combinations(SUITS, 2)]
    hi, lo, t = cls[0], cls[1], cls[2]
    if t == "s":
        return [(hi + s, lo + s) for s in SUITS]
    return [(hi + a, lo + b) for a in SUITS for b in SUITS if a != b]


def combo_count(cls):
    return 6 if len(cls) == 2 else (4 if cls.endswith("s") else 12)


COMBOS = [class_combos(c) for c in CLASSES]
WEIGHT = np.array([combo_count(c) for c in CLASSES], dtype=float)   # combos/class
TOTAL_COMBOS = 1326.0


# ---- equity matrix E[a][b] = P(class a beats class b) ----------------------
def build_matrix(samples=900, seed=12345, rebuild=False):
    if CACHE.exists() and not rebuild:
        d = np.load(CACHE, allow_pickle=True)
        if d["E"].shape == (N, N) and int(d["samples"]) >= samples:
            print(f"[matrix] cache hit ({CACHE.name}, samples={int(d['samples'])})")
            return d["E"]
    print(f"[matrix] building 169x169 equity matrix ({samples} samples/pair)...")
    rng = random.Random(seed)
    E = np.full((N, N), 0.5, dtype=float)
    full = [r + s for r in RANKS for s in SUITS]
    for a in range(N):
        ca = COMBOS[a]
        for b in range(a + 1, N):
            cb = COMBOS[b]
            wins = 0.0
            n = 0
            for _ in range(samples):
                ha = rng.choice(ca); hb = rng.choice(cb)
                cards = set(ha) | set(hb)
                if len(cards) < 4:
                    continue                          # share a card; resample
                deck = [c for c in full if c not in cards]
                board = rng.sample(deck, 5)
                hv = eval7.evaluate([eval7.Card(x) for x in (list(ha) + board)])
                vv = eval7.evaluate([eval7.Card(x) for x in (list(hb) + board)])
                if hv > vv:
                    wins += 1.0
                elif hv == vv:
                    wins += 0.5
                n += 1
            e = wins / n if n else 0.5
            E[a][b] = e
            E[b][a] = 1.0 - e
        if a % 20 == 0:
            print(f"   row {a}/{N}")
    np.savez_compressed(CACHE, E=E, samples=samples)
    print(f"[matrix] saved -> {CACHE.name}")
    return E


def eq_vs_range(hi, range_idx, E):
    """Combo-weighted equity of class index hi vs a set of class indices."""
    if not range_idx:
        return 0.5
    idx = np.fromiter(range_idx, dtype=int)
    w = WEIGHT[idx]
    return float(np.dot(E[hi, idx], w) / w.sum())


def range_freq(range_idx):
    """Fraction of all 1326 combos in this range (fold-equity weight)."""
    if not range_idx:
        return 0.0
    return float(WEIGHT[np.fromiter(range_idx, dtype=int)].sum() / TOTAL_COMBOS)


# ---- chip-EV Nash solver (damped fictitious play) -------------------------
# Per-spot constants in BB units (SB=0.5, BB=1.0). Hero is first-in with `k`
# callers behind. We solve a symmetric jam/call equilibrium by FICTITIOUS PLAY
# (soft mixed strategies updated toward best-response with step alpha) — this
# converges where naive set-swap iteration oscillates to corner solutions.
def _spot_params(s, hero_is_sb, hero_is_bb):
    if hero_is_sb:                       # k=1, caller is BB (posted 1.0)
        return dict(hero_fold=-0.5, hero_allfold=1.0, hero_pot=2.0 * s,
                    caller_fold=-1.0, caller_pot=2.0 * s)
    if hero_is_bb:                       # limped pot, k=1 (approx), caller posted 0.5
        return dict(hero_fold=0.0, hero_allfold=0.5, hero_pot=2.0 * s + 0.5,
                    caller_fold=-0.5, caller_pot=2.0 * s + 0.5)
    # non-blind (UTG/HJ/CO/BTN): callers are cold; SB+BB (1.5) are dead money
    return dict(hero_fold=0.0, hero_allfold=1.5, hero_pot=2.0 * s + 1.5,
                caller_fold=0.0, caller_pot=2.0 * s + 1.5)


def solve_spot(s, k, hero_is_sb, hero_is_bb, E, iters=120, alpha=0.25,
               margin_k2=0.03):
    """Return (jam_range_idx, call_range_idx) via damped fictitious play."""
    P = _spot_params(s, hero_is_sb, hero_is_bb)
    margin = 0.0 if k <= 1 else margin_k2 * s
    jam_p = np.full(N, 0.5)              # soft jam membership
    call_p = np.full(N, 0.3)            # soft call membership
    for _ in range(iters):
        wj = jam_p * WEIGHT
        wc = call_p * WEIGHT
        e_vs_jam = (E @ wj) / wj.sum() if wj.sum() > 0 else np.full(N, 0.5)
        e_vs_call = (E @ wc) / wc.sum() if wc.sum() > 0 else np.full(N, 0.5)
        # caller best response (vs hero's current jam range)
        br_call = ((e_vs_jam * P["caller_pot"] - s) > P["caller_fold"]).astype(float)
        # hero best response (vs callers' current call range)
        q = wc.sum() / TOTAL_COMBOS                       # one caller's call freq
        p_all_fold = (1.0 - q) ** max(k, 1)
        ev_called = e_vs_call * P["hero_pot"] - s
        ev_jam = p_all_fold * P["hero_allfold"] + (1.0 - p_all_fold) * ev_called
        br_jam = (ev_jam > P["hero_fold"] + margin).astype(float)
        # damped update
        new_jam = (1 - alpha) * jam_p + alpha * br_jam
        new_call = (1 - alpha) * call_p + alpha * br_call
        if np.max(np.abs(new_jam - jam_p)) < 1e-4 and \
           np.max(np.abs(new_call - call_p)) < 1e-4:
            jam_p, call_p = new_jam, new_call
            break
        jam_p, call_p = new_jam, new_call
    jam = set(int(i) for i in range(N) if jam_p[i] > 0.5)
    call = set(int(i) for i in range(N) if call_p[i] > 0.5)
    return jam, call


POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
K_BEHIND = {"UTG": 5, "HJ": 4, "CO": 3, "BTN": 2, "SB": 1, "BB": 1}
DEPTHS = list(range(2, 16))               # 2..15 effective BB


def solve_all(E):
    table = {}        # (pos, s) -> frozenset(hand classes)
    callt = {}        # (pos, s) -> frozenset (diagnostic only; not shipped)
    for pos in POSITIONS:
        k = K_BEHIND[pos]
        for s in DEPTHS:
            jam, call = solve_spot(s, k, pos == "SB", pos == "BB", E)
            table[(pos, s)] = frozenset(CLASSES[i] for i in jam)
            callt[(pos, s)] = frozenset(CLASSES[i] for i in call)
    return table, callt


# ---- chart-match validation (published push/fold sanity points) -----------
def chart_check(table, callt):
    checks = []

    def jam_has(pos, s, hand):
        return hand in table[(pos, s)]

    # premiums always jam (all positions, all depths)
    for pos in POSITIONS:
        for s in DEPTHS:
            for h in ("AA", "KK", "QQ"):
                checks.append((f"{h} jams {pos}@{s}", jam_has(pos, s, h)))
    # trash never jams from non-blind at 10bb
    for h in ("72o", "82o", "32o", "62o"):
        checks.append((f"{h} folds UTG@10", not jam_has("UTG", 10, h)))
        checks.append((f"{h} folds CO@10", not jam_has("CO", 10, h)))
    # all pairs jam very short from the button
    for r in RANKS:
        checks.append((f"{r}{r} jams BTN@5", jam_has("BTN", 5, r + r)))
    # SB jams very wide at 2bb (canonical HU push/fold: ~any two)
    checks.append(("SB jams >85% @2", range_freq({CIDX[c] for c in table[("SB", 2)]}) > 0.85))
    # directional: AKo jams BTN@15, A5s jams BTN@10, ATs jams CO@12
    checks.append(("AKo jams BTN@15", jam_has("BTN", 15, "AKo")))
    checks.append(("A5s jams BTN@10", jam_has("BTN", 10, "A5s")))
    checks.append(("ATs jams CO@12", jam_has("CO", 12, "ATs")))
    # monotonicity: jam range widens as stack shrinks (UTG)
    for s in range(3, 16):
        a = range_freq({CIDX[c] for c in table[("UTG", s)]})
        b = range_freq({CIDX[c] for c in table[("UTG", s - 1)]})
        checks.append((f"UTG widen {s}->{s-1}", b >= a - 0.02))

    fails = [name for name, ok in checks if not ok]
    rate = len(fails) / len(checks)
    print(f"\n[chart-check] {len(checks)-len(fails)}/{len(checks)} pass "
          f"({100*(1-rate):.1f}%)")
    if fails:
        print("  FAILURES:", fails[:20])
    return rate, fails


def emit_constant(table):
    """Print a compact Python literal: NASH_JAM[pos][s] = frozenset(...)."""
    print("\n# ===== PASTE INTO bot.py (generated by training/solve_push_fold.py) =====")
    print("# Chip-EV Nash first-in JAM ranges (B2). pos -> {eff_bb: frozenset(classes)}")
    print("NASH_PUSH_RAW = {")
    for pos in POSITIONS:
        print(f'    "{pos}": {{')
        for s in DEPTHS:
            hands = sorted(table[(pos, s)], key=lambda c: (len(c), c))
            print(f'        {s}: "{" ".join(hands)}",')
        print("    },")
    print("}")
    print("# ===== END PASTE =====")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--samples", type=int, default=900)
    args = ap.parse_args()
    E = build_matrix(samples=args.samples, rebuild=args.rebuild)
    table, callt = solve_all(E)
    # quick range-width summary
    print("\n[summary] jam-range width (% of 1326 combos):")
    print("  pos  " + " ".join(f"{s:>4}" for s in DEPTHS))
    for pos in POSITIONS:
        widths = [range_freq({CIDX[c] for c in table[(pos, s)]}) for s in DEPTHS]
        print(f"  {pos:>3}  " + " ".join(f"{100*w:4.0f}" for w in widths))
    rate, fails = chart_check(table, callt)
    emit_constant(table)
    if rate > 0.05:
        print(f"\n*** CHART CHECK FAILED ({100*rate:.1f}% > 5%) — DO NOT SHIP ***")
        sys.exit(1)
    print("\n[ok] chart check passed (<=5% fail). Safe to integrate.")


if __name__ == "__main__":
    main()
