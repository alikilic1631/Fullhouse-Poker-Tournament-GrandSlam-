"""Pokerbot B: EV maximiser with frequency-derived ranges (Hyperion-style four layers).

Layer 1  decision engine  : explicit chip EV per candidate action (fold/check/call, bets at
                            1/3, 2/3, pot, overbet, all-in), fixed opponent-independent formulas.
Layer 2  opponent model   : per-seat action frequencies with Beta priors (class Opp).
Layer 3  exploit bridge   : turns frequencies into ranges ("top p of hands for that action"),
                            gated by g = clamp((n - 20) / 40, 0, 1). It only changes ranges.
Layer 4  equity engine    : per-combo weights for every live villain, updated by the likelihood
                            of each action; exact river enumeration, Monte Carlo before it.
Standard library only, no I/O, never raises out of act().
"""
import base64
import gc
import random
import time
import zlib
from bisect import bisect_left
from itertools import accumulate
from math import exp, log
from operator import mul

_pc = time.perf_counter
_rng = random.Random()
_choices = _rng.choices

# --------------------------------------------------------------------------- preflop data
_R = "AKQJT98765432"
PF_COMBOS = []
for _i in range(13):
    for _j in range(13):
        PF_COMBOS.append(6 if _i == _j else (4 if _i < _j else 12))

_PF_BLOB = "@@BLOB@@"


def _decode_pf_eq():
    raw = zlib.decompress(base64.b85decode(_PF_BLOB))
    eq = [[0.5] * 169 for _ in range(169)]
    k = 0
    for a in range(169):
        row = eq[a]
        for b in range(a + 1, 169):
            v = raw[k] / 255.0
            k += 1
            row[b] = v
            eq[b][a] = 1.0 - v
    return eq


PF_EQ = _decode_pf_eq()
PF_VS_RANDOM = [sum(PF_EQ[a][b] * PF_COMBOS[b] for b in range(169)) / 1326.0 for a in range(169)]


def _rank_classes():
    """Playability-adjusted strength score per class (used for 'top p' ranges)."""
    s1 = PF_VS_RANDOM
    idx = sorted(range(169), key=lambda c: -s1[c])
    tot = 0
    top = []
    for c in idx:
        if tot > 0.3 * 1326:
            break
        top.append(c)
        tot += PF_COMBOS[c]
    wsum = float(sum(PF_COMBOS[c] for c in top))
    s2 = [sum(PF_EQ[a][b] * PF_COMBOS[b] for b in top) / wsum for a in range(169)]
    out = []
    for c in range(169):
        i, j = divmod(c, 13)
        adj = 0.0
        if i < j:
            adj = 0.022 + (0.012 if j - i <= 2 else 0.0)
        elif i > j and i - j >= 5:
            adj = -0.01
        out.append(0.5 * s1[c] + 0.5 * s2[c] + adj)
    return out


_SCORE = _rank_classes()
ORDER_ASC = sorted(range(169), key=lambda c: _SCORE[c])      # weakest class first
POS_OF = [0] * 169
for _p, _c in enumerate(ORDER_ASC):
    POS_OF[_c] = _p
MASS0 = [float(PF_COMBOS[c]) for c in ORDER_ASC]             # uniform range, mass per class
INVC = [1.0 / PF_COMBOS[c] for c in range(169)]
PCT = [0.0] * 169                                            # 0 = best hand, 1 = worst
_acc = 0.0
for _c in reversed(ORDER_ASC):
    PCT[_c] = (_acc + 0.5 * PF_COMBOS[_c]) / 1326.0
    _acc += PF_COMBOS[_c]
EQROW = [[PF_EQ[h][c] for c in ORDER_ASC] for h in range(169)]

# --------------------------------------------------------------------------- evaluator
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARD = {r + s: RANKS.index(r) * 4 + SUITS.index(s) for r in RANKS for s in SUITS}
RK = [5 ** (c >> 2) for c in range(52)]
SK = [8 ** (c & 3) for c in range(52)]
BIT = [1 << c for c in range(52)]
CARD_SM = [tuple((1 << (c >> 2)) if (c & 3) == s else 0 for s in range(4)) for c in range(52)]


def _straights():
    t = [-1] * 8192
    for m in range(8192):
        mm = (m << 1) | (1 if m & 4096 else 0)
        for top in range(13, 3, -1):
            if (mm >> (top - 4)) & 31 == 31:
                t[m] = top - 1
                break
    return t


STR = _straights()


def _build_nf():
    """Strength of every 5/6/7-card rank multiset ignoring flushes; key = sum of 5**rank."""
    nf = {}
    cnt = [0] * 13
    p5 = [5 ** r for r in range(13)]
    strt = STR

    def val():
        q = t1 = t2 = -1
        prs = []
        sg = []
        m = 0
        for r in range(12, -1, -1):
            n = cnt[r]
            if n:
                m |= 1 << r
                if n == 1:
                    sg.append(r)
                elif n == 2:
                    prs.append(r)
                elif n == 3:
                    if t1 < 0:
                        t1 = r
                    elif t2 < 0:
                        t2 = r
                else:
                    q = r
        if q >= 0:
            k = -1
            for r in range(12, -1, -1):
                if cnt[r] and r != q:
                    k = r
                    break
            return (7 << 20) | (q << 16) | (k << 12)
        if t1 >= 0 and (t2 >= 0 or prs):
            return (6 << 20) | (t1 << 16) | ((t2 if t2 >= 0 else prs[0]) << 12)
        sh = strt[m]
        if sh >= 0:
            return (4 << 20) | (sh << 16)
        if t1 >= 0:
            return (3 << 20) | (t1 << 16) | (sg[0] << 12) | (sg[1] << 8)
        if len(prs) >= 2:
            k = -1
            for r in range(12, -1, -1):
                if cnt[r] and r != prs[0] and r != prs[1]:
                    k = r
                    break
            return (2 << 20) | (prs[0] << 16) | (prs[1] << 12) | (k << 8)
        if prs:
            return (1 << 20) | (prs[0] << 16) | (sg[0] << 12) | (sg[1] << 8) | (sg[2] << 4)
        return (sg[0] << 16) | (sg[1] << 12) | (sg[2] << 8) | (sg[3] << 4) | sg[4]

    def rec(r, used, key):
        if r == 13:
            if used >= 5:
                nf[key] = val()
            return
        p = p5[r]
        top = 7 - used
        if top > 4:
            top = 4
        for n in range(top + 1):
            cnt[r] = n
            rec(r + 1, used + n, key + n * p)
        cnt[r] = 0

    rec(0, 0, 0)
    return nf


NF = _build_nf()


def _build_fl():
    fl = [0] * 8192
    for m in range(8192):
        if bin(m).count("1") >= 5:
            sh = STR[m]
            if sh >= 0:
                fl[m] = (8 << 20) | (sh << 16)
            else:
                rs = [r for r in range(12, -1, -1) if (m >> r) & 1][:5]
                fl[m] = (5 << 20) | (rs[0] << 16) | (rs[1] << 12) | (rs[2] << 8) | (rs[3] << 4) | rs[4]
    return fl


FL = _build_fl()
FS = [-1] * 4096
for _k in range(4096):
    for _s in range(4):
        if (_k >> (3 * _s)) & 7 >= 5:
            FS[_k] = _s
SD = [0] * 8192                       # number of ranks completing a straight (0, 1, 2)
for _m in range(8192):
    if STR[_m] < 0:
        _n = 0
        for _r in range(13):
            if not (_m >> _r) & 1 and STR[_m | (1 << _r)] >= 0:
                _n += 1
        SD[_m] = _n


def ev7(cards):
    """Strength int of the best 5-card hand from 5..7 card ints (same ordering as the engine)."""
    rk = sk = 0
    for c in cards:
        rk += RK[c]
        sk += SK[c]
    fs = FS[sk]
    if fs >= 0:
        m = 0
        for c in cards:
            if c & 3 == fs:
                m |= 1 << (c >> 2)
        return FL[m]
    return NF[rk]


# --------------------------------------------------------------------------- combo tables
CM = []
RKS = []
SKS = []
CSM = []
CLS = []
KID = [0] * 2704
CARD_COMBOS = [[] for _ in range(52)]
SUITED = [[] for _ in range(4)]
_rp = {}
for _a in range(52):
    for _b in range(_a + 1, 52):
        _k = len(CM)
        KID[_a * 52 + _b] = _k
        KID[_b * 52 + _a] = _k
        CM.append((1 << _a) | (1 << _b))
        RKS.append(RK[_a] + RK[_b])
        SKS.append(SK[_a] + SK[_b])
        CSM.append(tuple(x | y for x, y in zip(CARD_SM[_a], CARD_SM[_b])))
        _i, _j = 12 - (_a >> 2), 12 - (_b >> 2)
        if _i == _j:
            CLS.append(_i * 13 + _j)
        else:
            _hi, _lo = (_i, _j) if _i < _j else (_j, _i)
            CLS.append(_hi * 13 + _lo if (_a & 3) == (_b & 3) else _lo * 13 + _hi)
        CARD_COMBOS[_a].append(_k)
        CARD_COMBOS[_b].append(_k)
        if (_a & 3) == (_b & 3):
            SUITED[_a & 3].append(_k)
        _rp.setdefault((1 << (_a >> 2)) | (1 << (_b >> 2)), []).append(_k)
RPAIRS = list(_rp.items())
ALLK = list(range(1326))

# --------------------------------------------------------------------------- constants
NB = 48                 # likelihood look-up resolution (percentile grid)
_INB = 1.0 / NB
NBK = 12                # equity buckets over the villain's range percentile
_INBK = 1.0 / NBK
UNI = [_INBK] * NBK
VPEN = 0.035            # variance penalty coefficient (insurance against range-model error)
FOLD_P = (0.36, 0.46, 0.55, 0.66)     # population fold-to-bet by price bucket
RAISE_P = (0.09, 0.08, 0.07, 0.05)    # population raise-vs-bet by price bucket
BET_P = (0.0, 0.42, 0.38, 0.33)       # population bet-when-checked-to by street
BLUFF_SH = (0.0, 0.30, 0.25, 0.20)    # share of a betting range that is air, by street
UB = (0.50, 0.60, 0.69, 0.79)         # share of all hands too weak to continue, by bucket
OPEN_P = (0.15, 0.40, 0.42, 0.27, 0.21, 0.17, 0.14, 0.12)    # open % by players behind
POSF = (0.6, 1.6, 1.8, 1.25, 1.0, 0.85, 0.72, 0.62)          # villain open-freq position factor
STREET_IDX = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
FOLD = {"action": "fold"}
CHECK = {"action": "check"}
CALL = {"action": "call"}


def _top(q, tau, floor=0.0):
    """Likelihood table for 'top q of the current range' with a soft edge of width tau."""
    lo = 1.0 - q
    inv = 1.0 / tau
    return [min(1.0, max(floor, ((i + 0.5) * _INB - lo) * inv + 0.5)) for i in range(NB)]


def _apply(ws, t):
    """Multiply range weights (sorted weakest -> strongest) by a percentile likelihood table."""
    acc = list(accumulate(ws))
    tot = acc[-1]
    if tot <= 1e-12:
        return ws
    sc = NB / tot * 0.999999
    return [w * t[int(a * sc)] for w, a in zip(ws, acc)]


def _bucket(tc, pot_incl):
    """Price bucket of a call of tc into a pot that already includes the bet."""
    rho = tc / pot_incl if pot_incl > 0 else 1.0
    return 0 if rho < 0.30 else (1 if rho < 0.45 else (2 if rho < 0.58 else 3))


def _uninf(n, ssum, q):
    """Showdown calibration: how uninformative are this villain's raises (0 = top-q, 1 = random)."""
    if n < 2:
        return 0.0
    u = (ssum / n - 0.5 * q) / max(0.05, 0.5 - 0.5 * q)
    return min(1.0, max(0.0, u)) * n / (n + 3.0)


# --------------------------------------------------------------------------- layer 2: opponent model
class Opp:
    __slots__ = ("n", "g", "uo_n", "uo_r", "uo_l", "fr_n", "fr_c", "fr_r", "f3_n", "f3_c", "f3_r",
                 "fs_n", "fs_c", "fd_n", "fd_sh", "cb_n", "cb_b", "fb_n", "fb_f", "fb_r",
                 "bs_n", "bs_sum", "sd_r_n", "sd_r_sum", "sd_s_n", "sd_s_sum")

    def __init__(self):
        self.n = 0              # observed voluntary actions
        self.g = 0.0            # gating weight
        self.uo_n = self.uo_r = self.uo_l = 0       # unopened pot: chances / raises / limps
        self.fr_n = self.fr_c = self.fr_r = 0       # facing one raise: chances / calls / 3-bets
        self.f3_n = self.f3_c = self.f3_r = 0       # facing 3-bet+: chances / calls / re-raises
        self.fs_n = self.fs_c = 0                   # facing a shove: chances / calls
        self.fd_n = self.fd_sh = 0                  # hands seen / hands with a preflop shove
        self.cb_n = [0, 0, 0, 0]                    # postflop, checked to: chances by street
        self.cb_b = [0, 0, 0, 0]                    # ... bets
        self.fb_n = [0, 0, 0, 0]                    # facing a bet, by price bucket: chances
        self.fb_f = [0, 0, 0, 0]                    # ... folds
        self.fb_r = [0, 0, 0, 0]                    # ... raises
        self.bs_n = 0
        self.bs_sum = 0.0                           # bet sizes as pot fractions
        self.sd_r_n = 0
        self.sd_r_sum = 0.0                         # showdown percentiles after a preflop raise
        self.sd_s_n = 0
        self.sd_s_sum = 0.0                         # ... after a preflop shove

    def f(self, k, n, prior, kk):
        """Beta-posterior frequency, shrunk to the population prior by the gate."""
        return prior + self.g * ((k + prior * kk) / (n + kk) - prior)

    def foldp(self, b):
        fn = self.fb_n
        ff = self.fb_f
        tn = fn[0] + fn[1] + fn[2] + fn[3]
        base = FOLD_P[b]
        if tn:
            ex = (fn[0] * FOLD_P[0] + fn[1] * FOLD_P[1] + fn[2] * FOLD_P[2] + fn[3] * FOLD_P[3]) / tn
            ob = (ff[0] + ff[1] + ff[2] + ff[3]) / tn
            base = min(0.97, max(0.01, base + (ob - ex) * tn / (tn + 8.0)))
        post = (ff[b] + base * 5.0) / (fn[b] + 5.0)
        return FOLD_P[b] + self.g * (post - FOLD_P[b])

    def raisep(self, b):
        fn = self.fb_n
        fr = self.fb_r
        tn = fn[0] + fn[1] + fn[2] + fn[3]
        base = RAISE_P[b]
        if tn:
            ob = (fr[0] + fr[1] + fr[2] + fr[3] + 0.08 * 6.0) / (tn + 6.0)
            base = min(0.9, max(0.005, base * ob / 0.08))
        post = (fr[b] + base * 5.0) / (fn[b] + 5.0)
        return RAISE_P[b] + self.g * (post - RAISE_P[b])

    def callshove(self):
        c = self.f(self.fr_c + self.fr_r, self.fr_n, 0.20, 10.0)
        pr = min(0.9, max(0.04, c ** 4))
        return 0.06 + self.g * ((self.fs_c + pr * 5.0) / (self.fs_n + 5.0) - 0.06)


# --------------------------------------------------------------------------- the agent
class Agent:
    def __init__(self):
        self.me = 0
        self.n = 0
        self.opp = None
        self.hand_no = -1
        self.spent = 0.0
        self.S0 = 2000
        self.bd = []
        self.hole = [0, 1]
        self.hc = 0
        self.hk = 0
        self.hidx = 0

    def on_table_start(self, info):
        try:
            self.me = int(info.get("seat", 0))
            n = int(info.get("num_players", 8))
            self.n = n
            self.opp = [Opp() for _ in range(n)]
            self.S0 = int(info.get("starting_stack", 2000))
        except Exception:
            pass

    # ----------------------------------------------------------------- entry points
    def act(self, state):
        t0 = _pc()
        try:
            out = self._act(state, t0)
        except Exception:
            out = self._safe(state)
        self.spent += _pc() - t0 + 0.00015
        return out

    def on_hand_end(self, summary):
        try:
            self._learn(summary)
        except Exception:
            pass

    @staticmethod
    def _safe(state):
        try:
            legal = state.get("legal_actions", ())
            if "check" in legal:
                return CHECK
            if state.get("to_call", 1) <= 0.12 * state.get("pot", 0):
                return CALL
        except Exception:
            pass
        return FOLD

    def _act(self, s, t0):
        if s["hand_number"] != self.hand_no or len(s["history"]) < self.hidx:
            self._new_hand(s)
        if s["street"] == "preflop":
            self._sync(s, t0)
            return self._preflop(s)
        self.bd = [CARD[c] for c in s["board"]]
        if self.spent > 7.0:
            return self._cheap(s)          # time bank nearly gone: table-only play
        self._sync(s, t0)
        return self._postflop(s, t0)

    def _new_hand(self, s):
        n = len(s["stacks"])
        if self.opp is None or len(self.opp) != n:
            self.opp = [Opp() for _ in range(n)]
        self.n = n
        self.me = me = s["seat"]
        self.hand_no = s["hand_number"]
        self.hidx = 0
        self.r_si = -1
        self.nr = 0
        self.lvl = 0
        self.rpot = 0
        self.rb = [0] * n
        self.acted = set()
        self.last_raiser = -1
        self.pfa = [0] * n
        self.pfw = [MASS0] * n          # preflop range mass per class (ORDER_ASC)
        self.ws = [None] * n            # postflop combo weights, aligned with ctx order
        self.wst = [0] * n              # street the weights are aligned to (0 = preflop)
        self.ctx = [None, None, None, None]
        self.bd = []
        h = s["hole_cards"]
        a, b = CARD[h[0]], CARD[h[1]]
        if a > b:
            a, b = b, a
        self.hole = [a, b]
        self.hc = CLS[KID[a * 52 + b]]
        self.hk = a * 52 + b
        hist = s["history"]
        self.sbs = hist[0]["seat"] if hist else -1
        self.bbs = hist[1]["seat"] if len(hist) > 1 else -1
        if s["street"] == "preflop":
            self.S0 = s["stacks"][me] + s["bets"][me]
        self.shv = 0.4 * self.S0
        self.shc = 0.33 * self.S0

    def _u(self, salt):
        """Deterministic pseudo-random number in [0, 1) for mixed frequencies."""
        x = (self.hand_no * 2654435761 + self.hk * 40503 + salt * 977) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * 2246822519) & 0xFFFFFFFF
        x ^= x >> 13
        return x / 4294967296.0

    # ----------------------------------------------------------------- history replay (live)
    def _sync(self, s, t0):
        hist = s["history"]
        nh = len(hist)
        i = self.hidx
        folded = s["folded"]
        me = self.me
        while i < nh:
            e = hist[i]
            i += 1
            a = e["action"]
            seat = e["seat"]
            si = STREET_IDX[e["street"]]
            if si != self.r_si:
                self.r_si = si
                self.rb = [0] * self.n
                self.lvl = 0
                self.acted = set()
            amt = e["amount"]
            rb = self.rb
            if a == "small_blind" or a == "big_blind":
                rb[seat] = amt
                self.rpot += amt
                if amt > self.lvl:
                    self.lvl = amt
                continue
            mine = rb[seat]
            tc = self.lvl - mine
            if seat != me and not folded[seat]:
                if si == 0:
                    self._pf_upd(seat, a, amt, tc)
                else:
                    self._po_upd(seat, a, amt, tc, si, t0)
            if a == "call":
                rb[seat] = mine + amt
                self.rpot += amt
                self.acted.add(seat)
            elif a == "raise":
                self.rpot += amt - mine
                rb[seat] = amt
                self.lvl = amt
                if si == 0:
                    self.nr += 1
                self.acted = {seat}
                self.last_raiser = seat
            else:
                self.acted.add(seat)
            if si == 0:
                self.pfa[seat] += 1
        self.hidx = nh

    # ----------------------------------------------------------------- layer 3: bridge, preflop
    def _pf_upd(self, v, a, amt, tc):
        """Update villain v's preflop range for one action using his measured frequencies."""
        if a == "fold":
            return
        o = self.opp[v]
        m = self.pfw[v]
        nr = self.nr
        first = self.pfa[v] == 0
        frac = sum(m) / 1326.0
        if frac <= 1e-6:
            return
        if a == "raise":
            if amt >= self.shv:
                p = 0.055 + o.g * ((o.fd_sh + 0.4) / (o.fd_n + 12.4) - 0.055)
                q = p / frac
                u = _uninf(o.sd_s_n, o.sd_s_sum, p)
            elif nr == 0:
                nb = self.n - len(self.acted) - 1
                q = o.f(o.uo_r, o.uo_n, 0.17, 10.0) * POSF[nb if 0 <= nb < 8 else 4]
                u = _uninf(o.sd_r_n, o.sd_r_sum, q)
            elif nr == 1:
                p3 = o.f(o.fr_r, o.fr_n, 0.06, 10.0)
                q = p3 if first else min(0.5, p3 / frac)
                u = _uninf(o.sd_r_n, o.sd_r_sum, q) * 0.7
            else:
                p4 = o.f(o.f3_r, o.f3_n, 0.10, 6.0)
                q = 0.35 * p4 if first else p4
                u = _uninf(o.sd_r_n, o.sd_r_sum, q) * 0.5
            q = min(1.0, max(0.012, q))
            if q >= 0.97:
                return
            t = _top(q, 0.02 + 0.12 * q, 0.015)
            if u > 0.02:
                t = [(1.0 - u) * x + u for x in t]
        elif a == "call":
            if tc >= self.shc:
                q = min(1.0, max(0.03, o.callshove() / frac))
                if q >= 0.97:
                    return
                t = _top(q, 0.02 + 0.12 * q, 0.01)
            elif nr == 0:
                nb = self.n - len(self.acted) - 1
                pr = min(0.95, o.f(o.uo_r, o.uo_n, 0.17, 10.0) * POSF[nb if 0 <= nb < 8 else 4])
                pl = o.f(o.uo_l, o.uo_n, 0.10, 10.0)
                hi = min(1.0, pr + pl + 0.04)
                if hi >= 0.97 and pr < 0.03:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
                if pr >= 0.03:
                    t2 = _top(pr, 0.02 + 0.1 * pr)
                    t = [x * (1.0 - 0.8 * y) for x, y in zip(t, t2)]
            elif nr == 1:
                pc = o.f(o.fr_c, o.fr_n, 0.14, 10.0)
                p3 = o.f(o.fr_r, o.fr_n, 0.06, 10.0)
                if v == self.bbs:
                    pc = min(0.95, pc * 1.7)
                if first:
                    hi = min(1.0, pc + p3 + 0.03)
                else:
                    hi = min(1.0, max(0.4, (pc + p3) / frac))
                    p3 = min(0.5, p3 / frac)
                if hi >= 0.97 and p3 < 0.03:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
                if p3 >= 0.02:
                    t2 = _top(p3, 0.02 + 0.1 * p3)
                    t = [x * (1.0 - 0.7 * y) for x, y in zip(t, t2)]
            else:
                pc = o.f(o.f3_c, o.f3_n, 0.30, 6.0)
                p4 = o.f(o.f3_r, o.f3_n, 0.10, 6.0)
                if first:
                    hi = min(1.0, max(0.02, 0.3 * pc))
                else:
                    hi = min(1.0, pc + p4)
                if hi >= 0.97:
                    return
                t = _top(hi, 0.03 + 0.1 * hi, 0.02)
        else:  # big blind checks his option: no top of range
            pr = o.f(o.uo_r, o.uo_n, 0.17, 10.0) * 0.6
            if pr < 0.04:
                return
            t = [1.0 - 0.9 * x for x in _top(min(0.95, pr), 0.02 + 0.1 * pr)]
        self.pfw[v] = _apply(m, t)

    # ----------------------------------------------------------------- layer 3: bridge, postflop
    def _po_upd(self, v, a, amt, tc, si, t0):
        """Likelihood update of villain v's combo weights for one postflop action."""
        if a == "fold" or _pc() - t0 > 0.0013:
            return
        ctx = self.ctx[si]
        if ctx is None:
            if si + 2 > len(self.bd) or si != len(self.bd) - 2:
                return
            ctx = self._mkctx(si)
        o = self.opp[v]
        if tc <= 0:
            beta = o.f(o.cb_b[si], o.cb_n[si], BET_P[si], 8.0)
            if a == "check":
                if beta < 0.12:
                    return
            elif beta > 0.9:
                return
            bl = BLUFF_SH[si]
            vq = beta * (1.0 - bl)
            if a == "raise":
                # big-bet signal: far above this villain's usual size -> stronger range
                avg = (o.bs_sum + 0.6 * 4.0) / (o.bs_n + 4.0)
                avg = 0.6 + o.g * (avg - 0.6)
                pot0 = self.rpot
                rel = (amt / pot0) / max(0.2, avg) if pot0 > 0 else 1.0
                if rel > 1.4:
                    vq *= max(0.45, rel ** -0.8)
                elif rel < 0.5:
                    vq = min(0.95, vq * 1.25)
            eps = min(1.0, beta * bl / max(0.05, 1.0 - vq))
            t = _top(vq, 0.08, eps)
            if a == "check":
                t = [max(0.1, 1.0 - x) for x in t]
        else:
            b = _bucket(tc, self.rpot)
            if a == "raise":
                r = o.raisep(b)
                vq = r * 0.8
                t = _top(vq, 0.06, min(1.0, r * 0.2 / max(0.05, 1.0 - vq)))
            elif a == "call":
                f = o.foldp(b)
                if f < 0.08:
                    return
                r = o.raisep(b)
                t = _top(1.0 - f, 0.08, 0.03)
                if r > 0.02:
                    t2 = _top(r * 0.8, 0.06)
                    t = [x * (1.0 - 0.6 * y) for x, y in zip(t, t2)]
            else:
                return
        self._to_street(v, si)
        self.ws[v] = _apply(self.ws[v], t)

    def _to_street(self, v, si):
        """Re-align villain v's weights with the combo order of street si."""
        cur = self.wst[v]
        if cur == si and self.ws[v] is not None:
            return
        ok = self.ctx[si][1]
        if cur == 0 or self.ws[v] is None or self.ctx[cur] is None:
            m = self.pfw[v]
            cw = [0.0] * 169
            for pos, c in enumerate(ORDER_ASC):
                cw[c] = m[pos] * INVC[c]
            ws = [cw[CLS[k]] for k in ok]
        else:
            d = dict(zip(self.ctx[cur][1], self.ws[v]))
            ws = [d[k] for k in ok]
        self.ws[v] = ws
        self.wst[v] = si

    # ----------------------------------------------------------------- layer 4: street context
    def _mkctx(self, si):
        """All villain combos on this board sorted weakest -> strongest (draws promoted)."""
        bd = self.bd[:si + 2]
        used = BIT[self.hole[0]] | BIT[self.hole[1]]
        brk = 0
        bm = 0
        bsc = [0, 0, 0, 0]
        bsm = [0, 0, 0, 0]
        for c in bd:
            used |= BIT[c]
            brk += RK[c]
            s_ = c & 3
            bsc[s_] += 1
            bsm[s_] |= 1 << (c >> 2)
            bm |= 1 << (c >> 2)
        prev = self.ctx[si - 1] if si > 1 else None
        base = prev[1] if prev else ALLK
        live = [k for k in base if not CM[k] & used]
        over = {}
        for s_ in range(4):
            bc = bsc[s_]
            if bc >= 3:
                m0 = bsm[s_]
                if bc == 3:
                    for k in SUITED[s_]:
                        over[k] = FL[m0 | CSM[k][s_]]
                else:
                    for k in live:
                        f = FL[m0 | CSM[k][s_]]
                        if f:
                            over[k] = f
        og = over.get
        if si < 3:
            # draws count as continues: lift them to a made-hand-equivalent strength
            rs = sorted({c >> 2 for c in bd}, reverse=True)
            b1 = rs[0]
            b2 = rs[1] if len(rs) > 1 else rs[0]
            t3 = (1 << 20) | (b1 << 16) | (12 << 12)
            t2 = (1 << 20) | (b2 << 16) | (12 << 12)
            t1 = (1 << 20) | (rs[-1] << 16)
            for s_ in range(4):
                bc = bsc[s_]
                if bc == 2:
                    for k in SUITED[s_]:
                        over[k] = t2
                elif bc == 3:
                    m0 = bsm[s_]
                    for r in (12, 11, 10):
                        if not (m0 >> r) & 1:
                            for k in CARD_COMBOS[r * 4 + s_]:
                                if og(k, 0) < t2:
                                    over[k] = t2
            if STR[bm] < 0:
                sdb = SD[bm]
                for bits, lst in RPAIRS:
                    m2 = bm | bits
                    if m2 != bm and STR[m2] < 0:
                        d = SD[m2]
                        if d > sdb:
                            if d >= 2:
                                for k in lst:
                                    x = og(k, 0)
                                    if x == t2:
                                        over[k] = t3
                                    elif x < t2:
                                        over[k] = t2
                            else:
                                for k in lst:
                                    if og(k, 0) < t1:
                                        over[k] = t1
        nf = NF
        if over:
            enc = [(max(nf[brk + RKS[k]], og(k, 0)) << 11) | k for k in live]
        else:
            enc = [(nf[brk + RKS[k]] << 11) | k for k in live]
        enc.sort()
        ok = [e & 2047 for e in enc]
        ctx = (enc, ok, len(ok))
        self.ctx[si] = ctx
        return ctx

    # ----------------------------------------------------------------- layer 4: Monte Carlo
    def _mc(self, accs, tots, ok, n_s, dl):
        """Sample (villain combos, runout); per villain: bucketed counts/wins; overall wins."""
        bd = self.bd
        hole = self.hole
        b_rk = b_sk = 0
        b_sm = [0, 0, 0, 0]
        for c in bd:
            b_rk += RK[c]
            b_sk += SK[c]
            b_sm[c & 3] |= 1 << (c >> 2)
        h_rk = b_rk
        h_sk = b_sk
        h_sm = b_sm[:]
        used = 0
        for c in hole:
            h_rk += RK[c]
            h_sk += SK[c]
            h_sm[c & 3] |= 1 << (c >> 2)
            used |= BIT[c]
        if len(bd) == 3:
            runs = _choices(ok, k=n_s)
            ma, rka, ska, sma = CM, RKS, SKS, CSM
        else:
            for c in bd:
                used |= BIT[c]
            deck = [c for c in range(52) if not used & BIT[c]]
            runs = _choices(deck, k=n_s)
            ma, rka, ska, sma = BIT, RK, SK, CARD_SM
        nv = len(accs)
        rng_n = range(len(ok))
        fs_t = FS
        fl = FL
        nf = NF
        cm = CM
        rks = RKS
        sks = SKS
        csm = CSM
        cnts = [[0] * NBK for _ in range(nv)]
        wins = [[0.0] * NBK for _ in range(nv)]
        tot_n = 0
        tot_w = 0.0
        it = 0
        if nv == 1:
            acc = accs[0]
            sc = NBK / tots[0] * 0.999999
            cnt = cnts[0]
            win = wins[0]
            poss = _choices(rng_n, cum_weights=acc, k=n_s)
            for j, rk in zip(poss, runs):
                it += 1
                if not it & 63 and _pc() > dl:
                    break
                vk = ok[j]
                if cm[vk] & ma[rk]:
                    continue
                rr = rka[rk]
                rs = ska[rk]
                sm = sma[rk]
                f = fs_t[h_sk + rs]
                hs = fl[h_sm[f] | sm[f]] if f >= 0 else nf[h_rk + rr]
                f = fs_t[b_sk + rs + sks[vk]]
                vs = fl[b_sm[f] | sm[f] | csm[vk][f]] if f >= 0 else nf[b_rk + rr + rks[vk]]
                b = int(acc[j] * sc)
                cnt[b] += 1
                if hs > vs:
                    win[b] += 1.0
                    tot_w += 1.0
                elif hs == vs:
                    win[b] += 0.5
                    tot_w += 0.5
                tot_n += 1
            return cnts, wins, tot_n, tot_w
        poss = [_choices(rng_n, cum_weights=acc, k=n_s) for acc in accs]
        scs = [NBK / t * 0.999999 for t in tots]
        vr = range(nv)
        vks = [0] * nv
        for t in range(n_s):
            it += 1
            if not it & 31 and _pc() > dl:
                break
            rk = runs[t]
            um = ma[rk]
            bad = False
            for vi in vr:
                vk = ok[poss[vi][t]]
                x = cm[vk]
                if x & um:
                    bad = True
                    break
                um |= x
                vks[vi] = vk
            if bad:
                continue
            rr = rka[rk]
            rs = ska[rk]
            sm = sma[rk]
            f = fs_t[h_sk + rs]
            hs = fl[h_sm[f] | sm[f]] if f >= 0 else nf[h_rk + rr]
            best = 0
            for vi in vr:
                vk = vks[vi]
                f = fs_t[b_sk + rs + sks[vk]]
                vs = fl[b_sm[f] | sm[f] | csm[vk][f]] if f >= 0 else nf[b_rk + rr + rks[vk]]
                b = int(accs[vi][poss[vi][t]] * scs[vi])
                cnts[vi][b] += 1
                if hs > vs:
                    wins[vi][b] += 1.0
                elif hs == vs:
                    wins[vi][b] += 0.5
                if vs > best:
                    best = vs
            tot_n += 1
            if hs > best:
                tot_w += 1.0
            elif hs == best:
                tot_w += 0.5
        return cnts, wins, tot_n, tot_w

    # ----------------------------------------------------------------- layer 1: postflop EV
    def _postflop(self, s, t0):
        me = self.me
        n = self.n
        bd = self.bd
        si = len(bd) - 2
        folded = s["folded"]
        stacks = s["stacks"]
        bets = s["bets"]
        pot = s["pot"]
        tc = s["to_call"]
        legal = s["legal_actions"]
        vill = [v for v in range(n) if v != me and not folded[v]]
        if not vill:
            return CHECK if "check" in legal else CALL
        ctx = self.ctx[si] or self._mkctx(si)
        enc, ok, n_c = ctx
        dropped = 0
        if len(vill) > 4:
            vill.sort(key=lambda v: -bets[v])
            dropped = len(vill) - 4
            vill = vill[:4]
        hs = ev7(self.hole + bd)
        lo = bisect_left(enc, hs << 11)
        uh = lo / n_c
        accs = []
        tots = []
        for v in vill:
            self._to_street(v, si)
            acc = list(accumulate(self.ws[v]))
            if acc[-1] <= 1e-9:
                self.ws[v] = [1.0] * n_c
                acc = list(accumulate(self.ws[v]))
            accs.append(acc)
            tots.append(acc[-1])
        nv = len(vill)
        cbs = []
        wbs = []
        eqs = []
        eq_all = 1.0
        exact = si == 3
        if not exact:
            n_s = (440, 280, 190, 140)[nv - 1]
            if self.spent > 4.0:
                n_s = n_s // 2 if self.spent < 5.5 else n_s // 5
            cnts, wins, tot_n, tot_w = self._mc(accs, tots, ok, n_s, t0 + 0.0021)
            if tot_n >= 24:
                eq_all = tot_w / tot_n
                inv = 1.0 / tot_n
                for vi in range(nv):
                    cnt = cnts[vi]
                    win = wins[vi]
                    ev_ = sum(win) * inv
                    eqs.append(ev_)
                    cbs.append([c * inv for c in cnt])
                    wbs.append([(w + ev_) / (c + 1.0) for w, c in zip(win, cnt)])
            else:
                exact = True       # ran out of time: fall back to current-strength percentiles
        if exact:
            hi = bisect_left(enc, (hs + 1) << 11)
            for acc, tot in zip(accs, tots):
                below = acc[lo - 1] if lo else 0.0
                tie = (acc[hi - 1] if hi else 0.0) - below
                hp = (below + 0.5 * tie) / tot
                eqs.append(hp)
                eq_all *= hp
                cbs.append(UNI)
                wbs.append([min(1.0, max(0.0, hp * NBK - b)) for b in range(NBK)])
        if dropped:
            eq_all *= 0.8 ** dropped

        s0 = self.S0
        mybet = bets[me]
        mystack = stacks[me]
        btn = s["button"]
        myidx = (me - btn - 1) % n
        ip = True
        for v in vill:
            if stacks[v] > 0 and (v - btn - 1) % n > myidx:
                ip = False
        spr = mystack / pot if pot > 0 else 10.0
        commit_adj = (1.0 / (1.0 + exp(-(spr - 4.0) / 1.5)) - 0.3) * 0.05     # SPR-aware commitment

        # ---- passive option
        if tc <= 0:
            if si == 3:
                rk_ = 1.0 if ip else 0.95
            else:
                rk_ = 1.0 if ip else 0.92
            ev_pass = rk_ * eq_all * pot
            passive = CHECK
        else:
            rc = 1.0 if si == 3 else (0.96 if ip else 0.90)
            fin = pot + tc
            ev_call = rc * eq_all * fin - tc
            risk = tc / s0
            if risk > 0.1:
                ev_call -= VPEN * risk * risk * fin
            if tc >= 0.5 * mystack:
                ev_call -= commit_adj * fin
            if si == 3 and nv == 1 and ev_call <= 0 and risk < 0.3:
                # MDF floor against unknown opponents: do not be auto-bluffable on the river
                o = self.opp[vill[0]]
                mdf = (pot - tc) / pot if pot > 0 else 0.5
                if o.g < 0.5 and uh >= 1.0 - 0.45 * mdf:
                    ev_call = 0.01
            if ev_call > 0:
                ev_pass = ev_call
                passive = CALL
            else:
                ev_pass = 0.0
                passive = FOLD
        if "raise" not in legal:
            return passive

        # ---- aggressive options
        mn = s["min_raise_to"]
        mx = s["max_raise_to"]
        lvl = max(bets)
        base = pot + tc
        xs = []
        for f in (0.33, 0.66, 1.0, 1.7):
            x = int(lvl + f * base)
            x = mn if x < mn else (mx if x > mx else x)
            if x not in xs:
                xs.append(x)
        if mystack <= 3.2 * base and mx not in xs:
            xs.append(mx)
        capx = 0
        act_i = []
        eq_ai = 1.0
        n_ai = 0
        for vi, v in enumerate(vill):
            if stacks[v] > 0:
                act_i.append(vi)
                if bets[v] + stacks[v] > capx:
                    capx = bets[v] + stacks[v]
            else:
                eq_ai *= eqs[vi]
                n_ai += 1
        if not act_i:
            return passive
        opp = self.opp
        tau_inv = 1.0 / 0.12
        rb_ = 0.97 if ip else 0.93
        best_ev = -1e18
        best_x = 0
        cap = (0.0, 0.55, 0.38, 0.28)[si]
        if nv >= 2:
            cap *= 0.4
        if tc > 0:
            cap *= 0.6
        u = self._u(si * 7 + s.get("raises_this_street", 0))
        for x in xs:
            xe = x if x < capx else capx
            inv = xe - mybet
            if inv <= 0:
                continue
            pot_incl = pot + inv
            rs = []
            for vi in act_i:
                v = vill[vi]
                add = xe - bets[v]
                if add > stacks[v]:
                    add = stacks[v]
                if add <= 0:
                    continue
                # P(continue): share of his range strong enough, shifted by his measured stickiness
                b = _bucket(add, pot_incl)
                o = opp[v]
                acc = accs[vi]
                ub = UB[b] + (0.05 if si == 3 else 0.0)
                qr = 1.0 - acc[int(ub * n_c)] / tots[vi]
                qr = 0.03 if qr < 0.03 else (0.97 if qr > 0.97 else qr)
                fm = o.foldp(b)
                fp = FOLD_P[b]
                z = log(qr / (1.0 - qr)) + log((1.0 - fm) / fm) - log((1.0 - fp) / fp)
                q = 1.0 / (1.0 + exp(-z))
                thr = 1.0 - q
                qq = 0.0
                ee = 0.0
                cb = cbs[vi]
                wb = wbs[vi]
                for k in range(NBK):
                    c = ((k + 0.5) * _INBK - thr) * tau_inv + 0.5
                    if c <= 0.0:
                        continue
                    if c > 1.0:
                        c = 1.0
                    m = cb[k] * c
                    qq += m
                    ee += m * wb[k]
                if qq < 1e-6:
                    rs.append((0.0, wb[NBK - 1], add))
                else:
                    rs.append((qq if qq < 1.0 else 1.0, ee / qq, add))
            if not rs:
                continue
            rs.sort(reverse=True)
            extra = rs[3:]
            rs = rs[:3]
            k = len(rs)
            ev = 0.0
            p_call = 0.0
            e_call = 0.0
            for mask in range(1 << k):
                p = 1.0
                e = eq_ai
                adds = 0
                for i in range(k):
                    q, ei, ad = rs[i]
                    if (mask >> i) & 1:
                        p *= q
                        e *= ei
                        adds += ad
                    else:
                        p *= 1.0 - q
                if mask == 0:
                    ev += p * (pot if not n_ai else e * pot)
                else:
                    er = e if (si == 3 or e >= 0.6) else e * rb_
                    ev += p * (er * (pot + inv + adds) - inv)
                    p_call += p
                    e_call += p * e
            for q, ei, ad in extra:
                ev -= q * inv * 0.6
            e_c = e_call / p_call if p_call > 1e-9 else 1.0
            risk = inv / s0
            if risk > 0.1:
                ev -= VPEN * risk * risk * (pot + 2 * inv) * p_call
            if inv >= 0.5 * mystack:
                ev -= commit_adj * (pot + 2 * inv) * p_call
            # bluff-frequency cap: pure bluffs only a capped share of the time
            if e_c < (0.35 if si == 3 else 0.40) and eq_all < 0.45:
                c_ = cap
                if si < 3 and eq_all >= 0.30:
                    c_ = max(c_, 0.75)
                if u > c_:
                    continue
            if ev > best_ev:
                best_ev = ev
                best_x = x
        margin = 0.03 * pot + (0.05 * pot if tc > 0 else 0.0)
        if best_x and best_ev > ev_pass + margin:
            return {"action": "raise", "amount": int(best_x)}
        return passive

    def _cheap(self, s):
        """Table-only postflop play when the time bank is nearly spent."""
        legal = s["legal_actions"]
        cat = ev7(self.hole + self.bd) >> 20
        tc = s["to_call"]
        pot = s["pot"]
        if tc <= 0:
            if cat >= 2 and "raise" in legal:
                x = int(max(s["bets"]) + 0.66 * pot)
                return {"action": "raise", "amount": max(s["min_raise_to"], min(s["max_raise_to"], x))}
            return CHECK
        if cat >= 3 or (cat >= 2 and tc <= pot) or (cat >= 1 and tc <= 0.3 * pot):
            return CALL
        return FOLD

    # ----------------------------------------------------------------- layer 1: preflop
    def _rz(self, hc, ip, eq):
        """Equity realisation of a hand class when calling preflop."""
        i, j = divmod(hc, 13)
        r = 0.92 if ip else 0.80
        if i == j:
            r += 0.04
        elif i < j:
            r += 0.05 + (0.03 if j - i <= 2 else 0.0)
        else:
            r -= 0.04 + (0.03 if i - j >= 4 else 0.0)
        if eq < 0.38:
            r -= 0.08
        return r

    def _preflop(self, s):
        me = self.me
        n = self.n
        legal = s["legal_actions"]
        bets = s["bets"]
        stacks = s["stacks"]
        folded = s["folded"]
        pot = s["pot"]
        tc = s["to_call"]
        bb = s["big_blind"]
        lvl = max(bets)
        s0 = stacks[me] + bets[me]
        hc = self.hc
        hp = PCT[hc]
        row = EQROW[hc]
        live = [v for v in range(n) if v != me and not folded[v]]
        can_raise = "raise" in legal
        mn = s["min_raise_to"]
        mx = s["max_raise_to"]
        nr = self.nr
        acted = self.acted
        pfw = self.pfw
        opp = self.opp
        if not live:
            return CHECK if "check" in legal else CALL

        def eqv(m):
            t = sum(m)
            return sum(map(mul, m, row)) / t if t > 1e-9 else 0.5

        # ---- facing a shove: equity vs the frequency-derived shoving range against pot odds
        if tc >= 0.33 * s0:
            eq = 1.0
            for v in live:
                if bets[v] >= lvl * 0.6 or stacks[v] == 0:
                    eq *= eqv(pfw[v])
            beh = 0
            for v in live:
                if v not in acted and bets[v] < lvl and stacks[v] > 0:
                    beh += 1
            eq *= 1.0 - 0.012 * beh
            fin = pot + tc
            risk = tc / s0
            ev = eq * fin - tc - VPEN * risk * risk * fin
            return CALL if ev > 0 else FOLD

        btn = s["button"]
        myidx = (me - btn - 1) % n

        # ---- unopened / limped pot: position range, widened or tightened by fold equity
        if nr == 0:
            behind = [v for v in live if v not in acted and stacks[v] > 0]
            limpers = [v for v in live if v in acted]
            nb = len(behind)
            nl = len(limpers)
            p = OPEN_P[nb if nb < 8 else 7]
            if nl:
                p *= 0.9 ** nl
            ratio = 1.0
            csum = 0.0
            for v in behind:
                o = opp[v]
                pr = 0.30 if v == self.bbs else 0.17
                c = o.f(o.fr_c + o.fr_r, o.fr_n, pr, 10.0)
                ratio *= (1.0 - c) / (1.0 - pr)
                csum += c
            for v in limpers:
                o = opp[v]
                csum += o.f(o.fr_c + o.fr_r, o.fr_n, 0.45, 10.0)
            p *= min(2.0, max(0.55, ratio ** 0.9))
            if p > 0.85:
                p = 0.85
            loose = csum / max(1, nb + nl)
            if can_raise and hp <= 0.32 and mx >= 0.9 * s0:
                # value jam against opponents who call shoves far too wide
                ev_j = self._jam_ev(live, acted, row, pot, s0 - bets[me], bets, stacks, s0)
                alt = 40.0 + 2500.0 * max(0.0, PF_VS_RANDOM[hc] - 0.55)
                if ev_j > alt + 30.0:
                    return {"action": "raise", "amount": int(mx)}
            if hp <= p and can_raise:
                size = (3.0 if me == self.sbs else 2.5) * bb + bb * nl
                if loose > 0.3:
                    size *= 1.0 + min(1.2, (loose - 0.3) * 2.5)
                x = int(size)
                return {"action": "raise", "amount": max(mn, min(mx, x))}
            if tc <= 0:
                return CHECK
            if tc <= bb:
                if nl == 0:
                    o = opp[self.bbs] if 0 <= self.bbs < n else None
                    br = o.f(o.uo_r, o.uo_n, 0.17, 10.0) if o else 0.17
                    if hp <= 0.55 and br < 0.35:
                        return CALL
                elif hp <= min(0.5, 1.8 * p + 0.04 * nl):
                    return CALL
            return FOLD

        # ---- facing a raise / 3-bet: equity vs the raiser's frequency-derived range
        rz = self.last_raiser
        if rz < 0 or rz == me or folded[rz]:
            rz = max(live, key=lambda v: bets[v])
        callers = [v for v in live if v != rz and bets[v] >= lvl]
        behind = [v for v in live if v != rz and v not in acted and stacks[v] > 0]
        eq_r = eqv(pfw[rz])
        eq = eq_r
        for v in callers:
            eq *= eqv(pfw[v])
        ip = True
        for v in live:
            if stacks[v] > 0 and (v - btn - 1) % n > myidx:
                ip = False
        rzn = self._rz(hc, ip, eq_r)
        fin = pot + tc
        ev_call = rzn * eq * fin - tc
        i, j = divmod(hc, 13)
        if tc <= 0.08 * s0:
            if i == j and i >= 3:
                ev_call += 0.45 * min(tc, 120)          # set mining
            elif i < j and j - i <= 2:
                ev_call += 0.2 * min(tc, 120)
        for v in behind:
            o = opp[v]
            ev_call -= o.f(o.fr_r, o.fr_n, 0.06, 10.0) * tc * 0.8      # squeeze risk
        risk = tc / s0
        if risk > 0.1:
            ev_call -= VPEN * risk * risk * fin
        if tc <= 0:
            ev_call = max(ev_call, 0.0)

        best_ev = ev_call if ev_call > 0 else 0.0
        best = CALL if ev_call > 0 else (CHECK if tc <= 0 else FOLD)
        if can_raise:
            o = opp[rz]
            m = pfw[rz]
            frac = max(1e-6, sum(m) / 1326.0)
            mult = 2.3 if nr >= 2 else (3.0 if ip else 3.6)
            x = int(mult * lvl + lvl * len(callers))
            if x >= 0.45 * s0:
                x = mx
            x = max(mn, min(mx, x))
            cands = [x]
            if mx > x and mx >= 0.9 * s0 and hp <= 0.2:
                cands.append(mx)
            u = self._u(31 + nr)
            for x in cands:
                inv = x - bets[me]
                addv = min(x, bets[rz] + stacks[rz]) - bets[rz]
                if inv <= 0 or addv <= 0:
                    continue
                jam = addv >= 0.33 * s0
                if jam:
                    q = min(0.97, max(0.05, o.callshove() / frac))
                    p4 = 0.0
                else:
                    pc = o.f(o.f3_c, o.f3_n, 0.30, 6.0)
                    p4 = o.f(o.f3_r, o.f3_n, 0.10, 6.0)
                    q = min(0.97, pc + p4)
                eqc = eqv(_apply(m, _top(q, 0.03 + 0.1 * q, 0.01)))
                pfold = 1.0 - q
                for v in callers:
                    pfold *= 0.8
                for v in behind:
                    pfold *= 0.93
                r3 = 1.0 if jam else min(1.0, rzn + 0.08)
                ev = pfold * pot + (1.0 - pfold) * (r3 * eqc * (pot + inv + addv) - inv)
                if not jam and hp > 0.035:
                    ev -= p4 * inv * 0.5               # we usually give up to a 4-bet
                risk = inv / s0
                if risk > 0.1:
                    ev -= VPEN * risk * risk * (pot + inv + addv) * (1.0 - pfold)
                if eqc < 0.42 and u > 0.45:
                    continue                            # bluff-frequency cap on light re-raises
                if ev > best_ev + 0.5 * bb + (1.0 * bb if jam else 0.0):
                    best_ev = ev
                    best = {"action": "raise", "amount": int(x)}
        return best

    def _jam_ev(self, live, acted, row, pot, inv, bets, stacks, s0):
        """EV of an open/iso jam from each opponent's (gated) call-a-shove frequency and range."""
        opp = self.opp
        pfw = self.pfw
        rs = []
        for v in live:
            if stacks[v] <= 0:
                continue
            o = opp[v]
            m = pfw[v]
            pc = o.callshove()
            if v in acted:
                pc = min(1.0, pc * 1.5)
            if pc < 0.02:
                continue
            mc = _apply(m, _top(pc, 0.02 + 0.12 * pc, 0.005))
            t = sum(mc)
            e = sum(map(mul, mc, row)) / t if t > 1e-9 else 0.3
            rs.append((pc, e, min(stacks[v], s0 - bets[v])))
        rs.sort(reverse=True)
        rs = rs[:3]
        k = len(rs)
        ev = 0.0
        pany = 0.0
        for mask in range(1 << k):
            p = 1.0
            e = 1.0
            adds = 0
            for i in range(k):
                q, ei, ad = rs[i]
                if (mask >> i) & 1:
                    p *= q
                    e *= ei
                    adds += ad
                else:
                    p *= 1.0 - q
            if mask == 0:
                ev += p * pot
            else:
                ev += p * (e * (pot + inv + adds) - inv)
                pany += p
        risk = inv / s0
        return ev - VPEN * risk * risk * (pot + 2 * inv) * pany

    # ----------------------------------------------------------------- layer 2: learning
    def _learn(self, sm):
        """Replay the finished hand and update every opponent's frequencies (incl. showdowns)."""
        hist = sm["history"]
        opp = self.opp
        if opp is None:
            return
        shv = 0.4 * self.S0
        shc = 0.33 * self.S0
        cur = None
        si = 0
        lvl = 0
        nr = 0
        pot = 0
        rb = {}
        seen = set()
        shoved = set()
        pfr = set()
        for e in hist:
            a = e["action"]
            seat = e["seat"]
            st = e["street"]
            if st != cur:
                cur = st
                si = STREET_IDX[st]
                rb = {}
                lvl = 0
            amt = e["amount"]
            if a == "small_blind" or a == "big_blind":
                rb[seat] = amt
                pot += amt
                if amt > lvl:
                    lvl = amt
                continue
            o = opp[seat]
            mine = rb.get(seat, 0)
            tc = lvl - mine
            o.n += 1
            if si == 0:
                if seat not in seen:
                    seen.add(seat)
                    o.fd_n += 1
                if tc >= shc:
                    o.fs_n += 1
                    if a != "fold":
                        o.fs_c += 1
                elif nr == 0:
                    o.uo_n += 1
                    if a == "raise":
                        o.uo_r += 1
                    elif a == "call":
                        o.uo_l += 1
                elif nr == 1:
                    o.fr_n += 1
                    if a == "raise":
                        o.fr_r += 1
                    elif a == "call":
                        o.fr_c += 1
                else:
                    o.f3_n += 1
                    if a == "raise":
                        o.f3_r += 1
                    elif a == "call":
                        o.f3_c += 1
                if a == "raise":
                    pfr.add(seat)
                    if amt >= shv and seat not in shoved:
                        shoved.add(seat)
                        o.fd_sh += 1
            elif tc <= 0:
                o.cb_n[si] += 1
                if a == "raise":
                    o.cb_b[si] += 1
                    o.bs_n += 1
                    o.bs_sum += min(3.0, amt / pot) if pot > 0 else 0.6
            else:
                b = _bucket(tc, pot)
                o.fb_n[b] += 1
                if a == "fold":
                    o.fb_f[b] += 1
                elif a == "raise":
                    o.fb_r[b] += 1
            if a == "call":
                rb[seat] = mine + amt
                pot += amt
            elif a == "raise":
                pot += amt - mine
                rb[seat] = amt
                lvl = amt
                if si == 0:
                    nr += 1
        shown = sm.get("shown") or {}
        for k, cards in shown.items():
            seat = int(k)
            if seat in pfr:
                a, b = CARD[cards[0]], CARD[cards[1]]
                pct = PCT[CLS[KID[a * 52 + b]]]
                o = opp[seat]
                o.sd_r_n += 1
                o.sd_r_sum += pct
                if seat in shoved:
                    o.sd_s_n += 1
                    o.sd_s_sum += pct
        for o in opp:
            g = (o.n - 20) / 40.0
            o.g = 0.0 if g < 0.0 else (1.0 if g > 1.0 else g)


gc.collect()
gc.freeze()
gc.disable()
