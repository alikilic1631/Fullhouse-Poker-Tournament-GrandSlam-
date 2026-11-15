"""clone_adapt - ADAPTIVE opponent copies for the testbench (opt-in; clone.py stays the static default).

    import clone_adapt as CA
    params = CA.load_params()                                   # adaptive/params.json
    agent = CA.make_agent(profile_dict, seed, params, hero_seat)  # same tournament interface as clone.make_agent

duel.py / simreal.py use it with --adaptive (and --no-hero-level / --adaptive-off LIST for sensitivity checks);
without --adaptive nothing here is used and the static clones (clone.py) play exactly as before. With
null_params() the adaptive agent plays exactly like the static clone (checked bit for bit with duel.py).

Every clone keeps a TableModel of the other seats, updated only from the public hand_end summaries of the
round (history and the cards shown at showdown). On top of clone.CloneAgent it changes four things; every
slope is measured on the real logs by adaptive_fit.py (within one seat in one round, so it is the reaction to
what that seat has done so far, not a style difference between seats), see out/adaptive_fit.txt:

1. Folding facing a single postflop bet (spots <street>|vs_bet|.. and |xr|..) from seat b, bucket k:
       p_F' = p_F + k_bet[street] * (f_b - ref_bet[street][k])               bettor's bet frequency
                  + k_shown[street] * (d_b - ref_shown[street][k])          shown big-bet value (big buckets)
                  + hero_level[street][k]       if b is OUR seat            static calibrated correction
   f_b = b's bet-when-checked-to frequency on that street so far, shrunk to the population (m_bet); d_b = the
   value share (value_hand: top pair or better with a hole card) of b's big bets (> 0.55 pot) shown at showdown
   minus the population share, shrunk (m_shown). Real teams fold less to frequent bettors (k_bet about -0.3 per
   unit of frequency on every street); shown value matters only on the river (k_shown +0.31, flop/turn ~0).
   The references centre the shift on the clones' own population (adaptive_calibrate.py), so the clones' pooled
   fold rates stay on their profiles. Calls and raises are scaled down proportionally; the cut stays on the
   clone's strength scale, so the hands that switch from call to fold are its weakest calls.
   hero_level: real teams fold more to OUR pot-size bets and overbets, and less to our small bets, than these
   mechanisms give, from the first hands of a round on (not learned); adaptive_calibrate.py stores the gap per
   street and size bucket, shrunk by sample size. It is a static assumption about our seat (--no-hero-level).

2. Exploitative 3-betting at the first decision facing a single open (pf|vs_open|<group>), opener o:
       logit(R') = logit(R) + c_team + A_team * max(0, f_o - tau)
   f_o = o's fold-to-3-bet so far as the opener, shrunk to f0 (m3). Fitted per team (penalised logistic);
   only teams with A clearly > 0 that also reproduce their real 3-bet rate against our opens are adaptive
   (FisherMen A 24.7; Resonance Qt, Attention, AAST, Anker 13-14; Gherkers, Anton, Lehman 7-10; two small ones);
   c_team < 0 removes the part of the pooled profile rate that came from exploited openers. The extra 3-bets
   come from just below the calling range (light 3-bets) and a share s_call from the top of the calls.

3. Folding to a 3-bet (pf|opener_vs_3bet|all) from 3-bettor t:
       p_F' = p_F + k3 * (t3_t - ref3)   (+ hero_level fold_to_3bet if t is our seat; calibrated ~0)
   t3_t = t's 3-bet frequency so far (first decisions facing a single open), shrunk to p3 (m). Real openers fold
   much more to rare 3-bettors and much less to frequent ones (k3 about -0.9).

4. Facing a 4-bet after its own 3-bet the clone's range is its value + light 3-bets, strongest first (static
   clones keep only the region the hand fell in), so the light 3-bets fold first; after a widened 3-bet
   (w = adapted / profile 3-bet rate > 1) the continue share is (1 - p_F) / w (the same hands continue), as
   real adaptive teams fold more to our 4-bets than their profile says (FisherMen 89% n 37 vs 80% vs others).

Determinism: decisions still use clone.hash_u(seed, seat, hand, street, actions so far, salt); the TableModel
depends only on the table's history, so two paired runs stay identical until OUR first different action
(duel.py's opponent-determinism check still applies).
Python 3.9+ standard library only.
"""
import json
import math
import os

import clone as CL

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(HERE, "adaptive", "params.json")
BIG_FRAC = 0.55                      # a big bet: first bet of a postflop street of more than 0.55 pot
BIG_BUCKETS = ("b3", "b4", "b5")
STREET_NAMES = ("flop", "turn", "river")


# =============================================================================== hand classification
def board_only_value(board):
    """Value (clone.hand_value scale) of the 5-card board alone."""
    cnt = [0] * 13
    sn = [0, 0, 0, 0]
    sm = [0, 0, 0, 0]
    for c in board:
        cnt[c >> 2] += 1
        sn[c & 3] += 1
        sm[c & 3] |= 1 << (c >> 2)
    v = CL._nf_value(cnt)
    for s in range(4):
        if sn[s] >= 5:
            fv = CL._flush_value(sm[s])
            if fv > v:
                v = fv
    return v


def value_hand(c1, c2, board):
    """True when the two hole cards (clone int encoding) make TOP PAIR OR BETTER on this board with at least
    one hole card: overpair, top pair, two pair with both hole cards, trips/set using a hole card, or a
    straight/flush/full house or better that uses a hole card (on the river: beats the board alone).
    Second pair, underpairs and hands that only play the board are not value."""
    v = CL.hand_value(c1, c2, board)
    cat = v >> 20
    if cat >= 4:
        if len(board) >= 5:
            return v > board_only_value(board)
        return True
    br = [b >> 2 for b in board]
    top = max(br)
    r1 = c1 >> 2
    r2 = c2 >> 2
    m1 = br.count(r1)
    m2 = br.count(r2)
    if r1 == r2:
        return m1 >= 1 or r1 > top                  # set, or overpair
    if m1 >= 2 or m2 >= 2:
        return True                                 # trips with a hole card
    if m1 >= 1 and m2 >= 1:
        return True                                 # two pair with both hole cards
    return (m1 >= 1 and r1 == top) or (m2 >= 1 and r2 == top)


# =============================================================================== what a seat has shown
class TableModel:
    """Per-seat statistics learned from public hand_end summaries of the round (see module docstring).

    sh[s] = [n_flop, v_flop, n_turn, v_turn, n_river, v_river]: big bets of seat s shown at showdown and how
            many were value (per street of the bet);
    f3[s] = [n, folds]: seat s as the opener facing exactly one 3-bet."""

    def __init__(self, n):
        self.n = n
        self.sh = [[0, 0, 0, 0, 0, 0] for _ in range(n)]
        self.f3 = [[0, 0] for _ in range(n)]
        self.ag = [[0, 0, 0, 0, 0, 0] for _ in range(n)]     # checked-to decisions / bets, per postflop street
        self.vp = [[0, 0] for _ in range(n)]                 # hands dealt / voluntarily put money in preflop
        self.sd = [[0, 0] for _ in range(n)]                 # showdowns / showdowns won (any share of the pot)
        self.bw = [[0, 0] for _ in range(n)]                 # shown big bets / of which the bettor won the showdown
        self.t3 = [[0, 0] for _ in range(n)]                 # first decisions facing a single open / 3-bets made
        self.hands = 0

    def _resize(self, n):
        if n != self.n:
            self.__init__(n)

    def learn(self, history, shown, board, n, winners=None):
        """history: engine history list (dicts seat/street/action/amount, blinds included); shown: {seat str:
        [c1, c2]} for the seats that reached showdown; board: final board (strings)."""
        self._resize(n)
        trk = CL.Tracker(n, 0)
        bets = []                       # (seat, street idx) of big first bets
        vpip = set()
        seen_pf = set()
        for e in history:
            a = e.get("action")
            s = e.get("seat")
            if a in ("small_blind", "big_blind"):
                trk.post(s, e.get("amount") or 0)
                continue
            st = CL.ST_IDX.get(e.get("street"), 0)
            if st > trk.st:
                trk.board(st)
            if st == 0:
                if trk.nr == 1 and not (trk.limped[s] or trk.raised[s] or trk.called[s]) and s not in seen_pf:
                    self.t3[s][0] += 1
                    if a == "raise":
                        self.t3[s][1] += 1
                seen_pf.add(s)
                if a in ("fold", "call", "raise", "check") and trk.nr == 2 and trk.opener == s and trk.raised[s]:
                    self.f3[s][0] += 1
                    if a == "fold":
                        self.f3[s][1] += 1
                first_bet = False
                if a in ("call", "raise"):
                    vpip.add(s)
            else:
                first_bet = (a == "raise" and trk.nr == 0)
                if trk.to_call(s) <= 0 and a in ("check", "raise"):
                    self.ag[s][2 * (st - 1)] += 1
                    if a == "raise":
                        self.ag[s][2 * (st - 1) + 1] += 1
            trk.act(s, a, e.get("amount") or 0)
            if first_bet and trk.bet_rfrac is not None and trk.bet_rfrac > BIG_FRAC:
                bets.append((s, st))
        for s in range(n):
            self.vp[s][0] += 1
            if s in vpip:
                self.vp[s][1] += 1
        won = set()
        for w in winners or ():
            try:
                if (w.get("amount") or 0) > 0:
                    won.add(int(w.get("seat")))
            except Exception:
                pass
        if shown and len(shown) >= 2:
            for k in shown:
                s = int(k)
                if 0 <= s < n:
                    self.sd[s][0] += 1
                    if s in won:
                        self.sd[s][1] += 1
        if shown and bets:
            bc = [CL.CI[c] for c in board]
            seen_bw = set()
            for s, st in bets:
                cards = shown.get(str(s))
                if not cards or len(bc) < 2 + st:
                    continue
                v = value_hand(CL.CI[cards[0]], CL.CI[cards[1]], bc[:2 + st])
                row = self.sh[s]
                row[2 * (st - 1)] += 1
                row[2 * (st - 1) + 1] += 1 if v else 0
                if s not in seen_bw:
                    seen_bw.add(s)
                    self.bw[s][0] += 1
                    if s in won:
                        self.bw[s][1] += 1
        self.hands += 1

    def dev(self, s, pi, m):
        """Shrunk deviation of seat s's shown big-bet value share from the population (pi per street)."""
        row = self.sh[s]
        num = 0.0
        cnt = 0
        for k in range(3):
            nk = row[2 * k]
            if nk:
                num += row[2 * k + 1] - pi[k] * nk
                cnt += nk
        return num / (cnt + m) if (cnt + m) > 0 else 0.0

    def fold3(self, s, f0, m):
        n, f = self.f3[s]
        return (f + m * f0) / (n + m) if (n + m) > 0 else f0


def summary_from_hand(Hd):
    """hh.Hand -> (history, shown, board) in the engine's hand_end summary format (for measuring on logs)."""
    hist = [{"seat": Hd.sb, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": Hd.bb, "street": "preflop", "action": "big_blind", "amount": 20}]
    for A in Hd.acts:
        hist.append({"seat": A.seat, "street": CL.STREETS[A.st], "action": A.a, "amount": A.amt})
    shown = {str(s): list(Hd.hole[s]) for s in Hd.went_sd if s in Hd.hole}
    winners = [{"seat": s, "amount": a} for s, a in sorted(Hd.wins.items())]
    return hist, shown, list(Hd.board), winners


# =============================================================================== parameters
def load_params(path=None):
    with open(path or PARAMS_PATH) as fh:
        return json.load(fh)


def _logit(p):
    p = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# =============================================================================== the adaptive agent
class AdaptiveCloneAgent(CL.CloneAgent):
    """clone.CloneAgent + the adaptations of the module docstring (parameters: adaptive/params.json)."""

    def __init__(self, profile, seed=0, params=None, hero_seat=None):
        super().__init__(profile, seed)
        P = params or {}
        fp = P.get("fold") or {}
        self.f_on = bool(fp)
        self.k_bet = list(fp.get("k_bet") or (0.0, 0.0, 0.0))
        self.m_bet = float(fp.get("m_bet", 5))
        self.bet_prior = list(fp.get("bet_prior") or (0.57, 0.53, 0.45))
        self.ref_bet = fp.get("ref_bet") or [[p] * 5 for p in self.bet_prior]
        self.k_shown = list(fp.get("k_shown") or (0.0, 0.0, 0.0))
        self.m_shown = float(fp.get("m_shown", 5))
        self.value_pi = list(fp.get("value_pi") or (0.59, 0.69, 0.73))
        self.ref_shown = fp.get("ref_shown") or [[0.0] * 5 for _ in range(3)]
        self.lo, self.hi = (fp.get("clamp") or (0.02, 0.98))
        tb = P.get("threebet") or {}
        team = (tb.get("teams") or {}).get(self.name) or {}
        self.tb_c = float(team.get("c", 0.0))
        self.tb_A = float(team.get("A", 0.0))
        self.tb_on = bool(team) and (self.tb_A > 0 or self.tb_c != 0)
        self.f0 = float(tb.get("f0", 0.577))
        self.m3 = float(tb.get("m3", 8))
        self.tau = float(tb.get("tau", 0.55))
        self.s_call = float(tb.get("s_call", 0.0))
        f3 = P.get("fold3") or {}
        self.k3 = float(f3.get("k", 0.0))
        self.m3t = float(f3.get("m", 10))
        self.p3 = float(f3.get("p3", 0.075))
        self.ref3 = float(f3.get("ref", 0.13))
        self.union = bool(P.get("union_3bet_range", False))
        self.light_fold = bool(P.get("light_3bet_fold", False))
        self._w3 = (None, 1.0)          # (hand, widening factor of this hand's own 3-bet range vs the profile cell)
        hl = P.get("hero_level") or {}
        self.hero = hero_seat
        self.hl_post = [[float((hl.get(st) or {}).get(b, 0.0)) for b in CL.BUCKETS] for st in STREET_NAMES]
        self.hl_f3 = float(hl.get("fold_to_3bet", 0.0) or 0.0)
        self.model = None
        self.n_adj = [0, 0, 0]          # decisions changed by: postflop fold shift, 3-bet shift, fold-to-3-bet shift

    # ------------------------------------------------------------------ learning
    def on_table_start(self, info):
        super().on_table_start(info)
        if self.n:
            self.model = TableModel(self.n)

    def on_hand_end(self, summary):
        super().on_hand_end(summary)
        try:
            n = len(summary.get("stacks") or []) or self.n
            if self.model is None or self.model.n != n:
                self.model = TableModel(n)
            self.model.learn(summary.get("history") or [], summary.get("shown") or {}, summary.get("board") or [], n,
                             summary.get("winners") or [])
        except Exception:
            pass
        return None

    def _mdl(self):
        if self.model is None or self.model.n != self.n:
            self.model = TableModel(self.n)
        return self.model

    # ------------------------------------------------------------------ preflop
    def _pre(self, state, key):
        p, sizes, mode, beta = self._pf_params(key)
        pF, pP, pR, pJ = p
        ctx = key.split("|")[1]
        vR = pR * (1.0 - beta)
        bR = pR - vR
        w3 = 1.0
        if key == "pf|raiser_vs_4bet|all" and self.light_fold and self._w3[0] == self.hn and self._w3[1] > 1.0:
            # facing a 4-bet after a WIDENED (exploitative) 3-bet: the hands that continue are the same as with the
            # profile's range, so the continue share shrinks by the widening factor (the light 3-bets fold)
            w = self._w3[1]
            pF2 = min(self.hi, 1.0 - (1.0 - pF) / w)
            rest = 1.0 - pF
            sc = (1.0 - pF2) / rest if rest > 1e-9 else 0.0
            pF, pP, pR, pJ = pF2, pP * sc, pR * sc, pJ * sc
            vR = pR * (1.0 - beta)
            bR = pR - vR
        if ctx == "vs_open" and self.tb_on and 0 <= self.trk.opener < self.n:
            # exploitative 3-betting against an opener who has folded a lot to 3-bets this round
            f = self._mdl().fold3(self.trk.opener, self.f0, self.m3)
            R2 = _sigmoid(_logit(pR) + self.tb_c + self.tb_A * max(0.0, f - self.tau)) if pR > 0 else 0.0
            pR0 = pR
            d = R2 - pR
            if d:
                dP = self.s_call * d
                dF = d - dP
                if dP > pP:                     # cannot take more calls than there are
                    dF += dP - pP
                    dP = pP
                if dF > pF:
                    dF = pF
                vR2 = vR + dP                   # the top of the calls become (merged) value 3-bets
                bR2 = bR + dF                   # hands just below the calls become light 3-bets
                if vR2 < 0:
                    bR2 += vR2
                    vR2 = 0.0
                if bR2 < 0:
                    vR2 += bR2
                    bR2 = 0.0
                vR2 = max(0.0, vR2)
                pP = max(0.0, pP - dP)
                pR = vR2 + bR2
                pF = max(0.0, 1.0 - pJ - pP - pR)
                if pR0 > 0:
                    w3 = (vR2 + bR2) / pR0
                vR, bR = vR2, bR2
                self.n_adj[1] += 1
        elif key == "pf|opener_vs_3bet|all" and (self.k3 or self.hl_f3) and 0 <= self.trk.pfa < self.n:
            # fold more to a rare 3-bettor, less to a frequent one (3-bettor = last preflop raiser)
            t = self.trk.pfa
            n3, k3 = self._mdl().t3[t]
            sh = self.k3 * ((k3 + self.m3t * self.p3) / (n3 + self.m3t) - self.ref3)
            if t == self.hero:
                sh += self.hl_f3
            if sh:
                pF2 = min(self.hi, max(self.lo, pF + sh))
                rest = 1.0 - pF
                sc = (1.0 - pF2) / rest if rest > 1e-9 else 0.0
                pF, pP, pR, pJ = pF2, pP * sc, pR * sc, pJ * sc
                vR = pR * (1.0 - beta)
                bR = pR - vR
                self.n_adj[2] += 1
        if "raise" not in state["legal_actions"]:
            pP += pR + pJ
            pR = pJ = 0.0
            vR = bR = 0.0
        q = self._q()
        e1 = pJ
        e2 = e1 + vR
        e3 = e2 + pP
        e4 = e3 + bR
        Q = self._cdf_q(key)
        if Q:
            e1, e2, e3, e4 = CL.cdf_inv(Q, e1), CL.cdf_inv(Q, e2), CL.cdf_inv(Q, e3), CL.cdf_inv(Q, e4)
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
        if act == "R" and ctx == "vs_open":
            self._w3 = (self.hn, w3)
        if act == "R" and self.union and e4 > e3 and e2 > e1:
            # the 3-bet range is value + light 3-bets, strongest first: facing a 4-bet the light ones fold first
            self._restrict_union(((e1, e2), (e3, e4)))
        else:
            self._restrict(qa, qb)
        if act == "P":
            return self._passive(state)
        if act == "J":
            return self._raise_to(state, state.get("max_raise_to") or 0)
        u = CL.hash_u(self.seed, self.seat, self.hn, 0, self.trk.nacts, 23)
        x = CL._draw(sizes, u) if sizes else None
        if x is None:
            x = 2.5 if mode == "bb" else 3.0
        if mode == "bb":
            to = x * state.get("big_blind", CL.BB)
        else:
            to = x * max(state["bets"])
        return self._raise_to(state, to)

    def _restrict_union(self, parts):
        tot = sum(hi - lo for lo, hi in self.rng_)
        out = []
        for qa, qb in parts:
            xa = qa * tot
            xb = qb * tot
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

    # ------------------------------------------------------------------ postflop
    def _fold_shift(self, key):
        parts = key.split("|")
        if len(parts) != 4 or parts[1] not in CL.POST_FACING:
            return 0.0
        b = self.trk.agg_cur
        st = self.trk.st
        if not (0 <= b < self.n) or not (1 <= st <= 3):
            return 0.0
        bi = CL.BUCKETS.index(parts[3])
        m = self._mdl()
        ag = m.ag[b]
        o = ag[2 * (st - 1)]
        k = ag[2 * (st - 1) + 1]
        f = (k + self.m_bet * self.bet_prior[st - 1]) / (o + self.m_bet)
        sh = self.k_bet[st - 1] * (f - self.ref_bet[st - 1][bi])
        if bi >= 2 and self.k_shown[st - 1]:
            sh += self.k_shown[st - 1] * (m.dev(b, self.value_pi, self.m_shown) - self.ref_shown[st - 1][bi])
        if b == self.hero:
            sh += self.hl_post[st - 1][bi]
        return sh

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
                x = CL._draw(sizes, CL.hash_u(self.seed, self.seat, self.hn, self.trk.st, self.trk.nacts, 29))
                if x is None:
                    return self._raise_to(state, state["max_raise_to"])
                to = max(state["bets"]) + x * (state["pot"] + state["to_call"])
                return self._raise_to(state, to)
            if self.trace is not None:
                self.trace.append((key, s, u, "X"))
            return {"action": "check"}
        pF, pC, pR = p
        if self.f_on:
            sh = self._fold_shift(key)
            if sh:
                pF2 = min(self.hi, max(self.lo, pF + sh))
                rest = 1.0 - pF
                sc = (1.0 - pF2) / rest if rest > 1e-9 else 0.0
                pF, pC, pR = pF2, pC * sc, pR * sc
                self.n_adj[0] += 1
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
        x = CL._draw(sizes, CL.hash_u(self.seed, self.seat, self.hn, self.trk.st, self.trk.nacts, 31))
        if x is None:
            return self._raise_to(state, state["max_raise_to"])
        hi = max(state["bets"])
        to = hi + x * (state["pot"] + state["to_call"])
        return self._raise_to(state, to)


def make_agent(profile, seed=0, params=None, hero_seat=None):
    """Contract entry point (adaptive): a fresh agent for one table. params = load_params() (or a variant dict);
    hero_seat = our bot's seat (only used by the optional hero_level block)."""
    return AdaptiveCloneAgent(profile, seed, params, hero_seat)


COMPONENTS = {
    "postflop": "bettor-aware fold shifts facing a single postflop bet (bet frequency and shown value; not the hero level)",
    "shown": "only the shown-big-bet-value part of the postflop shift",
    "hero": "the calibrated static extra fold rate against OUR seat (same as --no-hero-level)",
    "exploit3": "exploitative 3-betting against openers who fold to 3-bets (team c, A)",
    "fold3": "openers folding more to rare 3-bettors and less to frequent ones",
    "union": "3-bet range kept as value + light 3-bets, strongest first",
    "light4": "fewer continues facing a 4-bet after a widened 3-bet",
}


def variant(params, off):
    """A copy of params with the named components (COMPONENTS) switched off (for sensitivity checks)."""
    p = json.loads(json.dumps(params))
    bad = [c for c in off if c not in COMPONENTS]
    if bad:
        raise ValueError("unknown adaptive component(s) %s; known: %s" % (", ".join(bad), ", ".join(sorted(COMPONENTS))))
    for c in off:
        if c == "postflop":
            p.setdefault("fold", {})["k_bet"] = [0.0, 0.0, 0.0]
            p["fold"]["k_shown"] = [0.0, 0.0, 0.0]
        elif c == "shown":
            p.setdefault("fold", {})["k_shown"] = [0.0, 0.0, 0.0]
        elif c == "hero":
            p["hero_level"] = {"note": "switched off"}
        elif c == "exploit3":
            p.setdefault("threebet", {})["teams"] = {}
        elif c == "fold3":
            p.setdefault("fold3", {})["k"] = 0.0
        elif c == "union":
            p["union_3bet_range"] = False
        elif c == "light4":
            p["light_3bet_fold"] = False
    p["components_off"] = sorted(set(off))
    return p


def null_params():
    """Parameters under which the adaptive agent must play exactly like the static clone (regression test)."""
    return {"fold": {}, "threebet": {}, "fold3": {}, "union_3bet_range": False, "hero_level": {}}
