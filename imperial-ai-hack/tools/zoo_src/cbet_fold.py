"""Opens the top 22% from any seat for 3bb, always c-bets two-thirds pot on the flop, then shuts down without top pair and folds to any raise without two pair."""
ARCHETYPE = "c-bet always, fold to raise"
TIER = "medium"
LEAK = "One-and-done: raise its flop c-bet with anything or float and bet when it checks the turn; 3-bet its opens (it folds all but QQ+/AK). Respect a second barrel."
#@KERNEL core


class Agent(Base):
    SALT = 1111

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        tc = st["to_call"]
        if r == 0:
            if p <= 0.22:
                return raise_to(st, (3 + limpers(st)) * bb)
            return check_fold(st)
        if r == 1:
            if p <= 0.03:
                return raise_to(st, 3 * max(st["bets"]))
            if p <= 0.10 and tc <= 4 * bb:
                return CALL
            return check_fold(st)
        return raise_to(st, JAM) if p <= 0.012 else check_fold(st)

    def post(self, st):
        tier, _ = self.tier(st)
        tc = st["to_call"]
        street = st["street"]
        if tc == 0:
            if street == "flop" and last_raiser(st, "preflop") == st["seat"]:
                return bet_frac(st, 0.66)
            return bet_frac(st, 0.66) if tier >= 3 else CHECK
        me = st["seat"]
        i_bet = any(h["seat"] == me and h["action"] == "raise" and h["street"] == street
                    for h in st["history"])
        if i_bet:
            if tier >= 5:
                return raise_to(st, JAM)
            return CALL if tier >= 4 else FOLD
        if tier >= 5:
            return bet_frac(st, 0.8)
        return CALL if tier >= 3 else FOLD
