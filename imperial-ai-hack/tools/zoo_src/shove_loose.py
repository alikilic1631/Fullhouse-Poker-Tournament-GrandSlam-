"""Push-or-fold bot: moves all in preflop with the top 40% of hands, folds the rest, and shoves any pair or better after the flop."""
ARCHETYPE = "preflop shove-bot (top 40%)"
TIER = "fish"
LEAK = "Jams 40% of hands for 100bb: call with the top 17-18% (66+, A8s+, ATo+, KTs+, KQo) and print; never raise-fold in front of it, and do not open hands that cannot call its shove when it is still to act."
#@KERNEL core


class Agent(Base):
    SALT = 606
    RANGE = 0.40

    def pre(self, st):
        if self.pct <= self.RANGE:
            return raise_to(st, JAM)
        return check_fold(st)

    def post(self, st):
        tier, _ = self.tier(st)
        if tier >= 1:
            return raise_to(st, JAM)
        return check_fold(st)
