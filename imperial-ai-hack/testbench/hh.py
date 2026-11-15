"""hh - shared, validated hand-history parser (testbench copy of the analysis parser) for the Imperial AI Hack pokerbots logs.

Usage (any python3 >= 3.9, standard library only):

    import sys; sys.path.insert(0, "<this folder>")
    import hh as H
    rounds = H.load_all()                       # every round file, sorted: practice first, then r001..r054
    v17 = H.select(rounds, versions={17})       # counted rounds played by site-version 17 (= repo v10/bot.py)
    for r in v17:
        for h in r.hands:
            me = r.seat
            h.results[me], h.pos[me], h.pf[me]["line"], ...

Facts about the logs (verified in validate()):
  * every hand starts every seat on 2000 chips, blinds 10/20, so there are never side pots;
  * events: ["post", seat, amt] (SB first, then BB), ["act", seat, action, amt], ["board", street, cards],
    ["refund", seat, amt], ["win", seat, amt, hand_name|None];
  * actions are only fold / check / call / raise.  For "raise" amt is the seat's TOTAL commitment on the
    street after the raise (raise-to; the first bet of a postflop street is logged as "raise").
    For "call" amt is the chips ADDED.  All-ins are ordinary raises/calls that leave the stack at 0;
  * results[seat] = net chips for the hand (sums to 0 per hand); hole{} has our cards plus any opponent
    cards shown at showdown; showdown{} maps seat -> hand name for seats that reached showdown.

Main objects:
  Round: ref, rnum, practice, version, table (letter), seat (hero), players, n, chips, timeouts, think_s,
         slot, hands (list of Hand)
  Hand : num, button, sb, bb, n, pos (list of position labels by seat), hole {seat: (c1, c2)},
         showdown {seat: name}, board [..], results [..], acts [Act..], invested [..], inv_st [[p,f,t,r]..],
         folded_st {seat: street_idx}, reach [street idx reached per seat, 4 = showdown], went_sd set,
         allin set, pfa (last preflop raiser or None), n_raises_pf, pf [per-seat preflop summary dict],
         n_flop (players who saw the flop), pot (final pot), last_dec_st (street of the last action),
         ev [per-seat all-in EV result or None], luck [per-seat result - ev or 0.0]
         (H.raw is None after loading; re-read the JSON file r.path if you need raw events)
  Act  : i, st (0..3), seat, a ('fold'|'check'|'call'|'raise'), amt (raw), add (chips added),
         to (street commitment after), pot (pot BEFORE the action, all streets), to_call (before action),
         hi (highest street commitment before), nr (raises on this street before; preflop excludes blinds),
         nl (preflop limpers before), active (players not folded before), stack (before), allin (bool),
         frac (to_call / pot, None if to_call == 0), rfrac (raise size: (to - hi) / (pot + to_call)),
         ctx (context label, see below), first (first voluntary action of this seat on this street)

Preflop contexts: 'unopened', 'limped', 'vs_open', 'vs_3bet', 'vs_4bet+'.
Postflop contexts: 'check_to' (nothing to call), 'vs_bet' (one bet), 'vs_raise' (a bet and >= 1 raise).
Preflop line tokens per seat (pf[seat]["line"]), one per action, joined by '-':
  unopened : F fold, L limp/complete, R open-raise
  limped   : F, L over-limp (or BB check = X), R iso-raise
  vs_open  : F, C call, 3 three-bet
  vs_3bet  : F, C, 4
  vs_4bet+ : F, C, 5
  'J' replaces the raise token when the raise is all-in.  BB that checks its option = 'X'.
"""
import glob
import json
import os
import pickle
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# real round logs downloaded with fetch_hands.py (override with the HH_HANDS_DIR environment variable)
HANDS_DIR = os.environ.get("HH_HANDS_DIR") or os.path.normpath(
    os.path.join(HERE, "..", "..", "imperial-ai-hack-pokerbots-kit", "hands"))
CACHE = os.path.join(HERE, "_cache", "rounds_cache.pkl")

STREETS = ["preflop", "flop", "turn", "river"]
ST_IDX = {s: i for i, s in enumerate(STREETS)}
TABLE_LETTERS = "ABCDEFGHIJ"
_POS_AFTER_BB = {
    0: [], 1: ["UTG"], 2: ["UTG", "CO"], 3: ["UTG", "HJ", "CO"], 4: ["UTG", "MP", "HJ", "CO"],
    5: ["UTG", "UTG+1", "MP", "HJ", "CO"], 6: ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO"],
}
POS_ORDER = ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"]
RANKS = "23456789TJQKA"
BB = 20

# site version -> what is known about the code (from the AI Poker Bots page + teammates' handoffs).
# Only v17 is verified byte-for-byte (SHA-256 226c2ab4bbfb == imperial-ai-hack/v10/bot.py).
SITE_VERSION_NOTES = {
    17: "repo imperial-ai-hack/v10/bot.py (verified by SHA-256 226c2ab4bbfb), uploaded Sat 16:28:42",
}


class Act:
    __slots__ = ("i", "st", "seat", "a", "amt", "add", "to", "pot", "to_call", "hi", "nr", "nl", "active",
                 "stack", "allin", "frac", "rfrac", "ctx", "first")

    def __repr__(self):
        return "Act(%s s%d %s %d ctx=%s pot=%d tc=%d)" % (STREETS[self.st], self.seat, self.a, self.amt,
                                                          self.ctx, self.pot, self.to_call)


class Hand:
    __slots__ = ("num", "button", "sb", "bb", "n", "pos", "hole", "showdown", "board", "results", "acts",
                 "invested", "inv_st", "folded_st", "reach", "went_sd", "allin", "pfa", "n_raises_pf", "pf",
                 "n_flop", "pot", "last_dec_st", "ev", "luck", "wins", "refunds", "raw")


class Round:
    __slots__ = ("ref", "rnum", "practice", "version", "table", "seat", "players", "n", "chips", "timeouts",
                 "think_s", "slot", "hands", "path")

    @property
    def team(self):
        return self.players[self.seat]

    @property
    def label(self):
        return ("P%d" % self.rnum) if self.practice else ("R%d" % self.rnum)

    def __repr__(self):
        return "Round(%s v%s table %s seat %d %+d)" % (self.label, self.version, self.table, self.seat, self.chips)


# ----------------------------------------------------------------------------------------------- helpers
def positions(n, button, sb_seat, bb_seat):
    out = [None] * n
    if n == 2:
        out[sb_seat] = "BTN"
        out[bb_seat] = "BB"
        return out
    out[button] = "BTN"
    out[sb_seat] = "SB"
    out[bb_seat] = "BB"
    rest = [(bb_seat + k) % n for k in range(1, n)]
    rest = [s for s in rest if out[s] is None]
    labels = _POS_AFTER_BB.get(len(rest), ["P%d" % i for i in range(len(rest))])
    for s, lab in zip(rest, labels):
        out[s] = lab
    return out


def hand_class(cards):
    """('As','Kd') -> 'AKo'; pairs 'QQ'; suited 'T9s'."""
    if not cards or len(cards) != 2:
        return None
    a, b = cards
    ra, rb = RANKS.index(a[0]), RANKS.index(b[0])
    if ra < rb:
        a, b, ra, rb = b, a, rb, ra
    if ra == rb:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


_PF_TOK = {
    "unopened": {"fold": "F", "call": "L", "raise": "R", "check": "X"},
    "limped": {"fold": "F", "call": "L", "raise": "R", "check": "X"},
    "vs_open": {"fold": "F", "call": "C", "raise": "3", "check": "X"},
    "vs_3bet": {"fold": "F", "call": "C", "raise": "4", "check": "X"},
    "vs_4bet+": {"fold": "F", "call": "C", "raise": "5", "check": "X"},
}


def _pf_ctx(nr, nl):
    if nr == 0:
        return "limped" if nl > 0 else "unopened"
    if nr == 1:
        return "vs_open"
    if nr == 2:
        return "vs_3bet"
    return "vs_4bet+"


# ----------------------------------------------------------------------------------------------- equity
_eq_mod = None


def _equities(hands, board):
    global _eq_mod
    if _eq_mod is None:
        sys.path.insert(0, HERE)
        import evalx as _A  # stand-alone stdlib evaluator (exact when <= 2 cards to come)
        _eq_mod = _A
    A = _eq_mod
    return A.equities([[A.card(c) for c in h] for h in hands], [A.card(c) for c in board], samples=1500)


# ----------------------------------------------------------------------------------------------- parsing
def parse_hand(h, n):
    H = Hand()
    H.raw = h
    H.num = h["n"]
    H.button = h["button"]
    ev = h["events"]
    posts = [e for e in ev if e[0] == "post"]
    H.sb = posts[0][1]
    H.bb = posts[1][1]
    H.n = n
    H.pos = positions(n, H.button, H.sb, H.bb)
    H.hole = {int(k): tuple(v) for k, v in (h.get("hole") or {}).items()}
    H.showdown = {int(k): v for k, v in (h.get("showdown") or {}).items()}
    H.board = list(h.get("board") or [])
    H.results = list(h["results"])
    H.went_sd = set(H.showdown)
    start = list(h.get("start_stacks") or [2000] * n)

    st = 0
    commit = [0] * n          # street commitment
    total = [0] * n           # hand commitment
    inv_st = [[0, 0, 0, 0] for _ in range(n)]
    folded = {}
    allin = set()
    nr = 0
    nl = 0
    acted_on_street = set()
    acts = []
    wins = defaultdict(int)
    refunds = defaultdict(int)
    pfa = None
    n_raises_pf = 0
    flop_players = None
    last_act_st = 0
    for i, e in enumerate(ev):
        t = e[0]
        if t == "post":
            s, amt = e[1], e[2]
            commit[s] += amt
            total[s] += amt
            inv_st[s][0] += amt
            continue
        if t == "board":
            st = ST_IDX[e[1]]
            if st == 1 and flop_players is None:
                flop_players = [s for s in range(n) if s not in folded]
            commit = [0] * n
            nr = 0
            nl = 0
            acted_on_street = set()
            continue
        if t == "refund":
            refunds[e[1]] += e[2]
            continue
        if t == "win":
            wins[e[1]] += e[2]
            continue
        if t != "act":
            continue
        s, a, amt = e[1], e[2], e[3]
        A = Act()
        A.i = i
        A.st = st
        A.seat = s
        A.a = a
        A.amt = amt
        hi = max(commit)
        A.hi = hi
        A.pot = sum(total)
        A.stack = start[s] - total[s]
        A.to_call = min(hi - commit[s], A.stack)
        A.nr = nr
        A.nl = nl
        A.active = sum(1 for x in range(n) if x not in folded)
        A.first = s not in acted_on_street
        if a == "raise":
            add = amt - commit[s]
        elif a == "call":
            add = amt
        else:
            add = 0
        A.add = add
        A.to = commit[s] + add
        A.frac = (A.to_call / A.pot) if A.to_call > 0 and A.pot > 0 else None
        A.rfrac = ((A.to - hi) / (A.pot + A.to_call)) if a == "raise" and (A.pot + A.to_call) > 0 else None
        if st == 0:
            A.ctx = _pf_ctx(nr, nl)
        else:
            A.ctx = "check_to" if A.to_call == 0 else ("vs_bet" if nr <= 1 else "vs_raise")
        commit[s] += add
        total[s] += add
        inv_st[s][st] += add
        A.allin = (start[s] - total[s]) <= 0 and a in ("raise", "call")
        if A.allin:
            allin.add(s)
        if a == "fold":
            folded[s] = st
        elif a == "raise":
            nr += 1
            if st == 0:
                pfa = s
                n_raises_pf += 1
        elif a == "call" and st == 0 and nr == 0:
            nl += 1
        acted_on_street.add(s)
        acts.append(A)
        last_act_st = st
    H.acts = acts
    H.invested = total
    H.inv_st = inv_st
    H.folded_st = folded
    H.allin = allin
    H.pfa = pfa
    H.n_raises_pf = n_raises_pf
    H.n_flop = len(flop_players) if flop_players else 0
    H.pot = sum(total) - sum(refunds.values())
    H.last_dec_st = last_act_st
    H.wins = dict(wins)
    H.refunds = dict(refunds)
    # street reached per seat (4 = showdown)
    max_board = 0
    for e in ev:
        if e[0] == "board":
            max_board = max(max_board, ST_IDX[e[1]])
    reach = []
    for s in range(n):
        if s in H.went_sd:
            reach.append(4)
        elif s in folded:
            reach.append(folded[s])
        else:
            reach.append(max_board)
    H.reach = reach
    # preflop summaries
    pf = []
    for s in range(n):
        toks = []
        ctx0 = None
        a0 = None
        for A in acts:
            if A.st != 0 or A.seat != s:
                continue
            tok = _PF_TOK[A.ctx][A.a]
            if A.a == "raise" and A.allin:
                tok = "J"
            if A.a == "check":
                tok = "X"
            toks.append(tok)
            if ctx0 is None:
                ctx0, a0 = A.ctx, A.a
        vp = any(A.st == 0 and A.seat == s and A.a in ("call", "raise") for A in acts)
        pr = any(A.st == 0 and A.seat == s and A.a == "raise" for A in acts)
        pf.append({"ctx0": ctx0, "a0": a0, "line": "-".join(toks) if toks else "",
                   "vpip": vp, "pfr": pr, "walk": (not toks and s == H.bb)})
    H.pf = pf
    # all-in luck (pokerdash method): showdown with every showdown hand known and board cards still to come
    H.ev = [None] * n
    H.luck = [0.0] * n
    return H


def compute_luck(H):
    """Fill H.ev / H.luck for hands that were all-in before the river with all showdown cards known."""
    sd = sorted(H.went_sd)
    if len(sd) < 2 or not all(s in H.hole for s in sd):
        return False
    ev = H.raw["events"]
    last_act_i = max((A.i for A in H.acts), default=-1)
    boards = [(i, e[1], e[2]) for i, e in enumerate(ev) if e[0] == "board"]
    later = [b for b in boards if b[0] > last_act_i]
    if not later:
        return False
    prior = [b for b in boards if b[0] < last_act_i]
    board_at = prior[-1][2] if prior else []
    eqs = _equities([list(H.hole[s]) for s in sd], board_at)
    pot = sum(H.wins.values())
    for s, q in zip(sd, eqs):
        contrib = H.wins.get(s, 0) - H.results[s]
        H.ev[s] = q * pot - contrib
        H.luck[s] = H.results[s] - H.ev[s]
    return True


def load_round(path, with_luck=True):
    d = json.load(open(path))
    r = Round()
    r.path = path
    r.ref = d["ref"]
    meta = d.get("round") or {}
    r.practice = "practice" in r.ref
    import re
    m = re.search(r"r0*(\d+)$", r.ref)
    r.rnum = int(m.group(1)) if m else -1
    r.version = meta.get("version")
    ti = meta.get("table")
    r.table = TABLE_LETTERS[ti] if isinstance(ti, int) and 0 <= ti < len(TABLE_LETTERS) else str(ti)
    r.seat = int(d["seat"])
    r.players = list(d["players"])
    r.n = len(r.players)
    r.chips = meta.get("chips")
    r.timeouts = meta.get("timeouts")
    r.think_s = meta.get("think_s")
    r.slot = meta.get("slot")
    r.hands = [parse_hand(h, r.n) for h in d["hands"]]
    if with_luck:
        for H in r.hands:
            compute_luck(H)
    for H in r.hands:
        H.raw = None   # drop the raw dict to keep memory low (events are fully represented by H.acts)
    return r


def load_all(use_cache=True, with_luck=True):
    files = sorted(glob.glob(os.path.join(HANDS_DIR, "*.json")))
    sig = [(os.path.basename(f), os.path.getsize(f)) for f in files]
    if use_cache and os.path.exists(CACHE):
        try:
            with open(CACHE, "rb") as fh:
                obj = pickle.load(fh)
            if obj.get("sig") == sig and obj.get("luck") == with_luck:
                return obj["rounds"]
        except Exception:
            pass
    rounds = [load_round(f, with_luck=with_luck) for f in files]
    rounds.sort(key=lambda r: (0 if r.practice else 1, r.rnum))
    if use_cache:
        try:
            with open(CACHE, "wb") as fh:
                pickle.dump({"sig": sig, "luck": with_luck, "rounds": rounds}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass
    return rounds


def select(rounds, versions=None, practice=False, rnums=None):
    out = []
    for r in rounds:
        if r.practice and not practice:
            continue
        if versions is not None and r.version not in versions:
            continue
        if rnums is not None and r.rnum not in rnums:
            continue
        out.append(r)
    return out


# ----------------------------------------------------------------------------------------------- analysis helpers
def bb100(chips, hands):
    return (chips / BB / hands * 100.0) if hands else 0.0


def seat_acts(H, seat, st=None):
    return [A for A in H.acts if A.seat == seat and (st is None or A.st == st)]


def cbet_info(H):
    """(pfa, flop_first_action_of_pfa, was_checked_to) for hands that saw a flop with a preflop aggressor."""
    if H.pfa is None or H.n_flop < 2 or H.pfa in H.folded_st and H.folded_st[H.pfa] == 0:
        return None
    fl = [A for A in H.acts if A.st == 1]
    for A in fl:
        if A.seat == H.pfa:
            return (H.pfa, A, all(B.a == "check" for B in fl if B.i < A.i))
    return None


def hero_summary_line(H, seat):
    parts = []
    for st in range(4):
        toks = []
        for A in H.acts:
            if A.seat != seat or A.st != st:
                continue
            c = {"fold": "F", "check": "X", "call": "C", "raise": "R"}[A.a]
            if A.allin and A.a in ("raise", "call"):
                c += "*"
            toks.append(c)
        if toks:
            parts.append("%s:%s" % (STREETS[st][0], "".join(toks)))
    return " ".join(parts)


def fmt_hand(r, H, show_all_holes=True):
    """Readable one-hand dump (seat names, positions, actions with pot sizes, results)."""
    out = []
    out.append("%s hand %d  (table %s, %d players, button seat %d)" % (r.label, H.num, r.table, r.n, H.button))
    for s in range(r.n):
        tag = " <== US" if s == r.seat else ""
        hc = " ".join(H.hole.get(s, ())) if (s in H.hole and (show_all_holes or s == r.seat)) else ""
        out.append("  seat %d %-5s %-26s %s%s" % (s, H.pos[s], r.players[s][:26], hc, tag))
    cur = -1
    for A in H.acts:
        if A.st != cur:
            cur = A.st
            if cur > 0:
                bcards = H.board[:3 + (cur - 1)]
                out.append("  -- %s %s" % (STREETS[cur], " ".join(bcards)))
            else:
                out.append("  -- preflop")
        extra = ""
        if A.a == "raise":
            extra = " to %d" % A.to
        elif A.a == "call":
            extra = " %d" % A.add
        out.append("     %-5s %-22s %-5s%s%s   (pot %d, to call %d)" % (
            H.pos[A.seat], r.players[A.seat][:22], A.a, extra, " ALL-IN" if A.allin else "", A.pot, A.to_call))
    if H.showdown:
        out.append("  -- showdown: " + ", ".join("%s %s (%s)" % (r.players[s][:14], " ".join(H.hole.get(s, ())), nm)
                                                for s, nm in H.showdown.items()))
    out.append("  results: " + ", ".join("%s %+d" % (r.players[s][:14], H.results[s]) for s in range(r.n) if H.results[s]))
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------- validation
def validate(rounds):
    problems = []
    for r in rounds:
        tot = 0
        for H in r.hands:
            if sum(H.results) != 0:
                problems.append("%s h%d results sum %d" % (r.label, H.num, sum(H.results)))
            tot += H.results[r.seat]
            # result consistency: won - invested + refunds == result
            for s in range(r.n):
                exp = H.wins.get(s, 0) + H.refunds.get(s, 0) - H.invested[s]
                if exp != H.results[s]:
                    problems.append("%s h%d seat %d result %d != wins+refund-inv %d" % (
                        r.label, H.num, s, H.results[s], exp))
                    break
            if max(H.invested) > 2000:
                problems.append("%s h%d invested > 2000" % (r.label, H.num))
        if r.chips is not None and tot != r.chips:
            problems.append("%s hero total %d != site chips %d" % (r.label, tot, r.chips))
    return problems


if __name__ == "__main__":
    import time
    t0 = time.time()
    rs = load_all(use_cache=False)
    print("loaded %d rounds in %.1fs" % (len(rs), time.time() - t0))
    probs = validate(rs)
    print("validation problems:", len(probs))
    for p in probs[:20]:
        print("  ", p)
