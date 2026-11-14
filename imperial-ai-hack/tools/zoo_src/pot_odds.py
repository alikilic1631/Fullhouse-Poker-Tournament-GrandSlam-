"""Pure pot-odds caller: estimates its equity against ONE random hand (table preflop, 200-rollout Monte Carlo after the flop) and calls exactly when equity beats the pot odds; bets half pot only above 80% equity, never bluffs."""
ARCHETYPE = "pot-odds bot (equity vs random hand)"
TIER = "fish"
LEAK = "Measures itself against a random hand, not your range: it limps and calls raises with 80% of hands, calls 100bb jams with any above-average hand and pays off bets with bottom pair or ace high. Value bet big and often, never bluff less than an overbet, fold when it bets."
#@KERNEL core mc


class Agent(Base):
    SALT = 1515
    ITERS = 200

    def new_hand(self, st):
        self._eq = None

    def equity(self, st):
        b = st["board"]
        k = len(b)
        if self._eq is None or self._eq[0] != k:
            if k == 0:
                e = _EVR[pf_index(self.c1, self.c2)] / 1000.0
            else:
                e = mc_equity(self.c1, self.c2, [_CI[c] for c in b], 1, self.ITERS, self.rng.random)
            self._eq = (k, e)
        return self._eq[1]

    def pre(self, st):
        e = self.equity(st)
        tc = st["to_call"]
        if tc == 0:
            return bet_frac(st, 0.5) if e >= 0.80 else CHECK
        if e >= 0.90 and st["raises_this_street"] <= 2:
            return bet_frac(st, 0.5)
        return CALL if e >= tc / (st["pot"] + tc) else FOLD

    post = pre


build_tables()
