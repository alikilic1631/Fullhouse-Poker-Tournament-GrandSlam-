"""Quick archetype opponents for in-process testing (not shipped)."""
import random
import bot as B

RANKS = "23456789TJQKA"


def pct(hole):
    a, b = B.CARD[hole[0]], B.CARD[hole[1]]
    return B.PCT[B.CLS[B.KID[a * 52 + b]]]


def eq_vs_random(hole, board, rng, n=60, nopp=1):
    h = [B.CARD[c] for c in hole]; bd = [B.CARD[c] for c in board]
    deck = [c for c in range(52) if c not in h and c not in bd]
    w = 0.0
    need = 5 - len(bd)
    for _ in range(n):
        s = rng.sample(deck, need + 2 * nopp)
        full = bd + s[:need]
        hs = B.ev7(h + full)
        best = max(B.ev7(s[need + 2 * i: need + 2 * i + 2] + full) for i in range(nopp))
        w += 1.0 if hs > best else (0.5 if hs == best else 0.0)
    return w / n


def _raise(state, x):
    return {"action": "raise", "amount": int(max(state["min_raise_to"], min(state["max_raise_to"], x)))}


class ShoveBot:
    P = 1.0
    def __init__(self): self.rng = random.Random(1)
    def act(self, s):
        legal = s["legal_actions"]
        if s["street"] == "preflop":
            if pct(s["hole_cards"]) <= self.P:
                return {"action": "all_in"}
            return {"action": "check"} if "check" in legal else {"action": "fold"}
        return {"action": "check"} if "check" in legal else {"action": "call"}


class Shove40(ShoveBot):
    P = 0.40


class Shove4(ShoveBot):
    P = 0.04


class Maniac:
    def __init__(self): self.rng = random.Random(2)
    def act(self, s):
        legal = s["legal_actions"]; r = self.rng.random()
        if "raise" in legal and r < 0.55:
            return _raise(s, max(s["bets"]) + (0.5 + self.rng.random()) * (s["pot"] + s["to_call"]))
        if "check" in legal: return {"action": "check"}
        if r < 0.92: return {"action": "call"}
        return {"action": "fold"}


class Nit:
    def __init__(self): self.rng = random.Random(3)
    def act(self, s):
        legal = s["legal_actions"]
        if s["street"] == "preflop":
            p = pct(s["hole_cards"])
            if p <= 0.05 and "raise" in legal:
                return _raise(s, 3 * max(s["bets"]))
            if p <= 0.10 and s["to_call"] <= 80:
                return {"action": "call"} if "call" in legal else {"action": "check"}
            return {"action": "check"} if "check" in legal else {"action": "fold"}
        e = eq_vs_random(s["hole_cards"], s["board"], self.rng, 40)
        if e > 0.8 and "raise" in legal:
            return _raise(s, max(s["bets"]) + 0.7 * (s["pot"] + s["to_call"]))
        if e > 0.65:
            return {"action": "check"} if "check" in legal else {"action": "call"}
        return {"action": "check"} if "check" in legal else {"action": "fold"}


class Station:
    def act(self, s):
        return {"action": "check" if "check" in s["legal_actions"] else "call"}


class EqBot:
    """Equity vs random hands + thresholds (the typical quickly written bot)."""
    def __init__(self): self.rng = random.Random(4)
    def act(self, s):
        legal = s["legal_actions"]; tc = s["to_call"]; pot = s["pot"]
        nopp = max(1, sum(1 for f in s["folded"] if not f) - 1)
        if s["street"] == "preflop":
            a, b = B.CARD[s["hole_cards"][0]], B.CARD[s["hole_cards"][1]]
            e = B.PF_VS_RANDOM[B.CLS[B.KID[a * 52 + b]]]
            if e > 0.62 and "raise" in legal and s["raises_this_street"] < 2:
                return _raise(s, 3 * max(s["bets"]))
            if e > 0.72 and "raise" in legal:
                return _raise(s, 3 * max(s["bets"]))
            if tc == 0: return {"action": "check"}
            if e > 0.5 and tc <= 0.1 * 2000 or e > 0.66:
                return {"action": "call"}
            return {"action": "fold"}
        e = eq_vs_random(s["hole_cards"], s["board"], self.rng, 60, min(nopp, 2))
        if e > 0.72 and "raise" in legal:
            return _raise(s, max(s["bets"]) + 0.66 * (pot + tc))
        if tc == 0:
            if e > 0.55 and "raise" in legal:
                return _raise(s, 0.5 * pot)
            return {"action": "check"}
        if e > tc / (pot + tc) + 0.08:
            return {"action": "call"}
        return {"action": "fold"}


class LAG:
    """Loose-aggressive but not crazy: opens wide, c-bets a lot, gives up to raises."""
    def __init__(self): self.rng = random.Random(5)
    def act(self, s):
        legal = s["legal_actions"]; tc = s["to_call"]; pot = s["pot"]; r = self.rng.random()
        if s["street"] == "preflop":
            p = pct(s["hole_cards"])
            if p <= 0.35 and "raise" in legal and s["raises_this_street"] == 0:
                return _raise(s, 60 + 20 * sum(1 for b in s["bets"] if b == 20))
            if p <= 0.08 and "raise" in legal:
                return _raise(s, 3 * max(s["bets"]))
            if tc == 0: return {"action": "check"}
            if p <= 0.25 and tc <= 200: return {"action": "call"}
            return {"action": "fold"}
        e = eq_vs_random(s["hole_cards"], s["board"], self.rng, 40)
        if tc == 0:
            if (e > 0.6 or r < 0.5) and "raise" in legal:
                return _raise(s, 0.6 * pot)
            return {"action": "check"}
        if e > 0.85 and "raise" in legal:
            return _raise(s, max(s["bets"]) + 0.8 * (pot + tc))
        if e > 0.5 + 0.3 * tc / (pot + tc): return {"action": "call"}
        return {"action": "fold"}


class Folder:
    def act(self, s):
        return {"action": "check" if "check" in s["legal_actions"] else "fold"}
