"""
v2 — hand-authored postflop strategy table (extends v1).

Preflop is UNCHANGED from v1 (positional blueprint).
Postflop is replaced: instead of v0's "check / 3:1-call / fold", v2 plays a
real mixed strategy built from poker theory.

Per ADDITIONAL_INSTRUCTIONS.md Patch 5:
  - This is a HAND-AUTHORED strategy in CFR-compatible form
    (infoset -> probability vector over abstract actions). It is NOT generated
    by running CFR. A future CFR table can drop into POSTFLOP_STRATEGY_TABLE.
  - The authored strategy is expressed as a generator (`authored_strategy`)
    that returns a probability vector for any infoset, giving ~100% coverage
    so we never resort to a dumb default ("fallback") in normal play.

Infoset = (hand_strength, board_texture, draw, spr, position, facing_action).
Abstract actions:
  when checked to : check, bet_33, bet_66, bet_100, bet_150, all_in
  facing a bet    : fold, call, raise_value, raise_pot, all_in

Why this fixes the v1 aggressor leak: facing small/medium bets, v2 now
bluff-catches with medium hands and raises back (value + some bluffs) instead
of folding everything.

Per Patch 8: submission imports are limited to stdlib + numpy + eval7 + scipy.
v2 uses only os/time/math/random + eval7.
"""
import os
import time
import math
import random

import eval7

BOT_NAME = "OurBot v2"

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
        tb = (BLIND_DEFEND_3BET if steal else VS_OPEN_3BET).get(pos, set())
        cl = (BLIND_DEFEND_CALL if steal else VS_OPEN_CALL).get(pos, set())
        if hand in tb:
            hero_rel = (p["seat"] - button) % n
            vill_rel = (last_raiser - button) % n if last_raiser is not None else 0
            return {"action": "raise", "amount": threebet_size(state, _is_in_position(hero_rel, vill_rel, n))}
        if hand in cl:
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    if raises == 2:
        if hand in VS_3BET_4BET.get(pos, set()):
            return {"action": "raise", "amount": fourbet_size(state)}
        if hand in VS_3BET_CALL.get(pos, set()):
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    if hand in VS_4BET_CONT:
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


def concrete_action(abstract, state, pot, owed):
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
        return {"action": "raise", "amount": max(int(frac * pot), min_r)}
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
    abstract = sample(dist)
    return concrete_action(abstract, state, state.get("pot", 0), state.get("amount_owed", 0))


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
