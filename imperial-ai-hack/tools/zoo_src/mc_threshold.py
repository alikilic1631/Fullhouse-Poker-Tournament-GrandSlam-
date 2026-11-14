"""The quickly written Monte Carlo bot: equity against random hands (one per live opponent, capped at two) and fixed thresholds - raise above 0.70, call when equity beats pot odds, fold otherwise; preflop it raises the top 13% and calls anything whose equity vs a random hand clears the price."""
ARCHETYPE = "Monte Carlo equity vs random + thresholds"
TIER = "medium"
LEAK = "Equity vs random hands over-values weak made hands against betting ranges: it calls two streets with second pair and raises top pair into anything. Value bet thinner and bigger, expect it to fold to very large bets without 60% raw equity, and note it never bluffs or bluff-raises - fold to its raises without a strong hand. Preflop it calls opens with ~65% of hands."
#@KERNEL core mc


class Agent(Base):
    SALT = 1616

    def new_hand(self, st):
        self._eq = None

    def pre(self, st):
        e = _EVR[pf_index(self.c1, self.c2)] / 1000.0
        tc = st["to_call"]
        bb = st["big_blind"]
        r = st["raises_this_street"]
        cur = max(st["bets"])
        if e >= 0.60 and r == 0:
            return raise_to(st, (3 + limpers(st)) * bb)
        if e >= 0.66 and r == 1:
            return raise_to(st, 3 * cur)
        if e >= 0.75 and r >= 2:
            return raise_to(st, JAM)
        if tc == 0:
            return CHECK
        if tc >= 25 * bb:
            return CALL if e >= 0.66 else FOLD
        return CALL if e > tc / (st["pot"] + tc) + 0.06 else FOLD

    def post(self, st):
        b = st["board"]
        nopp = st["folded"].count(False) - 1
        if nopp > 2:
            nopp = 2
        key = (len(b), nopp)
        if self._eq is None or self._eq[0] != key:
            e = mc_equity(self.c1, self.c2, [_CI[c] for c in b], nopp, 200 if nopp == 1 else 150,
                          self.rng.random)
            self._eq = (key, e)
        e = self._eq[1]
        tc = st["to_call"]
        if tc == 0:
            if e > 0.70:
                return bet_frac(st, 0.75)
            if e > 0.55 and nopp == 1:
                return bet_frac(st, 0.5)
            return CHECK
        rs = st["raises_this_street"]
        if e > 0.85 or (e > 0.70 and rs == 1):
            return bet_frac(st, 0.75)
        if tc >= 25 * st["big_blind"] and e < 0.60:
            return FOLD
        return CALL if e > tc / (st["pot"] + tc) else FOLD


build_tables()
