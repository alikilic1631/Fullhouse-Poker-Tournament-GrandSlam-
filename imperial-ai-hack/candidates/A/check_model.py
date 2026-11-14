"""Does the opponent model change RANGES (and hence decisions) after ~60 observed actions?

Warm a fresh Agent up at a table with known archetypes, then probe fixed spots.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0], "house"]
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
from engine import FixedHandsTable  # noqa: E402
from engine.players import LocalPlayer  # noqa: E402

B = H.B
R13 = "AKQJT98765432"


def cards_of(a):
    i, j = divmod(a, 13)
    if i == j:
        return [R13[i] + "s", R13[i] + "h"]
    if i < j:
        return [R13[i] + "s", R13[j] + "s"]
    return [R13[j] + "s", R13[i] + "h"]


def warm(opps, hands):
    seats = [B.Agent] + opps           # we are seat 0
    players = [LocalPlayer(c) for c in seats]
    FixedHandsTable(players, hands=hands, seed=3).play()
    return players[0].agent


def base_state(ag, hole, hist, pot, tc, bets, stacks, folded, button, board=(), street="preflop", legal=None,
               lo=None, hi=None):
    return {"hole_cards": hole, "board": list(board), "street": street, "seat": 0, "button": button,
            "stacks": stacks, "bets": bets, "folded": folded, "pot": pot, "to_call": tc,
            "min_raise_to": lo, "max_raise_to": hi, "legal_actions": legal or ["fold", "call"],
            "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 9999, "betting": "no_limit",
            "raise_cap": None, "raises_this_street": 1, "history": hist}


def call_width_vs_shove(ag, v):
    """We are the big blind (seat 0, button 6); seat v open-shoves, everyone else folds."""
    n = 8
    hist = [{"seat": 7, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 0, "street": "preflop", "action": "big_blind", "amount": 20}]
    folded = [False] * n
    for s in range(1, 8):
        if s == v:
            hist.append({"seat": s, "street": "preflop", "action": "raise", "amount": 2000})
        elif s != 7 or v != 7:
            hist.append({"seat": s, "street": "preflop", "action": "fold", "amount": 0})
            folded[s] = True
    bets = [0] * n
    bets[0] = 20
    bets[7] = 10
    bets[v] = 2000
    stacks = [2000] * n
    stacks[0] = 1980
    stacks[v] = 0
    tot = 0
    for a in range(169):
        ag.prc_hand = -1
        st = base_state(ag, cards_of(a), hist, 2030, 1980, bets, stacks, folded, 6)
        if ag.act(st)["action"] == "call":
            tot += B.PF_COMBOS[a]
    return tot / 1326.0


def open_width_btn(ag):
    """We are on the button (seat 0), folded to us; blinds are seats 1 and 2."""
    n = 8
    hist = [{"seat": 1, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 2, "street": "preflop", "action": "big_blind", "amount": 20}]
    folded = [False] * n
    for s in range(3, 8):
        hist.append({"seat": s, "street": "preflop", "action": "fold", "amount": 0})
        folded[s] = True
    bets = [0, 10, 20] + [0] * 5
    stacks = [2000, 1990, 1980] + [2000] * 5
    tot = 0
    for a in range(169):
        ag.prc_hand = -1
        st = base_state(ag, cards_of(a), hist, 30, 20, bets, stacks, folded, 0,
                        legal=["fold", "call", "raise"], lo=40, hi=2000)
        st["raises_this_street"] = 0
        if ag.act(st)["action"] == "raise":
            tot += B.PF_COMBOS[a]
    return tot / 1326.0


def cbet_freq(ag, v, hole=("5c", "4c"), board=("Ks", "7d", "2h")):
    """We raised the button (seat 0), seat v (big blind = seat 2) called; flop checked to us with air."""
    n = 8
    hist = [{"seat": 1, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 2, "street": "preflop", "action": "big_blind", "amount": 20}]
    folded = [False] * n
    for s in range(3, 8):
        hist.append({"seat": s, "street": "preflop", "action": "fold", "amount": 0})
        folded[s] = True
    hist += [{"seat": 0, "street": "preflop", "action": "raise", "amount": 50},
             {"seat": 1, "street": "preflop", "action": "fold", "amount": 0},
             {"seat": 2, "street": "preflop", "action": "call", "amount": 30},
             {"seat": 2, "street": "flop", "action": "check", "amount": 0}]
    folded[1] = True
    stacks = [1950, 1990, 1950] + [2000] * 5
    k = 0
    N = 300
    for i in range(N):
        ag.prc_hand = -1
        st = base_state(ag, list(hole), hist, 110, 0, [0] * n, stacks, folded, 0, board=board, street="flop",
                        legal=["check", "raise"], lo=20, hi=1950)
        st["raises_this_street"] = 0
        st["hand_number"] = 9000 + i
        if ag.act(st)["action"] == "raise":
            k += 1
    return k / N


if __name__ == "__main__":
    S40, S4 = H.mk_shove(0.40), H.mk_shove(0.04)
    for hands in (10, 30, 80, 200):
        ag = warm([H.STN, H.Nit, S40, S4, H.TAG, H.Maniac, H.RND], hands)
        # seats: 1 station, 2 nit, 3 shove40, 4 shove4, 5 tag, 6 maniac, 7 random
        print("after %3d hands: call width vs shove40 %.3f | vs shove4 %.3f | g(shove40)=%.2f psh=%.2f / %.2f" % (
            hands, call_width_vs_shove(ag, 3), call_width_vs_shove(ag, 4), ag._prof(3).g, ag._prof(3).psh,
            ag._prof(4).psh))
    for name, blinds in (("nits", [H.Nit, H.Nit]), ("stations", [H.STN, H.STN]), ("TAGs", [H.TAG, H.TAG])):
        for hands in (10, 200):
            ag = warm(blinds + [H.TAG, H.EqBot, H.TAG, H.EqBot, H.TAG], hands)
            print("blinds=%-8s after %3d hands: BTN open width %.2f | air c-bet freq vs seat2 %.2f | fold model %s "
                  "| arch %s" % (name, hands, open_width_btn(ag), cbet_freq(ag, 2),
                                 ["%.2f" % f for f in ag._prof(2).fold],
                                 B.ARCH[max(range(7), key=lambda k: ag._prof(2).A[k])]))
