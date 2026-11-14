"""
v12 — final hardening (extends v9; v10 LR and v11 LP were evaluated and skipped).

Content-NEUTRAL safety/discipline additions only (ADDITIONAL_INSTRUCTIONS Patch 12):
  - Score-aware aggression: in the last ~50 hands, nudge our bet/raise
    frequencies by a mild bounded factor in [0.97, 1.05] from hands_remaining +
    stack ratio (behind late -> slightly more aggressive; far ahead late ->
    slightly more passive). hand_num parsed explicitly.
  - Time-budget staged decide(): an 800ms soft budget with an emergency-fallback
    checkpoint, on top of the equity layer's per-decision deadline. Never fires
    in normal (sub-20ms) operation — pure insurance for the 0.5-CPU container.

No new strategic logic — v12 == v9 in the vast majority of decisions.

----------------------------------------------------------------------------
v8 — blocker-aware river overrides (extends v7).

River-only, bounded adjustment (brief P10). On a river where a flush is possible
(exactly 3 of one suit on board) and we hold the nut-flush blocker (the A — or
K if the A is on board — of that suit) WITHOUT a made flush, villain's nut-flush
combos are reduced. So:
  - checked to with a bluff candidate: bluff a little more (our line credibly
    reps the flush AND villain has fewer flushes to call) — gated OFF vs a
    confirmed call-station;
  - facing a bet with a marginal hand: bluff-catch a little more (villain's
    value range is lighter because we hold their nut card).
Small magnitude (~0.12), river-only, so it can't cause a robustness regression;
the edge shows up vs opponents with realistic ranges, not our caricatures.

----------------------------------------------------------------------------
v7 — irregular adversarial bet sizing (extends v6).

Single surgical change (brief P1): the abstract bet sizes map to IRREGULAR pot
fractions (0.29 / 0.71 / 1.13 / 1.87) instead of textbook 0.33 / 0.66 / 1.0 /
1.5. The edge is orthogonal positioning vs an LLM-built field that uses round
sizing + pot-odds calling; it shows up against the real field, not our own
test bots (which bucket sizes correctly), so the gate is "neutral or better".

----------------------------------------------------------------------------
v6 — deterministic mix-sampling + bet-size bucketing (extends v5).

Patch 9 (deterministic mixed-strategy sampling): the mixed strategy is now
sampled by hashing the FULL decision context (hand_id, seat, street, action
position, pot, current_bet, amount_owed, your_bet_this_street) instead of
random.random(). This (a) fixes the brief's seed which wasn't unique per
decision — we can act several times on a street — and (b) makes every decision
reproducible from the log (same state -> same action), which is essential for
debugging. The per-decision Monte-Carlo RNG is ALSO seeded from that hash (via
a LOCAL random.Random, so we never disturb the global RNG that opponents share
in-process), so the whole decision is reproducible.

Patch 10 (consistent bet-size bucketing): a single bucket_bet_size() maps any
bet to a generous size bucket, used when reading the bet we face. This keeps
encoding robust when v7 introduces irregular sizes (29%/71%/113%) — a 71% bet
still buckets the same as a 66% bet.

----------------------------------------------------------------------------
v5 — eval7 equity layer + multiway Layer 2 (extends v4).

New in v5 (ADDITIONAL_INSTRUCTIONS Patch 11; brief P19/P24/P34):
  - Runtime eval7 Monte Carlo equity vs N opponents on the actual board, with
    Wilson-CI early stopping and HARD time/rollout caps. Fires only on flagged
    spots (big pots, all-ins) so p99 stays low.
  - Precomputed preflop equity table (P34), built during the 30s warmup with a
    strict time box and graceful fallback to runtime MC.
  - Equity-based calling for big bets / all-ins: call iff raw equity beats a
    pot-odds threshold scaled by an opponent range factor, PLUS the P32
    variance premium for big-commitment spots (now done right, with equity).
  - Multiway Layer 2: before a multiway value bet / call in a big pot, verify
    equity-vs-best-of-N supports it; otherwise downgrade bet->check / call->fold.

A per-decision time budget (_EQ_DEADLINE) guards every equity call; if the
budget is gone we fall back to the v4 decision. So there is no timeout risk.

----------------------------------------------------------------------------
v4 — opponent modeling (extends v3.5).

Everything below v4 is the opponent-agnostic blueprint (preflop v1 + size-aware
v3.5, postflop v2 + multiway v3). v4 layers per-opponent adaptation ON TOP of
that correct foundation.

Components (ADDITIONAL_INSTRUCTIONS Patch 1 + Patch 6 + brief Step 7):
  - Per-opponent Bayesian Beta stats keyed by bot_id:
      fold_to_bet, aggression, shove_frequency, bluff_propensity (P33).
    These are the robustly-extractable, high-exploit-value stats; they power
    the three big exploits (bluff more vs over-folders, value-bet more vs call
    stations, bluff-catch more vs maniacs/bluffers).
  - Patch 1 hand-boundary memory: stats are accumulated from COMPLETED hands in
    match_action_log, deduped via PROCESSED_HANDS. This survives the 200-entry
    truncation that silently breaks the brief's LAST_LOG_INDEX scheme. (Step 2
    of Patch 1's pseudocode — incremental current-hand processing — is omitted
    on purpose: it double-counts each hand once it later appears completed.)
  - Patch 6 normal-approx (Wilson) CI in the hot path; no scipy.
  - Bounded lambda-blend perturbation of the postflop strategy dist toward an
    exploit distribution. lambda in [0, 0.30], 0 below MIN_OBS observations,
    scaling with data volume and CI tightness. Capped so a wrong read can't
    wreck us. Exploits: bluff more vs over-folders, value-bet more AND bigger
    vs call stations, bluff-catch more vs aggressors/bluffers.
  - Preflop steal-widening: when first-in vs proven over-folders, open a wider
    range (relentless blind stealing vs nits). Only ADDS opens vs confirmed
    folders, so it can't regress against anyone else.

NOTE on P32 (variance-adjusted calling buffer): deferred to v5. A safe version
needs an equity/range estimate to tell a value-heavy big bet from a bluff.
Action-only, street-agnostic stats can't distinguish a disguised river
over-bettor from a tight player, so a fold-premium here folds to bluffs (it
cost ~2k/match vs overbet_river_bluffer in testing). v5 adds eval7 equity-vs-
range, which is the right foundation for P32.

Per Patch 8: imports limited to os/time/math/random/re + eval7 (no scipy/sklearn).
"""
import os
import re
import time
import math
import random
import hashlib

import eval7

# v15 PATCH J: numpy is permitted (Patch 8). Used for precomputed equity tables.
try:
    import numpy as np
    _NUMPY_OK = True
except Exception:
    np = None
    _NUMPY_OK = False

BOT_NAME = "OurBot v13"
HANDS_PER_MATCH = 400
SOFT_BUDGET = 0.8        # seconds; staged decide() emergency-fallback threshold
_T0 = 0.0
# Phase-2 tune (river over-call leak fix): magnitude of river bluff-catch
# tightening. Env-overridable for the grid sweep; hardcode the winner for ship.
RIVER_FOLD = float(os.environ.get("RIVER_FOLD", "0.50"))   # grid-validated winner

DATA_DIR = os.environ.get("BOT_DATA_DIR",
                          os.path.join(os.path.dirname(__file__), "data"))

# === Module globals (persist across hands within a match) ===
HAND_COUNT = 0
POSTFLOP_DECISIONS = 0
FALLBACK_DECISIONS = 0          # times we used the emergency path postflop

DEFAULT_BB = 100
SHORT_STACK_BB = 15
RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

# CFR drop-in slot: infoset_key (str) -> {action: prob}. Empty in v2; the
# authored generator below is the strategy. Populating this later lets a solved
# table override specific infosets without touching code.
POSTFLOP_STRATEGY_TABLE = {}


# ===========================================================================
# ============================ PREFLOP (from v1) ============================
# ===========================================================================

def _expand_token(tok):
    tok = tok.strip()
    if not tok:
        return set()
    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok
    out = set()
    if len(core) == 2 and core[0] == core[1] and core[0] in RANK_VAL:
        lo = RANK_VAL[core[0]]
        hi = RANK_VAL["A"] if plus else lo
        for v in range(lo, hi + 1):
            out.add(RANKS[v] * 2)
        return out
    if len(core) == 3 and core[0] in RANK_VAL and core[1] in RANK_VAL and core[2] in "so":
        a, b, suit = core[0], core[1], core[2]
        hv, lv = RANK_VAL[a], RANK_VAL[b]
        if hv < lv:
            hv, lv = lv, hv
        if plus:
            for k in range(lv, hv):
                out.add(RANKS[hv] + RANKS[k] + suit)
        else:
            out.add(RANKS[hv] + RANKS[lv] + suit)
        return out
    return out


def R(s):
    out = set()
    for tok in s.replace(",", " ").split():
        out |= _expand_token(tok)
    return out


# --- Range tables (edit these; see v1 for the notation guide) ---
OPEN = {
    'UTG': R("22+, ATs+, KTs+, QTs+, JTs, T9s, AJo+, KQo"),
    'HJ':  R("22+, A9s+, A5s, KTs+, Q9s+, J9s+, T9s, 98s, ATo+, KJo+, QJo"),
    'CO':  R("22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, A9o+, A5o, KTo+, QTo+, JTo"),
    'BTN': R("22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K9o+, Q9o+, J9o+, T9o"),
    'SB':  R("22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, A7o+, A5o, K9o+, Q9o+, JTo"),
    'BB':  R("55+, A8s+, KTs+, QTs+, JTs, T9s, ATo+, KQo"),
}
VS_OPEN_3BET = {
    'UTG': R("QQ+, AKs, AKo"),
    'HJ':  R("JJ+, AKs, AKo, A5s"),
    'CO':  R("JJ+, AQs+, AKo, A5s, KQs"),
    'BTN': R("TT+, AQs+, AKo, A5s, A4s, KQs"),
    'SB':  R("QQ+, AKs, AKo, A5s"),
    'BB':  R("QQ+, AKs, AKo, A5s"),
}
VS_OPEN_CALL = {
    'UTG': R("JJ-TT, AQs, AJs, KQs"),
    'HJ':  R("TT-77, AJs, ATs, KQs, KJs, QJs, JTs, AQo"),
    'CO':  R("99-22, ATs+, KJs+, QJs, JTs, T9s, 98s, AQo, AJo"),
    'BTN': R("TT-22, A9s+, KTs+, QTs+, J9s+, T9s, 98s, 87s, 76s, AJo, KQo"),
    'SB':  R("JJ-77, AJs, ATs, KQs, QJs, JTs"),
    'BB':  R("99-22, ATs+, KJs+, QJs, JTs, T9s, 98s, AQo, KQo"),
}
BLIND_DEFEND_3BET = {
    'SB': R("TT+, AJs+, KQs, AQo+, A5s, A4s"),
    'BB': R("TT+, AQs+, AKo, A5s, A4s, K5s"),
}
BLIND_DEFEND_CALL = {
    'SB': R("99-22, ATs-AJs, KQs, KJs, QJs, JTs, T9s, 98s, AJo, KQo"),
    'BB': R("99-22, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 64s+, 54s, "
            "A2o+, K9o+, Q9o+, J9o+, T9o"),
}
VS_3BET_4BET = {
    'UTG': R("KK+, AKs"), 'HJ': R("KK+, AKs, A5s"), 'CO': R("QQ+, AKs, A5s, A4s"),
    'BTN': R("QQ+, AKs, AKo, A5s, A4s"), 'SB': R("QQ+, AKs, A5s"), 'BB': R("KK+, AKs"),
}
VS_3BET_CALL = {
    'UTG': R("QQ-JJ, AQs, AKo"), 'HJ': R("QQ-TT, AQs, AJs, AKo, KQs"),
    'CO': R("JJ-99, AQs, AJs, AKo, KQs, KJs, QJs"),
    'BTN': R("JJ-88, AQs-ATs, AKo, KQs, KJs, QJs, JTs"),
    'SB': R("JJ-TT, AQs, AKo"), 'BB': R("QQ-TT, AQs, AKo, KQs"),
}
VS_4BET_CONT = R("KK+, AKs")
JAM_FIRST_IN = {
    'UTG': R("66+, ATs+, AJo+, KQs"), 'HJ': R("55+, A9s+, ATo+, KJs+, KQo"),
    'CO': R("44+, A7s+, A9o+, KTs+, KJo+, QJs"),
    'BTN': R("22+, A2s+, A7o+, A5o, K9s+, KTo+, Q9s+, QJo, J9s+, T9s"),
    'SB': R("22+, A2s+, A2o+, K5s+, K9o+, Q8s+, QTo+, J8s+, T8s+, 98s"),
    'BB': R("33+, A7s+, A9o+, KTs+, KQo, QJs"),
}
JAM_VS_RAISE = R("88+, ATs+, AQo+, KQs")

# === v9: heads-up (n == 2) preflop ranges ===
# HU is a different game: the dealer IS the SB and acts first preflop. The
# button should open ~80% and the BB defend ~65%+ (folding the button HU is a
# big leak). Widths are expressed via the strength-ordered HAND_RANK_ORDER
# (defend_top), with explicit value/bluff sets for 3-bet/4-bet. The v4 exploit
# layer + v5 all-in equity still apply on top of this HU baseline.
HU_SB_OPEN_FRAC   = 0.80    # button opens ~80% first-in
HU_BB_DEFEND_FRAC = 0.66    # BB continues ~66% vs a standard open (size-adjusted)
HU_BB_ISO_FRAC    = 0.28    # BB iso-raise range when SB limps
HU_BB_3BET        = R("99+, ATs+, A5s, A4s, KTs+, QTs+, JTs, AJo+, KQo")
HU_SB_4BET        = R("QQ+, AKs, AKo, A5s")
HU_SB_VS_3BET_CALL = R("88-22, A9s+, KTs+, QTs+, JTs, T9s, AQo, AJo, KQo")
HU_5BET_CONT      = R("KK+, AKs")
HU_JAM_SB_FRAC    = 0.62    # short-stack button jams wide
HU_JAM_DEF_FRAC   = 0.45    # short-stack call/jam vs a raise


# ===========================================================================
# ===================== SIZE-AWARE PREFLOP DEFENSE (v3.5) ===================
# ===========================================================================

# --- 169-hand strength ordering (Patch 3 percentile-fallback source) --------
# Generated from a simple, complete preflop-strength heuristic so the fallback
# covers ALL 169 classes. source: generated (heuristic), not solver output.
def _build_hand_rank_order():
    hands = []
    for a in range(13):
        for b in range(13):
            if a == b:
                hands.append(RANKS[a] * 2)
            elif a > b:
                hands.append(RANKS[a] + RANKS[b] + "s")
                hands.append(RANKS[a] + RANKS[b] + "o")

    def score(cls):
        if len(cls) == 2:                       # pocket pair
            return 140 + RANK_VAL[cls[0]] * 10
        hi, lo = RANK_VAL[cls[0]], RANK_VAL[cls[1]]
        suited = cls[2] == "s"
        s = hi * 5 + lo * 3
        gap = hi - lo
        if gap == 1:
            s += 6
        elif gap == 2:
            s += 3
        elif gap == 3:
            s += 1
        if suited:
            s += 8
        if lo >= RANK_VAL["T"]:
            s += 6                               # both broadway
        if cls[0] == "A":
            s += 4                               # ace blockers / nut potential
        return s

    return sorted(hands, key=score, reverse=True)


HAND_RANK_ORDER = _build_hand_rank_order()       # 169 classes, strongest first
N_HANDS = len(HAND_RANK_ORDER)


def defend_top(frac):
    """Top `frac` of all hands by strength (percentile fallback range)."""
    k = max(1, min(N_HANDS, int(round(N_HANDS * frac))))
    return set(HAND_RANK_ORDER[:k])


def classify_raise_size(amount_to_call, big_blind=DEFAULT_BB):
    """Bucket a raise by what it costs us to call, in big blinds."""
    bb = big_blind or DEFAULT_BB
    if amount_to_call <= 1.5 * bb:
        return "min_raise"        # ~2bb total — defend very wide
    if amount_to_call <= 2.5 * bb:
        return "small_raise"      # ~2.5-3bb — defend wide
    if amount_to_call <= 4.0 * bb:
        return "standard_raise"   # ~3-5bb — current behavior
    if amount_to_call <= 7.0 * bb:
        return "large_raise"      # ~5-8bb — tight
    return "huge_raise"           # 8bb+ — very tight


# Defense width (fraction of all hands) at BB; scaled down by position factor.
# Only min/small (widen) and large/huge (tighten) use these; standard uses the
# existing hand-authored ranges unchanged.
DEFEND_WIDTH_OPEN = {
    "min_raise": 0.80, "small_raise": 0.55, "large_raise": 0.22, "huge_raise": 0.12,
}
DEFEND_WIDTH_3BET = {
    "min_raise": 0.30, "small_raise": 0.20, "large_raise": 0.09, "huge_raise": 0.055,
}
POS_DEFEND_FACTOR = {"BB": 1.0, "SB": 0.80, "BTN": 0.70, "CO": 0.62, "HJ": 0.52, "UTG": 0.45}


def size_aware_open_defense(pos, steal, bucket, hand):
    """Return 'raise' (3-bet), 'call', or 'fold' facing a single raise."""
    base_3bet = (BLIND_DEFEND_3BET if steal else VS_OPEN_3BET).get(pos, set())
    base_call = (BLIND_DEFEND_CALL if steal else VS_OPEN_CALL).get(pos, set())
    threebet = base_3bet
    if bucket in ("min_raise", "small_raise"):
        # Widen defense: we get great odds vs a small raise, so defend wider
        # by unioning the existing range with a percentile range.
        width = DEFEND_WIDTH_OPEN[bucket] * POS_DEFEND_FACTOR.get(pos, 0.6)
        call = (base_call | base_3bet | defend_top(width)) - threebet
    else:
        # standard / large / huge -> existing ranges unchanged.
        # Opponent-AGNOSTIC tightening vs large raises is a wash (good vs honest
        # big-openers like shark, bad vs maniacs whose big raises are wide);
        # paired testing showed widen-only is pure upside with zero regression.
        # Correct large-raise tightening is deferred to v4 (needs opener range
        # strength). DEFEND_WIDTH_OPEN large/huge keys are kept as that hook.
        call = base_call
    if hand in threebet:
        return "raise"
    if hand in call:
        return "call"
    return "fold"


def size_aware_3bet_defense(pos, bucket, hand):
    """Return '4bet', 'call', or 'fold' facing a 3-bet."""
    base_4bet = VS_3BET_4BET.get(pos, set())
    base_call = VS_3BET_CALL.get(pos, set())
    fourbet = base_4bet
    if bucket in ("min_raise", "small_raise"):
        width = DEFEND_WIDTH_3BET[bucket] * POS_DEFEND_FACTOR.get(pos, 0.6)
        call = (base_call | base_4bet | defend_top(width)) - fourbet
    else:
        call = base_call                                # standard/large/huge: existing
    if hand in fourbet:
        return "4bet"
    if hand in call:
        return "call"
    return "fold"


def hand_class(cards):
    r0, r1 = cards[0][0], cards[1][0]
    if r0 == r1:
        return r0 + r1
    if RANK_VAL[r0] < RANK_VAL[r1]:
        r0, r1 = r1, r0
    suited = cards[0][1] == cards[1][1]
    return r0 + r1 + ("s" if suited else "o")


def get_positions(state):
    players = state.get("players", []) or []
    n = len(players)
    sb = bb = None
    for e in state.get("action_log", []) or []:
        if e.get("action") == "small_blind":
            sb = e.get("seat")
        elif e.get("action") == "big_blind":
            bb = e.get("seat")
    if sb is None or bb is None or n == 0:
        return 0, max(n, 2), 0, min(1, max(n - 1, 0))
    button = sb if n == 2 else (sb - 1) % n
    return button, n, sb, bb


def position_label(seat, button, n):
    rel = (seat - button) % n
    if n == 2:
        return "SB" if rel == 0 else "BB"
    if rel == 0:
        return "BTN"
    if rel == 1:
        return "SB"
    if rel == 2:
        return "BB"
    if rel == n - 1:
        return "CO"
    if rel == 3:
        return "UTG"
    return "HJ"


def preflop_context(state):
    raises = 0
    last_raiser = None
    bb_amt = DEFAULT_BB
    limpers = 0
    for e in state.get("action_log", []) or []:
        a = e.get("action")
        if a == "big_blind":
            bb_amt = e.get("amount") or DEFAULT_BB
        elif a in ("raise", "all_in"):
            raises += 1
            last_raiser = e.get("seat")
        elif a == "call" and raises == 0:
            limpers += 1
    return raises, last_raiser, bb_amt, limpers


def _is_in_position(hero_rel, villain_rel, n):
    def order(rel):
        return rel - 1 if rel >= 1 else n - 1
    return order(hero_rel) > order(villain_rel)


def open_size(state, bb_amt, n_limpers):
    to = int(2.5 * bb_amt) + bb_amt * n_limpers
    return max(to, state.get("min_raise_to", to))


def threebet_size(state, ip):
    cur = state.get("current_bet", DEFAULT_BB)
    return max(int(cur * (3.0 if ip else 4.0)), state.get("min_raise_to", cur))


def fourbet_size(state):
    cur = state.get("current_bet", DEFAULT_BB)
    return max(int(cur * 2.3), state.get("min_raise_to", cur))


def hu_preflop_decision(state, p, pos, raises, bb_amt, eff_bb):
    """Heads-up preflop. SB == dealer/button (acts first preflop, in position
    postflop). Ranges are much wider than 6-max."""
    hand = hand_class(p["cards"])
    can_check = p["can_check"]

    # Short-stack push/fold (wide HU).
    if eff_bb <= SHORT_STACK_BB:
        if raises == 0:
            if pos == "SB":
                return {"action": "all_in"} if hand in defend_top(HU_JAM_SB_FRAC) \
                    else ({"action": "check"} if can_check else {"action": "fold"})
            if can_check:                               # BB with the option
                return {"action": "all_in"} if hand in defend_top(0.50) else {"action": "check"}
            return {"action": "fold"}
        return {"action": "all_in"} if hand in defend_top(HU_JAM_DEF_FRAC) \
            else ({"action": "check"} if can_check else {"action": "fold"})

    # Unopened.
    if raises == 0:
        if pos == "SB":                                 # button first-in: open wide or fold
            if hand in defend_top(HU_SB_OPEN_FRAC):
                return {"action": "raise", "amount": open_size(state, bb_amt, 0)}
            return {"action": "check"} if can_check else {"action": "fold"}
        if can_check:                                   # BB, SB limped: iso or check (never fold free)
            if hand in defend_top(HU_BB_ISO_FRAC):
                return {"action": "raise", "amount": open_size(state, bb_amt, 1)}
            return {"action": "check"}
        return {"action": "fold"}

    # Facing a single raise (usually BB vs the SB open).
    if raises == 1:
        bucket = classify_raise_size(p["owed"], bb_amt)
        if hand in HU_BB_3BET:
            return {"action": "raise", "amount": threebet_size(state, pos == "SB")}
        frac = HU_BB_DEFEND_FRAC
        if bucket in ("min_raise", "small_raise"):
            frac = min(0.95, frac + 0.20)
        elif bucket in ("large_raise", "huge_raise"):
            frac = frac * 0.60
        if hand in defend_top(frac):
            return {"action": "call"}
        return {"action": "check"} if can_check else {"action": "fold"}

    # Facing a 3-bet (usually SB vs the BB 3-bet).
    if raises == 2:
        bucket = classify_raise_size(p["owed"], bb_amt)
        if hand in HU_SB_4BET:
            return {"action": "raise", "amount": fourbet_size(state)}
        callset = HU_SB_VS_3BET_CALL
        if bucket in ("min_raise", "small_raise"):
            callset = callset | defend_top(0.28)
        elif bucket in ("large_raise", "huge_raise"):
            callset = callset & defend_top(0.12)
        if hand in callset:
            return {"action": "call"}
        return {"action": "check"} if can_check else {"action": "fold"}

    # Facing a 4-bet or beyond.
    # v14 (D2 patch): deep HU AKs flat-calls instead of 5-bet-shoves (mirrors
    # the full-ring patch). HU 5-bet range tightens to KK+ when deep.
    if hand in HU_5BET_CONT:
        if eff_bb > 30 and hand == "AKs":
            return {"action": "call"}
        return {"action": "all_in"}
    return {"action": "check"} if can_check else {"action": "fold"}


def preflop_decision(state, p):
    cards = p["cards"]
    hand = hand_class(cards)
    button, n, sb, bb = get_positions(state)
    pos = position_label(p["seat"], button, n)
    raises, last_raiser, bb_amt, n_limpers = preflop_context(state)
    eff_bb = p["stack"] / bb_amt if bb_amt else 100

    # v5: facing a preflop all-in -> decide by equity vs pot odds (P34 table).
    if len(cards) == 2 and _preflop_facing_allin(state):
        n_opp = max(1, _n_live_opponents(state))
        return preflop_allin_equity_decision(state, p, n_opp)

    # v9: heads-up gets its own (much wider) preflop ranges. 6-max is unchanged.
    if n == 2:
        return hu_preflop_decision(state, p, pos, raises, bb_amt, eff_bb)

    if eff_bb <= SHORT_STACK_BB:
        if raises == 0:
            if pos == "BB" and p["can_check"]:
                return {"action": "all_in"} if hand in JAM_FIRST_IN.get("BB", set()) else {"action": "check"}
            if hand in JAM_FIRST_IN.get(pos, set()):
                return {"action": "all_in"}
            return {"action": "check"} if p["can_check"] else {"action": "fold"}
        if hand in JAM_VS_RAISE:
            return {"action": "all_in"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    if raises == 0:
        if pos == "BB" and p["can_check"]:
            if hand in OPEN["BB"]:
                return {"action": "raise", "amount": open_size(state, bb_amt, n_limpers)}
            return {"action": "check"}
        if hand in OPEN.get(pos, set()):
            return {"action": "raise", "amount": open_size(state, bb_amt, n_limpers)}
        # v4: steal-widen vs proven over-folders. Only ADDS opens vs confirmed
        # folders -> cannot regress against anyone else.
        if pos in ("SB", "BTN", "CO", "HJ"):
            fr = opponents_fold_read(state)
            if fr is not None and fr > 0.6:
                extra = min(0.45, (fr - 0.6) * 2.0)
                base_pct = len(OPEN.get(pos, ())) / float(N_HANDS)
                if hand in defend_top(min(0.95, base_pct + extra)):
                    return {"action": "raise", "amount": open_size(state, bb_amt, n_limpers)}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    if raises == 1:
        villain_pos = position_label(last_raiser, button, n) if last_raiser is not None else "CO"
        steal = pos in ("SB", "BB") and villain_pos in ("CO", "BTN", "SB")
        bucket = classify_raise_size(p["owed"], bb_amt)
        action = size_aware_open_defense(pos, steal, bucket, hand)
        if action == "raise":
            hero_rel = (p["seat"] - button) % n
            vill_rel = (last_raiser - button) % n if last_raiser is not None else 0
            return {"action": "raise", "amount": threebet_size(state, _is_in_position(hero_rel, vill_rel, n))}
        if action == "call":
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    if raises == 2:
        bucket = classify_raise_size(p["owed"], bb_amt)
        action = size_aware_3bet_defense(pos, bucket, hand)
        if action == "4bet":
            return {"action": "raise", "amount": fourbet_size(state)}
        if action == "call":
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    # Facing a 4-bet or beyond: continue with the top; widen slightly vs a small 4bet.
    # v14 (D2 patch): stack-depth-aware 5-bet-jam response. Qualifier hand
    # histories showed 101 preflop-aggressor-all-in losses, avg -18.4k chips/hand
    # (the #1 leak by far). Root cause: v13 5-bet-shoves AKs (and KK) blindly
    # against any 4-bet regardless of effective stack -- against the real field
    # that 4-bets value-heavy, deep 5-bet shoves with AKs / KK are -EV. The fix:
    # when deep-stacked (>30bb) and facing a 4-bet, downgrade AKs from shove to
    # FLAT CALL (preserves implied odds, postflop tier handles the spot). KK+
    # still shoves (they're ahead of even tight 4-bet calling ranges).
    bucket = classify_raise_size(p["owed"], bb_amt)
    cont = VS_4BET_CONT | R("QQ, AKo") if bucket in ("min_raise", "small_raise") else VS_4BET_CONT
    if hand in cont:
        if eff_bb > 30 and hand == "AKs" and bucket not in ("min_raise", "small_raise"):
            return {"action": "call"}      # deep AKs vs a real 4-bet: flat-call
        return {"action": "all_in"}
    return {"action": "check"} if p["can_check"] else {"action": "fold"}


# ===========================================================================
# ============================ POSTFLOP (new) ===============================
# ===========================================================================

# ---- Card helpers ----------------------------------------------------------

def _vals(cards):
    return [RANK_VAL[c[0]] for c in cards]


def _has_straight(valset):
    lo = -1 if 12 in valset else 0
    for start in range(lo, 9):
        if all((start + i if start + i >= 0 else 12) in valset or (start + i) in valset
               for i in range(5)):
            # normalize: treat -1 as ace-low handled by including 12
            seq = set()
            for i in range(5):
                v = start + i
                seq.add(12 if v < 0 else v)
            if seq <= valset:
                return True
    return False


def _straight_completions(valset):
    present = set(valset)
    if 12 in present:
        present.add(-1)
    comps = set()
    for d in range(-1, 13):
        if d in present:
            continue
        s = set(present)
        s.add(d)
        # check 5 consecutive
        for start in range(-1, 9):
            if all((start + i) in s for i in range(5)):
                comps.add(d if d >= 0 else 12)
                break
    return len(comps)


# ---- Hand strength bucket (12) --------------------------------------------

def hand_strength_bucket(hole, board):
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
        v0, v1 = RANK_VAL[h0], RANK_VAL[h1]
        top = board_vals[0]
        if h0 == h1:  # pocket pair
            if v0 > top:
                return "overpair"
            return "third_pair_or_underpair"
        # one hole card pairs the board
        paired_val = v0 if v0 in _vals(board) else (v1 if v1 in _vals(board) else None)
        kicker_val = v1 if paired_val == v0 else v0
        if paired_val is None:
            return "weak_showdown"
        rank_idx = board_vals.index(paired_val) if paired_val in board_vals else 99
        if rank_idx == 0:
            return "strong_top_pair" if kicker_val >= RANK_VAL["T"] else "weak_top_pair"
        if rank_idx == 1:
            return "second_pair"
        return "third_pair_or_underpair"
    # High card
    board_top = max(_vals(board))
    overcards = sum(1 for c in hole if RANK_VAL[c[0]] > board_top)
    if overcards >= 2 or any(c[0] == "A" for c in hole):
        return "weak_showdown"
    return "air"


# ---- Board texture bucket --------------------------------------------------

def board_texture_bucket(board):
    vals = _vals(board)
    suits = [c[1] for c in board]
    distinct = sorted(set(vals))
    top = max(vals)
    suit_counts = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
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
    allbroadway = all(v >= RANK_VAL["T"] for v in vals)
    if allbroadway and connected:
        return "broadway_connected"
    if connected and top <= RANK_VAL["9"]:
        return "low_connected"
    if connected:
        return "connected"
    if maxsuit == 2:
        return "two_tone"
    if top == RANK_VAL["A"]:
        return "A_high_dry"
    if top == RANK_VAL["K"]:
        return "K_high_dry"
    return "disconnected_low"


# ---- Draw bucket -----------------------------------------------------------

def draw_bucket(hole, board):
    if len(board) >= 5:
        return "no_draw"
    combined = hole + board
    suit_counts = {}
    for c in combined:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    flush4 = any(v == 4 for v in suit_counts.values())
    nut_flush = False
    if flush4:
        fs = [s for s, v in suit_counts.items() if v == 4][0]
        nut_flush = any(c[0] == "A" and c[1] == fs for c in hole)

    valset = set(RANK_VAL[c[0]] for c in combined)
    comps = _straight_completions(valset)
    oesd = comps >= 2
    gutshot = comps == 1

    if flush4 and (oesd or gutshot):
        return "combo_draw"
    if nut_flush:
        return "nut_draw"
    if flush4:
        return "flush_draw"
    if oesd:
        return "OESD"
    if gutshot:
        return "gutshot"
    if len(board) == 3 and any(v == 3 for v in suit_counts.values()):
        return "backdoor"
    return "no_draw"


# ---- SPR / position / facing ----------------------------------------------

def spr_bucket(stack, pot):
    if pot <= 0:
        return "6-10"
    spr = stack / pot
    if spr < 1:
        return "<1"
    if spr < 3:
        return "1-3"
    if spr < 6:
        return "3-6"
    if spr < 10:
        return "6-10"
    return ">=10"


def postflop_position(state):
    button, n, sb, bb = get_positions(state)
    players = state.get("players", []) or []
    seat = state.get("seat_to_act", 0)
    active = [i for i, p in enumerate(players)
             if not p.get("is_folded") and p.get("state") != "busted"]
    if len(active) <= 1:
        return "IP"

    def order(s):
        rel = (s - button) % n
        return rel - 1 if rel >= 1 else n - 1

    mine = order(seat)
    others = [order(s) for s in active if s != seat]
    if all(mine > o for o in others):
        return "IP"
    if all(mine < o for o in others):
        return "OOP"
    return "sandwiched"


def _n_live_opponents(state):
    """Opponents still in the hand (not folded, not busted), excluding hero."""
    players = state.get("players", []) or []
    seat = state.get("seat_to_act", 0)
    n = 0
    for i, p in enumerate(players):
        if i == seat:
            continue
        if not p.get("is_folded") and p.get("state") != "busted":
            n += 1
    return n


def bucket_bet_size(bet_amount, pot_at_time):
    """Patch 10: map any bet to a generous size bucket. Used both when reading a
    bet we face and (in v7+) when reading prior actions — so irregular sizes
    (29%/71%/113%) bucket the same as 33%/66%/100%."""
    if pot_at_time <= 0:
        return "min_bet"
    ratio = bet_amount / pot_at_time
    if ratio < 0.20:
        return "tiny_bet"
    if ratio < 0.45:
        return "small_bet"
    if ratio < 0.80:
        return "medium_bet"
    if ratio < 1.20:
        return "pot_bet"
    if ratio < 2.00:
        return "overbet"
    return "huge_overbet"


# Generic size bucket -> the facing-action infoset category used by the
# postflop strategy table.
_FACING_FROM_SIZE = {
    "min_bet": "facing_small", "tiny_bet": "facing_small", "small_bet": "facing_small",
    "medium_bet": "facing_half", "pot_bet": "facing_pot",
    "overbet": "facing_overbet", "huge_overbet": "facing_overbet",
}


def facing_bucket(state):
    if state.get("can_check"):
        return "checked_to"
    if state.get("your_bet_this_street", 0) > 0:
        return "facing_raise"
    owed = state.get("amount_owed", 0)
    pot = state.get("pot", 0)
    return _FACING_FROM_SIZE[bucket_bet_size(owed, max(pot - owed, 1))]


# ---- Authored strategy generator ------------------------------------------

STRONG_MADE = {"two_pair", "set_or_trips", "straight", "flush",
               "full_house_or_better", "overpair"}
GOOD_MADE = {"strong_top_pair"}
MEDIUM_MADE = {"weak_top_pair", "second_pair"}
WEAK_MADE = {"third_pair_or_underpair", "weak_showdown"}
STRONG_DRAWS = {"flush_draw", "OESD", "combo_draw", "nut_draw"}
WEAK_DRAWS = {"gutshot", "backdoor"}


def river_value_respect(dist, state, p, hs, opp_id):
    """Phase-2 fix for the river over-call leak. Facing a RIVER bet with a
    marginal (non-strong) hand vs an opponent NOT flagged as a bluffer, fold a
    little more — the field's river bets skew value-heavy and our action-only
    stats can't flag a value-heavy river bettor. Gated OFF vs flagged bluffers
    (so we still pay off genuine bluffs), bounded, scaled by bet size."""
    if RIVER_FOLD <= 0 or state.get("street") not in ("turn", "river") or state.get("can_check"):
        return dist
    if hs in STRONG_MADE:                      # value hands keep calling/raising
        return dist
    bluff = stat_mean(opp_id, "bluff_propensity") if opp_id else 0.35
    agg = stat_mean(opp_id, "aggression") if opp_id else 0.25
    if bluff > 0.45 or agg > 0.45:             # known bluffer/maniac -> don't fold to bluffs
        return dist
    owed = state.get("amount_owed", 0)
    pot = state.get("pot", 0)
    ratio = owed / max(pot - owed, 1)          # bigger river bet = more value-weighted
    shift = RIVER_FOLD * min(1.0, ratio)
    d = dict(dist)
    if d.get("call", 0.0) > 0:
        mv = d["call"] * shift
        d["call"] -= mv
        d["fold"] = d.get("fold", 0.0) + mv
    return _norm(d)


# ---- v8: river blocker awareness ------------------------------------------

def river_flush_blocker(hole, board, hand_bucket):
    """True iff a flush is possible (exactly 3 of one suit on a 5-card board)
    and we hold the nut-flush blocker of that suit WITHOUT a made flush — i.e.
    we hold villain's nut card, removing nut-flush combos from their range."""
    if len(board) < 5 or hand_bucket in ("flush", "full_house_or_better"):
        return False
    suit_counts = {}
    for c in board:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    for suit, cnt in suit_counts.items():
        if cnt != 3:                       # 4-flush => holding the A *is* a made flush
            continue
        board_ranks = {c[0] for c in board if c[1] == suit}
        hole_ranks = {c[0] for c in hole if c[1] == suit}
        if len(hole_ranks) >= 2:           # we'd have a flush ourselves
            continue
        if "A" not in board_ranks and "A" in hole_ranks:
            return True
        if "A" in board_ranks and "K" not in board_ranks and "K" in hole_ranks:
            return True
    return False


def river_blocker_adjust(dist, state, p, hs, facing, opp_id):
    """Bounded, river-only nut-flush-blocker nudge (see module docstring)."""
    if state.get("street") != "river":
        return dist
    if not river_flush_blocker(p["cards"], state.get("community_cards", []) or [], hs):
        return dist
    shift = 0.12
    d = dict(dist)
    bluff_candidate = hs not in STRONG_MADE and hs not in GOOD_MADE and hs not in MEDIUM_MADE
    if facing == "checked_to":
        if bluff_candidate:
            f = stat_mean(opp_id, "fold_to_bet") if opp_id else 0.5
            if opp_id is None or f >= 0.35:          # don't bluff a confirmed station
                mv = shift * d.get("check", 0.0)
                d["bet_66"] = d.get("bet_66", 0.0) + mv
                d["check"] = d.get("check", 0.0) - mv
    else:                                            # facing a bet: bluff-catch a bit more
        if hs not in STRONG_MADE and d.get("fold", 0.0) > 0:
            mv = shift * d["fold"]
            d["fold"] -= mv
            d["call"] = d.get("call", 0.0) + mv
    return _norm(d)


def _norm(d):
    tot = sum(v for v in d.values() if v > 0)
    if tot <= 0:
        return {"check": 1.0} if "check" in d else {"fold": 1.0}
    return {k: v / tot for k, v in d.items() if v > 0}


def strategy_checked_to(hs, texture, draw, spr, pos):
    ip = pos == "IP"
    multiway = pos == "sandwiched"
    dry = texture in ("A_high_dry", "K_high_dry", "disconnected_low")

    if hs in STRONG_MADE:
        if spr == "<1":
            d = {"all_in": 0.35, "bet_100": 0.35, "bet_66": 0.2, "check": 0.1}
        else:
            d = {"bet_66": 0.5, "bet_100": 0.25, "bet_33": 0.1, "check": 0.15}
    elif hs in GOOD_MADE:
        d = {"bet_66": 0.5, "bet_33": 0.2, "check": 0.3}
    elif hs in MEDIUM_MADE:
        d = {"bet_33": 0.35, "check": 0.65}
    elif draw in STRONG_DRAWS:
        d = {"bet_66": 0.5, "bet_33": 0.1, "check": 0.4} if ip else {"bet_66": 0.4, "check": 0.6}
    elif draw in WEAK_DRAWS:
        d = {"bet_33": 0.25, "check": 0.75}
    elif hs == "weak_showdown":
        d = {"check": 0.9, "bet_33": 0.1}
    else:  # air
        if ip and dry:
            d = {"bet_66": 0.35, "bet_33": 0.1, "check": 0.55}
        else:
            d = {"bet_33": 0.18, "check": 0.82}

    if multiway:  # provisional shrink; full multiway logic arrives in v3
        shifted = {}
        moved = 0.0
        for k, v in d.items():
            if k.startswith("bet") or k == "all_in":
                shifted[k] = v * 0.4
                moved += v * 0.6
            else:
                shifted[k] = v
        shifted["check"] = shifted.get("check", 0.0) + moved
        d = shifted
    elif not ip:  # OOP: a touch more checking
        moved = 0.0
        for k in list(d.keys()):
            if k.startswith("bet"):
                moved += d[k] * 0.15
                d[k] *= 0.85
        d["check"] = d.get("check", 0.0) + moved
    return _norm(d)


def strategy_facing(hs, texture, draw, spr, pos, facing):
    pressure = {"facing_small": 0, "facing_half": 1, "facing_pot": 2,
                "facing_overbet": 3, "facing_raise": 3}.get(facing, 1)

    if hs in STRONG_MADE:
        d = {"raise_pot": 0.4, "raise_value": 0.2, "call": 0.4}
        if spr == "<1" or pressure >= 2:
            d = {"all_in": 0.3, "raise_pot": 0.25, "call": 0.45}
    elif hs in GOOD_MADE or hs == "overpair":
        base = {"call": 0.7, "raise_value": 0.15, "fold": 0.15}
        fold_bonus = 0.12 * pressure
        base["fold"] += fold_bonus
        base["call"] = max(0.0, base["call"] - fold_bonus)
        base["raise_value"] = max(0.0, base["raise_value"] - 0.03 * pressure)
        d = base
    elif hs in MEDIUM_MADE:
        if pressure <= 0:
            d = {"call": 0.75, "fold": 0.2, "raise_value": 0.05}
        elif pressure == 1:
            d = {"call": 0.62, "fold": 0.38}
        elif pressure == 2:
            d = {"call": 0.4, "fold": 0.6}
        else:
            d = {"call": 0.18, "fold": 0.82}
    elif draw in STRONG_DRAWS:
        if pressure <= 0:
            d = {"call": 0.5, "raise_pot": 0.3, "fold": 0.2}
        elif pressure == 1:
            d = {"call": 0.6, "raise_pot": 0.1, "fold": 0.3}
        elif pressure == 2:
            d = {"call": 0.5, "fold": 0.5}
        else:
            d = {"call": 0.35, "fold": 0.65}
    elif draw in WEAK_DRAWS or hs == "weak_showdown":
        if pressure <= 0:
            d = {"call": 0.45, "fold": 0.5, "raise_pot": 0.05}
        elif pressure == 1:
            d = {"call": 0.3, "fold": 0.7}
        else:
            d = {"call": 0.1, "fold": 0.9}
    else:  # air — fold a lot, occasional bluff-raise vs small bets
        if pressure <= 0:
            d = {"fold": 0.85, "raise_pot": 0.15}
        elif pressure == 1:
            d = {"fold": 0.92, "raise_pot": 0.08}
        else:
            d = {"fold": 1.0}

    if pos == "sandwiched":  # don't bluff-raise into multiple players
        if "raise_pot" in d:
            d["call"] = d.get("call", 0.0) + d["raise_pot"] * 0.5
            d["fold"] = d.get("fold", 0.0) + d["raise_pot"] * 0.5
            d.pop("raise_pot")
        if "raise_value" in d:
            d["call"] = d.get("call", 0.0) + d["raise_value"]
            d.pop("raise_value")
    return _norm(d)


def lookup_strategy(infoset_key, components, facing):
    # CFR drop-in override first (empty in v2), then the authored generator.
    if infoset_key in POSTFLOP_STRATEGY_TABLE:
        return POSTFLOP_STRATEGY_TABLE[infoset_key]
    hs, texture, draw, spr, pos = components
    if facing == "checked_to":
        return strategy_checked_to(hs, texture, draw, spr, pos)
    return strategy_facing(hs, texture, draw, spr, pos, facing)


# ---- Multiway tightening (v3, Layer 1 / rules-only) ------------------------
# brief P9 prescribes {bluff_freq_mult, size_mult<1, call_threshold}. Paired
# testing showed the two tightening levers (bluff_freq_mult, call_tighten) are
# clearly +EV multiway, but the brief's size_mult<1 was NET-NEGATIVE: shrinking
# value bets bleeds EV against the call-heavy opponents who dominate multiway
# pots. So size_mult is held at 1.0 here (the hook stays for v4's opponent model
# to tune per-villain — e.g. size UP vs stations).
N_OPP_ADJUSTMENTS = {
    1: {"bluff_freq_mult": 1.0,  "size_mult": 1.0, "call_tighten": 0.00},
    2: {"bluff_freq_mult": 0.30, "size_mult": 1.0, "call_tighten": 0.15},
    3: {"bluff_freq_mult": 0.05, "size_mult": 1.0, "call_tighten": 0.30},
    4: {"bluff_freq_mult": 0.02, "size_mult": 1.0, "call_tighten": 0.45},
    5: {"bluff_freq_mult": 0.00, "size_mult": 1.0, "call_tighten": 0.55},
}

AGG_ACTIONS = ("bet_33", "bet_66", "bet_100", "bet_150", "raise_value",
               "raise_pot", "all_in")


def multiway_adjust(dist, n_opp, hs, draw, facing):
    """Shrink bluffs / tighten marginal continues for multiway pots.
    Returns dist unchanged when heads-up (n_opp <= 1)."""
    if n_opp <= 1:
        return dist
    adj = N_OPP_ADJUSTMENTS[min(n_opp, 5)]
    bf = adj["bluff_freq_mult"]
    is_value = hs in STRONG_MADE or hs in GOOD_MADE
    strong_draw = draw in STRONG_DRAWS
    d = dict(dist)

    # 1) Cut bluffs: aggressive actions taken WITHOUT a value hand or a strong
    #    (semi-bluff) draw are bluffs — scale them down by bluff_freq_mult and
    #    move the freed probability to the passive option.
    if not is_value and not strong_draw:
        moved = 0.0
        for k in list(d):
            if k in AGG_ACTIONS:
                keep = d[k] * bf
                moved += d[k] - keep
                d[k] = keep
        passive = "check" if facing == "checked_to" else "fold"
        d[passive] = d.get(passive, 0.0) + moved

    # 2) Tighten marginal calls: facing a bet with a non-strong hand, shift
    #    some calling frequency to folding (need a stronger hand multiway).
    if facing != "checked_to" and not is_value and "call" in d:
        if hs in MEDIUM_MADE or hs == "weak_showdown" or draw in WEAK_DRAWS or hs == "air":
            shift = min(d["call"], adj["call_tighten"])
            d["call"] -= shift
            d["fold"] = d.get("fold", 0.0) + shift

    return _norm(d)


# ===========================================================================
# ======================= OPPONENT MODELING (v4) ============================
# ===========================================================================

# Per-opponent Beta(alpha, beta) stats keyed by bot_id. Module globals persist
# across the 400 hands of ONE match and reset between matches (fresh process).
OPPONENT_STATS = {}
PROCESSED_HANDS = set()

# Deliberately WEAK priors (sum ~10 pseudo-counts). The brief's (25,75)-style
# priors total 100 pseudo-counts, which swamp the ~30-150 real observations we
# get on an opponent in one match — stats would barely move and perturbation
# would never fire. Weak priors keep the same prior MEANS but let real data
# dominate quickly, which is the whole point of in-match adaptation.
PRIORS = {
    "fold_to_bet":      (4.5, 5.5),   # ~45% fold when facing a bet
    "aggression":       (2.5, 7.5),   # ~25% of actions are bet/raise/all_in
    "shove_frequency":  (0.3, 9.7),   # ~3% of actions are all-in (maniac sensor)
    "bluff_propensity": (3.0, 7.0),   # aggressive-then-folded within a hand (P33)
}
MIN_OBS = 10        # need this many observed actions before we adapt
LAMBDA_CAP = 0.30   # bounded perturbation


def parse_hand_num(hand_id):
    if not hand_id:
        return None
    m = re.search(r"h(\d+)$", str(hand_id))
    return int(m.group(1)) if m else None


def aggression_modifier(state):
    """Patch 12: mild [0.97, 1.05] multiplier on bet/raise frequencies, only in
    the last ~50 hands, weighted primarily by hands_remaining (cash format, not
    ICM). Graceful 1.0 if hand_num is unknown."""
    hn = parse_hand_num(state.get("hand_id", ""))
    if hn is None or (HANDS_PER_MATCH - hn) > 50:
        return 1.0
    delta_ratio = state.get("your_stack", 0) / 10000.0
    if delta_ratio < 0.5:
        return 1.05
    if delta_ratio < 0.8:
        return 1.02
    if delta_ratio > 2.0:
        return 0.97
    if delta_ratio > 1.5:
        return 0.99
    return 1.0


def apply_aggression_modifier(dist, state):
    m = aggression_modifier(state)
    if m == 1.0:
        return dist
    d = dict(dist)
    for k in list(d):
        if k.startswith("bet") or k.startswith("raise") or k == "all_in":
            d[k] *= m
    return _norm(d)


def _ensure(bot_id):
    if bot_id not in OPPONENT_STATS:
        OPPONENT_STATS[bot_id] = {k: [a, b] for k, (a, b) in PRIORS.items()}
    return OPPONENT_STATS[bot_id]


def update_stat(bot_id, stat, success):
    s = _ensure(bot_id)[stat]
    if success:
        s[0] += 1
    else:
        s[1] += 1


def _ab(bot_id, stat):
    if bot_id in OPPONENT_STATS:
        a, b = OPPONENT_STATS[bot_id][stat]
    else:
        a, b = PRIORS[stat]
    return a, b


def stat_mean(bot_id, stat):
    a, b = _ab(bot_id, stat)
    return a / (a + b) if (a + b) else 0.5


def wilson_ci(a, b):
    """Patch 6: cheap normal/Wilson 90% CI for a Beta(a,b) posterior."""
    n = a + b
    if n <= 0:
        return 0.5, 0.0, 1.0
    mean = a / n
    se = math.sqrt(max(mean * (1.0 - mean), 0.0) / n)
    half = 1.645 * se
    return mean, max(0.0, mean - half), min(1.0, mean + half)


def process_hand_actions(entries):
    """Accumulate stats from one COMPLETED hand's ordered action entries."""
    by_bot = {}
    for e in entries:
        bid, act = e.get("bot_id"), e.get("action")
        if bid is None or act is None:
            continue
        by_bot.setdefault(bid, []).append(act)
    for bid, acts in by_bot.items():
        had_agg = False
        gave_up = False
        for act in acts:
            update_stat(bid, "aggression", act in ("raise", "all_in"))
            update_stat(bid, "shove_frequency", act == "all_in")
            if act == "fold":
                update_stat(bid, "fold_to_bet", True)
            elif act == "call":
                update_stat(bid, "fold_to_bet", False)
            if act in ("raise", "all_in"):
                had_agg = True
            elif act == "fold" and had_agg:
                gave_up = True
        if had_agg:
            update_stat(bid, "bluff_propensity", gave_up)


def update_opponent_memory(state):
    """Patch 1: process completed hands at hand boundaries, deduped."""
    cur = parse_hand_num(state.get("hand_id", ""))
    if cur is None:
        return
    by_hand = {}
    for e in state.get("match_action_log", []) or []:
        hn = e.get("hand_num")
        if hn is None or hn == cur or hn in PROCESSED_HANDS:
            continue
        by_hand.setdefault(hn, []).append(e)
    for hn in sorted(by_hand):
        process_hand_actions(by_hand[hn])
        PROCESSED_HANDS.add(hn)


def compute_lambda(opp_id):
    """Confidence-gated blend weight in [0, LAMBDA_CAP]."""
    if opp_id is None or opp_id not in OPPONENT_STATS:
        return 0.0
    a, b = OPPONENT_STATS[opp_id]["aggression"]
    n_obs = (a + b) - sum(PRIORS["aggression"])      # actions actually observed
    if n_obs < MIN_OBS:
        return 0.0
    data_factor = min(1.0, (n_obs - MIN_OBS) / 40.0)
    fa, fb = OPPONENT_STATS[opp_id]["fold_to_bet"]
    _, lo, hi = wilson_ci(fa, fb)
    conf = max(0.0, 1.0 - (hi - lo))                  # tight CI -> confident
    return min(LAMBDA_CAP, LAMBDA_CAP * data_factor * (0.5 + 0.5 * conf))


def relevant_opponent_id(state):
    """bot_id of the opponent our decision is 'against': the last aggressor when
    facing a bet, else the sole live opponent (heads-up). None if ambiguous."""
    players = state.get("players", []) or []
    seat = state.get("seat_to_act", 0)
    if not state.get("can_check"):
        for e in reversed(state.get("action_log", []) or []):
            if e.get("action") in ("raise", "all_in") and e.get("seat") != seat:
                s = e.get("seat")
                if isinstance(s, int) and 0 <= s < len(players):
                    return players[s].get("bot_id")
    live = [i for i, pl in enumerate(players)
            if i != seat and not pl.get("is_folded") and pl.get("state") != "busted"]
    if len(live) == 1:
        return players[live[0]].get("bot_id")
    return None


def perturb_postflop(dist, opp_id, facing, hs, draw, n_opp):
    """Bounded lambda-blend of the blueprint dist toward an exploit direction."""
    lam = compute_lambda(opp_id)
    if lam <= 0:
        return dist
    f = stat_mean(opp_id, "fold_to_bet")
    agg = stat_mean(opp_id, "aggression")
    bluff = stat_mean(opp_id, "bluff_propensity")
    d = dict(dist)
    # value_ish = any real made hand (pair or better) -> bet for value;
    # bluff_ish = air / ace-high / underpair with no strong draw -> pure bluff.
    value_ish = hs in STRONG_MADE or hs in GOOD_MADE or hs in MEDIUM_MADE
    bluff_ish = (not value_ish) and (draw not in STRONG_DRAWS)
    bet_keys = [k for k in d if k.startswith("bet") or k == "all_in"]

    if facing == "checked_to":
        if n_opp > 1:
            return dist                       # only adapt checked-to spots heads-up
        if bluff_ish:
            if f > 0.55:                       # over-folder -> bluff more
                move = lam * (f - 0.55) * 2.0 * d.get("check", 0.0)
                d["bet_66"] = d.get("bet_66", 0.0) + move
                d["check"] = d.get("check", 0.0) - move
            elif f < 0.35:                     # call station -> stop bluffing
                frac = min(1.0, lam * (0.35 - f) * 2.5)
                moved = 0.0
                for k in bet_keys:
                    moved += d[k] * frac
                    d[k] *= (1.0 - frac)
                d["check"] = d.get("check", 0.0) + moved
        else:                                  # value hand or strong draw
            if f < 0.40:                       # station -> bet more AND bigger value
                move = lam * (0.40 - f) * 2.0 * d.get("check", 0.0)
                d["bet_66"] = d.get("bet_66", 0.0) + move
                d["check"] = max(0.0, d.get("check", 0.0) - move)
                up = min(0.6, lam * (0.40 - f) * 2.0)   # they call any size -> upsize
                for small, big in (("bet_33", "bet_66"), ("bet_66", "bet_100"),
                                   ("bet_100", "bet_150")):
                    if d.get(small, 0.0) > 0:
                        mv = d[small] * up
                        d[small] -= mv
                        d[big] = d.get(big, 0.0) + mv
    else:                                      # facing a bet
        # Only the +EV direction: bluff-catch more vs aggressors/bluffers.
        # (No "fold more vs tight" branch — street-agnostic stats misread
        # disguised bluffers like a river over-bettor, and folding to bluffs
        # is the costliest mistake.)
        if "fold" in d and (agg > 0.40 or bluff > 0.45):
            g = min(0.8, lam * max((agg - 0.40) * 2.0, (bluff - 0.45) * 2.0))
            move = d["fold"] * g
            d["fold"] -= move
            d["call"] = d.get("call", 0.0) + move
    return _norm(d)


def opponents_fold_read(state):
    """Average fold_to_bet over the live opponents we have a CONFIDENT read on
    (lambda > 0). Returns None if we have no confident read yet."""
    players = state.get("players", []) or []
    seat = state.get("seat_to_act", 0)
    reads = []
    for i, pl in enumerate(players):
        if i == seat or pl.get("is_folded") or pl.get("state") == "busted":
            continue
        bid = pl.get("bot_id")
        if bid and bid in OPPONENT_STATS and compute_lambda(bid) > 0:
            reads.append(stat_mean(bid, "fold_to_bet"))
    if not reads:
        return None
    return sum(reads) / len(reads)


# ===========================================================================
# ========================= EQUITY LAYER (v5) ===============================
# ===========================================================================

_DECK_STR = [r + s for r in "23456789TJQKA" for s in "shdc"]
_DECK = [eval7.Card(s) for s in _DECK_STR]
PREFLOP_EQ = {}                 # (hand_class, n_opp) -> equity vs random (warmup)
_EQ_DEADLINE = 0.0              # absolute time by which equity work must finish
_RNG = random                  # per-decision MC RNG (local Random in decide; see Patch 9)
EQ_BUDGET = 0.45               # per-decision soft budget for equity work (s)
EQ_CALL_CAP = 0.15             # per-MC hard cap (s)


def _now():
    return time.time()


def _canonical_hole(cls):
    if len(cls) == 2:                      # pocket pair
        return [cls[0] + "s", cls[1] + "h"]
    hi, lo, suit = cls[0], cls[1], cls[2]
    return [hi + "s", lo + "s"] if suit == "s" else [hi + "s", lo + "h"]


# ===========================================================================
# ============ v15 PATCH J: precomputed equity tables (data/) ==============
# ===========================================================================
# Loaded at module import (= competition warmup). Failure is non-fatal; we
# fall back to runtime MC if the .npz is missing or numpy is unavailable.

_EQUITY_TABLES = None
_TABLE_HAND_IDX = None     # hand_class string -> row index in T1/T2
_TABLE_TEX_IDX = None      # board texture name -> row index in T3
_TABLE_HS_IDX = None       # hand strength bucket -> col index in T3
_TABLE_FIRE_COUNTS = {"preflop_hit": 0, "postflop_hit": 0, "miss": 0}


def _load_equity_tables():
    global _EQUITY_TABLES, _TABLE_HAND_IDX, _TABLE_TEX_IDX, _TABLE_HS_IDX
    if not _NUMPY_OK:
        return False
    data_dir = os.environ.get(
        "BOT_DATA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    path = os.path.join(data_dir, "equity_tables.npz")
    try:
        d = np.load(path, allow_pickle=False)
        tables = {}
        for k in ("preflop_hand_vs_hand", "preflop_vs_random",
                  "postflop_class_n_opp", "postflop_class_filled",
                  "range_vs_range", "range_vs_range_filled"):
            if k in d.files:
                tables[k] = d[k]
        hand_classes = list(d["hand_classes"]) if "hand_classes" in d.files else None
        textures = list(d["board_textures"]) if "board_textures" in d.files else None
        strengths = list(d["hand_strengths"]) if "hand_strengths" in d.files else None
        if not tables or not hand_classes:
            return False
        _EQUITY_TABLES = tables
        _TABLE_HAND_IDX = {str(c): i for i, c in enumerate(hand_classes)}
        if textures:
            _TABLE_TEX_IDX = {str(t): i for i, t in enumerate(textures)}
        if strengths:
            _TABLE_HS_IDX = {str(h): i for i, h in enumerate(strengths)}
        return True
    except Exception:
        return False


_TABLES_LOADED = _load_equity_tables()


def lookup_preflop_vs_random(cls, n_opp):
    """Table 2 lookup. Returns equity or None on miss."""
    if not _TABLES_LOADED or _TABLE_HAND_IDX is None:
        return None
    t = _EQUITY_TABLES.get("preflop_vs_random")
    if t is None:
        return None
    idx = _TABLE_HAND_IDX.get(cls)
    if idx is None:
        return None
    n_clamped = max(1, min(5, n_opp))
    try:
        return float(t[idx, n_clamped - 1])
    except Exception:
        return None


def lookup_preflop_hand_vs_hand(cls_a, cls_b):
    """Table 1 lookup. Returns A's equity vs B (or None)."""
    if not _TABLES_LOADED or _TABLE_HAND_IDX is None:
        return None
    t = _EQUITY_TABLES.get("preflop_hand_vs_hand")
    if t is None:
        return None
    ia = _TABLE_HAND_IDX.get(cls_a); ib = _TABLE_HAND_IDX.get(cls_b)
    if ia is None or ib is None:
        return None
    try:
        return float(t[ia, ib])
    except Exception:
        return None


def lookup_postflop_class(texture, strength, n_opp):
    """Table 3 lookup. Returns equity or None on miss."""
    if not _TABLES_LOADED or _TABLE_TEX_IDX is None or _TABLE_HS_IDX is None:
        return None
    t = _EQUITY_TABLES.get("postflop_class_n_opp")
    f = _EQUITY_TABLES.get("postflop_class_filled")
    if t is None:
        return None
    ti = _TABLE_TEX_IDX.get(texture); hi = _TABLE_HS_IDX.get(strength)
    if ti is None or hi is None:
        return None
    if f is not None and int(f[ti, hi]) == 0:
        return None
    n_clamped = max(1, min(5, n_opp))
    try:
        v = float(t[ti, hi, n_clamped - 1])
        if v <= 0.0 or v >= 1.0:
            return None
        return v
    except Exception:
        return None


# v15 PATCH I: deep MC on critical decisions. Detects big pots / large-commit /
# river spots and spends up to ~1.5s with 50k iterations (CI ~0.4pp) instead of
# the shallow ~200ms / 5k-iter default (CI ~1.5pp). Non-critical spots stay
# fast. Guarded by SOFT_BUDGET so total decide() stays under 1.8s.
CRITICAL_EQ_BUDGET_S = 1.5            # seconds for deep MC
CRITICAL_MAX_ROLL = 50_000
CRITICAL_HARD_CAP_S = 1.7             # hard ceiling on total decision time
_CRIT_EQ_FIRE_COUNT = 0


def critical_decision_equity(state, hole, board, n_opp, k_will_fire=False):
    """Drop-in for _equity_vs_random when called from a decision site. On
    'critical' spots (pot >= 3000 OR amount_owed >= 30% stack OR river),
    runs deep MC; otherwise delegates to the shallow MC with the existing
    per-decision _EQ_DEADLINE. v15 PATCH J: postflop critical spots also try
    a Table 3 lookup and blend 0.7*table + 0.3*refinement-MC for near-instant
    high-quality estimates.
    v15.5 PATCH K-aware: when caller signals k_will_fire=True, reduces I's
    budget 1.5s -> 1.0s and CI 0.005 -> 0.008 to reserve room for K's 500ms
    simulation budget. Total stays under 1.85s.
    Never exceeds CRITICAL_HARD_CAP_S since start of decide()."""
    global _CRIT_EQ_FIRE_COUNT
    try:
        pot = int(state.get("pot", 0) or 0)
        owed = int(state.get("amount_owed", 0) or 0)
        stack = int(state.get("your_stack", 0) or 0)
        street = state.get("street") or ""
        is_critical = (
            pot >= 3000
            or (stack > 0 and owed >= stack * 0.30)
            or street == "river"
        )
        if is_critical:
            _CRIT_EQ_FIRE_COUNT += 1
            # PATCH J: try table-blend first for postflop critical spots.
            if board and len(board) >= 3 and len(hole) == 2:
                try:
                    tex = board_texture_bucket(board)
                    hs = hand_strength_bucket(hole, board)
                    cached = lookup_postflop_class(tex, hs, n_opp)
                    if cached is not None:
                        _TABLE_FIRE_COUNTS["postflop_hit"] += 1
                        # Quick refinement MC (50ms) for hand-specific blockers.
                        ref_deadline = min(_T0 + 1.0, _now() + 0.05)
                        refined = _equity_vs_random(
                            hole, board, n_opp, ref_deadline,
                            batch=200, max_roll=1500, ci_threshold=0.02)
                        return 0.70 * cached + 0.30 * refined
                except Exception:
                    pass
            # PATCH K-aware budget allocation.
            if k_will_fire:
                # Reserve 0.6s for K (500ms K + 100ms slack). I uses up to 1.0s.
                crit_budget = 1.0
                ci_thresh = 0.008
            else:
                crit_budget = CRITICAL_EQ_BUDGET_S
                ci_thresh = 0.005
            # Cap absolute time: never exceed CRITICAL_HARD_CAP_S since _T0.
            crit_deadline = min(_T0 + crit_budget,
                                _T0 + CRITICAL_HARD_CAP_S - 0.05)
            # If we're already past or near the cap, fall back to shallow.
            if crit_deadline <= _now() + 0.05:
                return _equity_vs_random(
                    hole, board, n_opp,
                    min(_EQ_DEADLINE, _now() + EQ_CALL_CAP),
                    batch=300, max_roll=3000, ci_threshold=0.02)
            # Deep MC.
            return _equity_vs_random(
                hole, board, n_opp, crit_deadline,
                batch=500, max_roll=CRITICAL_MAX_ROLL, ci_threshold=ci_thresh)
    except Exception:
        pass
    # Non-critical: existing shallow MC
    _TABLE_FIRE_COUNTS["miss"] += 1
    return _equity_vs_random(
        hole, board, n_opp,
        min(_EQ_DEADLINE, _now() + EQ_CALL_CAP),
        batch=300, max_roll=3000)


def _equity_vs_random(hole, board, n_opp, deadline, batch=300, max_roll=3000,
                       ci_threshold=0.02):
    """Monte Carlo equity of `hole` vs n_opp random opponents on `board`.
    Wilson-CI early stop (half-width < ci_threshold) + hard caps. Never raises.
    v15 PATCH I: ci_threshold exposed so critical-decision callers can request
    tighter CI (e.g. 0.005 = 0.5pp) to actually realize the deep MC budget."""
    try:
        hero = [eval7.Card(c) for c in hole]
        bd = [eval7.Card(c) for c in board]
    except Exception:
        return 0.5
    n_opp = max(1, min(8, n_opp))
    used = set(hole) | set(board)
    deck = [c for c, s in zip(_DECK, _DECK_STR) if s not in used]
    need = 5 - len(bd)
    take = n_opp * 2 + need
    if need < 0 or take > len(deck):
        return 0.5
    wins = 0.0
    n = 0
    while n < max_roll:
        for _ in range(batch):
            _RNG.shuffle(deck)
            full = bd + deck[n_opp * 2: n_opp * 2 + need]
            hv = eval7.evaluate(hero + full)
            best = -1
            for o in range(n_opp):
                ov = eval7.evaluate([deck[2 * o], deck[2 * o + 1]] + full)
                if ov > best:
                    best = ov
            if hv > best:
                wins += 1.0
            elif hv == best:
                wins += 0.5
            n += 1
        eq = wins / n
        half = 1.96 * math.sqrt(max(eq * (1.0 - eq), 1e-9) / n)
        if half < ci_threshold or _now() > deadline:
            break
    return wins / n if n else 0.5


def preflop_equity(cls, n_opp):
    """v15 PATCH J: try precomputed Table 2 first (instant, accurate), then
    warmup cache, then runtime MC."""
    n = max(1, min(5, n_opp))
    tbl = lookup_preflop_vs_random(cls, n)
    if tbl is not None:
        return tbl
    v = PREFLOP_EQ.get((cls, n))
    if v is not None:
        return v
    return _equity_vs_random(_canonical_hole(cls), [], n,
                             _now() + 0.05, batch=200, max_roll=800)


def precompute_preflop_equity(budget_s=2.0, max_opp=2):
    """Warmup: fill PREFLOP_EQ for all 169 classes vs 1..max_opp random
    opponents. v15: if Table 2 is loaded, fill from the table instantly
    (saves ~2s warmup AND gives exact precomputed equity at all 5 opp counts).
    Otherwise fall through to the v14 time-boxed runtime MC."""
    if _TABLES_LOADED and _EQUITY_TABLES.get("preflop_vs_random") is not None:
        for cls in HAND_RANK_ORDER:
            for n in range(1, 6):                   # populate all 1..5 opps, not just 2
                v = lookup_preflop_vs_random(cls, n)
                if v is not None:
                    PREFLOP_EQ[(cls, n)] = v
        return
    end = _now() + budget_s
    for cls in HAND_RANK_ORDER:
        if _now() > end:
            return
        hole = _canonical_hole(cls)
        for n in range(1, max_opp + 1):
            if (cls, n) in PREFLOP_EQ:
                continue
            PREFLOP_EQ[(cls, n)] = _equity_vs_random(
                hole, [], n, _now() + 0.03, batch=150, max_roll=450)


def _range_factor(opp_id, bet_ratio):
    """Multiplier on the pot-odds threshold when CALLING a bet. Larger bets =>
    stronger ranges => need more equity. Lower vs aggressive/bluffy bettors
    (call lighter); higher vs passive/value bettors and unknowns."""
    base = 1.10 + 0.35 * min(max(bet_ratio, 0.0), 1.5)
    if opp_id is not None:
        agg = stat_mean(opp_id, "aggression")
        bluff = stat_mean(opp_id, "bluff_propensity")
        base -= 0.6 * max(agg - 0.30, 0.0) + 0.6 * max(bluff - 0.30, 0.0)
        base += 0.8 * max(0.20 - agg, 0.0)
    return max(0.70, min(1.70, base))


def apply_equity_facing(dist, state, p, hs, n_opp, opp_id):
    """Equity-based call/fold facing a bet. For ALL-INS, equity-vs-random is a
    reliable showdown estimate, so we make a full call/fold decision (+ P32
    variance premium). For NON-all-in bets, equity-vs-random over-states our
    equity vs a polarized betting range, so we only FOLD clear losers (and the
    range factor is low vs known bluffers, so this never folds a bluff-catch)."""
    if state.get("can_check"):
        return dist
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    if owed <= 0:
        return dist
    risk = p["stack"] + state.get("your_bet_this_street", 0)
    commit = owed / (risk + 1) if risk > 0 else 1.0
    is_allin = any(pl.get("is_all_in") for pl in (state.get("players") or [])
                   if pl.get("seat") != state.get("seat_to_act"))
    if pot < 1200 and commit < 0.30 and not is_allin:
        return dist                                   # small spot -> trust blueprint
    if _now() >= _EQ_DEADLINE and (state.get("pot", 0) < 3000 and state.get("street") != "river"):
        return dist
    # v15 PATCH I: critical spots get deep MC (50k iters, 1.5s); else shallow.
    eq = critical_decision_equity(state, p["cards"],
                                   state.get("community_cards", []),
                                   max(n_opp, 1))
    be = owed / (pot + owed)
    bet_ratio = owed / max(pot - owed, 1)
    req = be * _range_factor(opp_id, bet_ratio)
    if commit > 0.5:                                  # P32 variance premium
        req += 0.03 * min(1.0, (commit - 0.5) * 2.0)
    d = dict(dist)
    margin = 0.04
    if is_allin:                                      # reliable showdown equity
        if eq >= req + margin and d.get("fold", 0.0) > 0:
            d["call"] = d.get("call", 0.0) + d["fold"]
            d["fold"] = 0.0
        elif eq < req - margin and d.get("call", 0.0) > 0:
            d["fold"] = d.get("fold", 0.0) + d["call"]
            d["call"] = 0.0
    else:                                             # non-all-in: only fold clear losers
        if eq < req - margin and d.get("call", 0.0) > 0:
            d["fold"] = d.get("fold", 0.0) + d["call"]
            d["call"] = 0.0
    return _norm(d)


def multiway_value_verify(dist, state, p, hs, n_opp):
    """Layer 2: don't over-value multiway. If equity-vs-best-of-N is below a
    'ahead of the field' threshold, downgrade value bets/calls."""
    if n_opp < 2 or state.get("pot", 0) < 1500:
        return dist
    if _now() >= _EQ_DEADLINE and state.get("pot", 0) < 3000:
        return dist
    # v15 PATCH I: critical-aware deep MC.
    eq = critical_decision_equity(state, p["cards"],
                                   state.get("community_cards", []), n_opp)
    fair = 1.0 / (n_opp + 1)
    d = dict(dist)
    if state.get("can_check"):
        if eq < fair * 1.25:                          # too thin to value-bet multiway
            for k in list(d):
                if k.startswith("bet") or k == "all_in":
                    d["check"] = d.get("check", 0.0) + d[k] * 0.6
                    d[k] *= 0.4
    else:
        if eq < fair * 1.10 and d.get("call", 0.0) > 0:
            d["fold"] = d.get("fold", 0.0) + d["call"] * 0.6
            d["call"] *= 0.4
    return _norm(d)


def _preflop_facing_allin(state):
    if state.get("can_check") or state.get("amount_owed", 0) <= 0:
        return False
    seat = state.get("seat_to_act")
    for pl in state.get("players", []) or []:
        if pl.get("seat") != seat and pl.get("is_all_in"):
            return True
    return False


PRE_AI_FOLD = float(os.environ.get("PRE_AI_FOLD", "0.15"))


def preflop_allin_equity_decision(state, p, n_opp):
    """Equity-based call/fold facing a preflop shove (uses the P34 table).
    v14: base rf bumped 1.10 -> 1.10 + PRE_AI_FOLD (default 0.15 -> 1.25) after
    D2 qualifier hand-history analysis: 33 hands where we called a preflop bet
    and lost, avg -6.3k chips/hand. The real qualifier field is far more
    value-weighted in preflop all-in spots than our local synthetic field;
    require more equity edge before calling. Opponent-read adjustments still
    apply on top (maniacs -> looser; tight -> tighter)."""
    cls = hand_class(p["cards"])
    eq = preflop_equity(cls, max(n_opp, 1))
    pot, owed = p["pot"], p["owed"]
    be = owed / (pot + owed) if (pot + owed) > 0 else 1.0
    opp_id = relevant_opponent_id(state)
    shove = stat_mean(opp_id, "shove_frequency") if opp_id else 0.05
    agg = stat_mean(opp_id, "aggression") if opp_id else 0.25
    rf = (1.10 + PRE_AI_FOLD) - 1.5 * max(shove - 0.05, 0.0) - 0.4 * max(agg - 0.30, 0.0)
    rf = max(0.7, min(1.3 + PRE_AI_FOLD, rf))
    return {"action": "call"} if eq >= be * rf else \
        ({"action": "check"} if p["can_check"] else {"action": "fold"})


# ---- Sampling + concrete sizing -------------------------------------------

def _decision_seed(state):
    """Patch 9: a hash that uniquely identifies this decision point, so the
    mixed strategy (and the MC RNG) are reproducible and not self-correlated
    across our own decisions within a street."""
    parts = [
        str(state.get("hand_id", "")),
        str(state.get("seat_to_act", "")),
        str(state.get("street", "")),
        str(len(state.get("action_log", []) or [])),
        str(state.get("pot", "")),
        str(state.get("current_bet", "")),
        str(state.get("amount_owed", "")),
        str(state.get("your_bet_this_street", "")),
    ]
    return int(hashlib.md5("|".join(parts).encode()).hexdigest()[:16], 16)


def sample_mixed_action(dist, state):
    """Deterministic draw from a {action: prob} dict, keyed on the decision."""
    if not dist:
        return None
    actions = sorted(dist.keys())
    probs = [max(0.0, dist[a]) for a in actions]
    total = sum(probs)
    if total <= 0:
        return actions[0]
    probs = [p / total for p in probs]
    rv = (_decision_seed(state) % 10**9) / 10**9
    c = 0.0
    for a, p in zip(actions, probs):
        c += p
        if rv < c:
            return a
    return actions[-1]


# v7 (P1): irregular adversarial bet sizes. Most LLM-built bots use textbook
# 33%/66%/100%/150% sizing and pot-odds calling calibrated to those round
# numbers. Betting 29%/71%/113%/187% instead gives them non-round pot odds and
# off-grid sizes their thresholds/bucketing mis-handle — an orthogonal edge vs
# the modal field. Our own encoding is unaffected because v6's bucket_bet_size
# maps these to the same buckets as the round sizes.
SIZE_MAP = {"bet_33": 0.29, "bet_66": 0.71, "bet_100": 1.13, "bet_150": 1.87}


def concrete_action(abstract, state, pot, owed, size_mult=1.0):
    cur = state.get("current_bet", 0)
    min_r = state.get("min_raise_to", 0)
    if abstract == "check":
        return {"action": "check"}
    if abstract == "call":
        return {"action": "call"}
    if abstract == "fold":
        return {"action": "fold"}
    if abstract == "all_in":
        return {"action": "all_in"}
    if abstract.startswith("bet_"):
        frac = SIZE_MAP[abstract]
        return {"action": "raise", "amount": max(int(frac * size_mult * pot), min_r)}
    if abstract == "raise_value":
        return {"action": "raise", "amount": max(int(cur * 2.5), min_r)}
    if abstract == "raise_pot":
        return {"action": "raise", "amount": max(cur + pot + owed, min_r)}
    return {"action": "check"} if state.get("can_check") else {"action": "fold"}


def postflop_decision(state, p):
    global POSTFLOP_DECISIONS, FALLBACK_DECISIONS
    POSTFLOP_DECISIONS += 1
    cards = p["cards"]
    board = state.get("community_cards", []) or []
    if len(cards) != 2 or len(board) < 3:
        FALLBACK_DECISIONS += 1
        return _simple_postflop(state, p)

    hs = hand_strength_bucket(cards, board)
    texture = board_texture_bucket(board)
    draw = draw_bucket(cards, board)
    spr = spr_bucket(p["stack"], max(state.get("pot", 1), 1))
    pos = postflop_position(state)
    facing = facing_bucket(state)

    key = "|".join((hs, texture, draw, spr, pos, facing))
    dist = lookup_strategy(key, (hs, texture, draw, spr, pos), facing)

    # v3: multiway tightening (Layer 1). No-op heads-up.
    n_opp = _n_live_opponents(state)
    dist = multiway_adjust(dist, n_opp, hs, draw, facing)
    size_mult = N_OPP_ADJUSTMENTS[min(max(n_opp, 1), 5)]["size_mult"]

    # v4: per-opponent perturbation (bounded; no-op when we lack data on the
    # relevant villain).
    opp_id = relevant_opponent_id(state)
    dist = perturb_postflop(dist, opp_id, facing, hs, draw, n_opp)

    # v5: equity layer (flagged spots only; each guarded by the time budget).
    dist = multiway_value_verify(dist, state, p, hs, n_opp)
    dist = apply_equity_facing(dist, state, p, hs, n_opp, opp_id)

    # v8: river nut-flush-blocker nudge (bounded, river-only).
    dist = river_blocker_adjust(dist, state, p, hs, facing, opp_id)

    # v13: respect value-heavy river betting (fold marginal bluff-catchers more
    # vs non-flagged opponents; gated off vs known bluffers).
    dist = river_value_respect(dist, state, p, hs, opp_id)

    # v12: score-aware aggression (mild, last ~50 hands only).
    dist = apply_aggression_modifier(dist, state)

    abstract = sample_mixed_action(dist, state)
    return concrete_action(abstract, state, state.get("pot", 0),
                           state.get("amount_owed", 0), size_mult)


def _simple_postflop(state, p):
    if p["can_check"]:
        return {"action": "check"}
    if p["owed"] > 0 and p["pot"] / p["owed"] >= 3:
        return {"action": "call"}
    return {"action": "fold"}


# ===========================================================================
# Safety layer + entry point
# ===========================================================================

# ===========================================================================
# ============ v14-final: stack-off governor chain (D2 patch) ==============
# ===========================================================================
# Diagnosis (GPT-refined): v13 commits too much stack with non-nutted hands on
# dangerous boards against tight continuing ranges. The fix is texture-aware
# stack-off restraint, NOT MDF-style folding. Five layered governors fire AFTER
# the existing strategy returns a concrete action and before legality mapping.

_GOV_COUNTS = {"called": 0, "B": 0, "D": 0, "A": 0, "C": 0, "E": 0}


def _board_vals(board):
    return [RANK_VAL[c[0]] for c in board if c]


def _gov_is_paired_board(board):
    if len(board) < 2:
        return False
    vs = _board_vals(board)
    return len(vs) != len(set(vs))


def _gov_is_double_paired_board(board):
    if len(board) < 4:
        return False
    vs = _board_vals(board)
    counts = {}
    for v in vs:
        counts[v] = counts.get(v, 0) + 1
    return sum(1 for n in counts.values() if n >= 2) >= 2


def _gov_has_trips_on_board(board):
    if len(board) < 3:
        return False
    vs = _board_vals(board)
    counts = {}
    for v in vs:
        counts[v] = counts.get(v, 0) + 1
    return any(n >= 3 for n in counts.values())


def _gov_flush_completed(board):
    if len(board) < 5:
        return False
    suits = {}
    for c in board:
        suits[c[1]] = suits.get(c[1], 0) + 1
    return max(suits.values()) >= 5


def _gov_four_flush_board(board):
    if len(board) < 4:
        return False
    suits = {}
    for c in board:
        suits[c[1]] = suits.get(c[1], 0) + 1
    return max(suits.values()) >= 4


def _gov_one_card_straight_possible(board):
    if len(board) < 4:
        return False
    vs = sorted(set(_board_vals(board)))
    for i in range(len(vs) - 3):
        if vs[i + 3] - vs[i] <= 4:
            return True
    if 12 in vs and {0, 1, 2}.issubset(vs):
        return True
    return False


def _gov_board_very_wet(board):
    if len(board) < 3:
        return False
    bt = board_texture_bucket(board)
    return bt in ("monotone", "broadway_connected", "low_connected", "connected")


def _gov_last_agg_villain_seat(action_log, hero_seat):
    last = None
    for a in action_log or []:
        if a.get("seat") != hero_seat and a.get("action") in ("raise", "all_in"):
            last = a.get("seat")
    return last


def _gov_villain_check_raised(action_log, villain_seat):
    if villain_seat is None or not action_log:
        return False
    saw_check = False
    for a in action_log:
        if a.get("seat") == villain_seat:
            if a.get("action") == "check":
                saw_check = True
            elif a.get("action") in ("raise", "all_in") and saw_check:
                return True
    return False


def _gov_villain_2plus_raises(action_log, villain_seat):
    if villain_seat is None:
        return False
    return sum(1 for a in (action_log or [])
               if a.get("seat") == villain_seat
               and a.get("action") in ("raise", "all_in")) >= 2


def _gov_hero_has_nut_blocker(hole, board):
    if len(board) < 3 or len(hole) < 2:
        return False
    suits = {}
    for c in board:
        suits[c[1]] = suits.get(c[1], 0) + 1
    if not suits or max(suits.values()) < 3:
        return False
    flush_suit = max(suits, key=suits.get)
    return any(c[0] == "A" and c[1] == flush_suit for c in hole)


def _gov_hero_actual_nuts(hole, board, hand_class):
    if hand_class != "full_house_or_better":
        return False
    if not _gov_is_paired_board(board):
        return False
    return True


# ===========================================================================
# ============ v15.6 RIO_INDEX: nut_danger amplifier ========================
# ===========================================================================
# Precomputed reverse-implied-odds per (hand_strength, board_texture, street,
# SPR_bucket): for each cell, the fraction of villain's top-33% continuing
# range that dominates us (villain eval7 score > hero by >1000). Loaded at
# module import with graceful fallthrough -> if missing, v15.6 == v15.5.
# Wires into the stack-off governor by ADDING `rio_score * 2.0` (capped at
# +2.0) to nut_danger_score's output BEFORE _patch_A / _patch_C consume it.
# This is UPSTREAM of Patch K's commit gate -> high-RIO spots trigger A/C
# vetoes that suppress K. The structural goal.

_RIO_INDEX = None
_RIO_FILLED = None
_RIO_HS_IDX = None
_RIO_TEX_IDX = None
_RIO_ST_IDX = None
_RIO_FIRED_COUNT = 0
_RIO_CHANGED_ACTION_COUNT = 0
_RIO_SUPPRESSED_K_COUNT = 0

# SPR bucket -> index in dim 3 of RIO_INDEX. Mirrors spr_bucket() order.
_RIO_SPR_STR_TO_IDX = {"<1": 0, "1-3": 1, "3-6": 2, "6-10": 3, ">=10": 4}


def _load_rio_index():
    global _RIO_INDEX, _RIO_FILLED, _RIO_HS_IDX, _RIO_TEX_IDX, _RIO_ST_IDX
    if not _NUMPY_OK:
        return False
    data_dir = os.environ.get(
        "BOT_DATA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    path = os.path.join(data_dir, "rio_index.npz")
    try:
        d = np.load(path, allow_pickle=False)
        if "rio_index" not in d.files:
            return False
        _RIO_INDEX = d["rio_index"]
        _RIO_FILLED = d["filled"] if "filled" in d.files else None
        if "hand_strengths" in d.files:
            _RIO_HS_IDX = {str(s): i for i, s in enumerate(d["hand_strengths"])}
        if "board_textures" in d.files:
            _RIO_TEX_IDX = {str(s): i for i, s in enumerate(d["board_textures"])}
        if "streets" in d.files:
            _RIO_ST_IDX = {str(s): i for i, s in enumerate(d["streets"])}
        return True
    except Exception:
        return False


_RIO_LOADED = _load_rio_index()


def rio_lookup(hand_strength, board, street, spr_str):
    """Return (rio_score, stackoff_cap_adj, call_buffer_adj) or None.
    Lookup hits when (hand_strength, board_texture, street, spr_bucket) all
    map to valid indices AND the (hand_strength, board_texture, street) cell
    has actual data (>0 samples used in generation, or rio_score > 0)."""
    if not _RIO_LOADED or _RIO_INDEX is None or _RIO_HS_IDX is None:
        return None
    try:
        hs_i = _RIO_HS_IDX.get(hand_strength)
        tex = board_texture_bucket(board) if board else None
        tex_i = _RIO_TEX_IDX.get(tex) if tex and _RIO_TEX_IDX else None
        st_i = _RIO_ST_IDX.get(street) if street and _RIO_ST_IDX else None
        spr_i = _RIO_SPR_STR_TO_IDX.get(spr_str)
        if hs_i is None or tex_i is None or st_i is None or spr_i is None:
            return None
        # Skip unfilled cells (rio_score may be 0 from default, not real data)
        if _RIO_FILLED is not None and int(_RIO_FILLED[hs_i, tex_i, st_i]) < 5:
            return None
        row = _RIO_INDEX[hs_i, tex_i, st_i, spr_i]
        return float(row[0]), float(row[1]), float(row[2])
    except Exception:
        return None


def _nut_danger_with_rio(state, hand_class, hand_strength=None):
    """Returns (danger_with_rio, danger_base, rio_score_or_None).
    Caller compares with/without to detect RIO-caused decision changes."""
    global _RIO_FIRED_COUNT
    base = nut_danger_score(state, hand_class)
    if not _RIO_LOADED:
        return base, base, None
    board = state.get("community_cards") or []
    if len(board) < 3:
        return base, base, None
    # Compute current hand_strength on this board (if not pre-passed).
    hole = state.get("your_cards") or []
    if hand_strength is None:
        if len(hole) != 2:
            return base, base, None
        try:
            hand_strength = hand_strength_bucket(hole, board)
        except Exception:
            return base, base, None
    street = state.get("street") or ""
    if street not in ("flop", "turn", "river"):
        return base, base, None
    stack = state.get("your_stack", 0) or 0
    pot = state.get("pot", 0) or 0
    spr_str = spr_bucket(stack, pot)
    rio = rio_lookup(hand_strength, board, street, spr_str)
    if rio is None:
        return base, base, None
    rio_score, _, _ = rio
    _RIO_FIRED_COUNT += 1
    # Additive amplification: amplifier raised 2.0 -> 3.5 after first-validation
    # showed literal action-change rate too low (1.3%) -- many spots had base
    # danger 0-1 and rio_score 0.4-0.7 amplifications didn't cross the >=2
    # veto threshold. Cap at +3.5 (so rio_score 1.0 adds 3.5 danger).
    amped = base + min(3.5, rio_score * 3.5)
    return amped, base, rio_score


def nut_danger_score(state, hand_class):
    board = state.get("community_cards") or []
    action_log = state.get("action_log") or []
    hero_seat = state.get("seat_to_act")
    hole = state.get("your_cards") or []
    s = 0
    if _gov_is_paired_board(board): s += 1
    if _gov_is_double_paired_board(board): s += 2
    if _gov_has_trips_on_board(board): s += 2
    if _gov_flush_completed(board): s += 1
    if _gov_four_flush_board(board): s += 2
    if _gov_one_card_straight_possible(board): s += 1
    if _gov_board_very_wet(board): s += 1
    villain = _gov_last_agg_villain_seat(action_log, hero_seat)
    if villain is not None:
        if _gov_villain_check_raised(action_log, villain): s += 2
        if _gov_villain_2plus_raises(action_log, villain): s += 2
    if _gov_hero_has_nut_blocker(hole, board): s -= 1
    if _gov_hero_actual_nuts(hole, board, hand_class): s -= 3
    if hand_class in ("straight", "flush", "full_house_or_better"):
        s -= 1
    if hand_class == "set_or_trips" and not _gov_has_trips_on_board(board) \
            and not _gov_is_double_paired_board(board):
        s -= 1
    return max(0, s)


def _gov_commit_fraction(state, action):
    stack = state.get("your_stack", 0) or 0
    already = state.get("your_bet_this_street", 0) or 0
    base = stack + already
    if base <= 0:
        return 0.0
    a = action.get("action")
    if a == "all_in":
        return 1.0
    if a == "raise":
        amt = action.get("amount", 0) or 0
        addl = max(0, amt - already)
        return min(1.0, addl / max(base, 1))
    if a == "call":
        owed = state.get("amount_owed", 0) or 0
        return min(1.0, owed / max(base, 1))
    return 0.0


def _gov_to_call_or_fold(state):
    if state.get("can_check"):
        return {"action": "check"}
    if (state.get("amount_owed", 0) or 0) > 0:
        return {"action": "call"}
    return {"action": "fold"}


def _gov_hero_class(state, p):
    hole = (p or {}).get("cards") or state.get("your_cards") or []
    board = state.get("community_cards") or []
    if len(hole) == 2 and len(board) >= 3:
        try:
            return hand_strength_bucket(hole, board)
        except Exception:
            return None
    return None


# --- PATCH B: Worse-Hands-That-Call test (raises/all-ins only) -------------
# Refined after first validation showed PATCH B was over-firing (4.8% of
# decisions) and killing upside. The spec's intent: re-raises must be true
# value, but legitimate strong-made-hand value raises should pass through.
# Only downgrade WEAK made hands and AIR -- where "raise = bluff requiring
# fold equity that the real value-heavy field rarely concedes".
def _patch_B(state, action, hand_class):
    if action.get("action") not in ("raise", "all_in"):
        return action
    board = state.get("community_cards") or []
    if not board or hand_class is None:
        return action  # preflop / no class -> not applicable
    # Strong made hands raise for value -- pass through.
    if hand_class in ("set_or_trips", "straight", "flush", "full_house_or_better",
                      "two_pair", "overpair", "strong_top_pair"):
        return action
    # Marginal/weak hands and air: raising relies on fold equity. Against the
    # real qualifier field (value-heavy callers), these raises mostly lose.
    _GOV_COUNTS["B"] += 1
    return _gov_to_call_or_fold(state)


# --- PATCH D: trap-line dampener (raises/all-ins only) ---------------------
def _patch_D(state, action, hand_class):
    if action.get("action") not in ("raise", "all_in"):
        return action
    al = state.get("action_log") or []
    hero_seat = state.get("seat_to_act")
    villain = _gov_last_agg_villain_seat(al, hero_seat)
    if villain is None:
        return action
    villain_acts = [a.get("action") for a in al if a.get("seat") == villain]
    score = 0
    if "check" in villain_acts:
        idx = villain_acts.index("check")
        if any(x in ("raise", "all_in") for x in villain_acts[idx:]):
            score += 2
    if "call" in villain_acts and "raise" in villain_acts:
        cidx = villain_acts.index("call")
        if "raise" in villain_acts[cidx + 1:]:
            score += 1
    if score >= 3 and hand_class not in ("straight", "flush", "full_house_or_better"):
        _GOV_COUNTS["D"] += 1
        return _gov_to_call_or_fold(state)
    return action


# --- PATCH A: nut-disadvantage stack-off governor --------------------------
def _patch_A(state, action, hand_class, opp_id):
    """v15.6 RIO-amplified: danger is augmented by rio_score*2.0 (capped +2.0)
    when RIO has data for this (texture, strength, street). Tracks
    _RIO_SUPPRESSED_K_COUNT when amplification flips a non-veto into a veto."""
    global _RIO_SUPPRESSED_K_COUNT
    cf = _gov_commit_fraction(state, action)
    if cf < 0.40:
        return action, False
    danger_rio, danger_base, rio_score = _nut_danger_with_rio(state, hand_class)
    bluff = stat_mean(opp_id, "bluff_propensity") if opp_id else 0.30
    if bluff > 0.50:
        danger_rio -= 1
        danger_base -= 1
    is_marginal_class = hand_class in (
        "weak_top_pair", "strong_top_pair", "overpair", "two_pair", "set_or_trips")
    veto_rio = danger_rio >= 2 and is_marginal_class
    veto_base = danger_base >= 2 and is_marginal_class
    if veto_rio:
        _GOV_COUNTS["A"] += 1
        if rio_score is not None and not veto_base:
            # RIO turned a non-veto into a veto -> K can't fire here.
            _RIO_SUPPRESSED_K_COUNT += 1
        return _gov_to_call_or_fold(state), True
    return action, False


# --- PATCH C: street-specific commitment threshold paired with danger ------
_STACKOFF_BASE = {"flop": 0.62, "turn": 0.58, "river": 0.52}


def _patch_C(state, action, hand_class, equity_est):
    """v15.6 RIO-amplified threshold: required equity = base + 0.04 * danger
    where danger is the RIO-amplified value. Higher RIO -> higher required ->
    more likely to veto -> K suppressed."""
    global _RIO_SUPPRESSED_K_COUNT
    cf = _gov_commit_fraction(state, action)
    if cf < 0.40:
        return action, False
    if equity_est is None:
        return action, False
    street = state.get("street") or "preflop"
    base = _STACKOFF_BASE.get(street, 0.60)
    danger_rio, danger_base, rio_score = _nut_danger_with_rio(state, hand_class)
    required_rio = min(0.85, base + 0.04 * danger_rio)
    required_base = min(0.85, base + 0.04 * danger_base)
    veto_rio = equity_est < required_rio
    veto_base = equity_est < required_base
    if veto_rio:
        _GOV_COUNTS["C"] += 1
        if rio_score is not None and not veto_base:
            _RIO_SUPPRESSED_K_COUNT += 1
        return _gov_to_call_or_fold(state), True
    return action, False


# --- PATCH E: selective river MDF (only flips fold->call, blocker required) -
def _patch_E(state, action, opp_id, hand_class, vetoed):
    if vetoed:
        return action
    if (state.get("street") or "") != "river":
        return action
    if action.get("action") != "fold":
        return action
    bluff = stat_mean(opp_id, "bluff_propensity") if opp_id else 0.30
    if bluff < 0.30:
        return action
    hole = state.get("your_cards") or []
    board = state.get("community_cards") or []
    if not _gov_hero_has_nut_blocker(hole, board):
        return action
    if (state.get("amount_owed", 0) or 0) > 0:
        _GOV_COUNTS["E"] += 1
        return {"action": "call"}
    return action


# ===========================================================================
# ============ v15.5 PATCH K: multi-candidate EV simulation =================
# ===========================================================================
# For stack-off decisions (commit_fraction >= 0.40), run MC rollouts of each
# candidate action and pick the highest-EV one. Uses opponent's RUNTIME stats
# (no offline training, no distribution shift). Strict 500ms budget enforced.

K_TOTAL_BUDGET_S = 0.50          # hard ceiling per decision
K_PER_CANDIDATE_OVERHEAD_S = 0.005
_K_FIRED_COUNT = 0
_K_TIMED_OUT_COUNT = 0
_K_CHANGED_ACTION_COUNT = 0
# Generic mid-tight range used to seed villain sampling when we have no read.
# Built lazily so we don't reference defend_top before it's defined at import.
_K_GENERIC_RANGE_CACHE = None


def _k_generic_range():
    """A reasonable 30% range used when opp stats are uninformative."""
    global _K_GENERIC_RANGE_CACHE
    if _K_GENERIC_RANGE_CACHE is None:
        try:
            _K_GENERIC_RANGE_CACHE = list(defend_top(0.30))
        except Exception:
            _K_GENERIC_RANGE_CACHE = []
    return _K_GENERIC_RANGE_CACHE


def _k_villain_range_classes(opp_id, board, action_log, hero_seat):
    """Pick a hand-class set representing villain's plausible range. Uses opp's
    tracked aggression to widen/tighten. Returns list of hand-class strings.
    NO offline learning -- pure runtime stat scaling."""
    base_pct = 0.30                                     # default 30% of hands
    if opp_id:
        try:
            agg = stat_mean(opp_id, "aggression")        # 0..1
            bluff = stat_mean(opp_id, "bluff_propensity")
            # Aggressive opp -> wider continuing range. Cap [0.15, 0.55].
            base_pct = max(0.15, min(0.55, 0.30 + 0.3 * (agg - 0.30) + 0.2 * (bluff - 0.30)))
        except Exception:
            pass
    # If villain has check-raised or 2+ raises, tighten (signals strong range).
    villain_seat = _gov_last_agg_villain_seat(action_log or [], hero_seat)
    if villain_seat is not None and villain_seat == _last_aggressive_seat_in_log(action_log or []):
        if _gov_villain_check_raised(action_log or [], villain_seat):
            base_pct = max(0.10, base_pct - 0.15)
        elif _gov_villain_2plus_raises(action_log or [], villain_seat):
            base_pct = max(0.12, base_pct - 0.10)
    try:
        return list(defend_top(base_pct))
    except Exception:
        return _k_generic_range()


def _last_aggressive_seat_in_log(action_log):
    last = None
    for a in action_log:
        if a.get("action") in ("raise", "all_in"):
            last = a.get("seat")
    return last


def _k_estimate_fold_prob(state, bet_amount, opp_id):
    """Estimate opp fold probability given OUR bet size, using opp's
    fold_to_bet stat scaled by bet pressure. No training, just stat lookup."""
    pot = max(state.get("pot", 0) or 0, 1)
    base = 0.40                                          # weak prior
    if opp_id:
        try:
            f2b = stat_mean(opp_id, "fold_to_bet")        # 0..1
            base = max(0.05, min(0.95, f2b))
        except Exception:
            pass
    # Pressure: bigger bet relative to pot -> more folds. Linear in [0, 1.5x pot].
    pressure_ratio = bet_amount / pot if pot > 0 else 1.0
    pressure_mult = 1.0 + 0.4 * max(0.0, min(1.5, pressure_ratio - 0.5))
    return max(0.02, min(0.95, base * pressure_mult))


_K_FULL_DECK = None
def _k_full_deck():
    global _K_FULL_DECK
    if _K_FULL_DECK is None:
        ranks = "23456789TJQKA"; suits = "shdc"
        _K_FULL_DECK = [r + s for r in ranks for s in suits]
    return _K_FULL_DECK


def _k_sample_villain_hole(range_classes, dead_cards, rng):
    """Sample one concrete 2-card hole from a hand-class range. Returns
    (card_a, card_b) or None if no valid combo found."""
    if not range_classes:
        return None
    # Try up to ~20 random class picks
    for _ in range(20):
        cls = range_classes[rng.randrange(len(range_classes))]
        try:
            hole = _canonical_hole(cls)
        except Exception:
            continue
        if hole[0] in dead_cards or hole[1] in dead_cards:
            continue
        return tuple(hole)
    return None


def _k_simulate_to_terminal(state, our_action, hero_cards, board, opp_id,
                              villain_range, rng):
    """One rollout: apply our action, simulate opp response, evaluate.
    Returns net chip outcome relative to start of this decision.
    EV-conventions follow user spec:
      fold -> 0 (we forfeit invested chips as sunk cost)
      opp folds -> +pot
      showdown win -> +(final_pot - bet_amount)
      showdown loss -> -bet_amount
      tie -> 0
    Returns None on unrecoverable error (caller skips that sample)."""
    try:
        action = our_action.get("action")
        if action == "fold":
            return 0
        pot = state.get("pot", 0) or 0
        stack = state.get("your_stack", 0) or 0
        already = state.get("your_bet_this_street", 0) or 0
        if action == "all_in":
            bet_amount = stack
        elif action == "call":
            bet_amount = state.get("amount_owed", 0) or 0
        elif action == "raise":
            total = our_action.get("amount", 0) or 0
            bet_amount = max(0, total - already)
        else:
            return None
        # Bet must be non-negative and within stack.
        bet_amount = max(0, min(bet_amount, stack))
        # Opp fold model.
        fold_prob = _k_estimate_fold_prob(state, bet_amount, opp_id)
        if rng.random() < fold_prob:
            return pot                                  # opp folds, we collect pot
        # Opp continues -> sample villain hole.
        dead = set(hero_cards) | set(board)
        villain = _k_sample_villain_hole(villain_range, dead, rng)
        if villain is None:
            return None
        # Complete board.
        full_board = list(board)
        need = 5 - len(full_board)
        if need > 0:
            deck_dead = dead | set(villain)
            deck = [c for c in _k_full_deck() if c not in deck_dead]
            if len(deck) < need:
                return None
            # rejection-sample without shuffle
            picks = []
            while len(picks) < need:
                c = deck[rng.randrange(len(deck))]
                if c not in picks:
                    picks.append(c)
            full_board = full_board + picks
        # Evaluate showdown.
        hero_score = eval7.evaluate(
            [eval7.Card(c) for c in list(hero_cards) + full_board])
        villain_score = eval7.evaluate(
            [eval7.Card(c) for c in list(villain) + full_board])
        final_pot = pot + 2 * bet_amount                # both contributed
        if hero_score > villain_score:
            return final_pot - bet_amount
        if hero_score < villain_score:
            return -bet_amount
        return 0
    except Exception:
        return None


def _k_legal_raise_amount(state, fraction_of_pot):
    """Compute a legal raise total = max(min_raise, current_bet + fraction*pot)."""
    pot = max(state.get("pot", 0) or 0, 1)
    cur = state.get("current_bet", 0) or 0
    min_r = state.get("min_raise_to", 0) or 0
    your_bet = state.get("your_bet_this_street", 0) or 0
    max_r = (state.get("your_stack", 0) or 0) + your_bet
    target = cur + int(fraction_of_pot * pot)
    target = max(target, min_r)
    target = min(target, max_r)
    return target


def _k_build_candidate_actions(state, current_action):
    """Build the candidate slate for stack-off decisions."""
    cand = []
    can_check = state.get("can_check", False)
    owed = state.get("amount_owed", 0) or 0
    your_bet = state.get("your_bet_this_street", 0) or 0
    stack = state.get("your_stack", 0) or 0
    min_r = state.get("min_raise_to", 0) or 0
    max_r = stack + your_bet
    # fold / check
    if can_check:
        cand.append({"action": "check"})
    else:
        cand.append({"action": "fold"})
    # call (only if there's something to call)
    if owed > 0:
        cand.append({"action": "call"})
    # raises (only if a raise is legal at all)
    if min_r > your_bet and min_r <= max_r:
        small = _k_legal_raise_amount(state, 0.5)
        potraise = _k_legal_raise_amount(state, 1.0)
        if small > your_bet:
            cand.append({"action": "raise", "amount": small})
        if potraise > your_bet and potraise != small:
            cand.append({"action": "raise", "amount": potraise})
        # all-in
        if max_r > your_bet:
            cand.append({"action": "all_in"})
    # Dedupe by (action, amount).
    seen, dedup = set(), []
    for a in cand:
        key = (a.get("action"), a.get("amount"))
        if key not in seen:
            seen.add(key); dedup.append(a)
    return dedup


def k_stack_off_ev_simulation(state, hero_cards, board, opp_id,
                                current_action, hero_seat):
    """Returns a (possibly new) action chosen by max-EV across candidates,
    or None to leave current_action unchanged. Strict 500ms budget."""
    global _K_FIRED_COUNT, _K_TIMED_OUT_COUNT
    try:
        cf = _gov_commit_fraction(state, current_action)
        if cf < 0.40:
            return None
        candidates = _k_build_candidate_actions(state, current_action)
        if not candidates or len(candidates) < 2:
            return None
        _K_FIRED_COUNT += 1
        start = _now()
        # Hard deadline relative to K start; also clamp to global hard cap.
        k_deadline = min(start + K_TOTAL_BUDGET_S,
                         _T0 + CRITICAL_HARD_CAP_S - 0.02)
        if k_deadline <= start + 0.01:
            _K_TIMED_OUT_COUNT += 1
            return None
        per_cand_budget = (k_deadline - start) / max(len(candidates), 1)
        # Build a per-decision RNG that's reproducible
        try:
            rng = random.Random(_decision_seed(state) ^ 0xABCDEF)
        except Exception:
            rng = random.Random()
        action_log = state.get("action_log") or []
        villain_range = _k_villain_range_classes(
            opp_id, board or [], action_log, hero_seat)
        candidate_evs = []
        timed_out = False
        for action in candidates:
            if _now() >= k_deadline:
                timed_out = True
                break
            cand_start = _now()
            cand_deadline = min(cand_start + per_cand_budget, k_deadline)
            ev_sum = 0.0
            n_sims = 0
            n_skipped = 0
            while n_sims < 5000:
                if _now() >= cand_deadline:
                    break
                outcome = _k_simulate_to_terminal(
                    state, action, hero_cards, board or [], opp_id,
                    villain_range, rng)
                if outcome is None:
                    n_skipped += 1
                    if n_skipped > 50:
                        break
                    continue
                ev_sum += outcome
                n_sims += 1
            if n_sims >= 50:                            # need a few samples to trust
                candidate_evs.append((ev_sum / n_sims, action, n_sims))
        if timed_out:
            _K_TIMED_OUT_COUNT += 1
        if len(candidate_evs) < 2:
            return None
        # Pick max-EV action.
        candidate_evs.sort(key=lambda x: -x[0])
        best_ev, best_action, _ = candidate_evs[0]
        return best_action
    except Exception:
        return None


# ===========================================================================
# ============ v15.10c River-Pair Transition Guard ==========================
# ===========================================================================
# Narrower than 10a: fires ONLY when the RIVER card itself pairs an unpaired
# flop/turn rank (the transition trap subset). When the board pre-river was
# unpaired and the river creates a pair, villain's continuing range often
# slowplays full houses on this exact transition. Caps hero on commit > 0.30.
# Aggressive intent -> call/check. Large call into transition -> fold.

_V1510C_FIRED = 0
_V1510C_FIRED_LOG = []
_V1510C_FH_OR_BETTER = ("Full House", "Quads", "Straight Flush")


def _v1510c_river_creates_pair(board):
    """Returns True iff len(board)==5, pre-river board was unpaired,
    and the river card matches a rank from board[:4]."""
    if not board or len(board) != 5:
        return False
    pre_ranks = [c[0] for c in board[:4]]
    counts = {}
    for r in pre_ranks:
        counts[r] = counts.get(r, 0) + 1
    if counts and max(counts.values()) >= 2:
        return False                                    # board already paired pre-river
    return board[4][0] in pre_ranks


def _v1510c_hero_is_fh_or_better(hero_cards, board):
    try:
        if len(hero_cards) != 2 or len(board) != 5:
            return True
        score = eval7.evaluate([eval7.Card(c) for c in list(hero_cards) + list(board)])
        ht = str(eval7.handtype(score))
        return ht in _V1510C_FH_OR_BETTER
    except Exception:
        return True


def river_pair_transition_guard(state, intended_action, hero_cards, board):
    """v15.10c gate. Caps aggression OR folds large calls on the transition."""
    global _V1510C_FIRED
    try:
        if state.get("street") != "river":
            return intended_action
        if not _v1510c_river_creates_pair(board):
            return intended_action
        if _v1510c_hero_is_fh_or_better(hero_cards, board):
            return intended_action
        commit = _gov_commit_fraction(state, intended_action)
        if commit < 0.30:
            return intended_action
        action_type = intended_action.get("action")
        if action_type in ("raise", "bet", "all_in"):
            _V1510C_FIRED += 1
            if len(_V1510C_FIRED_LOG) < 50:
                _V1510C_FIRED_LOG.append({
                    "hand_id": state.get("hand_id"), "pot": state.get("pot", 0),
                    "hero_cards": list(hero_cards), "board": list(board),
                    "old": dict(intended_action),
                })
            can_check = state.get("can_check", False)
            new_action = {"action": "check"} if can_check else {"action": "call"}
            if _V1510C_FIRED_LOG:
                _V1510C_FIRED_LOG[-1]["new"] = dict(new_action)
            return new_action
        if action_type == "call":
            owed = state.get("amount_owed", 0) or 0
            pot = max(state.get("pot", 1) or 1, 1)
            if owed > 0.45 * pot:
                _V1510C_FIRED += 1
                if len(_V1510C_FIRED_LOG) < 50:
                    _V1510C_FIRED_LOG.append({
                        "hand_id": state.get("hand_id"), "pot": state.get("pot", 0),
                        "hero_cards": list(hero_cards), "board": list(board),
                        "old": dict(intended_action), "new": {"action": "fold"},
                    })
                return {"action": "fold"}
        return intended_action
    except Exception:
        return intended_action


# ===========================================================================
# ============ v15.10d Multiway Paired-River Super-Cap ======================
# ===========================================================================
# Stricter than 10c. When 3+ players were active going into river AND board
# is paired, multiway continuing ranges are very strong. Cap aggression even
# when hero has trips (only straight/flush/FH+ exempt). Built on v15.10c.

_V1510D_FIRED = 0
_V1510D_FIRED_LOG = []
_V1510D_TRIPS_OR_BETTER = ("Trips", "Three of a Kind", "Straight", "Flush",
                            "Full House", "Quads", "Straight Flush")


def _v1510d_is_paired_board(board):
    if not board or len(board) < 5:
        return False
    ranks = [c[0] for c in board if c]
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    return max(counts.values()) >= 2 if counts else False


def _v1510d_multiway_active_at_river(action_log, n_players):
    """Count seats that didn't fold on flop/turn/river. Returns True if 3+."""
    if n_players <= 2:
        return False
    folded = set()
    for a in (action_log or []):
        if a.get("action") == "fold":
            folded.add(a.get("seat"))
    return (n_players - len(folded)) >= 3


def _v1510d_hero_trips_or_better(hero_cards, board):
    """eval7 check. FAIL OPEN (returns True -> no cap) on errors."""
    try:
        if len(hero_cards) != 2 or len(board) != 5:
            return True
        score = eval7.evaluate([eval7.Card(c) for c in list(hero_cards) + list(board)])
        ht = str(eval7.handtype(score))
        return ht in _V1510D_TRIPS_OR_BETTER
    except Exception:
        return True


def multiway_paired_river_supercap(state, intended_action, hero_cards, board,
                                     action_log, n_players):
    """v15.10d: cap aggression on multiway paired river when hero < trips."""
    global _V1510D_FIRED
    try:
        if state.get("street") != "river":
            return intended_action
        if not _v1510d_is_paired_board(board):
            return intended_action
        if not _v1510d_multiway_active_at_river(action_log, n_players):
            return intended_action
        action_type = intended_action.get("action")
        if action_type not in ("raise", "bet", "all_in"):
            return intended_action
        if _v1510d_hero_trips_or_better(hero_cards, board):
            return intended_action
        _V1510D_FIRED += 1
        if len(_V1510D_FIRED_LOG) < 50:
            _V1510D_FIRED_LOG.append({
                "hand_id": state.get("hand_id"), "pot": state.get("pot", 0),
                "hero_cards": list(hero_cards), "board": list(board),
                "old": dict(intended_action),
            })
        can_check = state.get("can_check", False)
        new_action = {"action": "check"} if can_check else {"action": "call"}
        if _V1510D_FIRED_LOG:
            _V1510D_FIRED_LOG[-1]["new"] = dict(new_action)
        return new_action
    except Exception:
        return intended_action


# ===========================================================================
# ============ v15.12a Flop Deep-Stack All-In Cap (Phase A) =================
# ===========================================================================
# Targets the 100% all-in flop big-loss leak. Caps the ACTION 'all_in' only
# when hero is deep-stacked (>=40 BB effective) without a protected hand or
# equity profile. Downgrades to a large raise (preserves pressure). Fails
# OPEN: any error returns intended_action unchanged.

_V1512A_FIRED = 0
_V1512A_SKIPPED_PROTECTED = 0
_V1512A_DECISION_LOG = []
_V1512A_STRAIGHT_OR_BETTER = ("Straight", "Flush", "Full House", "Quads",
                              "Straight Flush")
_V1512A_PAIR_LIKE = ("Pair", "Two Pair", "Trips", "Three of a Kind")


def _v1512a_hand_class(hero_cards, board):
    """Returns eval7 handtype string. On error returns 'Full House' so the
    cap fails open (FH+ is protected -> no cap applied)."""
    try:
        if len(hero_cards) != 2 or len(board) < 3:
            return "Full House"
        score = eval7.evaluate(
            [eval7.Card(c) for c in list(hero_cards) + list(board)])
        return str(eval7.handtype(score))
    except Exception:
        return "Full House"


def _v1512a_has_set(hero_cards, board):
    """Pocket pair matching a board card. Excludes board-only trips."""
    try:
        if len(hero_cards) != 2:
            return False
        r1, r2 = hero_cards[0][0], hero_cards[1][0]
        if r1 != r2:
            return False
        return r1 in [c[0] for c in board]
    except Exception:
        return False


def _v1512a_has_nut_flush_draw(hero_cards, board):
    """Hero has 4 cards to the nut flush (Ace of the suit OR no Ace on
    board higher than hero's high)."""
    try:
        all_cards = list(hero_cards) + list(board)
        suit_counts = {}
        for c in all_cards:
            s = c[1]
            suit_counts[s] = suit_counts.get(s, 0) + 1
        for suit, cnt in suit_counts.items():
            if cnt == 4:
                hero_in_suit = [c for c in hero_cards if c[1] == suit]
                if any(c[0] == 'A' for c in hero_in_suit):
                    return True
        return False
    except Exception:
        return False


def _v1512a_has_oesd(hero_cards, board):
    """Hero has an open-ended straight draw (8 outs)."""
    try:
        rank_to_idx = {r: i for i, r in enumerate('23456789TJQKA')}
        idxs = set()
        for c in (list(hero_cards) + list(board)):
            r = c[0]
            if r in rank_to_idx:
                idxs.add(rank_to_idx[r])
            if r == 'A':
                idxs.add(-1)
        sr = sorted(idxs)
        for i in range(len(sr) - 3):
            if sr[i + 3] - sr[i] == 3:
                low = sr[i] - 1
                high = sr[i + 3] + 1
                if low >= -1 and high <= 12:
                    return True
        return False
    except Exception:
        return False


def _v1512a_mc_equity(hero_cards, board, n_opp, time_budget_s=0.18):
    """Returns (equity, ci_half) using v15.6's _equity_vs_random. On any
    failure returns (None, None) so the cap proceeds without equity proof."""
    try:
        deadline = _now() + time_budget_s
        eq = _equity_vs_random(hero_cards, board, max(1, n_opp), deadline,
                               batch=200, max_roll=2400, ci_threshold=0.03)
        # _equity_vs_random doesn't return ci half-width; approximate from
        # max_roll completion. Assume CI is below 0.03 since that's the
        # early-stop threshold.
        return float(eq), 0.03
    except Exception:
        return None, None


def flop_deepstack_allin_cap(state, intended_action, hero_cards, board, n_opp):
    """v15.12a: cap all-in on the flop when deep without protected hand."""
    global _V1512A_FIRED, _V1512A_SKIPPED_PROTECTED
    try:
        if state.get("street") != "flop":
            return intended_action
        if len(board) != 3:
            return intended_action
        if intended_action.get("action") != "all_in":
            return intended_action
        your_stack = state.get("your_stack", 0) or 0
        your_bet = state.get("your_bet_this_street", 0) or 0
        effective = your_stack + your_bet
        if effective < 4000:
            return intended_action
        hand_class = _v1512a_hand_class(hero_cards, board)
        if hand_class in _V1512A_STRAIGHT_OR_BETTER:
            _V1512A_SKIPPED_PROTECTED += 1
            return intended_action
        if _v1512a_has_set(hero_cards, board):
            _V1512A_SKIPPED_PROTECTED += 1
            return intended_action
        has_nfd = _v1512a_has_nut_flush_draw(hero_cards, board)
        has_oesd = _v1512a_has_oesd(hero_cards, board)
        has_pair = hand_class in _V1512A_PAIR_LIKE
        # (c) nut FD + pair
        if has_nfd and has_pair:
            _V1512A_SKIPPED_PROTECTED += 1
            return intended_action
        # (d) nut FD + 2 overcards
        if has_nfd and not has_pair:
            rank_to_idx = {r: i for i, r in enumerate('23456789TJQKA')}
            board_idx = [rank_to_idx.get(c[0], 0) for c in board]
            max_board = max(board_idx) if board_idx else 0
            hero_overs = sum(1 for c in hero_cards
                             if rank_to_idx.get(c[0], 0) > max_board)
            if hero_overs >= 2:
                _V1512A_SKIPPED_PROTECTED += 1
                return intended_action
        # (e) combo: OESD + pair
        if has_oesd and has_pair:
            _V1512A_SKIPPED_PROTECTED += 1
            return intended_action
        # (f) MC equity backup
        deep_multiplier = your_stack > 30000
        threshold = 0.68 if deep_multiplier else 0.62
        eq, ci = _v1512a_mc_equity(hero_cards, board, max(1, n_opp))
        if eq is not None and ci is not None and ci <= 0.03 and eq >= threshold:
            _V1512A_SKIPPED_PROTECTED += 1
            return intended_action
        # Fire: downgrade to large raise.
        _V1512A_FIRED += 1
        if len(_V1512A_DECISION_LOG) < 50:
            _V1512A_DECISION_LOG.append({
                "hand_id": state.get("hand_id"),
                "pot": state.get("pot", 0),
                "stack": your_stack,
                "hero": list(hero_cards),
                "board": list(board),
                "hand_class": hand_class,
                "has_nfd": has_nfd,
                "has_oesd": has_oesd,
                "equity": eq,
                "deep": deep_multiplier,
            })
        pot = state.get("pot", 0) or 0
        amount_owed = state.get("amount_owed", 0) or 0
        current_bet = amount_owed + your_bet
        min_raise_to = state.get("min_raise_to", 0) or 0
        target = max(min_raise_to, int(2.5 * pot))
        target = max(target, int(current_bet * 3))
        target = min(target, effective)
        if target <= 0 or target >= effective:
            return intended_action  # nothing to downgrade to; ship all_in
        return {"action": "raise", "amount": target}
    except Exception:
        return intended_action


def apply_governors(action, state, p):
    """Master chain: B -> D -> A -> C -> E -> K. Vetoes from A/C disable E.
    v15.5: PATCH K is the last step on stack-off decisions (commit >= 0.40)
    that haven't been vetoed by A or C. K runs multi-candidate EV simulation
    with a strict 500ms budget; Patch I's budget is reduced when K will fire."""
    global _K_CHANGED_ACTION_COUNT
    try:
        _GOV_COUNTS["called"] += 1
        opp_id = relevant_opponent_id(state)
        hand_class = _gov_hero_class(state, p)
        # Predict whether K will fire this decision so I can reserve its budget.
        will_k_fire = _gov_commit_fraction(state, action) >= 0.40
        eq = None
        if hand_class is not None and _gov_commit_fraction(state, action) >= 0.40:
            try:
                eq = critical_decision_equity(
                    state,
                    p.get("cards") or [],
                    state.get("community_cards") or [],
                    max(1, _n_live_opponents(state)),
                    k_will_fire=will_k_fire)
            except Exception:
                eq = None
        action = _patch_B(state, action, hand_class)
        action = _patch_D(state, action, hand_class)
        action, v_a = _patch_A(state, action, hand_class, opp_id)
        action, v_c = _patch_C(state, action, hand_class, eq)
        action = _patch_E(state, action, opp_id, hand_class, v_a or v_c)
        # v15.5 PATCH K: only fires when not A/C vetoed AND action is still a
        # stack-off commit. Multi-candidate EV via runtime stat-based sim.
        if (not (v_a or v_c)
                and action.get("action") in ("call", "raise", "all_in")
                and _gov_commit_fraction(state, action) >= 0.40):
            try:
                hero_seat = state.get("seat_to_act")
                hero_cards = p.get("cards") or []
                board = state.get("community_cards") or []
                # Only run K postflop (board with >=3 cards) where range
                # estimation is meaningful. Preflop stack-off relies on
                # existing preflop_allin_equity_decision.
                if len(board) >= 3 and len(hero_cards) == 2:
                    k_action = k_stack_off_ev_simulation(
                        state, hero_cards, board, opp_id, action, hero_seat)
                    if k_action is not None and (
                            k_action.get("action") != action.get("action")
                            or k_action.get("amount") != action.get("amount")):
                        _K_CHANGED_ACTION_COUNT += 1
                        action = k_action
            except Exception:
                pass
        # v15.10c FINAL VETO: river-pair transition guard.
        try:
            board = state.get("community_cards") or []
            hole = p.get("cards") if p else (state.get("your_cards") or [])
            action = river_pair_transition_guard(state, action, hole, board)
        except Exception:
            pass
        # v15.10d FINAL VETO #2: multiway paired-river super-cap.
        # Multiway pots have much stronger continuing ranges; cap even trips.
        try:
            board = state.get("community_cards") or []
            hole = p.get("cards") if p else (state.get("your_cards") or [])
            al = state.get("action_log") or []
            n_players = len(state.get("players") or [])
            action = multiway_paired_river_supercap(state, action, hole, board, al, n_players)
        except Exception:
            pass
        # v15.12a FINAL VETO #3: flop deep-stack all-in cap.
        try:
            board = state.get("community_cards") or []
            hole = p.get("cards") if p else (state.get("your_cards") or [])
            n_opp = max(1, _n_live_opponents(state))
            action = flop_deepstack_allin_cap(state, action, hole, board, n_opp)
        except Exception:
            pass
        return action
    except Exception:
        return action


def emergency_fallback(state):
    if state.get("can_check"):
        return {"action": "check"}
    return {"action": "fold"}


def map_to_legal_action(intended, state):
    a = intended.get("action")
    if a == "check" and not state.get("can_check"):
        return {"action": "fold"}
    if a == "raise":
        try:
            amt = int(intended.get("amount", 0))
        except (TypeError, ValueError):
            return emergency_fallback(state)
        min_r = state.get("min_raise_to", 0)
        max_r = state.get("your_stack", 0) + state.get("your_bet_this_street", 0)
        if min_r > max_r:
            return {"action": "call"} if not state.get("can_check") else {"action": "check"}
        if amt >= max_r:
            return {"action": "all_in"}
        return {"action": "raise", "amount": max(amt, min_r)}
    if a in ("fold", "call", "all_in"):
        return {"action": a}
    return emergency_fallback(state)


def parse_state(state):
    return {
        "cards": state.get("your_cards", []) or [],
        "seat": state.get("seat_to_act", 0),
        "street": state.get("street", "preflop"),
        "pot": state.get("pot", 0),
        "owed": state.get("amount_owed", 0),
        "stack": state.get("your_stack", 0),
        "can_check": state.get("can_check", False),
    }


def decide(state):
    global _EQ_DEADLINE, _RNG, _T0
    if state.get("type") == "warmup":
        try:
            eval7.evaluate([eval7.Card("As"), eval7.Card("Kd"), eval7.Card("Qc"),
                            eval7.Card("Jh"), eval7.Card("9s")])
            precompute_preflop_equity(2.0)        # P34 table (common cases), time-boxed
        except Exception:
            pass
        return {"action": "check"}

    _T0 = _now()
    # v12 time budget: cap the equity layer so the whole decision stays well under
    # the 800ms soft budget (and far under the 2s hard limit) even on slow hardware.
    _EQ_DEADLINE = min(_T0 + EQ_BUDGET, _T0 + SOFT_BUDGET - 0.15)
    try:
        _RNG = random.Random(_decision_seed(state))
    except Exception:
        _RNG = random
    try:
        try:
            update_opponent_memory(state)        # cheap; keeps per-villain stats current
        except Exception:
            pass                                  # modeling must never break the decision
        p = parse_state(state)
        if _now() - _T0 > SOFT_BUDGET:           # staged checkpoint: bail to a safe action
            return emergency_fallback(state)
        if p["street"] == "preflop" and len(p["cards"]) == 2:
            act = preflop_decision(state, p)
        else:
            act = postflop_decision(state, p)
        # v14-final D2 patch: stack-off governor chain (B->D->A->C->E)
        act = apply_governors(act, state, p)
        return map_to_legal_action(act, state)
    except Exception:
        return emergency_fallback(state)
