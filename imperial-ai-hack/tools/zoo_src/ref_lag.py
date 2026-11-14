"""Strong reference 2, a balanced-ish aggressive bot: wide position opens (14% early to 52% on the button), polarised 3-bets with suited bluffs, and after the flop a range-aware equity model - Monte Carlo equity vs a random hand, re-scaled against the share of hands each opponent still holds given his actions and measured frequencies - driving value bets, mixed-frequency bluffs with the betting lead, check-raise traps and a minimum-defence-frequency backstop so it cannot be barrelled off the top of its range."""
ARCHETYPE = "strong reference: balanced-ish aggressive, range-aware equity"
TIER = "strong"
LEAK = "Its bluff frequency follows your measured fold-to-bet: call it down a few times early and the bluffs dry up; it opens wide, so 3-bet it for value in position and it folds most of that range; its range model treats every bet from an unknown player the same, so unusual lines (small donk bets, check-raises with air) cost it chips in the first ~30 hands."
#@KERNEL core mc tracker


class Agent(Base):
    SALT = 1818
    OPEN = {7: 0.14, 6: 0.17, 5: 0.20, 4: 0.25, 3: 0.33, 2: 0.52, 1: 0.44}
    ITERS = 300

    def __init__(self):
        Base.__init__(self)
        self.tr = Tracker(10)
        self._eq = None

    def on_hand_end(self, summary):
        self.tr.update(summary)

    def new_hand(self, st):
        self._eq = None

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
        rnd = self.rng.random
        suited = (self.c1 & 3) == (self.c2 & 3)
        premium = p <= 0.012 or (self.c1 >> 2) + (self.c2 >> 2) == 23      # QQ+ or AK
        if r == 0:
            limp = limpers(st)
            if pos == 2:
                return raise_to(st, (4 + limp) * bb) if p <= 0.16 else CHECK
            f = self.OPEN.get(behind, 0.14)
            if limp > 1:
                f *= 0.8
            left = [(me + k) % n for k in range(1, behind + 1)]
            jb = max(tr.jam_f(s) for s in left)
            if jb > 0.20:
                f = min(f, 0.5 * jb + 0.05)
            if p <= f:
                return raise_to(st, (2.3 + limp) * bb)
            return FOLD
        v = last_raiser(st, "preflop")
        if st["stacks"][v] == 0 or cur >= 1500:
            pj = tr.jam_f(v)
            lim = max(0.027, 0.45 * pj)
            if r >= 2 and pj < 0.08:
                lim = 0.012
            for i in range(n):
                if i != v and i != me and not st["folded"][i] and bets[i] >= cur:
                    lim *= 0.6
            return CALL if (p <= lim or premium) else FOLD
        pv = tr.pfr_f(v)
        ip = (pos - 1) % n > ((v - st["button"]) - 1) % n
        if r == 1:
            callers = 0
            for i in range(n):
                if i != v and bets[i] >= cur:
                    callers += 1
            if premium or p <= max(0.035, 0.24 * pv):
                return raise_to(st, cur * (3.0 if ip else 3.8) + callers * cur)
            if suited and 0.14 < p <= 0.32 and rnd() < (0.16 if ip else 0.10):
                return raise_to(st, cur * 3.0)             # polar 3-bet bluff
            if pos == 2:
                cf = 0.34 if cur <= 3 * bb else 0.20
            elif pos == 1:
                cf = 0.10
            else:
                cf = 0.17 if ip else 0.11
            x = (pv / 0.15) ** 0.5
            cf *= 0.75 if x < 0.75 else 1.8 if x > 1.8 else x
            if cur > 3.5 * bb:
                cf *= 3.5 * bb / cur
            return CALL if p <= cf else FOLD
        loose = pv > 0.30
        if premium or (loose and p <= 0.06):
            if cur >= 22 * bb or r >= 3:
                return raise_to(st, JAM)
            return raise_to(st, 2.3 * cur)
        opened = bets[me] > bb
        if r == 2 and opened and suited and (self.c1 >> 2 == 12 or self.c2 >> 2 == 12) \
                and p > 0.075 and rnd() < 0.12:
            return raise_to(st, 2.2 * cur)                 # ace-blocker 4-bet bluff
        if opened and tc <= 20 * bb and p <= (0.14 if loose else 0.075):
            return CALL
        return FOLD

    # ----------------------------------------------------------- postflop
    def post(self, st):
        me = st["seat"]
        board = [_CI[c] for c in st["board"]]
        tc = st["to_call"]
        pot = st["pot"]
        street = st["street"]
        folded = st["folded"]
        n = len(folded)
        opps = [i for i in range(n) if not folded[i] and i != me]
        no = len(opps)
        tr = self.tr
        rnd = self.rng.random
        k = len(board)
        if self._eq is None or self._eq[0] != k:
            pr = mc_equity(self.c1, self.c2, board, 1, self.ITERS, rnd)
            tier, outs = classify(self.c1, self.c2, board)
            self._eq = (k, pr, tier, outs)
        _, pr, tier, outs = self._eq

        # Share of a random-hand distribution each live opponent can still hold.
        q = {}
        for i in opps:
            q[i] = 1.0
        pfa = agg_seat = -1
        pre_raises = my_prev_aggr = 0
        bet_street = ""
        for h in st["history"]:
            a = h["action"]
            s = h["seat"]
            hs = h["street"]
            if hs == "preflop":
                if a == "raise":
                    pfa = s
                    pre_raises += 1
                    if s in q:
                        w = tr.pfr_f(s) * (1.0 if pre_raises == 1 else 0.4)
                        q[s] = 0.70 + 0.30 * (w if w < 1.0 else 1.0) ** 0.5
                continue
            if a == "raise":
                if hs == street:
                    agg_seat = s
                elif s == me:
                    my_prev_aggr += 1
                if s in q:
                    af = tr.agg_f(s)
                    if bet_street == hs:                   # a raise over a bet: much narrower
                        x = 0.7 * af
                        q[s] *= 0.10 if x < 0.10 else 0.60 if x > 0.60 else x
                    else:
                        x = 1.4 * af
                        q[s] *= 0.30 if x < 0.30 else 0.90 if x > 0.90 else x
                bet_street = hs
            elif a == "call" and s in q:
                x = 1.0 - 0.8 * tr.fold_f(s)
                q[s] *= 0.45 if x < 0.45 else 0.95 if x > 0.95 else x
        river = street == "river"
        flop = street == "flop"
        floor = 0.0 if river else outs * (0.034 if flop else 0.020)
        e = 1.0
        for i in opps:
            qi = q[i]
            ei = (pr - (1.0 - qi)) / qi
            e *= ei if ei > floor else floor
        if e < floor:
            e = floor
        btn = st["button"]
        myo = (me - btn - 1) % n
        ip = True
        for i in opps:
            if (i - btn - 1) % n > myo:
                ip = False

        if tc == 0:
            ff = min(tr.fold_f(i) for i in opps)
            if e >= 0.66:
                if flop and not ip and rnd() < 0.15:
                    return CHECK                           # set up a check-raise
                size = 0.85 if wetness(board) > 0.4 else 0.7
                if (river and e >= 0.85) or ff < 0.30:
                    size = 1.0
                return bet_frac(st, size)
            if e >= 0.52:
                if (no == 1 or flop) and rnd() < 0.65:
                    return bet_frac(st, 0.4)
                return CHECK
            if no <= 2 and ff > 0.30:
                if outs >= 8 and not river and rnd() < 0.75:
                    return bet_frac(st, 0.66)
                lead = pfa == me if flop else my_prev_aggr > 0
                if flop:
                    base = 0.55 if lead else 0.30
                elif river:
                    base = 0.28 if lead else 0.06
                else:
                    base = 0.38 if lead else 0.12
                if no == 2:
                    base *= 0.45
                x = ff / 0.45
                base *= x if x < 1.5 else 1.5
                if tier <= 1 and rnd() < base:
                    return bet_frac(st, 0.5 if flop else 0.8 if river else 0.7)
            return CHECK

        v = agg_seat if agg_seat >= 0 and agg_seat != me else opps[0]
        f = tc / max(1, pot - tc)
        po = tc / (pot + tc)
        stack = st["stacks"][me]
        rs = st["raises_this_street"]
        can_raise = "raise" in st["legal_actions"]
        if e >= 0.75:
            if can_raise and (rs <= 2 or e >= 0.9):
                if stack <= 2.5 * pot or rs >= 2:
                    return raise_to(st, JAM)
                return bet_frac(st, 0.9)
            return CALL
        risk = tc / 2000.0
        if e >= po + 0.03 + 0.15 * risk * risk:
            return CALL
        if outs >= 9 and not river and rs == 1 and can_raise and no == 1 and rnd() < 0.25:
            return bet_frac(st, 0.9)                       # semi-bluff raise
        if rs == 1 and no == 1 and tier >= 2 and tr.agg_f(v) >= 0.30:
            if pr >= 1.0 - 0.45 / (1.0 + f):               # minimum-defence backstop
                return CALL
        return FOLD


build_tables()
