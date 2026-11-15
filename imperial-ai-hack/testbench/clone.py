"""clone - fast frequency-matching copies of the real teams (testbench).

    import clone
    agent = clone.make_agent(profile_dict, seed)      # profile = json.load(open("profiles/<slug>.json"))
    agent.on_table_start(info); agent.act(state) -> {"action": ..., "amount": ...}; agent.on_hand_end(summary)

The object has exactly the tournament Agent interface. Standard library only (Python 3.9+).

How a clone decides
-------------------
Every decision is first classified into a SPOT by Tracker (the same code profiles.py uses on the real logs,
so a spot means exactly the same thing in the logs and at the table):
  preflop  "pf|<ctx>|<group>"  ctx: unopened, limped, vs_open (first decision of those three is keyed by the
           position group EP/MP/CO/BTN/SB/BB), limper_vs_raise, opener_vs_3bet, cold_vs_3bet, caller_vs_3bet,
           raiser_vs_4bet (group "all"), vs_jam, vs_jam_inv (group = jammer type "tight"/"wild": the last
           jammer's preflop jam rate at this table is < or >= 5% of hands; real teams call wild jammers far
           more often, so the split keeps clones from paying off tight jammers).
  postflop "<street>|agg|hu", "|donk|", "|probe|", "|noagg|" (nothing to call), "<street>|vs_bet|hu|b3" and
           "<street>|xr|hu|b3" (facing one bet, first action / after checking; b1..b5 = the bettor's size
           bucket), "<street>|vs_raise_agg", "<street>|vs_raise_cold".
The profile gives smoothed action probabilities for the spot (field "p").

PREFLOP: the hand's percentile p in a fixed 169-class order (playability-adjusted, 0 = aces, combo-weighted,
exact within a class by a hash draw). At the first decision q = p; later decisions use q = the hand's position
inside the range that took the same earlier actions (the clone knows its own policy), so e.g. "fold 55% to a
3-bet" means the bottom 55% of the clone's opening range in that spot. Regions from the top of q:
jam (top pJ), value raise, passive (call/limp/check), bluff raise (the raise share beta, taken from just below
the passive range), fold. The region edges are cut at the quantiles of the clone's own q in that spot
(profile["policy"]["cdf"], fitted by calibrate.py) because q is not uniform after others acted (card removal:
after five folds the button holds stronger hands); without a fitted CDF the edges are used as they are.

POSTFLOP: strength s in [0, 1] = percentile of the made hand among all holdings on the board (ties half) plus
a draw bonus on the flop/turn (flush/straight draw outs). s is mapped to u = F_spot(s), the CDF of the clone's
own strength in that spot measured by calibrate.py (stored in profile["policy"]["cdf"]; identity if absent),
so that thresholds on u reproduce the profile's frequencies:
  nothing to call : bet if u >= 1 - b*(1-beta) (value) or u < b*beta (bluffs from the bottom); jam share of
                    the size distribution goes to the very top.
  facing a bet    : raise top r*(1-beta_r), call the next c, bluff-raise the next r*beta_r, fold the rest.
Sizes are drawn from the profile's size histogram for the spot with a deterministic hash.

Determinism: all randomness is a hash of (seed, seat, hand_number, street, actions so far in the hand, salt),
so two runs with the same deck and the same history give identical clone decisions.
"""
import bisect

BB = 20
STACK = 2000
JAM_TO = 1000            # a preflop raise to >= 50bb (or an all-in) counts as a jam
STREETS = ("preflop", "flop", "turn", "river")
ST_IDX = {s: i for i, s in enumerate(STREETS)}
RANKS = "23456789TJQKA"
SUITS = "cdhs"
CI = {r + s: i * 4 + j for i, r in enumerate(RANKS) for j, s in enumerate(SUITS)}
POS_GROUP = {"UTG": "EP", "UTG+1": "EP", "UTG+2": "EP", "MP": "MP", "HJ": "MP", "CO": "CO",
             "BTN": "BTN", "SB": "SB", "BB": "BB"}
GROUPS = ("EP", "MP", "CO", "BTN", "SB", "BB")
PF_GROUPED = ("unopened", "limped", "vs_open")
PF_POOLED = ("limper_vs_raise", "opener_vs_3bet", "cold_vs_3bet", "caller_vs_3bet", "raiser_vs_4bet")
PF_JAM = ("vs_jam", "vs_jam_inv")         # keyed by the jammer's type instead of a position group
JAM_TYPES = ("tight", "wild")
WILD_JAM = 0.05                           # a jammer is "wild" when it jams preflop in >= 5% of hands
PF_CTXS = PF_GROUPED + PF_POOLED + PF_JAM
BUCKETS = ("b1", "b2", "b3", "b4", "b5")
BUCKET_EDGES = (0.35, 0.55, 0.8, 1.1)          # bettor's bet / pot before the bet: <=.35, <=.55, <=.8, <=1.1, >1.1
POST_CHECKED = ("agg", "donk", "probe", "noagg")
POST_FACING = ("vs_bet", "xr")
POST_RAISE = ("vs_raise_agg", "vs_raise_cold")

_POS_AFTER_BB = {
    0: [], 1: ["UTG"], 2: ["UTG", "CO"], 3: ["UTG", "HJ", "CO"], 4: ["UTG", "MP", "HJ", "CO"],
    5: ["UTG", "UTG+1", "MP", "HJ", "CO"], 6: ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO"],
}


def positions(n, button, sb_seat, bb_seat):
    """Position labels by seat (identical to hh.positions)."""
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


def bucket(rfrac):
    if rfrac is None:
        return "b3"
    for i, e in enumerate(BUCKET_EDGES):
        if rfrac <= e + 1e-9:
            return BUCKETS[i]
    return BUCKETS[-1]


# ============================================================================ deterministic hashing
_M64 = (1 << 64) - 1


def _mix(x):
    x = (x + 0x9E3779B97F4A7C15) & _M64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _M64
    return x ^ (x >> 31)


def hash_u(seed, seat, hand, street, nacts, salt=0):
    """Uniform [0, 1) from (seed, seat, hand_number, street, actions so far, salt). No shared RNG."""
    x = _mix((seed * 0x100000001B3 + seat) & _M64)
    x = _mix((x ^ (hand * 0x9E3779B1 + street * 0x85EBCA77 + nacts * 0xC2B2AE3D + salt * 0x27D4EB2F)) & _M64)
    return (x >> 11) / 9007199254740992.0


# ============================================================================ preflop hand order
# Index layout: hi*13+lo suited, lo*13+hi offsuit, r*13+r pairs (ranks 0..12 = 2..A).
# _PCT: playability-adjusted position in 1/1000 of all combos (0 = aces) - from tools/zoo_src/_kernel.py.
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


def pf_index(c1, c2):
    a = c1 >> 2
    b = c2 >> 2
    if a < b:
        a, b = b, a
    return a * 13 + b if ((c1 & 3) == (c2 & 3) or a == b) else b * 13 + a


def _class_combos(idx):
    hi, lo = divmod(idx, 13)
    if hi == lo:
        return 6
    return 4 if hi > lo else 12


def _build_pf_intervals():
    order = sorted(range(169), key=lambda i: (_PCT[i], i))
    lo = 0
    iv = [None] * 169
    for i in order:
        k = _class_combos(i)
        iv[i] = (lo / 1326.0, (lo + k) / 1326.0)
        lo += k
    return iv


PF_IV = _build_pf_intervals()          # class index -> [lo, hi) percentile interval (0 = best)


def class_name(idx):
    hi, lo = divmod(idx, 13)
    if hi == lo:
        return RANKS[hi] * 2
    if hi > lo:
        return RANKS[hi] + RANKS[lo] + "s"
    return RANKS[lo] + RANKS[hi] + "o"


def pf_percentile_mid(cards):
    """Mid-point percentile (0 = best) of a two-card hand given as strings, e.g. ('As', 'Kd')."""
    lo, hi = PF_IV[pf_index(CI[cards[0]], CI[cards[1]])]
    return 0.5 * (lo + hi)


# ============================================================================ hand strength on a board
_SHC = {}


def _sh(mask):
    """Top rank of a straight in a 13-bit rank mask, or -1 (the ace also plays low)."""
    v = _SHC.get(mask)
    if v is None:
        m = (mask << 1) | ((mask >> 12) & 1)
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
            if not (mask >> r) & 1 and _sh(mask | (1 << r)) >= 0:
                v += 1
        _SOC[mask] = v
    return v


def _nf_value(cnt):
    """Value (int, higher wins) of the best non-flush 5-card hand from rank counts (5..7 cards)."""
    q = t = -1
    p = []
    s1 = []
    mask = 0
    for r in range(12, -1, -1):
        k = cnt[r]
        if k:
            mask |= 1 << r
            if k == 1:
                s1.append(r)
            elif k == 2:
                p.append(r)
            elif k == 3:
                if t < 0:
                    t = r
                else:
                    p.append(r)
            else:
                q = r
    if q >= 0:
        kick = 0
        for r in range(12, -1, -1):
            if cnt[r] and r != q:
                kick = r
                break
        return (7 << 20) | (q << 16) | (kick << 12)
    if t >= 0 and p:
        return (6 << 20) | (t << 16) | (p[0] << 12)
    h = _sh(mask)
    if h >= 0:
        return (4 << 20) | (h << 16)
    if t >= 0:
        return (3 << 20) | (t << 16) | (s1[0] << 12) | (s1[1] << 8)
    if len(p) >= 2:
        k = s1[0] if s1 else 0
        if len(p) > 2 and p[2] > k:
            k = p[2]
        return (2 << 20) | (p[0] << 16) | (p[1] << 12) | (k << 8)
    if p:
        return (1 << 20) | (p[0] << 16) | (s1[0] << 12) | (s1[1] << 8) | (s1[2] << 4)
    return (s1[0] << 16) | (s1[1] << 12) | (s1[2] << 8) | (s1[3] << 4) | s1[4]


def _flush_value(m):
    h = _sh(m)
    if h >= 0:
        return (8 << 20) | (h << 16)
    rs = [r for r in range(12, -1, -1) if (m >> r) & 1][:5]
    return (5 << 20) | (rs[0] << 16) | (rs[1] << 12) | (rs[2] << 8) | (rs[3] << 4) | rs[4]


_BT = {}


def _board_table(board):
    """(nonflush value by rank pair, flush suit, board suit count/mask, sorted values of all holdings)."""
    key = tuple(sorted(board))
    t = _BT.get(key)
    if t is not None:
        return t
    if len(_BT) > 256:          # boards rarely repeat across hands: keep the cache small (~40 KB per board)
        _BT.clear()
    bcnt = [0] * 13
    bsn = [0, 0, 0, 0]
    bsm = [0, 0, 0, 0]
    for c in board:
        bcnt[c >> 2] += 1
        bsn[c & 3] += 1
        bsm[c & 3] |= 1 << (c >> 2)
    fs = -1
    for s in range(4):
        if bsn[s] >= 3:
            fs = s
    nf = [0] * 169
    for r1 in range(13):
        if bcnt[r1] >= 4:
            continue
        bcnt[r1] += 1
        for r2 in range(r1 + 1):
            if bcnt[r2] >= 4:
                continue
            bcnt[r2] += 1
            v = _nf_value(bcnt)
            nf[r1 * 13 + r2] = v
            nf[r2 * 13 + r1] = v
            bcnt[r2] -= 1
        bcnt[r1] -= 1
    used = set(board)
    deck = [c for c in range(52) if c not in used]
    vals = []
    ap = vals.append
    nd = len(deck)
    if fs < 0:
        for i in range(nd):
            ra13 = (deck[i] >> 2) * 13
            for j in range(i + 1, nd):
                ap(nf[ra13 + (deck[j] >> 2)])
    else:
        need = 5 - bsn[fs]
        fm = bsm[fs]
        for i in range(nd):
            a = deck[i]
            ra = a >> 2
            sa = (a & 3) == fs
            for j in range(i + 1, nd):
                b = deck[j]
                rb = b >> 2
                v = nf[ra * 13 + rb]
                sb = (b & 3) == fs
                if sa + sb >= need:
                    m = fm
                    if sa:
                        m |= 1 << ra
                    if sb:
                        m |= 1 << rb
                    fv = _flush_value(m)
                    if fv > v:
                        v = fv
                ap(v)
    vals.sort()
    t = (nf, fs, bsn, bsm, vals)
    _BT[key] = t
    return t


def hand_value(c1, c2, board):
    nf, fs, bsn, bsm, _ = _board_table(board)
    v = nf[(c1 >> 2) * 13 + (c2 >> 2)]
    if fs >= 0:
        sa = (c1 & 3) == fs
        sb = (c2 & 3) == fs
        if bsn[fs] + sa + sb >= 5:
            m = bsm[fs]
            if sa:
                m |= 1 << (c1 >> 2)
            if sb:
                m |= 1 << (c2 >> 2)
            fv = _flush_value(m)
            if fv > v:
                v = fv
    return v


def made_strength(c1, c2, board):
    """Percentile of the made hand among all two-card holdings on this board (ties count half), 0..1."""
    vals = _board_table(board)[4]
    v = hand_value(c1, c2, board)
    lo = bisect.bisect_left(vals, v)
    hi = bisect.bisect_right(vals, v, lo)
    return (lo + 0.5 * (hi - lo)) / len(vals)


def draw_outs(c1, c2, board):
    """Rough outs of a flush draw (9) and straight draw (8 open-ended / 4 gutshot) using a hole card."""
    if len(board) >= 5:
        return 0
    outs = 0
    sn = [0, 0, 0, 0]
    for c in board:
        sn[c & 3] += 1
    s1 = c1 & 3
    s2 = c2 & 3
    if s1 == s2:
        if sn[s1] == 2:
            outs += 9
    else:
        if sn[s1] == 3 or sn[s2] == 3:
            outs += 9
    bm = 0
    for c in board:
        bm |= 1 << (c >> 2)
    hm = bm | (1 << (c1 >> 2)) | (1 << (c2 >> 2))
    if _sh(hm) < 0:
        a = _souts(hm)
        if a > _souts(bm):
            outs += 8 if a >= 2 else 4
    return outs


def strength(c1, c2, board):
    """Clone strength: made-hand percentile plus a draw bonus on the flop/turn (0..1, 1 = nuts)."""
    s = made_strength(c1, c2, board)
    if len(board) < 5:
        outs = draw_outs(c1, c2, board)
        if outs:
            if outs > 15:
                outs = 15
            left = 52 - 2 - len(board)
            if len(board) == 3:
                e = 1.0 - (1.0 - outs / left) * (1.0 - outs / (left - 1.0))
            else:
                e = outs / left
            s = s + (1.0 - s) * e * 0.9
    return s


def made_category(c1, c2, board):
    return hand_value(c1, c2, board) >> 20


# ============================================================================ hand tracker (spot classifier)
class Tracker:
    """Replays one hand's events and names the spot of the seat to act.

    Feed: post(seat, amt) for the blinds, act(seat, action, amount) with the engine/log convention (raise
    amount = raise-to street total, call amount = chips added), board(street_idx) when a street starts.
    spot(seat) -> key string (see module docstring). Used identically by profiles.py and the clones.
    """
    __slots__ = ("n", "button", "st", "commit", "total", "folded", "posts", "sb", "bb", "grp", "nr", "nl",
                 "opener", "pfa", "raised", "called", "limped", "acted", "checked", "aggs", "agg_prev", "agg_cur",
                 "bet_rfrac", "nacts", "last_rfrac", "last_allin", "jam_rate", "last_jammer")

    def __init__(self, n, button):
        self.n = n
        self.button = button
        self.st = 0
        self.commit = [0] * n
        self.total = [0] * n
        self.folded = [False] * n
        self.posts = 0
        self.sb = -1
        self.bb = -1
        self.grp = None
        self.nr = 0
        self.nl = 0
        self.opener = -1
        self.pfa = -1
        self.raised = [False] * n
        self.called = [False] * n
        self.limped = [False] * n
        self.acted = set()
        self.checked = set()
        self.aggs = set()
        self.agg_prev = -1
        self.agg_cur = -1
        self.bet_rfrac = None
        self.nacts = 0
        self.last_rfrac = None
        self.last_allin = False
        self.jam_rate = None        # optional per-seat preflop jam rate (list), set by the caller
        self.last_jammer = -1

    def post(self, seat, amt):
        self.commit[seat] += amt
        self.total[seat] += amt
        if self.posts == 0:
            self.sb = seat
        elif self.posts == 1:
            self.bb = seat
            pos = positions(self.n, self.button, self.sb, self.bb)
            self.grp = [POS_GROUP.get(p, "MP") for p in pos]
        self.posts += 1

    def board(self, st):
        if st <= self.st:
            return
        a = self.pfa if self.st == 0 else self.agg_cur
        self.agg_prev = a if (a >= 0 and not self.folded[a]) else -1
        self.st = st
        self.commit = [0] * self.n
        self.nr = 0
        self.acted = set()
        self.checked = set()
        self.aggs = set()
        self.agg_cur = -1
        self.bet_rfrac = None

    def act(self, s, a, amt):
        hi = max(self.commit)
        stack = STACK - self.total[s]
        tc = hi - self.commit[s]
        if tc > stack:
            tc = stack
        if a == "raise":
            add = amt - self.commit[s]
            den = sum(self.total) + tc
            rf = (amt - hi) / den if den > 0 else 0.0
            self.last_rfrac = rf
            self.last_allin = add >= stack
            if self.nr == 0 and self.st > 0:
                self.bet_rfrac = rf
            self.nr += 1
            self.aggs.add(s)
            self.agg_cur = s
            if self.st == 0:
                if self.opener < 0:
                    self.opener = s
                self.pfa = s
                self.raised[s] = True
                if add >= stack or amt >= JAM_TO:
                    self.last_jammer = s
        elif a == "call":
            add = amt
            if self.st == 0:
                if self.nr == 0:
                    self.nl += 1
                    self.limped[s] = True
                else:
                    self.called[s] = True
        elif a == "check":
            add = 0
            self.checked.add(s)
        else:
            add = 0
            self.folded[s] = True
        self.commit[s] += add
        self.total[s] += add
        self.acted.add(s)
        self.nacts += 1

    def to_call(self, s):
        tc = max(self.commit) - self.commit[s]
        stack = STACK - self.total[s]
        return tc if tc < stack else stack

    def spot(self, s):
        hi = max(self.commit)
        tc = self.to_call(s)
        if self.st == 0:
            inv = self.raised[s] or self.called[s] or self.limped[s]
            if tc > 0 and hi >= JAM_TO:
                jr = self.jam_rate
                wild = jr is not None and 0 <= self.last_jammer < len(jr) and jr[self.last_jammer] >= WILD_JAM
                return ("pf|vs_jam_inv|" if inv else "pf|vs_jam|") + ("wild" if wild else "tight")
            if self.nr == 0:
                return ("pf|limped|" if self.nl > 0 else "pf|unopened|") + self.grp[s]
            if self.nr == 1:
                if self.limped[s]:
                    return "pf|limper_vs_raise|all"
                return "pf|vs_open|" + self.grp[s]
            if self.raised[s]:
                if self.nr == 2 and self.opener == s:
                    return "pf|opener_vs_3bet|all"
                return "pf|raiser_vs_4bet|all"
            return "pf|caller_vs_3bet|all" if inv else "pf|cold_vs_3bet|all"
        st = STREETS[self.st]
        active = self.n - sum(self.folded)
        hm = "hu" if active <= 2 else "mw"
        if tc <= 0:
            a = self.agg_prev
            if a == s:
                ctx = "agg"
            elif a < 0 or self.folded[a]:
                ctx = "noagg"
            elif a in self.acted:
                ctx = "probe"
            else:
                ctx = "donk"
            return "%s|%s|%s" % (st, ctx, hm)
        if self.nr <= 1:
            return "%s|%s|%s|%s" % (st, "xr" if s in self.checked else "vs_bet", hm, bucket(self.bet_rfrac))
        return "%s|%s" % (st, "vs_raise_agg" if s in self.aggs else "vs_raise_cold")


def parent_keys(key):
    """Fallback chain for a spot key (most specific first), used when a key is missing from a profile or
    has too few calibration samples: drop the size bucket first (the range that reaches a facing-a-bet spot
    does not depend on the size the opponent chose), then hu/mw, then the position group (preflop)."""
    parts = key.split("|")
    out = [key]
    if parts[0] == "pf":
        if parts[2] != "all":
            out.append("pf|%s|all" % parts[1])
    elif len(parts) == 4:
        out.append("%s|%s|%s" % (parts[0], parts[1], parts[2]))
        out.append("%s|%s" % (parts[0], parts[1]))
    elif len(parts) == 3:
        out.append("%s|%s" % (parts[0], parts[1]))
    return out


# ============================================================================ defaults (used only if a profile lacks a spot)
_DEF_PF = {
    "unopened": {"F": 0.75, "P": 0.03, "R": 0.21, "J": 0.01},
    "limped": {"F": 0.6, "P": 0.15, "R": 0.24, "J": 0.01},
    "vs_open": {"F": 0.8, "P": 0.13, "R": 0.06, "J": 0.01},
    "limper_vs_raise": {"F": 0.4, "P": 0.5, "R": 0.08, "J": 0.02},
    "opener_vs_3bet": {"F": 0.55, "P": 0.3, "R": 0.1, "J": 0.05},
    "cold_vs_3bet": {"F": 0.9, "P": 0.06, "R": 0.02, "J": 0.02},
    "caller_vs_3bet": {"F": 0.6, "P": 0.3, "R": 0.05, "J": 0.05},
    "raiser_vs_4bet": {"F": 0.5, "P": 0.3, "R": 0.05, "J": 0.15},
    "vs_jam": {"F": 0.92, "P": 0.08, "R": 0.0, "J": 0.0},
    "vs_jam_inv": {"F": 0.6, "P": 0.4, "R": 0.0, "J": 0.0},
}
_DEF_SIZE_BB = {"2.5": 3, "3.0": 2}
_DEF_SIZE_X = {"3.0": 3, "2.5": 1}
_DEF_BET = {"0.5": 2, "0.65": 2, "1.0": 1}
_DEF_RAISE = {"0.8": 2, "1.0": 1}


def _norm(d, keys):
    tot = sum(max(0.0, float(d.get(k, 0.0))) for k in keys)
    if tot <= 0:
        return None
    return [max(0.0, float(d.get(k, 0.0))) / tot for k in keys]


def _size_table(sz):
    """{label: count} -> (labels list, cumulative probabilities, allin share)."""
    items = [(k, float(v)) for k, v in (sz or {}).items() if float(v) > 0]
    tot = sum(v for _, v in items)
    if tot <= 0:
        return None
    allin = sum(v for k, v in items if k == "allin") / tot
    rest = sorted((k, v) for k, v in items if k != "allin")
    rt = sum(v for _, v in rest)
    labels = []
    cum = []
    acc = 0.0
    for k, v in rest:
        acc += v / rt
        labels.append(float(k))
        cum.append(acc)
    if cum:
        cum[-1] = 1.0
    return (labels, cum, allin)


def _draw(table, u):
    labels, cum, _ = table
    if not labels:
        return None
    return labels[min(bisect.bisect_left(cum, u), len(labels) - 1)]


def cdf_inv(q, u):
    """Inverse of cdf_u: the value at quantile u (linear between the stored quantile points)."""
    m = len(q) - 1
    if u <= 0.0:
        return -1.0          # empty region: nothing is below it
    if u >= 1.0:
        return 2.0           # everything is below it
    x = u * m
    i = int(x)
    f = x - i
    if i >= m:
        return q[m]
    return q[i] + f * (q[i + 1] - q[i])


def cdf_u(q, s, v):
    """Map strength s to u = F(s) with F given by quantile points q[k] at u = k/m (k = 0..m).

    Linear interpolation between quantile points; when s sits on an atom (several equal quantile points)
    the atom is spread uniformly with the hash-uniform v (randomised probability integral transform), so u
    is uniform in the spot even when many hands share one strength (e.g. everyone playing the board)."""
    m = len(q) - 1
    if s < q[0]:
        return 0.0
    if s > q[-1]:
        return 1.0
    i = bisect.bisect_left(q, s)       # q[i-1] < s <= q[i]
    j = bisect.bisect_right(q, s)      # q[j-1] <= s < q[j]
    if j > i:
        lo = max(0.0, (i - 0.5) / m)
        hi = min(1.0, (j - 0.5) / m)
        return lo + (hi - lo) * v
    a = q[i - 1]
    b = q[i]
    return ((i - 1) + (s - a) / (b - a)) / m if b > a else (i - 0.5) / m


# ============================================================================ the agent
class CloneAgent:
    """Tournament-interface agent driven by a profile (see module docstring)."""

    def __init__(self, profile, seed=0):
        self.seed = int(seed) & 0xFFFFFFFF
        self.name = profile.get("team", "clone")
        self.trace = None              # set to a list to record (key, x, u, action) per decision
        self._compile(profile)
        self.seat = 0
        self.n = 0
        self.hn = None
        self.trk = None
        self.hpos = 0
        self.jams = []              # per-seat count of hands with a preflop jam (from on_hand_end histories)
        self.seen = 0

    # ------------------------------------------------------------------ compile the profile
    def _compile(self, prof):
        pre = {}
        for key, cell in (prof.get("spots") or {}).items():
            pre[key] = cell
        self.cells = pre
        pol = prof.get("policy") or {}
        self.cdf = {}
        for key, c in (pol.get("cdf") or {}).items():
            q = c.get("q") if isinstance(c, dict) else c
            if q and len(q) >= 2:
                self.cdf[key] = [float(x) for x in q]
        self.beta_pf = dict(prof.get("bluff", {}).get("preflop", {}))
        self.beta_post = dict(prof.get("bluff", {}).get("postflop", {}))
        adj = pol.get("adjust") or {}
        self.adjust = {k: dict(v) for k, v in adj.items()}
        self._pf_cache = {}
        self._post_cache = {}

    def _cell(self, key):
        for k in parent_keys(key):
            c = self.cells.get(k)
            if c and c.get("p"):
                return k, c
        return None, None

    def _pf_params(self, key):
        r = self._pf_cache.get(key)
        if r is not None:
            return r
        ctx = key.split("|")[1]
        k, cell = self._cell(key)
        p = None
        if cell:
            p = _norm(cell["p"], ("F", "P", "R", "J"))
        if p is None:
            p = _norm(_DEF_PF.get(ctx, _DEF_PF["vs_open"]), ("F", "P", "R", "J"))
        adj = self.adjust.get(key)
        if adj:
            p = _norm({a: max(0.0, p[i] + adj.get(a, 0.0)) for i, a in enumerate(("F", "P", "R", "J"))},
                      ("F", "P", "R", "J")) or p
        sizes = None
        if cell:
            sizes = _size_table(cell.get("sizes"))
        mode = "bb" if ctx in ("unopened", "limped") else "x"
        if sizes is None or not sizes[0]:
            sizes = _size_table(_DEF_SIZE_BB if mode == "bb" else _DEF_SIZE_X)
        beta = float(self.beta_pf.get(ctx, 0.0))
        r = (p, sizes, mode, beta)
        self._pf_cache[key] = r
        return r

    def _post_params(self, key):
        r = self._post_cache.get(key)
        if r is not None:
            return r
        parts = key.split("|")
        ctx = parts[1]
        k, cell = self._cell(key)
        checked = ctx in POST_CHECKED
        acts = ("X", "B") if checked else ("F", "C", "R")
        p = _norm(cell["p"], acts) if cell else None
        if p is None:
            p = [0.6, 0.4] if checked else [0.5, 0.4, 0.1]
        adj = self.adjust.get(key)
        if adj:
            p = _norm({a: max(0.0, p[i] + adj.get(a, 0.0)) for i, a in enumerate(acts)}, acts) or p
        sizes = _size_table(cell.get("sizes")) if cell else None
        if sizes is None or (not sizes[0] and sizes[2] <= 0):
            sizes = _size_table(_DEF_BET if checked else _DEF_RAISE)
        st = parts[0]
        beta = float(self.beta_post.get("%s|%s" % (st, "bet" if checked else "raise"), 0.0))
        r = (p, sizes, beta, checked)
        self._post_cache[key] = r
        return r

    # ------------------------------------------------------------------ interface
    def on_table_start(self, info):
        try:
            self.seat = int(info.get("seat", 0))
            self.n = int(info.get("num_players", 0))
        except Exception:
            pass

    def on_hand_end(self, summary):
        try:
            hist = summary.get("history") or []
            n = len(summary.get("stacks") or []) or self.n
            if len(self.jams) != n:
                self.jams = [0] * n
            done = set()
            for e in hist:
                if (e.get("street") == "preflop" and e.get("action") == "raise" and (e.get("amount") or 0) >= JAM_TO
                        and e.get("seat") not in done):
                    done.add(e["seat"])
                    if 0 <= e["seat"] < n:
                        self.jams[e["seat"]] += 1
            self.seen += 1
        except Exception:
            pass
        return None

    def act(self, state):
        try:
            return self._act(state)
        except Exception:
            try:
                return {"action": "check"} if state.get("to_call", 0) <= 0 else {"action": "fold"}
            except Exception:
                return {"action": "fold"}

    # ------------------------------------------------------------------ internals
    def _new_hand(self, state):
        self.hn = state["hand_number"]
        self.seat = state["seat"]
        self.n = len(state["stacks"])
        self.trk = Tracker(self.n, state["button"])
        if len(self.jams) == self.n:
            # running estimate of every seat's preflop jam rate, shrunk toward ~1.5% for the first hands
            self.trk.jam_rate = [(j + 0.3) / (self.seen + 20.0) for j in self.jams]
        self.hpos = 0
        h = state["hole_cards"]
        self.c1 = CI[h[0]]
        self.c2 = CI[h[1]]
        lo, hi = PF_IV[pf_index(self.c1, self.c2)]
        self.p = lo + (hi - lo) * hash_u(self.seed, self.seat, self.hn, 0, 0, 11)
        self.rng_ = [(0.0, 1.0)]       # preflop range (p-intervals, strongest first)
        self.s_st = -1
        self.s_val = 0.0

    def _sync(self, state):
        trk = self.trk
        hist = state["history"]
        for i in range(self.hpos, len(hist)):
            e = hist[i]
            a = e["action"]
            if a in ("small_blind", "big_blind"):
                trk.post(e["seat"], e["amount"])
                continue
            st = ST_IDX.get(e["street"], 0)
            if st > trk.st:
                trk.board(st)
            trk.act(e["seat"], a, e["amount"])
        self.hpos = len(hist)
        st = ST_IDX.get(state["street"], 0)
        if st > trk.st:
            trk.board(st)

    def _act(self, state):
        if state["hand_number"] != self.hn or self.trk is None or len(state["history"]) < self.hpos:
            self._new_hand(state)
        self._sync(state)
        key = self.trk.spot(self.seat)
        if self.trk.st == 0:
            return self._pre(state, key)
        return self._post(state, key)

    # q <-> p mapping inside the current preflop range (union of p-intervals, strongest first)
    def _q(self):
        tot = 0.0
        pos = None
        for lo, hi in self.rng_:
            if pos is None and lo <= self.p < hi:
                pos = tot + (self.p - lo)
            tot += hi - lo
        if pos is None or tot <= 0:
            return 0.999
        return min(0.999999, pos / tot)

    def _restrict(self, qa, qb):
        tot = sum(hi - lo for lo, hi in self.rng_)
        xa = qa * tot
        xb = qb * tot
        out = []
        acc = 0.0
        for lo, hi in self.rng_:
            w = hi - lo
            a = max(xa, acc)
            b = min(xb, acc + w)
            if b > a:
                out.append((lo + (a - acc), lo + (b - acc)))
            acc += w
        if out:
            self.rng_ = out

    def _raise_to(self, state, to):
        if "raise" not in state["legal_actions"] or state.get("min_raise_to") is None:
            return {"action": "call"} if state["to_call"] > 0 else {"action": "check"}
        lo = state["min_raise_to"]
        hi = state["max_raise_to"]
        to = int(round(to))
        if to < lo:
            to = lo
        if to > hi:
            to = hi
        return {"action": "raise", "amount": to}

    def _passive(self, state):
        return {"action": "call"} if state["to_call"] > 0 else {"action": "check"}

    def _fold(self, state):
        return {"action": "check"} if state["to_call"] <= 0 else {"action": "fold"}

    def _pre(self, state, key):
        p, sizes, mode, beta = self._pf_params(key)
        pF, pP, pR, pJ = p
        if "raise" not in state["legal_actions"]:
            pP += pR + pJ
            pR = pJ = 0.0
        vR = pR * (1.0 - beta)
        bR = pR - vR
        q = self._q()
        e1 = pJ
        e2 = e1 + vR
        e3 = e2 + pP
        e4 = e3 + bR
        Q = self._cdf_q(key)
        if Q:
            # calibrated: the distribution of q in this spot is not uniform (card removal by the players who
            # folded/raised before), so cut at the q-quantiles that give the target frequencies
            e1, e2, e3, e4 = cdf_inv(Q, e1), cdf_inv(Q, e2), cdf_inv(Q, e3), cdf_inv(Q, e4)
        if q < e1:
            act, qa, qb = "J", 0.0, e1
        elif q < e2:
            act, qa, qb = "R", e1, e2
        elif q < e3:
            act, qa, qb = "P", e2, e3
        elif q < e4:
            act, qa, qb = "R", e3, e4
        else:
            act, qa, qb = "F", e4, 1.0
        if self.trace is not None:
            self.trace.append((key, q, q, act))
        if act == "F":
            return self._fold(state)
        self._restrict(qa, qb)
        if act == "P":
            return self._passive(state)
        if act == "J":
            return self._raise_to(state, state.get("max_raise_to") or 0)
        u = hash_u(self.seed, self.seat, self.hn, 0, self.trk.nacts, 23)
        x = _draw(sizes, u) if sizes else None
        if x is None:
            x = 2.5 if mode == "bb" else 3.0
        if mode == "bb":
            to = x * state.get("big_blind", BB)
        else:
            to = x * max(state["bets"])
        return self._raise_to(state, to)

    def _strength(self, state):
        st = self.trk.st
        if st != self.s_st:
            board = [CI[c] for c in state["board"]]
            self.s_val = strength(self.c1, self.c2, board)
            self.s_st = st
        return self.s_val

    def _cdf_q(self, key):
        for k in parent_keys(key):
            q = self.cdf.get(k)
            if q:
                return q
        return None

    def _u(self, key, s):
        q = self._cdf_q(key)
        if not q:
            return s
        return cdf_u(q, s, hash_u(self.seed, self.seat, self.hn, self.trk.st, self.trk.nacts, 37))

    def _post(self, state, key):
        p, sizes, beta, checked = self._post_params(key)
        s = self._strength(state)
        u = self._u(key, s)
        can_raise = "raise" in state["legal_actions"]
        if checked:
            b = p[1]
            top = 1.0 - b * (1.0 - beta)
            bot = b * beta
            if can_raise and (u >= top or u < bot):
                if self.trace is not None:
                    self.trace.append((key, s, u, "B"))
                allin = sizes[2] if sizes else 0.0
                if allin > 0 and u >= 1.0 - b * (1.0 - beta) * allin:
                    return self._raise_to(state, state["max_raise_to"])
                x = _draw(sizes, hash_u(self.seed, self.seat, self.hn, self.trk.st, self.trk.nacts, 29))
                if x is None:
                    return self._raise_to(state, state["max_raise_to"])
                to = max(state["bets"]) + x * (state["pot"] + state["to_call"])
                return self._raise_to(state, to)
            if self.trace is not None:
                self.trace.append((key, s, u, "X"))
            return {"action": "check"}
        pF, pC, pR = p
        if not can_raise:
            pC += pR
            pR = 0.0
        vR = pR * (1.0 - beta)
        bR = pR - vR
        if u >= 1.0 - vR:
            act = "R"
        elif u >= 1.0 - vR - pC:
            act = "C"
        elif u >= 1.0 - vR - pC - bR:
            act = "R"
        else:
            act = "F"
        if self.trace is not None:
            self.trace.append((key, s, u, act))
        if act == "F":
            return self._fold(state)
        if act == "C":
            return self._passive(state)
        allin = sizes[2] if sizes else 0.0
        if allin > 0 and u >= 1.0 - vR * allin:
            return self._raise_to(state, state["max_raise_to"])
        x = _draw(sizes, hash_u(self.seed, self.seat, self.hn, self.trk.st, self.trk.nacts, 31))
        if x is None:
            return self._raise_to(state, state["max_raise_to"])
        hi = max(state["bets"])
        to = hi + x * (state["pot"] + state["to_call"])
        return self._raise_to(state, to)


def make_agent(profile, seed=0):
    """Contract entry point: a fresh tournament-interface agent for one table."""
    return CloneAgent(profile, seed)
