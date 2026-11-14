"""Enemy zoo (HELD-OUT): solver_approximator — the modal 'good LLM-built' bot.

Patch 16a Priority 1. Standard 6-max charts, eval7 equity postflop, ~70% IP /
60% OOP c-bet, half-pot default sizing, calls down top-pair-good-kicker+, folds
to large bets without a strong made hand. If we can't beat this, we won't make
finals — so it's the single most important held-out yardstick.
"""
import random
import eval7

BOT_NAME = "SolverApproximator"
RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA")}

OPEN = {  # by seat fraction (early->late); generated lazily below
    "early": {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'),
              ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('K', 'Q'), ('K', 'J'), ('Q', 'J')},
    "mid":   {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'),
              ('7', '7'), ('6', '6'), ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'),
              ('K', 'Q'), ('K', 'J'), ('K', 'T'), ('Q', 'J'), ('Q', 'T'), ('J', 'T'), ('T', '9')},
    "late":  None,  # widest; handled by a percentile-ish check below
}
THREEBET = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('A', 'K'), ('A', 'Q'), ('J', 'J')}


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = str(eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board])))
    return cats.index(ht) if ht in cats else 0


def _top_pair_good(hole, board):
    if len(board) < 3:
        return False
    c = _cat(hole, board)
    if c >= 2:
        return True
    if c == 1:
        branks = [x[0] for x in board]
        top = max(branks, key=lambda r: RANK_VAL[r])
        hr = [x[0] for x in hole]
        if hr[0] == hr[1] and RANK_VAL[hr[0]] > RANK_VAL[top]:
            return True
        if top in hr:
            kicker = hr[1] if hr[0] == top else hr[0]
            return RANK_VAL[kicker] >= RANK_VAL['T']  # good kicker
    return False


def _pos_bucket(seat, n):
    frac = seat / max(n - 1, 1)
    if frac < 0.34:
        return "early"
    if frac < 0.67:
        return "mid"
    return "late"


def _in_open_range(hole, seat, n):
    ranks = tuple(sorted([c[0] for c in hole], reverse=True))
    suited = hole[0][1] == hole[1][1]
    pb = _pos_bucket(seat, n)
    if pb == "late":
        # wide: any pair, any ace, any two broadway, suited connectors-ish
        if ranks[0] == ranks[1]:
            return True
        if 'A' in ranks:
            return True
        if RANK_VAL[ranks[0]] >= RANK_VAL['T'] and RANK_VAL[ranks[1]] >= RANK_VAL['9']:
            return True
        if suited and RANK_VAL[ranks[0]] - RANK_VAL[ranks[1]] <= 2 and RANK_VAL[ranks[1]] >= RANK_VAL['5']:
            return True
        return False
    return ranks in OPEN[pb]


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}
    cards = state.get("your_cards", []) or []
    board = state.get("community_cards", []) or []
    street = state.get("street")
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)
    seat = state.get("seat_to_act", 0)
    n = len(state.get("players", []) or [1, 1])
    max_to = stack + my_bet

    if street == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        current = state.get("current_bet", 100)
        facing_raise = current > 100
        if facing_raise:
            if ranks in THREEBET:
                return {"action": "raise", "amount": min(int(current * 3), max_to)}
            if _in_open_range(cards, seat, n) and owed <= pot:
                return {"action": "call"}
            return {"action": "check"} if state.get("can_check") else {"action": "fold"}
        if _in_open_range(cards, seat, n):
            return {"action": "raise", "amount": min(int(min_r * 2.3), max_to)}
        return {"action": "check"} if state.get("can_check") else {"action": "fold"}

    # Postflop
    strong = _top_pair_good(cards, board)
    very_strong = _cat(cards, board) >= 2
    in_position = (seat / max(n - 1, 1)) > 0.5
    if state.get("can_check"):
        cbet_freq = 0.70 if in_position else 0.60
        if very_strong or (strong and random.random() < 0.85) or random.random() < cbet_freq * 0.5:
            return {"action": "raise", "amount": min(int(pot * 0.5), max_to)}  # half-pot
        return {"action": "check"}
    # facing a bet: pot odds + made-hand gating
    ratio = owed / max(pot, 1)
    if very_strong:
        if random.random() < 0.4:
            return {"action": "raise", "amount": min(int(pot * 0.9), max_to)}
        return {"action": "call"}
    if strong:
        return {"action": "call"} if ratio <= 0.8 else ({"action": "call"} if random.random() < 0.4 else {"action": "fold"})
    # weak: call only cheap, fold to large
    if owed > 0 and pot / owed >= 4:
        return {"action": "call"}
    return {"action": "fold"}
