"""
v1 — hand-crafted preflop blueprint (extends v0).

What changed from v0:
  - Real positional preflop play: open / 3-bet / 4-bet / flat / blind-defense,
    indexed by hero position and the raiser's position.
  - Short-stack push/fold (jam-or-fold) when effective stack <= 15bb.
  - Fixes v0's biggest leak: it no longer surrenders the blinds.

Postflop is UNCHANGED from v0 (free check / 3:1 pot-odds call / else fold).
Real postflop play arrives in v2.

================================================================
HOW TO EDIT THE RANGES (this is the part a poker player tunes)
================================================================
All ranges live in the "RANGE DEFINITIONS" block below, written in standard
poker shorthand and expanded automatically at import time. Notation supported:

  AA            one specific class (pair)
  AKs / AKo     suited / offsuit specific class
  T9s           any specific two-card class
  88+           that pair and every higher pair  (88,99,...,AA)
  ATs+          fixed HIGH card, kicker upward    (ATs,AJs,AQs,AKs)
  AJo+          same, offsuit                     (AJo,AQo,AKo)
  A2s+          (A2s,A3s,...,AKs)

Connectors/gappers that are NOT "fixed-high-card" must be listed explicitly,
e.g. write "T9s, 98s, 87s" rather than "T9s+". Separate tokens with commas
and/or spaces. Edit the strings, save, and re-run bench.py to measure.
================================================================
"""
import os
import time

BOT_NAME = "OurBot v1"

DATA_DIR = os.environ.get("BOT_DATA_DIR",
                          os.path.join(os.path.dirname(__file__), "data"))

# === Module globals (persist across hands within a match) ===
HAND_COUNT = 0
LAST_LOG_INDEX = 0
OPPONENT_STATS = {}

DEFAULT_BB = 100
SHORT_STACK_BB = 15           # at/below this effective depth -> push/fold
RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}


# ---------------------------------------------------------------------------
# Range-notation parser
# ---------------------------------------------------------------------------

def _expand_token(tok):
    tok = tok.strip()
    if not tok:
        return set()
    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok
    out = set()
    # Pair, e.g. "99" or "99+"
    if len(core) == 2 and core[0] == core[1] and core[0] in RANK_VAL:
        lo = RANK_VAL[core[0]]
        hi = RANK_VAL["A"] if plus else lo
        for v in range(lo, hi + 1):
            out.add(RANKS[v] * 2)
        return out
    # Non-pair "AKs"/"AKo" (optionally +)
    if len(core) == 3 and core[0] in RANK_VAL and core[1] in RANK_VAL and core[2] in "so":
        a, b, suit = core[0], core[1], core[2]
        hv, lv = RANK_VAL[a], RANK_VAL[b]
        if hv < lv:
            hv, lv = lv, hv
        if plus:
            for k in range(lv, hv):           # kicker from lv up to hi-1
                out.add(RANKS[hv] + RANKS[k] + suit)
        else:
            out.add(RANKS[hv] + RANKS[lv] + suit)
        return out
    return out  # unrecognised token -> ignore (kept robust)


def R(s):
    """Expand a shorthand range string into a set of canonical hand classes."""
    out = set()
    for tok in s.replace(",", " ").split():
        out |= _expand_token(tok)
    return out


# ===========================================================================
# RANGE DEFINITIONS  —  EDIT THESE
# (Draft ranges: solid, standard 100bb 6-max. Tune to taste.)
# ===========================================================================

# --- First-in opening ranges, by hero position ---
OPEN = {
    'UTG': R("22+, ATs+, KTs+, QTs+, JTs, T9s, AJo+, KQo"),
    'HJ':  R("22+, A9s+, A5s, KTs+, Q9s+, J9s+, T9s, 98s, ATo+, KJo+, QJo"),
    'CO':  R("22+, A2s+, K9s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, A9o+, A5o, KTo+, QTo+, JTo"),
    'BTN': R("22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K9o+, Q9o+, J9o+, T9o"),
    'SB':  R("22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, A7o+, A5o, K9o+, Q9o+, JTo"),
    # BB never opens first-in; this is the BB iso-raise range when checked to over limpers.
    'BB':  R("55+, A8s+, KTs+, QTs+, JTs, T9s, ATo+, KQo"),
}

# --- Facing a single raise, NON-steal spots (e.g. hero CO vs UTG open) ---
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

# --- Blind defense vs a late-position steal (villain in CO/BTN/SB) ---
BLIND_DEFEND_3BET = {
    'SB': R("TT+, AJs+, KQs, AQo+, A5s, A4s"),
    'BB': R("TT+, AQs+, AKo, A5s, A4s, K5s"),
}
BLIND_DEFEND_CALL = {
    'SB': R("99-22, ATs-AJs, KQs, KJs, QJs, JTs, T9s, 98s, AJo, KQo"),
    'BB': R("99-22, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 64s+, 54s, "
            "A2o+, K9o+, Q9o+, J9o+, T9o"),
}

# --- Facing a 3-bet (hero opened, got re-raised) ---
VS_3BET_4BET = {
    'UTG': R("KK+, AKs"),
    'HJ':  R("KK+, AKs, A5s"),
    'CO':  R("QQ+, AKs, A5s, A4s"),
    'BTN': R("QQ+, AKs, AKo, A5s, A4s"),
    'SB':  R("QQ+, AKs, A5s"),
    'BB':  R("KK+, AKs"),
}
VS_3BET_CALL = {
    'UTG': R("QQ-JJ, AQs, AKo"),
    'HJ':  R("QQ-TT, AQs, AJs, AKo, KQs"),
    'CO':  R("JJ-99, AQs, AJs, AKo, KQs, KJs, QJs"),
    'BTN': R("JJ-88, AQs-ATs, AKo, KQs, KJs, QJs, JTs"),
    'SB':  R("JJ-TT, AQs, AKo"),
    'BB':  R("QQ-TT, AQs, AKo, KQs"),
}

# --- Facing a 4-bet or beyond: continue only with the very top ---
VS_4BET_CONT = R("KK+, AKs")

# --- Short-stack push/fold (effective stack <= 15bb) ---
JAM_FIRST_IN = {
    'UTG': R("66+, ATs+, AJo+, KQs"),
    'HJ':  R("55+, A9s+, ATo+, KJs+, KQo"),
    'CO':  R("44+, A7s+, A9o+, KTs+, KJo+, QJs"),
    'BTN': R("22+, A2s+, A7o+, A5o, K9s+, KTo+, Q9s+, QJo, J9s+, T9s"),
    'SB':  R("22+, A2s+, A2o+, K5s+, K9o+, Q8s+, QTo+, J8s+, T8s+, 98s"),
    'BB':  R("33+, A7s+, A9o+, KTs+, KQo, QJs"),
}
JAM_VS_RAISE = R("88+, ATs+, AQo+, KQs")

# ===========================================================================
# END RANGE DEFINITIONS
# ===========================================================================


# ---------------------------------------------------------------------------
# State parsing helpers
# ---------------------------------------------------------------------------

def hand_class(cards):
    """['Ah','Kh'] -> 'AKs'; ['Kd','As'] -> 'AKo'; ['7c','7d'] -> '77'."""
    r0, r1 = cards[0][0], cards[1][0]
    if r0 == r1:
        return r0 + r1
    if RANK_VAL[r0] < RANK_VAL[r1]:
        r0, r1 = r1, r0
        hi_suit, lo_suit = cards[1][1], cards[0][1]
    else:
        hi_suit, lo_suit = cards[0][1], cards[1][1]
    suited = cards[0][1] == cards[1][1]
    return r0 + r1 + ("s" if suited else "o")


def get_positions(state):
    """Return (button_seat, n, sb_seat, bb_seat) inferred from blind posts."""
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
    """Return (n_raises, last_raiser_seat, bb_amount, n_limpers)."""
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
    """Postflop action order: SB(rel1) first ... BTN(rel0) last."""
    def order(rel):
        return rel - 1 if rel >= 1 else n - 1
    return order(hero_rel) > order(villain_rel)


# ---------------------------------------------------------------------------
# Safety layer (identical contract to v0)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Preflop sizing
# ---------------------------------------------------------------------------

def open_size(state, bb_amt, n_limpers):
    to = int(2.5 * bb_amt) + bb_amt * n_limpers
    return max(to, state.get("min_raise_to", to))


def threebet_size(state, ip):
    cur = state.get("current_bet", DEFAULT_BB)
    to = int(cur * (3.0 if ip else 4.0))
    return max(to, state.get("min_raise_to", to))


def fourbet_size(state):
    cur = state.get("current_bet", DEFAULT_BB)
    to = int(cur * 2.3)
    return max(to, state.get("min_raise_to", to))


# ---------------------------------------------------------------------------
# Preflop strategy
# ---------------------------------------------------------------------------

def preflop_decision(state, p):
    cards = p["cards"]
    hand = hand_class(cards)
    button, n, sb, bb = get_positions(state)
    pos = position_label(p["seat"], button, n)
    raises, last_raiser, bb_amt, n_limpers = preflop_context(state)
    eff_bb = p["stack"] / bb_amt if bb_amt else 100

    # --- Short stack: push/fold ---
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

    # --- Unopened pot: open-raise / iso / check ---
    if raises == 0:
        if pos == "BB" and p["can_check"]:
            if hand in OPEN["BB"]:
                return {"action": "raise", "amount": open_size(state, bb_amt, n_limpers)}
            return {"action": "check"}
        if hand in OPEN.get(pos, set()):
            return {"action": "raise", "amount": open_size(state, bb_amt, n_limpers)}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    # --- Facing a single raise ---
    if raises == 1:
        villain_pos = position_label(last_raiser, button, n) if last_raiser is not None else "CO"
        steal = pos in ("SB", "BB") and villain_pos in ("CO", "BTN", "SB")
        if steal:
            tb = BLIND_DEFEND_3BET.get(pos, set())
            cl = BLIND_DEFEND_CALL.get(pos, set())
        else:
            tb = VS_OPEN_3BET.get(pos, set())
            cl = VS_OPEN_CALL.get(pos, set())
        if hand in tb:
            hero_rel = (p["seat"] - button) % n
            vill_rel = (last_raiser - button) % n if last_raiser is not None else 0
            return {"action": "raise", "amount": threebet_size(state, _is_in_position(hero_rel, vill_rel, n))}
        if hand in cl:
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    # --- Facing a 3-bet ---
    if raises == 2:
        if hand in VS_3BET_4BET.get(pos, set()):
            return {"action": "raise", "amount": fourbet_size(state)}
        if hand in VS_3BET_CALL.get(pos, set()):
            return {"action": "call"}
        return {"action": "check"} if p["can_check"] else {"action": "fold"}

    # --- Facing a 4-bet or beyond ---
    if hand in VS_4BET_CONT:
        return {"action": "all_in"}
    return {"action": "check"} if p["can_check"] else {"action": "fold"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
        return {"action": "check"}

    try:
        p = parse_state(state)

        if p["street"] == "preflop" and len(p["cards"]) == 2:
            return map_to_legal_action(preflop_decision(state, p), state)

        # Postflop: v0 logic (free check / 3:1 pot-odds call / else fold).
        if p["can_check"]:
            return {"action": "check"}
        if p["owed"] > 0 and p["pot"] / p["owed"] >= 3:
            return {"action": "call"}
        return {"action": "fold"}

    except Exception:
        return emergency_fallback(state)
