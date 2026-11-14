"""Enemy zoo (tuning): nit_preflop — only QQ+/AK preflop, straightforward postflop."""
import eval7

BOT_NAME = "NitPreflop"
RANK_ORDER = "23456789TJQKA"
NIT_RANGE = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('A', 'K')}


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board]))
    try:
        return cats.index(ht)
    except ValueError:
        return 0


def _top_pair_plus(hole, board):
    if len(board) < 3:
        return False
    c = _cat(hole, board)
    if c >= 2:
        return True
    if c == 1:
        branks = [x[0] for x in board]
        top = max(branks, key=lambda r: RANK_ORDER.index(r))
        hranks = [x[0] for x in hole]
        if hranks[0] == hranks[1] and RANK_ORDER.index(hranks[0]) > RANK_ORDER.index(top):
            return True
        if top in hranks:
            return True
    return False


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    cards = state.get("your_cards", []) or []
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)

    if state.get("street") == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        if ranks in NIT_RANGE:
            return {"action": "raise", "amount": min(min_r * 3, stack + my_bet)}
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    # Postflop: bet/call with top pair or better, otherwise check/fold.
    board = state.get("community_cards", []) or []
    strong = _top_pair_plus(cards, board)
    if state.get("can_check"):
        if strong:
            return {"action": "raise", "amount": min(int(pot * 0.66), stack + my_bet)}
        return {"action": "check"}
    if strong:
        return {"action": "call"}
    if owed > 0 and pot / owed >= 4:
        return {"action": "call"}
    return {"action": "fold"}
