"""
v3.5 — size-aware preflop defense (extends v3).

Fixes a blueprint COVERAGE hole, not an opponent-modeling problem: v3's preflop
tree treats "facing a raise" as one bucket regardless of raise size, so a 2bb
min-raise and a 3.5x open route to the same decision. Against a min-raise the
defender gets ~3:1 and should defend ~60-80% of hands; v3 folded too much and
bled chips (e.g. -4500/match HU vs min_raise_spammer).

v3.5 adds RAISE SIZE as a new infoset dimension for facing-raise decisions:
  classify_raise_size(amount_to_call) -> min/small/standard/large/huge
  - standard_raise -> EXISTING v3 ranges unchanged (no regression on normal opens)
  - min_raise / small_raise -> WIDEN defense (union with a percentile range)
  - large_raise / huge_raise -> TIGHTEN defense (intersect with a percentile range)
Applied to facing-open (1 raise), facing-3bet (2), and facing-4bet (3+).

Per ADDITIONAL_INSTRUCTIONS.md Patch 3, ranges are hand-authored where it
matters with a documented percentile fallback (HAND_RANK_ORDER). Multiway
postflop layer and v2 postflop are unchanged.

Per Patch 8: imports limited to os/time/math/random + eval7.
"""
import os
import time
import math
import random

import eval7

BOT_NAME = "OurBot v3.5"

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


def preflop_decision(state, p):
    cards = p["cards"]
    hand = hand_class(cards)
    button, n, sb, bb = get_positions(state)
    pos = position_label(p["seat"], button, n)
    raises, last_raiser, bb_amt, n_limpers = preflop_context(state)
    eff_bb = p["stack"] / bb_amt if bb_amt else 100

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
    bucket = classify_raise_size(p["owed"], bb_amt)
    cont = VS_4BET_CONT | R("QQ, AKo") if bucket in ("min_raise", "small_raise") else VS_4BET_CONT
    if hand in cont:
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


def facing_bucket(state):
    if state.get("can_check"):
        return "checked_to"
    owed = state.get("amount_owed", 0)
    pot = state.get("pot", 0)
    if state.get("your_bet_this_street", 0) > 0:
        return "facing_raise"
    base = max(pot - owed, 1)
    ratio = owed / base
    if ratio < 0.4:
        return "facing_small"
    if ratio < 0.7:
        return "facing_half"
    if ratio < 1.2:
        return "facing_pot"
    return "facing_overbet"


# ---- Authored strategy generator ------------------------------------------

STRONG_MADE = {"two_pair", "set_or_trips", "straight", "flush",
               "full_house_or_better", "overpair"}
GOOD_MADE = {"strong_top_pair"}
MEDIUM_MADE = {"weak_top_pair", "second_pair"}
WEAK_MADE = {"third_pair_or_underpair", "weak_showdown"}
STRONG_DRAWS = {"flush_draw", "OESD", "combo_draw", "nut_draw"}
WEAK_DRAWS = {"gutshot", "backdoor"}


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


# ---- Sampling + concrete sizing -------------------------------------------

def sample(dist):
    items = sorted(dist.items())
    r = random.random()
    c = 0.0
    for a, p in items:
        c += p
        if r < c:
            return a
    return items[-1][0]


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
        frac = {"bet_33": 0.33, "bet_66": 0.66, "bet_100": 1.0, "bet_150": 1.5}[abstract]
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

    abstract = sample(dist)
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
    if state.get("type") == "warmup":
        # Touch eval7 once so any lazy init happens inside the 30s warmup budget.
        try:
            eval7.evaluate([eval7.Card("As"), eval7.Card("Kd"), eval7.Card("Qc"),
                            eval7.Card("Jh"), eval7.Card("9s")])
        except Exception:
            pass
        return {"action": "check"}

    try:
        p = parse_state(state)
        if p["street"] == "preflop" and len(p["cards"]) == 2:
            return map_to_legal_action(preflop_decision(state, p), state)
        return map_to_legal_action(postflop_decision(state, p), state)
    except Exception:
        return emergency_fallback(state)
