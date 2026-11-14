"""Loose-aggressive: opens 22-60% by position, 3-bets light, c-bets and barrels most boards, floats and semi-bluff-raises draws."""
ARCHETYPE = "loose-aggressive"
TIER = "medium"
LEAK = "Too many bluffs and too many light calls: 3-bet and 4-bet it for value wider, call down with top pair and good second pair, value bet big; do not try to bluff it off pairs."
#@KERNEL core


class Agent(Base):
    SALT = 303
    OPEN = {7: 0.22, 6: 0.25, 5: 0.28, 4: 0.33, 3: 0.42, 2: 0.60, 1: 0.50}

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        pos, behind = self.spot(st)
        tc = st["to_call"]
        rnd = self.rng.random
        if r == 0:
            limp = limpers(st)
            if pos == 2:
                return raise_to(st, (4 + limp) * bb) if p <= 0.25 else CHECK
            if p <= self.OPEN.get(behind, 0.22):
                return raise_to(st, (2.5 + limp) * bb)
            return FOLD
        cur = max(st["bets"])
        if r == 1:
            if p <= 0.07 or (p <= 0.25 and rnd() < 0.18):
                return raise_to(st, 3 * cur)
            if p <= 0.30 and tc <= 5 * bb:
                return CALL
            return FOLD
        if p <= 0.03:
            return raise_to(st, JAM)
        if p <= 0.10 and tc <= 22 * bb:
            return CALL
        if r == 2 and p <= 0.30 and rnd() < 0.06:
            return raise_to(st, 2.4 * cur)
        return FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        street = st["street"]
        nopp = st["folded"].count(False) - 1
        rnd = self.rng.random
        if tc == 0:
            if tier >= 2 or (outs >= 8 and street != "river"):
                return bet_frac(st, 0.7)
            if nopp <= 2:
                freq = 0.6 if street == "flop" else 0.45 if street == "turn" else 0.35
                if rnd() < freq:
                    return bet_frac(st, 0.66)
            return CHECK
        f = tc / max(1, st["pot"] - tc)
        rs = st["raises_this_street"]
        if tier >= 4:
            return bet_frac(st, 0.9) if rs <= 2 else CALL
        if tier == 3:
            if rs == 1 and rnd() < 0.2:
                return bet_frac(st, 0.8)
            return CALL if f <= 1.5 else FOLD
        if tier == 2:
            lim = 0.8 if street != "river" else 0.6
            return CALL if f <= lim else FOLD
        if outs >= 8 and street != "river":
            if rs == 1 and rnd() < 0.35:
                return bet_frac(st, 0.8)
            return CALL if f <= 1.0 else FOLD
        if tier == 1 and street != "river" and f <= 0.7:
            return CALL
        if street == "flop" and rs == 1 and nopp == 1 and rnd() < 0.10:
            return bet_frac(st, 0.9)
        return FOLD
