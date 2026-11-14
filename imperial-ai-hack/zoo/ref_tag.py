"""Strong reference 1, a solid adaptive TAG: position opening ranges (10% early to 44% on the button), value-heavy 3-bets, calls shoves by the shover's measured frequency, steals more from tight blinds; after the flop it sizes by board texture and by how sticky the opponents are, and reads hands by action (folds one pair to raises and triple barrels from passive players, calls down wild ones)."""
ARCHETYPE = "strong reference: solid TAG with action-based hand reading"
TIER = "strong"
LEAK = "No easy money: it needs ~30 hands to adapt, its small c-bet on dry boards is often air (raise it occasionally), it over-folds one pair to turn/river raises from players it has tagged as passive, and it rarely bluffs rivers - fold bluff-catchers to its river bets. Stay near baseline against it."

# ---- shared zoo kernel (pasted in by tools/build_zoo.py; edit tools/zoo_src) ----
import random

_RANKS = "23456789TJQKA"
_CI = {r + s: i * 4 + j for i, r in enumerate(_RANKS) for j, s in enumerate("cdhs")}

# Preflop tables, index = hi*13+lo (suited), lo*13+hi (offsuit), r*13+r (pair), ranks 0..12 = 2..A.
# _PCT: where the hand sits in a playability-adjusted ranking, in 1/1000 of all combos
#       (0 = aces, 1000 = seven-deuce offsuit). _EVR: all-in equity vs one random hand, x1000.
_PCT = (
    198, 986, 977, 959, 968, 995, 950, 923, 851, 814, 742, 609, 356,
    649, 161, 905, 878, 914, 932, 941, 896, 842, 769, 697, 552, 332,
    637, 546, 117, 805, 833, 860, 869, 887, 824, 751, 655, 531, 296,
    633, 510, 416, 91, 733, 760, 796, 778, 787, 724, 643, 483, 265,
    670, 591, 468, 377, 72, 664, 676, 706, 715, 688, 585, 443, 253,
    682, 630, 498, 410, 326, 61, 576, 621, 600, 567, 540, 404, 211,
    615, 627, 525, 419, 347, 275, 48, 504, 519, 492, 459, 383, 186,
    594, 561, 558, 474, 362, 302, 241, 31, 434, 425, 395, 311, 142,
    513, 477, 471, 449, 368, 317, 247, 195, 20, 341, 284, 220, 101,
    465, 452, 413, 374, 365, 320, 244, 202, 151, 16, 235, 170, 78,
    389, 371, 350, 323, 305, 271, 226, 179, 136, 110, 11, 130, 54,
    290, 278, 259, 229, 205, 192, 176, 154, 107, 87, 68, 7, 38,
    164, 157, 148, 121, 124, 113, 95, 84, 65, 44, 27, 24, 2,
)
_EVR = (
    514, 322, 331, 344, 342, 346, 371, 391, 416, 442, 470, 503, 545,
    361, 545, 351, 362, 364, 367, 375, 401, 426, 454, 480, 513, 553,
    369, 387, 577, 381, 379, 386, 394, 407, 434, 463, 491, 521, 565,
    380, 396, 415, 610, 400, 405, 414, 426, 442, 471, 497, 531, 573,
    378, 391, 413, 432, 640, 424, 433, 446, 462, 478, 506, 540, 575,
    384, 399, 419, 438, 455, 668, 451, 463, 480, 499, 519, 551, 585,
    406, 410, 428, 446, 464, 479, 698, 482, 497, 515, 536, 558, 595,
    425, 432, 437, 455, 475, 492, 508, 727, 515, 534, 554, 578, 605,
    450, 460, 466, 473, 489, 506, 525, 540, 754, 553, 575, 597, 627,
    472, 482, 490, 500, 506, 520, 539, 556, 576, 779, 584, 608, 636,
    498, 509, 517, 527, 533, 542, 562, 579, 594, 604, 802, 615, 646,
    533, 536, 546, 557, 562, 573, 582, 599, 618, 629, 634, 827, 657,
    570, 579, 587, 596, 596, 605, 619, 629, 644, 655, 663, 672, 857,
)

FOLD = {"action": "fold"}
CHECK = {"action": "check"}
CALL = {"action": "call"}
JAM = 10 ** 9


def pf_index(c1, c2):
    a = c1 >> 2
    b = c2 >> 2
    if a < b:
        a, b = b, a
    return a * 13 + b if (c1 & 3) == (c2 & 3) or a == b else b * 13 + a


def raise_to(st, amount):
    """Raise to `amount` clamped to the legal range; call/check when raising is not legal."""
    if "raise" not in st["legal_actions"]:
        return CALL if st["to_call"] > 0 else CHECK
    lo = st["min_raise_to"]
    hi = st["max_raise_to"]
    amount = int(amount)
    if amount < lo:
        amount = lo
    if amount > hi:
        amount = hi
    return {"action": "raise", "amount": amount}


def bet_frac(st, frac):
    """Bet, or raise by, `frac` of the pot as it stands after calling."""
    tc = st["to_call"]
    return raise_to(st, max(st["bets"]) + frac * (st["pot"] + tc))


def check_fold(st):
    return CHECK if st["to_call"] == 0 else FOLD


def check_call(st):
    return CHECK if st["to_call"] == 0 else CALL


def limpers(st):
    """Players who called the big blind in a so-far-unraised pot."""
    k = 0
    for h in st["history"]:
        if h["action"] == "call":
            k += 1
    return k


def last_raiser(st, street):
    seat = -1
    for h in st["history"]:
        if h["action"] == "raise" and h["street"] == street:
            seat = h["seat"]
    return seat


_SHC = {}


def _sh(mask):
    """Top rank of a straight in a 13-bit rank mask, or -1 (the ace also plays low)."""
    v = _SHC.get(mask)
    if v is None:
        m = (mask << 1) | (mask >> 12 & 1)
        v = -1
        for top in range(13, 3, -1):
            if (m >> (top - 4)) & 31 == 31:
                v = top - 1
                break
        _SHC[mask] = v
    return v


_SOC = {}


def _souts(mask):
    """How many missing ranks would complete a straight."""
    v = _SOC.get(mask)
    if v is None:
        v = 0
        for r in range(13):
            if not mask >> r & 1 and _sh(mask | 1 << r) >= 0:
                v += 1
        _SOC[mask] = v
    return v


def ev(cards):
    """Best five-card hand from 3 to 7 card ints, as a tuple that compares like the engine's."""
    cnt = [0] * 13
    sm = [0, 0, 0, 0]
    sn = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        r = c >> 2
        s = c & 3
        cnt[r] += 1
        sm[s] |= 1 << r
        sn[s] += 1
        mask |= 1 << r
    for s in (0, 1, 2, 3):
        if sn[s] >= 5:
            fm = sm[s]
            h = _sh(fm)
            if h >= 0:
                return (8, h)
            return (5,) + tuple([r for r in range(12, -1, -1) if fm >> r & 1][:5])
    q = t = -1
    p = []
    s1 = []
    for r in range(12, -1, -1):
        k = cnt[r]
        if k == 1:
            s1.append(r)
        elif k == 2:
            p.append(r)
        elif k == 3:
            if t < 0:
                t = r
            else:
                p.append(r)
        elif k == 4:
            q = r
    if q >= 0:
        k = -1
        for r in range(12, -1, -1):
            if cnt[r] and r != q:
                k = r
                break
        return (7, q, k)
    if t >= 0 and p:
        return (6, t, p[0])
    h = _sh(mask)
    if h >= 0:
        return (4, h)
    if t >= 0:
        return (3, t) + tuple(s1[:2])
    if len(p) >= 2:
        k = s1[0] if s1 else -1
        if len(p) > 2 and p[2] > k:
            k = p[2]
        return (2, p[0], p[1], k)
    if p:
        return (1, p[0]) + tuple(s1[:3])
    return (0,) + tuple(s1[:5])


def classify(c1, c2, board):
    """(tier, outs) for hole cards c1, c2 on a 3-5 card board (all card ints).

    tier: 0 nothing, 1 weak pair (under/middle/bottom pair, or only playing the board),
    2 decent pair (top pair weak kicker, pocket pair between top and second card),
    3 strong pair (top pair J+ kicker, overpair), 4 two pair, 5 trips/set, 6 straight,
    7 flush, 8 full house or better. outs: rough draw outs (9 flush draw, 8 open-ended,
    4 gutshot), 0 on the river or when already holding a straight or better.
    """
    mine = ev([c1, c2] + board)
    brd = ev(board)
    cat = mine[0]
    bcat = brd[0]
    r1 = c1 >> 2
    r2 = c2 >> 2
    if cat >= 4:
        if cat == bcat and mine <= brd:
            tier = 1
        else:
            tier = 6 if cat == 4 else 7 if cat == 5 else 8
    elif cat == 3:
        tier = 5 if bcat < 3 else (1 if r1 == 12 or r2 == 12 else 0)
    elif cat == 2 and bcat == 0:
        tier = 4
    elif cat == 2 and bcat == 2:
        tier = 2 if mine[1:3] != brd[1:3] else 0
    elif (cat == 2 and bcat == 1) or (cat == 1 and bcat == 0):
        br = sorted({c >> 2 for c in board}, reverse=True)
        top = br[0]
        second = br[1] if len(br) > 1 else -1
        if r1 == r2:
            tier = 3 if r1 > top else 2 if r1 > second else 1
        else:
            if r1 in br:
                pr, kick = r1, r2
            else:
                pr, kick = r2, r1
            if pr == top:
                tier = 3 if kick >= 9 else 2
            else:
                tier = 1
    else:
        tier = 0
    outs = 0
    if len(board) < 5 and tier < 6:
        s1 = c1 & 3
        s2 = c2 & 3
        n1 = 1
        n2 = 1
        bm = 0
        for c in board:
            s = c & 3
            if s == s1:
                n1 += 1
            if s == s2:
                n2 += 1
            bm |= 1 << (c >> 2)
        if s1 == s2:
            n1 += 1
            n2 = 0
        if n1 == 4 or n2 == 4:
            outs = 9
        a = _souts(bm | 1 << r1 | 1 << r2)
        if a > _souts(bm):
            outs += 8 if a >= 2 else 4
    return tier, outs


def wetness(board):
    """0 (dry, e.g. K72 rainbow) .. 1 (wet, e.g. 9h8h7c) from suits and connectedness."""
    sn = [0, 0, 0, 0]
    for c in board:
        sn[c & 3] += 1
    mx = max(sn)
    w = 0.0
    if mx >= 3:
        w += 0.5
    elif mx == 2 and len(board) <= 4:
        w += 0.25
    rs = sorted({c >> 2 for c in board})
    for i in range(len(rs) - 1):
        if rs[i + 1] - rs[i] <= 2:
            w += 0.17
    return w if w < 1.0 else 1.0


class Base:
    """Shared plumbing: per-hand deterministic RNG, hole-card parsing, street dispatch.

    The RNG is re-seeded at the first decision of every hand from (seat, hand number, own
    hole cards), so a bot's dice in a hand do not depend on what anybody did in earlier
    hands. Two runs on the same deck seed therefore see the same opponent randomness, which
    is what makes paired comparisons of candidates tight.
    """
    SALT = 0

    def __init__(self):
        self.rng = random.Random(self.SALT)
        self.seat = 0
        self.n = 8
        self._hn = -1
        self.c1 = self.c2 = 0
        self.pct = 1.0

    def on_table_start(self, info):
        self.seat = info.get("seat", 0)
        self.n = info.get("num_players", 8)

    def act(self, st):
        hn = st["hand_number"]
        if hn != self._hn:
            self._hn = hn
            h = st["hole_cards"]
            c1 = _CI[h[0]]
            c2 = _CI[h[1]]
            self.c1 = c1
            self.c2 = c2
            self.pct = _PCT[pf_index(c1, c2)] / 1000.0
            self.rng.seed(((c1 * 52 + c2) * 1009 + hn) * 37 + st["seat"] * 7 + self.SALT)
            self.new_hand(st)
        if st["street"] == "preflop":
            return self.pre(st)
        return self.post(st)

    def new_hand(self, st):
        pass

    def pre(self, st):
        return check_fold(st)

    def post(self, st):
        return check_fold(st)

    def spot(self, st):
        """Preflop seat facts: (pos, behind) with pos 0 = button, 1 = SB, 2 = BB, 3 = UTG...
        and behind = players still to act after us preflop when nobody has raised."""
        n = len(st["bets"])
        pos = (st["seat"] - st["button"]) % n
        return pos, (2 - pos) % n

    def tier(self, st):
        return classify(self.c1, self.c2, [_CI[c] for c in st["board"]])

class Tracker:
    """Per-seat frequencies learned from the full histories handed to on_hand_end."""

    def __init__(self, n):
        self.hands = 0
        self.vpip = [0] * n
        self.pfr = [0] * n
        self.jam = [0] * n
        self.agg = [0] * n       # postflop bets and raises
        self.pas = [0] * n       # postflop checks and calls
        self.faced = [0] * n     # postflop decisions facing a bet
        self.gave = [0] * n      # ... that were folds

    def update(self, summary):
        self.hands += 1
        vp = set()
        pr = set()
        jm = set()
        street = "preflop"
        facing = False
        agg = self.agg
        pas = self.pas
        for h in summary["history"]:
            a = h["action"]
            s = h["seat"]
            st = h["street"]
            if st == "preflop":
                if a == "raise":
                    vp.add(s)
                    pr.add(s)
                    if h["amount"] >= 1500:
                        jm.add(s)
                elif a == "call":
                    vp.add(s)
                continue
            if st != street:
                street = st
                facing = False
            if a == "raise":
                agg[s] += 1
                if facing:
                    self.faced[s] += 1
                facing = True
            elif a == "call":
                pas[s] += 1
                self.faced[s] += 1
            elif a == "check":
                pas[s] += 1
            elif a == "fold" and facing:
                self.faced[s] += 1
                self.gave[s] += 1
        for s in vp:
            self.vpip[s] += 1
        for s in pr:
            self.pfr[s] += 1
        for s in jm:
            self.jam[s] += 1

    # Estimates shrunk towards a population prior (prior weight in hands/decisions).
    def vpip_f(self, s):
        return (self.vpip[s] + 3.6) / (self.hands + 12.0)

    def pfr_f(self, s):
        return (self.pfr[s] + 1.8) / (self.hands + 12.0)

    def jam_f(self, s):
        return (self.jam[s] + 0.6) / (self.hands + 20.0)

    def agg_f(self, s):
        return (self.agg[s] + 3.0) / (self.agg[s] + self.pas[s] + 10.0)

    def fold_f(self, s):
        return (self.gave[s] + 3.6) / (self.faced[s] + 8.0)


# ---- the bot ----
class Agent(Base):
    SALT = 1717
    OPEN = {7: 0.10, 6: 0.12, 5: 0.15, 4: 0.19, 3: 0.27, 2: 0.44, 1: 0.36}

    def __init__(self):
        Base.__init__(self)
        self.tr = Tracker(10)

    def on_hand_end(self, summary):
        self.tr.update(summary)

    # ------------------------------------------------------------ preflop
    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        tc = st["to_call"]
        bets = st["bets"]
        cur = max(bets)
        r = st["raises_this_street"]
        pos, behind = self.spot(st)
        tr = self.tr
        me = st["seat"]
        n = len(bets)
        premium = p <= 0.012 or (self.c1 >> 2) + (self.c2 >> 2) == 23      # QQ+ or AK
        if r == 0:
            limp = limpers(st)
            if pos == 2:
                return raise_to(st, (4 + limp) * bb) if p <= 0.10 else CHECK
            f = self.OPEN.get(behind, 0.10)
            left = [(me + k) % n for k in range(1, behind + 1)]
            if limp:
                f *= 0.85 if limp == 1 else 0.7
            elif behind <= 2 and max(tr.vpip_f(s) for s in left) < 0.20:
                f *= 1.4                                   # only tight players left: steal wider
            jb = max(tr.jam_f(s) for s in left)
            if jb > 0.20:                                  # a shove-bot behind: no raise-folding
                f = min(f, 0.5 * jb + 0.05)
            if p <= f:
                return raise_to(st, (2.5 + limp) * bb)
            return FOLD
        v = last_raiser(st, "preflop")
        if st["stacks"][v] == 0 or cur >= 1500:
            pj = tr.jam_f(v)
            lim = max(0.027, 0.45 * pj)
            if r >= 2 and pj < 0.08:
                lim = 0.012                                # a normal player's 4-bet jam: QQ+/AK only
            for i in range(n):
                if i != v and i != me and not st["folded"][i] and bets[i] >= cur:
                    lim *= 0.6                             # somebody already called the shove
            return CALL if (p <= lim or premium) else FOLD
        pv = tr.pfr_f(v)
        ip = (pos - 1) % n > ((v - st["button"]) - 1) % n
        if r == 1:
            callers = 0
            for i in range(n):
                if i != v and bets[i] >= cur:
                    callers += 1
            if premium or p <= max(0.028, 0.20 * pv):
                return raise_to(st, cur * (3.0 if ip else 3.6) + callers * cur)
            if ip and pv > 0.22 and 0.10 < p <= 0.17 and self.rng.random() < 0.25:
                return raise_to(st, cur * 3.0)
            if pos == 2:
                cf = 0.26 if cur <= 3 * bb else 0.16
            elif pos == 1:
                cf = 0.08
            else:
                cf = 0.13 if ip else 0.09
            x = (pv / 0.15) ** 0.5
            cf *= 0.75 if x < 0.75 else 1.8 if x > 1.8 else x
            if cur > 3.5 * bb:
                cf *= 3.5 * bb / cur
            return CALL if p <= cf else FOLD
        loose = pv > 0.30
        if premium or (loose and p <= 0.05):
            if cur >= 25 * bb or r >= 3:
                return raise_to(st, JAM)
            return raise_to(st, 2.3 * cur)
        if bets[me] > bb and tc <= 18 * bb and p <= (0.12 if loose else 0.055):
            return CALL
        return FOLD

    # ----------------------------------------------------------- postflop
    def post(self, st):
        me = st["seat"]
        board = [_CI[c] for c in st["board"]]
        tier, outs = classify(self.c1, self.c2, board)
        tc = st["to_call"]
        pot = st["pot"]
        street = st["street"]
        folded = st["folded"]
        n = len(folded)
        opps = [i for i in range(n) if not folded[i] and i != me]
        no = len(opps)
        pfa = agg_seat = -1
        prev_opp_aggr = my_prev_aggr = 0
        for h in st["history"]:
            if h["action"] == "raise":
                hs = h["street"]
                if hs == "preflop":
                    pfa = h["seat"]
                elif hs == street:
                    agg_seat = h["seat"]
                elif h["seat"] == me:
                    my_prev_aggr += 1
                else:
                    prev_opp_aggr += 1
        rs = st["raises_this_street"]
        wet = wetness(board)
        tr = self.tr
        rnd = self.rng.random
        btn = st["button"]
        myo = (me - btn - 1) % n
        ip = True
        for i in opps:
            if (i - btn - 1) % n > myo:
                ip = False
        river = street == "river"
        flop = street == "flop"

        if tc == 0:
            ff = min(tr.fold_f(i) for i in opps)           # the stickiest opponent decides
            if tier >= 4:
                if ff < 0.30:
                    return bet_frac(st, 1.0)
                return bet_frac(st, 0.75 if wet > 0.4 or ff < 0.38 else 0.6)
            if tier == 3:
                if river:
                    if no == 1 and (prev_opp_aggr == 0 or ff < 0.30):
                        return bet_frac(st, 0.75 if ff < 0.30 else 0.5)
                    return CHECK
                if no <= 2 or flop:
                    return bet_frac(st, 0.7 if wet > 0.4 or ff < 0.30 else 0.55)
                return CHECK
            if tier == 2:
                if flop and no <= 2:
                    return bet_frac(st, 0.5)
                if no == 1 and prev_opp_aggr == 0 and (ff < 0.35 or (ip and not river)):
                    return bet_frac(st, 0.45)
                return CHECK
            if outs >= 8 and not river and no <= 2 and ff > 0.30:
                return bet_frac(st, 0.6)
            if ff > 0.33:
                if flop and pfa == me:
                    pr = (0.7 if wet < 0.3 else 0.45) if no == 1 else 0.3 if no == 2 else 0.0
                    if rnd() < pr:
                        return bet_frac(st, 0.4 if wet < 0.3 else 0.55)
                elif flop and ip and no == 1 and ff > 0.5 and rnd() < 0.4:
                    return bet_frac(st, 0.5)
                elif street == "turn" and no == 1 and my_prev_aggr and ff > 0.5 and rnd() < 0.35:
                    return bet_frac(st, 0.66)
                elif river and no == 1 and my_prev_aggr >= 2 and tier == 0 and ff > 0.55 and rnd() < 0.3:
                    return bet_frac(st, 0.7)
            return CHECK

        v = agg_seat if agg_seat >= 0 and agg_seat != me else opps[0]
        f = tc / max(1, pot - tc)
        po = tc / (pot + tc)
        va = tr.agg_f(v)
        wild = va > 0.48
        passive = va < 0.22
        stack = st["stacks"][me]
        allin = tc >= stack
        multi = no >= 2
        can_raise = "raise" in st["legal_actions"]
        if tier >= 5:
            if can_raise and (tier >= 6 or rs <= 2 or wild):
                if stack <= 2.5 * pot or rs >= 2:
                    return raise_to(st, JAM)
                return bet_frac(st, 0.85)
            return CALL
        if tier == 4:
            if rs >= 3 and not wild:
                return FOLD if passive and f > 0.4 else CALL
            if rs == 2 and river and passive and f > 0.5:
                return FOLD
            if rs == 1 and not river and can_raise and (wet > 0.3 or wild):
                return bet_frac(st, 0.8)
            return CALL
        if tier == 3:
            if rs >= 2:
                return CALL if wild and f <= 1.2 else FOLD
            if multi and not flop and f > 0.6 and not wild:
                return FOLD
            if river and not wild and (f > 0.9 or (passive and f > 0.5) or (prev_opp_aggr >= 2 and f > 0.6)):
                return FOLD
            return CALL
        if tier == 2:
            lim = 0.8 if flop else 0.6 if street == "turn" else 0.45
            if wild:
                lim = 1.3
            elif passive:
                lim *= 0.6
            if multi:
                lim *= 0.7
            if (rs == 1 or wild) and f <= lim:
                return CALL
        elif tier == 1:
            if rs == 1 and ((flop and f <= 0.5 and not multi and not passive) or (wild and f <= 0.8)):
                return CALL
        if outs and not river:
            eq = outs * (0.040 if flop and allin else 0.022)
            if not allin:
                eq *= 1.3                                  # implied odds
            if eq >= po:
                if outs >= 12 and rs == 1 and can_raise and not multi and rnd() < 0.3:
                    return bet_frac(st, 0.8)
                return CALL
        return FOLD
