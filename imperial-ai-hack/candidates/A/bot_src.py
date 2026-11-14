"""Candidate A: Hyperion-faithful four-layer NLHE bot (stdlib only, single file).

  Layer 1  decision engine: fixed equity thresholds, never opponent specific.
  Layer 2  opponent model: Beta-prior statistics + 7-archetype posterior.
  Layer 3  exploit bridge: turns the model into range widths only (gated 20..60 actions).
  Layer 4  range-aware equity: preflop action -> base range -> postflop narrowing tiers
           -> exploit adjustment -> Monte Carlo (exact on the river) -> equity to layer 1.
"""
import base64
import gc
import math
import random
import time
import zlib
from bisect import bisect_left, bisect_right
from itertools import accumulate
from operator import mul

_pc = time.perf_counter

# ----------------------------------------------------------------------------- tables
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CARD = {r + s: ri * 4 + si for ri, r in enumerate(RANKS) for si, s in enumerate(SUITS)}
# index 52 is a "no card" sentinel so turn rollouts can share the flop loop
RK = [5 ** (c >> 2) for c in range(52)] + [0]
SK = [8 ** (c & 3) for c in range(52)] + [0]
BIT = [1 << c for c in range(52)] + [0]
SBIT = [[(1 << (c >> 2)) if (c & 3) == s else 0 for c in range(52)] + [0] for s in range(4)]


def _straight_tbl():
    t = [-1] * 8192
    for m in range(8192):
        mm = (m << 1) | (1 if m & 4096 else 0)
        for top in range(13, 3, -1):
            if (mm >> (top - 4)) & 31 == 31:
                t[m] = top - 1
                break
    return t


STRT = _straight_tbl()


def _flush_tbl():
    t = [0] * 8192
    for m in range(8192):
        if bin(m).count("1") >= 5:
            sh = STRT[m]
            if sh >= 0:
                t[m] = (8 << 20) | (sh << 16)
            else:
                v = 5 << 20
                sft = 16
                for r in range(12, -1, -1):
                    if (m >> r) & 1:
                        v |= r << sft
                        sft -= 4
                        if sft < 0:
                            break
                t[m] = v
    return t


FLUSH = _flush_tbl()
FSUIT = [-1] * 4096      # suit holding >= 5 cards, from the packed 3-bit suit counters
FD4 = [0] * 4096         # 3 if some suit holds >= 4 cards (flush draw), else 0
for _k in range(4096):
    for _s in range(4):
        _n = (_k >> (3 * _s)) & 7
        if _n >= 5:
            FSUIT[_k] = _s
        if _n >= 4:
            FD4[_k] = 3


def _sdraw_tbl():
    t = [0] * 8192
    for m in range(8192):
        if STRT[m] >= 0:
            continue
        outs = 0
        for r in range(13):
            if not (m >> r) & 1 and STRT[m | (1 << r)] >= 0:
                outs += 1
        t[m] = 2 if outs >= 2 else outs
    return t


SDR = _sdraw_tbl()       # 0 none, 1 gutshot, 2 open-ended / double gutter


def _build_noflush():
    """Strength of every 5/6/7-card rank multiset, ignoring suits. key = sum(5**rank)."""
    T = {}
    cnt = [0] * 13
    ST = STRT

    def leaf(key):
        q = t0 = t1 = p0 = p1 = p2 = -1
        s = []
        mask = 0
        for r in range(12, -1, -1):
            n = cnt[r]
            if n:
                mask |= 1 << r
                if n == 1:
                    s.append(r)
                elif n == 2:
                    if p0 < 0:
                        p0 = r
                    elif p1 < 0:
                        p1 = r
                    elif p2 < 0:
                        p2 = r
                elif n == 3:
                    if t0 < 0:
                        t0 = r
                    elif t1 < 0:
                        t1 = r
                elif q < 0:
                    q = r
        if q >= 0:
            k = 0
            for r in range(12, -1, -1):
                if cnt[r] and r != q:
                    k = r
                    break
            v = (7 << 20) | (q << 16) | (k << 12)
        elif t0 >= 0 and (t1 >= 0 or p0 >= 0):
            v = (6 << 20) | (t0 << 16) | ((t1 if t1 >= 0 else p0) << 12)
        else:
            sh = ST[mask]
            if sh >= 0:
                v = (4 << 20) | (sh << 16)
            elif t0 >= 0:
                v = (3 << 20) | (t0 << 16) | (s[0] << 12) | (s[1] << 8)
            elif p1 >= 0:
                k = s[0] if s else -1
                if p2 > k:
                    k = p2
                v = (2 << 20) | (p0 << 16) | (p1 << 12) | (k << 8)
            elif p0 >= 0:
                v = (1 << 20) | (p0 << 16) | (s[0] << 12) | (s[1] << 8) | (s[2] << 4)
            else:
                v = (s[0] << 16) | (s[1] << 12) | (s[2] << 8) | (s[3] << 4) | s[4]
        T[key] = v

    def rec(r, used, key):
        if r == 13:
            if used >= 5:
                leaf(key)
            return
        pw = 5 ** r
        top = 7 - used
        if top > 4:
            top = 4
        for n in range(top + 1):
            cnt[r] = n
            rec(r + 1, used + n, key + n * pw)
        cnt[r] = 0

    rec(0, 0, 0)
    return T


NOFLUSH = _build_noflush()


def ev(cards):
    """Strength int of the best 5-card hand from 5-7 card ints (same order as the engine)."""
    k = 0
    s = 0
    for c in cards:
        k += RK[c]
        s += SK[c]
    f = FSUIT[s]
    if f < 0:
        return NOFLUSH[k]
    m = 0
    for c in cards:
        if c & 3 == f:
            m |= 1 << (c >> 2)
    return FLUSH[m]


# ----------------------------------------------------------------------------- combos
CA, CB, CCLS, CRK, CSK, CMASK, CRM = [], [], [], [], [], [], []
CSM = [[], [], [], []]


def _cls(c1, c2):
    i = 12 - (c1 >> 2)
    j = 12 - (c2 >> 2)
    if i == j:
        return i * 13 + j
    hi, lo = (i, j) if i < j else (j, i)
    return hi * 13 + lo if (c1 & 3) == (c2 & 3) else lo * 13 + hi


for _a in range(52):
    for _b in range(_a + 1, 52):
        CA.append(_a)
        CB.append(_b)
        CCLS.append(_cls(_a, _b))
        CRK.append(RK[_a] + RK[_b])
        CSK.append(SK[_a] + SK[_b])
        CMASK.append(BIT[_a] | BIT[_b])
        CRM.append((1 << (_a >> 2)) | (1 << (_b >> 2)))
        for _s in range(4):
            CSM[_s].append(SBIT[_s][_a] | SBIT[_s][_b])
ALLI = list(range(1326))

# ----------------------------------------------------------------------------- preflop data
_R13 = "AKQJT98765432"
PF_COMBOS = [6 if i == j else (4 if i < j else 12) for i in range(13) for j in range(13)]
_PF_BLOB = "__PF_BLOB__"


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


def _rank_classes():
    vs_rand = [sum(map(mul, PF_EQ[a], PF_COMBOS)) / 1326.0 for a in range(169)]
    o0 = sorted(range(169), key=lambda a: -vs_rand[a])
    wt = [0.0] * 169
    acc = 0
    for a in o0:                      # top ~35% as the "playing" population
        if acc < 0.35 * 1326:
            wt[a] = PF_COMBOS[a]
        acc += PF_COMBOS[a]
    tw = sum(wt)
    score = []
    for a in range(169):
        i, j = divmod(a, 13)
        e = 0.45 * vs_rand[a] + 0.55 * sum(map(mul, PF_EQ[a], wt)) / tw
        if i == j:
            e += 0.012
        elif i < j:                   # suited: playability
            e += 0.02 + (0.012 if j - i <= 2 else 0.0)
        elif abs(j - i) >= 5 and j != 0:
            e -= 0.008
        score.append(e)
    order = sorted(range(169), key=lambda a: -score[a])
    pct = [0.0] * 169
    acc = 0.0
    for a in order:
        pct[a] = (acc + 0.5 * PF_COMBOS[a]) / 1326.0
        acc += PF_COMBOS[a]
    return pct


PF_PCT = _rank_classes()             # 0 = best hand class, 1 = worst (combo weighted)
PF_PLAY = [1 if (a // 13 == a % 13 or (a // 13 < a % 13 and (a % 13 - a // 13 <= 3 or a // 13 == 0)))
           else 0 for a in range(169)]   # pairs, suited connectors/gappers, suited aces

_RCACHE = {}


def _range(lo, hi, rb=0.0):
    """Soft-edged class range: classes ranked between top-lo and top-hi, blended rb to random.
    Returns (w per class, w*combos per class, total)."""
    if hi > 1.0:
        hi = 1.0
    if hi < 0.012:
        hi = 0.012
    if lo < 0.0:
        lo = 0.0
    if lo > hi - 0.03:
        lo = max(0.0, hi - 0.03)
    key = (int(lo * 200 + 0.5), int(hi * 200 + 0.5), int(rb * 20 + 0.5))
    r = _RCACHE.get(key)
    if r is not None:
        return r
    lo, hi, rb = key[0] / 200.0, key[1] / 200.0, key[2] / 20.0
    soft = 0.2 * hi + 0.01
    softl = 0.3 * lo + 0.005
    w = []
    for a in range(169):
        p = PF_PCT[a]
        x = 1.0 if p <= hi else (1.0 - (p - hi) / soft if p < hi + soft else 0.0)
        if lo > 0.0:                  # the very top would have raised: keep a little (traps)
            if p <= lo:
                x *= 0.15
            elif p < lo + softl:
                x *= 0.15 + 0.85 * (p - lo) / softl
        if rb:
            x = (1.0 - rb) * x + rb
        w.append(x)
    wc = list(map(mul, w, PF_COMBOS))
    r = (w, wc, sum(wc))
    if len(_RCACHE) > 6000:
        _RCACHE.clear()
    _RCACHE[key] = r
    return r


# ----------------------------------------------------------------------------- constants
# Layer 1 thresholds (fixed; never per opponent)
T_VALUE = 0.76        # value bet / raise
T_THIN = 0.55         # bet for value in position
T_THIN_OOP = 0.64     # out of position: check below this
T_CALL = 0.42         # reference call threshold for a pot-sized bet
VAR_C = 0.03          # quadratic variance penalty above 10% of the stack (small: chip EV)
T_PRE_VALUE = 0.60    # preflop re-raise for value (equity vs the raiser's range)
T_OPEN_VALUE = 0.55   # unopened/limped pot: raise when ahead of the ranges that continue
MW = (1.0, 1.0, 0.80, 0.72, 0.66, 0.62, 0.6, 0.6, 0.6)   # multiway scaling of value thresholds
OPEN_FRAC = (0.44, 0.29, 0.22, 0.17, 0.14, 0.12, 0.11)   # by seats before the button
OPEN_SB = 0.36
# Layer 2 archetypes: (vpip, pfr, shove, fold cheap/medium/expensive, bet freq, raise freq)
ARCH = ("balanced", "caller", "potOdds", "randomized", "ruleBased", "shover", "tightAggro")
PROTO = (
    (0.26, 0.19, 0.01, 0.30, 0.45, 0.55, 0.40, 0.10),
    (0.80, 0.04, 0.00, 0.03, 0.05, 0.08, 0.08, 0.02),
    (0.45, 0.10, 0.01, 0.12, 0.45, 0.78, 0.25, 0.06),
    (0.66, 0.33, 0.02, 0.33, 0.33, 0.33, 0.40, 0.33),
    (0.16, 0.06, 0.00, 0.62, 0.66, 0.70, 0.45, 0.04),
    (0.45, 0.40, 0.35, 0.30, 0.35, 0.40, 0.50, 0.30),
    (0.20, 0.16, 0.01, 0.42, 0.52, 0.62, 0.55, 0.12),
)
PSD2 = tuple(x * x for x in (0.12, 0.09, 0.07, 0.15, 0.15, 0.15, 0.18, 0.08))
LOGPRI = tuple(math.log(x) for x in (0.26, 0.15, 0.12, 0.11, 0.14, 0.08, 0.14))
# Layer 3: what each archetype does to RANGES (never to thresholds)
A_WR = (0.95, 1.0, 1.0, 1.5, 0.80, 1.3, 0.90)     # raise-range width multiplier
A_RB = (0.0, 0.0, 0.0, 0.75, 0.0, 0.25, 0.0)      # blend of raise range towards random
A_WC = (1.0, 1.6, 1.15, 1.3, 0.8, 1.1, 0.9)       # calling-range width multiplier
A_EPS = (1.0, 0.5, 0.6, 4.0, 0.4, 2.5, 1.0)       # postflop bluff floor multiplier
A_QM = (0.95, 0.9, 0.9, 1.8, 0.75, 1.5, 0.9)      # postflop aggression-range width
# Layer 4 narrowing tiers by postflop aggression level: (top fraction kept, bluff floor)
TIER = ((1.0, 1.0), (0.42, 0.14), (0.20, 0.07), (0.10, 0.035))
PRI_FOLD = (0.28, 0.42, 0.52)                     # population fold vs cheap/medium/expensive bet


class _Opp:
    __slots__ = ("n_act", "hands", "vpip", "pfr", "shv", "uo_n", "uo_r", "uo_l", "fr_n", "fr_3b",
                 "fr_c", "fr_f", "shf_n", "shf_c", "pb_n", "pb_b", "pf_n", "pf_f", "pf_r", "pf_c",
                 "bs_n", "bs_sum", "st_n", "st_f", "cr_n", "cr_r", "sd_n", "sd_weak", "shsd_n",
                 "shsd_sum", "prof")

    def __init__(self):
        self.n_act = self.hands = self.vpip = self.pfr = self.shv = 0
        self.uo_n = self.uo_r = self.uo_l = self.fr_n = self.fr_3b = self.fr_c = self.fr_f = 0
        self.shf_n = self.shf_c = self.pb_n = self.pb_b = self.pf_r = self.pf_c = 0
        self.pf_n = [0, 0, 0]
        self.pf_f = [0, 0, 0]
        self.bs_n = 0
        self.bs_sum = 0.0
        self.st_n = [0, 0, 0]
        self.st_f = [0, 0, 0]
        self.cr_n = self.cr_r = self.sd_n = self.sd_weak = self.shsd_n = 0
        self.shsd_sum = 0.0
        self.prof = None


class _Prof:
    __slots__ = ("at", "g", "ratio", "p3", "p4", "psh", "pcsh", "vpip", "wcall", "rb", "ab", "ar",
                 "cq", "fold", "epsm", "passive", "mfrac", "bsn", "A", "cont")


class _Ctx:
    __slots__ = ("R", "cur", "pre_rl", "pre_cl", "pre_sh", "pre_csh", "pre_limp", "pre_last",
                 "n_limp", "nr", "ncl", "rover", "ai", "lfrac", "chk", "prev_aggr", "aggr",
                 "prev_nb", "st_nb")

    def __init__(self, n):
        z = [0] * n
        self.R = 0
        self.cur = 0
        self.pre_rl = z[:]
        self.pre_cl = z[:]
        self.pre_sh = z[:]
        self.pre_csh = z[:]
        self.pre_limp = z[:]
        self.pre_last = -1
        self.n_limp = 0
        self.nr = z[:]
        self.ncl = z[:]
        self.rover = z[:]
        self.ai = z[:]
        self.lfrac = [0.0] * n
        self.chk = z[:]
        self.prev_aggr = -1
        self.aggr = -1
        self.prev_nb = 0
        self.st_nb = 0


class _St:
    __slots__ = ("key", "idx_s", "cls_s", "vals_s", "sc_s", "hv", "hsc", "hrk", "hsk", "brk",
                 "bsk", "bm", "hm", "deck", "need", "wet", "cb", "paired", "rc", "hpct", "eqc")


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class Agent:
    def __init__(self):
        self.n = 8
        self.seat = 0
        self.start = 2000
        self.bb = 20
        self.shove_thr = 800
        self.opp = [_Opp() for _ in range(10)]
        self.rng = random.Random(0xA11CE)
        self.spent = 0.0
        self.st = None
        self.prc = {}
        self.prc_hand = -1
        self.button = 0
        try:
            gc.collect()
            gc.freeze()
            gc.disable()
        except Exception:
            pass

    def on_table_start(self, info):
        try:
            self.n = int(info.get("num_players", 8))
            self.seat = int(info.get("seat", 0))
            self.start = int(info.get("starting_stack", 2000))
            self.bb = int(info.get("big_blind", 20))
            self.shove_thr = int(0.4 * self.start)
            self.opp = [_Opp() for _ in range(max(self.n, 10))]
        except Exception:
            pass

    # ========================================================================= entry points
    def act(self, state):
        t0 = _pc()
        a = None
        try:
            a = self._act(state, t0)
        except Exception:
            a = None
        try:
            out = self._fix(a, state)
        except Exception:
            out = {"action": "check"} if "check" in state.get("legal_actions", ()) else {"action": "fold"}
        self.spent += _pc() - t0 + 0.0002
        return out

    def _fix(self, a, state):
        legal = state["legal_actions"]
        if not isinstance(a, dict):       # fallback: check, else call only if it is nearly free
            if "check" in legal:
                return {"action": "check"}
            if state["to_call"] * 12 <= state["pot"] and "call" in legal:
                return {"action": "call"}
            return {"action": "fold"}
        act = a.get("action")
        if act == "raise" or act == "all_in":
            if "raise" not in legal:
                return {"action": "call"} if "call" in legal else {"action": "check"}
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            amt = hi if act == "all_in" else int(a.get("amount", lo))
            if amt < lo:
                amt = lo
            if amt > hi:
                amt = hi
            return {"action": "raise", "amount": int(amt)}
        if act == "call":
            return {"action": "call"} if "call" in legal else {"action": "check"}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "fold"}

    def on_hand_end(self, summary):
        try:
            self._learn(summary)
        except Exception:
            pass

    # ========================================================================= layer 2: model
    def _learn(self, sm):
        hist = sm["history"]
        n = self.n
        O = self.opp
        bets = [0] * n
        pot = 0
        cur = 0
        street = "preflop"
        R = 0
        seen = [0] * n
        vp = [0] * n
        pr = [0] * n
        sh = [0] * n
        agg = [0] * n
        chk = [0] * n
        si = -1
        thr = self.shove_thr
        for e in hist:
            s = e["seat"]
            a = e["action"]
            if e["street"] != street:
                street = e["street"]
                bets = [0] * n
                cur = 0
                chk = [0] * n
                si += 1
            amt = e.get("amount") or 0
            if a == "small_blind" or a == "big_blind":
                bets[s] = amt
                pot += amt
                if amt > cur:
                    cur = amt
                continue
            o = O[s]
            o.n_act += 1
            if si < 0:                                   # preflop
                first = not seen[s]
                seen[s] = 1
                if cur >= thr and a != "raise":          # decision facing a shove
                    o.shf_n += 1
                    if a == "call":
                        o.shf_c += 1
                if a == "raise":
                    if first:
                        if R == 0:
                            o.uo_n += 1
                            o.uo_r += 1
                        else:
                            o.fr_n += 1
                            o.fr_3b += 1
                    vp[s] = pr[s] = 1
                    if amt >= thr:
                        sh[s] = 1
                    pot += amt - bets[s]
                    bets[s] = amt
                    cur = amt
                    R += 1
                elif a == "call":
                    if first:
                        if R == 0:
                            o.uo_n += 1
                            o.uo_l += 1
                        else:
                            o.fr_n += 1
                            o.fr_c += 1
                    vp[s] = 1
                    pot += amt
                    bets[s] += amt
                elif first:
                    if R == 0:
                        o.uo_n += 1
                    else:
                        o.fr_n += 1
                        if a == "fold":
                            o.fr_f += 1
            else:                                        # postflop
                tc = cur - bets[s]
                if tc <= 0:
                    o.pb_n += 1
                    if a == "raise":
                        o.pb_b += 1
                        o.bs_n += 1
                        f = (amt - bets[s]) / pot if pot > 0 else 1.0
                        o.bs_sum += f if f < 3.0 else 3.0
                        agg[s] += 1
                        pot += amt - bets[s]
                        bets[s] = amt
                        cur = amt
                    else:
                        chk[s] = 1
                else:
                    price = tc / (pot + tc)
                    b = 0 if price < 0.22 else (1 if price < 0.31 else 2)
                    o.pf_n[b] += 1
                    o.st_n[si] += 1
                    if chk[s]:
                        o.cr_n += 1
                    if a == "fold":
                        o.pf_f[b] += 1
                        o.st_f[si] += 1
                    elif a == "call":
                        o.pf_c += 1
                        pot += amt
                        bets[s] += amt
                    elif a == "raise":
                        o.pf_r += 1
                        if chk[s]:
                            o.cr_r += 1
                        agg[s] += 1
                        pot += amt - bets[s]
                        bets[s] = amt
                        cur = amt
        for s in range(n):
            o = O[s]
            o.hands += 1
            o.vpip += vp[s]
            o.pfr += pr[s]
            o.shv += sh[s]
        shown = sm.get("shown")
        if shown:
            board = [CARD[x] for x in sm.get("board", ())]
            bcat = (ev(board) >> 20) if len(board) == 5 else -1
            for k, cards in shown.items():
                s = int(k)
                if s == self.seat or s >= n:
                    continue
                c1 = CARD[cards[0]]
                c2 = CARD[cards[1]]
                o = O[s]
                if sh[s]:                                 # what do they really shove with?
                    o.shsd_n += 1
                    o.shsd_sum += PF_PCT[_cls(c1, c2)]
                if agg[s] and bcat >= 0:                  # aggressive postflop, hole cards add nothing
                    o.sd_n += 1
                    if (ev(board + [c1, c2]) >> 20) <= bcat and bcat < 4:
                        o.sd_weak += 1

    def _classify(self, x, nn):
        ll = []
        best = -1e18
        for k in range(7):
            pk = PROTO[k]
            v = LOGPRI[k]
            for j in range(8):
                d = x[j] - pk[j]
                v -= d * d / (2.0 * (PSD2[j] + x[j] * (1.0 - x[j]) / (nn[j] + 2.0)))
            # price gradient: "folds because the price is bad" vs "folds everything"
            d = (x[5] - x[3]) - (pk[5] - pk[3])
            v -= d * d / (2.0 * (0.0225 + 0.25 / (nn[3] + 2.0) + 0.25 / (nn[5] + 2.0)))
            ll.append(v)
            if v > best:
                best = v
        ex = [math.exp(v - best) for v in ll]
        t = sum(ex)
        return [e / t for e in ex]

    # ========================================================================= layer 3: bridge
    def _prof(self, s):
        o = self.opp[s]
        P = o.prof
        if P is not None and o.n_act - P.at < 6:
            return P
        P = _Prof()
        P.at = o.n_act
        g = (o.n_act - 20) / 40.0                 # dynamic gating: 0 below 20 actions, 1 at 60+
        g = 0.0 if g < 0.0 else (1.0 if g > 1.0 else g)
        h = o.hands
        vpip = (o.vpip + 1.5) / (h + 5.0)
        pfr = (o.pfr + 0.85) / (h + 5.0)
        shv = (o.shv + 0.15) / (h + 10.0)
        uor = (o.uo_r + 0.85) / (o.uo_n + 5.0)
        f3 = (o.fr_3b + 0.48) / (o.fr_n + 8.0)
        fc = (o.fr_c + 1.2) / (o.fr_n + 6.0)
        csh = (o.shf_c + 0.56) / (o.shf_n + 8.0)
        pb = (o.pb_b + 1.65) / (o.pb_n + 5.0)
        n0, n1, n2 = o.pf_n
        nf = n0 + n1 + n2
        prr = (o.pf_r + 0.72) / (nf + 8.0)
        fa = (o.pf_f[0] + o.pf_f[1] + o.pf_f[2] + 1.6) / (nf + 4.0) / 0.40
        f0 = (o.pf_f[0] + 3.0 * min(0.95, PRI_FOLD[0] * fa)) / (n0 + 3.0)
        f1 = (o.pf_f[1] + 3.0 * min(0.95, PRI_FOLD[1] * fa)) / (n1 + 3.0)
        f2 = (o.pf_f[2] + 3.0 * min(0.95, PRI_FOLD[2] * fa)) / (n2 + 3.0)
        A = self._classify((vpip, pfr, shv, f0, f1, f2, pb, prr), (h, h, h, n0, n1, n2, o.pb_n, nf))
        wr = rbk = wc = em = qm = 0.0
        for k in range(7):
            a = A[k]
            wr += a * A_WR[k]
            rbk += a * A_RB[k]
            wc += a * A_WC[k]
            em += a * A_EPS[k]
            qm += a * A_QM[k]
        P.g = g
        P.A = A
        P.ratio = _clamp((1.0 + g * (uor / 0.17 - 1.0)) * (1.0 + g * (wr - 1.0)), 0.25, 6.0)
        P.p3 = _clamp(((1.0 - g) * 0.06 + g * f3) * (1.0 + g * (wr - 1.0)), 0.012, 0.95)
        P.p4 = _clamp(0.03 * P.ratio ** 0.7, 0.012, 0.6)
        sm = shv
        if o.shsd_n >= 3:                          # showdown calibration of the shove range
            w = o.shsd_n / (o.shsd_n + 4.0)
            sm = (1.0 - w) * sm + w * min(1.0, 2.0 * o.shsd_sum / o.shsd_n)
        P.psh = sm
        P.vpip = vpip
        P.wcall = _clamp(((1.0 - g) * 0.17 + g * fc) * (1.0 + g * (wc - 1.0)), 0.03, 0.95)
        P.pcsh = _clamp((1.0 - g) * 0.07 + g * csh, 0.02, 1.0)
        P.rb = g * rbk
        P.ab = _clamp((1.0 + g * (pb / 0.33 - 1.0)) * (1.0 + g * (qm - 1.0)), 0.3, 3.0)
        P.ar = _clamp((1.0 + g * (prr / 0.09 - 1.0)) * (1.0 + g * (qm - 1.0)), 0.3, 5.0)
        P.cq = _clamp(1.0 - ((1.0 - g) * 0.40 + g * (f0 + f1 + f2) / 3.0), 0.3, 0.98)
        P.fold = ((1.0 - g) * PRI_FOLD[0] + g * f0, (1.0 - g) * PRI_FOLD[1] + g * f1,
                  (1.0 - g) * PRI_FOLD[2] + g * f2)
        e = 1.0 + g * (em - 1.0)
        if o.sd_n >= 4:
            e *= 0.6 + 1.6 * o.sd_weak / o.sd_n
        P.epsm = e
        P.passive = (g >= 0.5 and nf >= 8 and o.pf_r <= 0.07 * nf and pb < 0.22
                     and o.pf_c >= 0.5 * nf and pfr < 0.12)
        P.mfrac = (o.bs_sum + 1.8) / (o.bs_n + 3.0)
        P.bsn = o.bs_n
        P.cont = (1.0 - g) * 0.22 + g * (1.0 - (o.fr_f + 4.5) / (o.fr_n + 6.0))
        o.prof = P
        return P

    # ========================================================================= hand context
    def _parse(self, state):
        n = len(state["stacks"])
        self.n = n
        c = _Ctx(n)
        bets = [0] * n
        contrib = [0] * n
        pot = 0
        cur = 0
        street = "preflop"
        R = 0
        thr = self.shove_thr
        start = self.start
        pre = True
        for e in state["history"]:
            a = e["action"]
            if e["street"] != street:
                street = e["street"]
                pre = False
                bets = [0] * n
                cur = 0
                c.chk = [0] * n
                c.prev_aggr = c.aggr
                c.aggr = -1
                c.prev_nb = c.st_nb
                c.st_nb = 0
            if a == "fold":
                continue
            s = e["seat"]
            amt = e.get("amount") or 0
            if a == "small_blind" or a == "big_blind":
                bets[s] = amt
                contrib[s] += amt
                pot += amt
                if amt > cur:
                    cur = amt
                continue
            if pre:
                if a == "raise":
                    R += 1
                    c.pre_rl[s] = R
                    c.pre_last = s
                    c.aggr = s
                    add = amt - bets[s]
                    contrib[s] += add
                    pot += add
                    bets[s] = amt
                    cur = amt
                    if amt >= thr or contrib[s] >= start:
                        c.pre_sh[s] = 1
                elif a == "call":
                    if R == 0:
                        c.pre_limp[s] = 1
                        c.n_limp += 1
                    else:
                        c.pre_cl[s] = R
                        if cur >= thr:
                            c.pre_csh[s] = 1
                    contrib[s] += amt
                    pot += amt
                    bets[s] += amt
            elif a == "raise":
                add = amt - bets[s]
                c.nr[s] += 1
                if cur > 0:
                    c.rover[s] += 1
                c.lfrac[s] = add / pot if pot > 0 else 1.0
                contrib[s] += add
                pot += add
                bets[s] = amt
                cur = amt
                if contrib[s] >= start:
                    c.ai[s] = 1
                c.aggr = s
                c.st_nb += 1
            elif a == "call":
                c.ncl[s] += 1
                contrib[s] += amt
                pot += amt
                bets[s] += amt
            elif a == "check":
                c.chk[s] = 1
        c.R = R
        c.cur = cur
        return c

    # ========================================================================= layer 4: ranges
    def _pre_range(self, s, c):
        """Preflop action -> base range, with the exploit bridge's widths applied."""
        key = (s, c.pre_rl[s], c.pre_cl[s], c.pre_sh[s], c.pre_csh[s], c.pre_limp[s])
        r = self.prc.get(key)
        if r is not None:
            return r
        P = self._prof(s)
        g = P.g
        rl = c.pre_rl[s]
        cl = c.pre_cl[s]
        if rl and c.pre_sh[s]:
            prior = 0.06 if rl <= 1 else (0.045 if rl == 2 else 0.03)
            r = _range(0.0, (1.0 - g) * prior + g * P.psh, P.rb)
        elif rl:
            if rl == 1:
                n = self.n
                pos = (s - self.button) % n
                base = OPEN_SB if pos == 1 else (0.14 if pos == 2 else OPEN_FRAC[min((n - pos) % n, 6)])
                p = base * 1.15 * P.ratio
            elif rl == 2:
                p = P.p3
            else:
                p = P.p4
            p = _clamp(p, 0.015, 1.0)
            r = _range(min(0.02, p / 3.0), p, P.rb) if cl >= rl else _range(0.0, p, P.rb)
        elif c.pre_csh[s]:
            r = _range(0.0, P.pcsh, 0.0)
        elif cl:
            lo = min(P.p3 * 0.6, 0.06)
            r = _range(lo, lo + max(P.wcall if cl == 1 else 0.5 * P.wcall, 0.04), 0.0)
        elif c.pre_limp[s]:
            lo = _clamp(0.085 * P.ratio, 0.02, 0.5)
            r = _range(lo, max(lo + 0.12, (1.0 - g) * 0.45 + g * P.vpip), 0.0)
        else:                                       # big blind that checked its option
            r = _range(_clamp(0.085 * P.ratio, 0.02, 0.5), 1.0, 0.0)
        self.prc[key] = r
        return r

    def _post_q(self, s, c, P, wet):
        """Postflop narrowing: (top fraction of the range kept, weight of the rest, cap weight)."""
        nr = c.nr[s]
        nc = c.ncl[s]
        if nr == 0:
            if nc:
                q = P.cq ** nc
                return (q if q > 0.2 else 0.2), 0.3, 1.0
            return 1.0, 1.0, (0.6 if c.chk[s] else 1.0)
        ro = c.rover[s]
        L = nr + ro
        lf = c.lfrac[s]
        if L < 2 and lf >= max(0.95, 1.8 * P.mfrac) and (P.bsn >= 5 or lf >= 1.5):
            L = 2                                   # big-bet signal: far above their own average
        if c.ai[s] and lf >= 0.5:
            L = 3                                   # all-in: strongest tier
        qb, e = TIER[L if L < 3 else 3]
        q = qb * (P.ar if ro else P.ab) * (1.0 - 0.25 * wet)
        if nc:
            q *= P.cq ** (0.5 * nc)
        eps = e * P.epsm
        if P.passive and (ro or L >= 2):            # passive rocket
            q = min(q, 0.07)
            eps = 0.01
        return _clamp(q, 0.03, 1.0), _clamp(eps, 0.005, 0.9), 1.0

    def _vrange(self, st, s, c, q, eps, capw):
        key = (s, c.nr[s], c.ncl[s], c.rover[s], c.ai[s], c.chk[s], int(q * 500), int(eps * 200))
        r = st.rc.get(key)
        if r is not None:
            return r
        w = self._pre_range(s, c)[0]
        ws = [w[k] for k in st.cls_s]               # combos sorted weakest -> strongest
        cum = list(accumulate(ws))
        tot = cum[-1]
        if tot <= 1e-9:
            ws = [1.0] * len(ws)
            cum = list(accumulate(ws))
            tot = cum[-1]
        if q < 0.999:
            cut = bisect_left(cum, (1.0 - q) * tot)
            cut0 = bisect_left(cum, (1.0 - min(1.0, 1.4 * q)) * tot)
            mid = 0.5 * (1.0 + eps)
            ws = [x * eps for x in ws[:cut0]] + [x * mid for x in ws[cut0:cut]] + ws[cut:]
            cum = list(accumulate(ws))
        elif capw < 1.0:                            # checked: fewer of the very strong hands
            cut = bisect_left(cum, 0.85 * tot)
            ws = ws[:cut] + [x * capw for x in ws[cut:]]
            cum = list(accumulate(ws))
        r = (ws, cum)
        st.rc[key] = r
        return r

    def _setup(self, key, hole, board):
        st = _St()
        st.key = key
        st.rc = {}
        st.eqc = {}
        dead = 0
        for x in hole:
            dead |= BIT[x]
        brk = bsk = brm = 0
        bm = [0, 0, 0, 0]
        scnt = [0, 0, 0, 0]
        rcnt = [0] * 13
        for x in board:
            dead |= BIT[x]
            brk += RK[x]
            bsk += SK[x]
            r = x >> 2
            brm |= 1 << r
            bm[x & 3] |= 1 << r
            scnt[x & 3] += 1
            rcnt[r] += 1
        hm = bm[:]
        for x in hole:
            hm[x & 3] |= 1 << (x >> 2)
        st.brk = brk
        st.bsk = bsk
        st.bm = bm
        st.hm = hm
        st.hrk = brk + RK[hole[0]] + RK[hole[1]]
        st.hsk = bsk + SK[hole[0]] + SK[hole[1]]
        nb = len(board)
        st.need = 5 - nb
        st.deck = [x for x in range(52) if not dead & BIT[x]]
        CM = CMASK
        idx = [i for i in ALLI if not CM[i] & dead]
        NF = NOFLUSH
        mx = max(scnt)
        crk = CRK
        csk = CSK
        if mx >= 3:
            fs = scnt.index(mx)
            bms = bm[fs]
            csm = CSM[fs]
            FS = FSUIT
            FL = FLUSH
            vals = [FL[bms | csm[i]] if FS[bsk + csk[i]] >= 0 else NF[brk + crk[i]] for i in idx]
        else:
            vals = [NF[brk + crk[i]] for i in idx]
        hv = ev(board + hole)
        st.hv = hv
        # texture features (continuous): paired, monotone, connected, high card
        paired = 1.0 if max(rcnt) >= 2 else 0.0
        mono = ((0.0, 0.0, 0.45, 1.0), (0.0, 0.0, 0.35, 0.8, 1.0), (0.0, 0.0, 0.0, 0.6, 1.0, 1.0))[nb - 3][mx]
        mm = (brm << 1) | ((brm >> 12) & 1)
        best = 0
        for lo in range(10):
            k = bin((mm >> lo) & 31).count("1")
            if k > best:
                best = k
        if nb == 3:
            conn = 1.0 if best >= 3 else (0.3 if best == 2 else 0.0)
        else:
            conn = 1.0 if best >= 4 else (0.6 if best == 3 else (0.2 if best == 2 else 0.0))
        rs = sorted((x >> 2 for x in board), reverse=True)
        high = _clamp((rs[0] - 6) / 6.0, 0.0, 1.0)
        st.paired = paired
        st.wet = min(1.0, 0.6 * mono + 0.6 * conn)
        st.cb = _clamp(0.58 + 0.12 * paired + 0.14 * high - 0.25 * mono - 0.22 * conn, 0.12, 0.85)
        if nb < 5:
            # draws are ranked as if they were made hands of comparable value
            top, mid, low = rs[0], rs[1], rs[-1]
            if nb == 3:
                dv = (0, (1 << 20) | (low << 16), (1 << 20) | (mid << 16) | 0xFFFF, (1 << 20) | (top << 16),
                      (2 << 20) - 1, (2 << 20) - 1)
            else:
                dv = (0, 0, (1 << 20) | (low << 16), (1 << 20) | (mid << 16),
                      (1 << 20) | (mid << 16) | 0xFFFF, (1 << 20) | (top << 16))
            fd = FD4
            sd = SDR
            crm = CRM
            sc = [max(v, dv[fd[bsk + csk[i]] + sd[brm | crm[i]]]) for v, i in zip(vals, idx)]
            hi = CCIDX[hole[0] * 52 + hole[1]]
            hsc = max(hv, dv[fd[bsk + csk[hi]] + sd[brm | crm[hi]]])
        else:
            sc = vals
            hsc = hv
        order = sorted(range(len(idx)), key=sc.__getitem__)
        st.idx_s = [idx[k] for k in order]
        ccls = CCLS
        st.cls_s = [ccls[i] for i in st.idx_s]
        st.vals_s = [vals[k] for k in order]
        st.sc_s = [sc[k] for k in order]
        st.hsc = hsc
        n = len(order)
        st.hpct = (bisect_left(st.sc_s, hsc) + bisect_right(st.sc_s, hsc)) / (2.0 * n)
        self.st = st
        return st

    def _equity(self, st, vr, deadline, N):
        """Equity vs sampled villain ranges; exact enumeration on the river."""
        if st.need == 0:
            hv = st.hv
            vs = st.vals_s
            lo = bisect_left(vs, hv)
            hi = bisect_right(vs, hv)
            eq = 1.0
            for ws, cum in vr:
                tot = cum[-1]
                w = cum[lo - 1] if lo else 0.0
                t = (cum[hi - 1] if hi else 0.0) - w
                eq *= (w + 0.5 * t) / tot
            return eq
        rng = self.rng
        ch = rng.choices
        deck = st.deck
        xs = ch(deck, k=N)
        ys = ch(deck, k=N) if st.need == 2 else [52] * N
        idx_s = st.idx_s
        hrk = st.hrk
        hsk = st.hsk
        brk = st.brk
        bsk = st.bsk
        hm = st.hm
        bm = st.bm
        NF = NOFLUSH
        FS = FSUIT
        FL = FLUSH
        rk = RK
        sk = SK
        bit = BIT
        sbit = SBIT
        cmask = CMASK
        crk = CRK
        csk = CSK
        csm = CSM
        wins = 0.0
        cnt = 0
        if len(vr) == 1:
            s1 = ch(idx_s, cum_weights=vr[0][1], k=N)
            for it in range(N):
                x = xs[it]
                y = ys[it]
                i = s1[it]
                if x == y or cmask[i] & (bit[x] | bit[y]):
                    continue
                r2 = rk[x] + rk[y]
                s2 = sk[x] + sk[y]
                f = FS[hsk + s2]
                if f < 0:
                    hv = NF[hrk + r2]
                else:
                    hv = FL[hm[f] | sbit[f][x] | sbit[f][y]]
                f = FS[bsk + s2 + csk[i]]
                if f < 0:
                    vv = NF[brk + r2 + crk[i]]
                else:
                    vv = FL[bm[f] | sbit[f][x] | sbit[f][y] | csm[f][i]]
                if hv > vv:
                    wins += 1.0
                elif hv == vv:
                    wins += 0.5
                cnt += 1
                if not it & 63 and _pc() > deadline:
                    break
        else:
            samp = [ch(idx_s, cum_weights=v[1], k=N) for v in vr]
            for it in range(N):
                x = xs[it]
                y = ys[it]
                if x == y:
                    continue
                used = bit[x] | bit[y]
                r2 = rk[x] + rk[y]
                s2 = sk[x] + sk[y]
                best = -1
                ok = True
                for sv in samp:
                    i = sv[it]
                    m = cmask[i]
                    if m & used:
                        ok = False
                        break
                    used |= m
                    f = FS[bsk + s2 + csk[i]]
                    if f < 0:
                        vv = NF[brk + r2 + crk[i]]
                    else:
                        vv = FL[bm[f] | sbit[f][x] | sbit[f][y] | csm[f][i]]
                    if vv > best:
                        best = vv
                if not ok:
                    continue
                f = FS[hsk + s2]
                if f < 0:
                    hv = NF[hrk + r2]
                else:
                    hv = FL[hm[f] | sbit[f][x] | sbit[f][y]]
                if hv > best:
                    wins += 1.0
                elif hv == best:
                    wins += 0.5
                cnt += 1
                if not it & 31 and _pc() > deadline:
                    break
        if cnt < 8:
            return st.hpct ** len(vr)
        return wins / cnt

    # ========================================================================= layer 1: decisions
    def _act(self, state, t0):
        hn = state["hand_number"]
        if hn != self.prc_hand:
            self.prc_hand = hn
            self.prc = {}
            self.st = None
        self.seat = state["seat"]
        self.button = state["button"]
        c = self._parse(state)
        hole = [CARD[x] for x in state["hole_cards"]]
        board = [CARD[x] for x in state["board"]]
        if not board:
            return self._preflop(state, c, hole)
        return self._postflop(state, c, hole, board, t0)

    def _pf_eq(self, h, r):
        return sum(map(mul, PF_EQ[h], r[1])) / r[2]

    def _preflop(self, state, c, hole):
        me = self.seat
        n = self.n
        bb = state["big_blind"]
        pot = state["pot"]
        tc = state["to_call"]
        legal = state["legal_actions"]
        can_raise = "raise" in legal
        folded = state["folded"]
        stacks = state["stacks"]
        bets = state["bets"]
        h = _cls(hole[0], hole[1])
        pct = PF_PCT[h]
        pos = (me - self.button) % n
        dist = (n - pos) % n
        start = self.start
        R = c.R
        if R == 0:
            limp = c.n_limp
            bbseat = (self.button + 2) % n
            # who may continue and with what range (bridge input): limpers are in already,
            # players behind continue with their measured frequency
            fe = fep = 1.0
            wsum = esum = 0.0
            for s in range(n):
                if s == me or folded[s]:
                    continue
                P = self._prof(s)
                if c.pre_limp[s]:
                    r = self._pre_range(s, c)
                    wgt = 1.0
                else:
                    isbb = s == bbseat
                    wgt = min(0.95, P.cont * (1.5 if isbb else 1.0))
                    fe *= 1.0 - wgt
                    fep *= 1.0 - (0.33 if isbb else 0.22)
                    lo = min(P.p3 * 0.6, 0.06)
                    r = _range(lo, lo + max(P.wcall, 0.04), 0.0)
                wsum += wgt
                esum += wgt * self._pf_eq(h, r)
            eqv = esum / wsum if wsum > 0 else 0.5
            k = max(1, sum(1 for s in range(n) if s != me and not folded[s]))
            loose = wsum / k
            size = (2.5 + limp + (0.5 if pos == 1 else 0.0)) * (1.0 + 1.2 * max(0.0, loose - 0.3))
            if limp:
                size += 1.0
            amount = int(bb * min(size, 12.0))
            if can_raise and wsum >= 0.7 and eqv >= T_OPEN_VALUE + 0.02 * max(0.0, wsum - 1.0):
                return {"action": "raise", "amount": amount}       # value: ahead of what continues
            if pos == 2:
                return {"action": "check"}
            frac = OPEN_SB if pos == 1 else OPEN_FRAC[dist if dist < 7 else 6]
            if limp == 0:
                mult = _clamp(fe / fep, 0.75, 2.2) if fep > 0 else 1.0
                steal = fe * 1.5 * bb > (1.0 - fe) * amount * 0.75 + 2.0   # any-two steal is +EV
                if can_raise and (pct <= min(0.9, frac * mult) or steal):
                    return {"action": "raise", "amount": amount}
                return {"action": "fold"}
            if can_raise and pct <= min(frac, 0.30) * 0.6:
                return {"action": "raise", "amount": amount}
            if (pos <= 1 or dist <= 2) and pct <= 0.5 and (PF_PLAY[h] or pct <= 0.25) and tc <= bb:
                return {"action": "call"}
            return {"action": "fold"}
        # ---- facing a raise: equity vs the raiser's adjusted range against fixed thresholds
        v = c.pre_last
        if v < 0 or v == me or folded[v]:
            v = -1
            for s in range(n):
                if s != me and not folded[s] and (v < 0 or c.pre_rl[s] > c.pre_rl[v]):
                    v = s
        eq = self._pf_eq(h, self._pre_range(v, c))
        nother = 0
        for s in range(n):
            if s != me and s != v and not folded[s] and (c.pre_cl[s] or c.pre_rl[s]):
                e2 = self._pf_eq(h, self._pre_range(s, c))
                eq *= min(1.0, e2 ** 0.85 + 0.06)
                nother += 1
        po = tc / float(pot + tc)
        risk = tc / float(start)
        pen = VAR_C * risk * risk if risk > 0.10 else 0.0
        mystack = stacks[me]
        if tc >= 0.35 * start or tc >= mystack or (c.pre_sh[v] and tc >= 0.25 * start):
            # facing a shove: pure pot odds + variance penalty
            if eq >= po + pen + 0.01:
                return {"action": "call"}
            return {"action": "fold"}
        cur = c.cur
        # who acts after us postflop? in position if no live opponent sits between us and the button
        myo = (me - self.button - 1) % n
        ip = all(folded[s] or s == me or (s - self.button - 1) % n < myo for s in range(n))
        if can_raise and eq >= T_PRE_VALUE + (0.03 if nother else 0.0):
            to = int(cur * (3.0 if ip else 3.6)) + nother * cur
            if to >= 0.4 * start:
                return {"action": "all_in"} if eq >= T_PRE_VALUE + 0.04 else {"action": "call"}
            return {"action": "raise", "amount": to}
        rz = (0.92 if ip else 0.80) * (0.92 if R >= 2 else 1.0)
        play = 0.0
        if tc <= 0.08 * start:
            i, j = divmod(h, 13)
            if i == j:
                play = 0.03
            elif PF_PLAY[h]:
                play = 0.02
            elif i > j and i - j >= 4:
                play = -0.02
        need = po / rz + 0.02 + pen
        if tc > 0.12 * start:
            need = max(need, po + 0.08)
        if eq + play >= need:
            return {"action": "call"}
        return {"action": "fold"}

    def _postflop(self, state, c, hole, board, t0):
        me = self.seat
        n = self.n
        folded = state["folded"]
        stacks = state["stacks"]
        bets = state["bets"]
        pot = state["pot"]
        tc = state["to_call"]
        legal = state["legal_actions"]
        can_raise = "raise" in legal
        button = self.button
        opps = [s for s in range(n) if s != me and not folded[s]]
        if not opps:
            return {"action": "check"} if tc == 0 else {"action": "call"}
        nb = len(board)
        key = (state["hand_number"], nb)
        st = self.st
        if st is None or st.key != key:
            st = self._setup(key, hole, board)
        nv = len(opps)
        # ---- layer 3 + 4: adjusted ranges, then equity
        vinfo = []
        for s in opps:
            P = self._prof(s)
            q, eps, capw = self._post_q(s, c, P, st.wet)
            vinfo.append((q, s, eps, capw, P))
        vinfo.sort(key=lambda t: t[0])
        use = vinfo[:3]
        spent = self.spent
        if spent > 7.5:                                    # time bank nearly gone: table-only play
            eq = st.hpct ** nv
        else:
            vr = [self._vrange(st, s, c, q, eps, capw) for q, s, eps, capw, P in use]
            ek = tuple(id(r) for r in vr)
            eq = st.eqc.get(ek)
            if eq is None:
                N = (0, 560, 360, 250)[len(vr)]
                if spent > 4.0:
                    N = N // 2 if spent < 6.0 else N // 4
                eq = self._equity(st, vr, t0 + 0.0022, N)
                st.eqc[ek] = eq
            if nv > 3:
                eq *= 0.9 ** (nv - 3)
        # ---- layer 1: fixed thresholds on equity
        mystack = stacks[me]
        mybet = bets[me]
        myo = (me - button - 1) % n
        ip = all((s - button - 1) % n < myo for s in opps)
        effv = max(stacks[s] + bets[s] for s in opps)
        eff = min(mystack + mybet, effv)
        spr = (eff - mybet - tc) / float(pot + tc) if pot + tc > 0 else 10.0
        if spr < 0:
            spr = 0.0
        t_commit = 0.50 + 0.22 / (1.0 + math.exp(-(spr - 4.0) / 1.5))   # SPR sigmoid
        river = nb == 5
        rnd = self.rng.random()
        # opponent-aware sizing input: how often do these villains call a medium bet?
        callp = 1.0
        for q, s, eps, capw, P in use:
            callp *= P.fold[1]
        callp = 1.0 - callp ** (1.0 / len(use))            # mean call propensity
        if tc == 0:
            if not can_raise:
                return {"action": "check"}
            lo = state["min_raise_to"]
            mw = MW[nv]
            if eq >= T_VALUE * mw:
                frac = (0.8 if river else 0.7) if ip else 0.75
                if callp > 0.88:
                    frac = 1.25                            # confirmed stations: overbet for value
                elif callp > 0.72:
                    frac *= 1.35                           # stations pay: bet bigger
                elif callp < 0.45:
                    frac *= 0.8
                return self._bet(state, pot, frac, eq, t_commit, mystack, mybet)
            init = c.prev_aggr == me
            thin = (T_THIN if ip else T_THIN_OOP) * mw
            if river:
                thin += 0.04
            if eq >= thin:
                frac = 0.5 if callp < 0.72 else 0.66
                amt = int(pot * frac)
                if amt <= 0.33 * mystack:
                    return {"action": "raise", "amount": mybet + max(amt, lo)}
                return {"action": "check"}
            # bluffs: c-bet / barrel by texture, rare steal; fold equity comes from the model
            if nv <= 2:
                frac = 0.66 if river else (0.4 if st.wet < 0.4 else 0.6)
                po_v = frac / (1.0 + 2.0 * frac)
                b = 0 if po_v < 0.22 else (1 if po_v < 0.31 else 2)
                fe = 1.0
                for q, s, eps, capw, P in use:
                    f = P.fold[b]
                    if c.nr[s]:
                        f *= 0.5
                    fe *= f
                freq = 0.0
                if init:
                    freq = st.cb * (1.0 if nb == 3 else (0.7 if nb == 4 else 0.45))
                elif ip and nb >= 4 and c.prev_nb == 0 and c.st_nb == 0:
                    freq = 0.33                            # rare steal after two streets of checks
                freq *= min(1.6, fe / 0.42)
                if nv == 2:
                    freq *= 0.45
                if not river and eq >= 0.33:
                    freq *= 1.25
                if river and eq >= 0.32:
                    freq = 0.0                             # showdown value: do not turn it into a bluff
                need = frac / (1.0 + frac) - 0.4 * eq
                if freq > 0.0 and fe >= need and rnd < freq:
                    amt = max(int(pot * frac), lo)
                    if amt <= 0.3 * mystack:
                        return {"action": "raise", "amount": mybet + amt}
            return {"action": "check"}
        # ---- facing a bet
        po = tc / float(pot + tc)
        risk = tc / float(self.start)
        pen = VAR_C * risk * risk if risk > 0.10 else 0.0
        sig = 1.0 / (1.0 + math.exp(-(spr - 4.0) / 1.5))
        pen += 0.06 * risk * sig                            # high SPR: demand more to stack off
        allin_call = tc >= mystack
        if can_raise and not allin_call and eq >= (T_VALUE + 0.04 if river else T_VALUE) \
                and (nv == 1 or eq >= 0.82):
            to = mybet + tc + int(0.75 * (pot + tc))
            if to >= 0.55 * (mystack + mybet):
                if eq >= max(t_commit, T_VALUE):
                    return {"action": "all_in"}
                return {"action": "call"}
            return {"action": "raise", "amount": to}
        if river:
            req = po + 0.02 + pen
            if eq >= req:
                return {"action": "call"}
            # near-MDF defence with bluff catchers so that we are not auto-bluffable
            mdf = (pot - tc) / float(pot) if pot > 0 else 0.5
            if eq >= po - 0.05 and st.hpct >= 1.0 - 0.5 * mdf and risk <= 0.35:
                return {"action": "call"}
            return {"action": "fold"}
        m = (0.06 if nb == 3 else 0.05) + (0.0 if ip else 0.02)
        req = max(po + m, T_CALL * math.sqrt(po / 0.3333)) + pen
        if allin_call:
            req = po + 0.02 + pen
        if eq >= req:
            return {"action": "call"}
        return {"action": "fold"}

    def _bet(self, state, pot, frac, eq, t_commit, mystack, mybet):
        lo = state["min_raise_to"]
        amt = int(pot * frac)
        if amt >= 0.6 * mystack:                           # the bet commits us: SPR-aware
            if eq >= t_commit:
                return {"action": "all_in"}
            amt = int(0.33 * mystack)
        to = mybet + amt
        return {"action": "raise", "amount": to if to > lo else lo}


CCIDX = {}
for _i in range(1326):
    CCIDX[CA[_i] * 52 + CB[_i]] = _i
    CCIDX[CB[_i] * 52 + CA[_i]] = _i

try:
    gc.collect()
    gc.freeze()
except Exception:
    pass
