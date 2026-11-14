#!/usr/bin/env python3
"""Feed real tournament hands back through a bot and see what it would do in the same spots.

    python3 tools/replay.py v2/bot.py hands/saturday_r002.json            # summary
    python3 tools/replay.py v2/bot.py hands/saturday_r002.json --show 966 440 738

The bot sees every real hand in order (so its opponent model learns exactly what the live
bot saw) and is asked for a decision at each of our real decision points. Later decisions in
a hand follow the real trajectory even if the bot would have deviated earlier.
"""
import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict

BB = 20


def load(path):
    spec = importlib.util.spec_from_file_location("rbot_%d" % abs(hash(path)), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Agent


def replay(bot_path, log_path):
    d = json.load(open(log_path))
    hero, n = d["seat"], len(d["players"])
    agent = load(os.path.abspath(bot_path))()
    if hasattr(agent, "on_table_start"):
        agent.on_table_start({"seat": hero, "num_players": n, "hands": len(d["hands"]), "starting_stack": 2000,
                              "stacks_reset_each_hand": True, "small_blind": 10, "big_blind": 20,
                              "betting": "no_limit", "raise_cap": None})
    out = []
    for h in d["hands"]:
        stacks = list(h["start_stacks"])
        bets = [0] * n
        folded = [False] * n
        contrib = 0
        history = []
        street = "preflop"
        board = []
        current = 0
        min_inc = h["bb"]
        raises = 0
        npost = 0
        pre_raises = 0
        decisions = []
        for ev in h["events"]:
            if ev[0] == "post":
                _, seat, amt = ev
                stacks[seat] -= amt
                bets[seat] += amt
                contrib += amt
                current = max(current, bets[seat])
                history.append({"seat": seat, "street": "preflop",
                                "action": "small_blind" if npost == 0 else "big_blind", "amount": amt})
                npost += 1
            elif ev[0] == "board":
                street = ev[1]
                board = list(ev[2])
                bets = [0] * n
                current = 0
                min_inc = h["bb"]
                raises = 0
            elif ev[0] == "act":
                _, seat, a, amt = ev
                to_call = min(current - bets[seat], stacks[seat])
                if seat == hero:
                    max_to = bets[seat] + stacks[seat]
                    others = any(not folded[j] and stacks[j] > 0 for j in range(n) if j != seat)
                    can_raise = max_to > current and others
                    state = {
                        "type": "act", "hand_number": h["n"], "street": street, "seat": seat, "button": h["button"],
                        "hole_cards": list(h["hole"][str(hero)]), "board": list(board), "small_blind": h["sb"],
                        "big_blind": h["bb"], "blind_level": 0, "pot": contrib, "stacks": list(stacks),
                        "bets": list(bets), "folded": list(folded), "to_call": to_call,
                        "min_raise_to": min(current + min_inc, max_to) if can_raise else None,
                        "max_raise_to": max_to if can_raise else None,
                        "legal_actions": (["fold", "call"] if to_call > 0 else ["check"]) + (["raise"] if can_raise else []),
                        "betting": "no_limit", "raise_cap": None, "raises_this_street": raises,
                        "history": list(history),
                    }
                    try:
                        r = agent.act(state) or {}
                    except Exception as e:  # noqa: BLE001
                        r = {"action": "EXC:" + repr(e)}
                    na = str(r.get("action"))
                    namt = r.get("amount")
                    if na == "all_in":
                        na, namt = ("raise", max_to) if can_raise else ("call", to_call)
                    if na == "raise":
                        if not can_raise:
                            na = "call" if to_call > 0 else "check"
                        else:
                            namt = max(state["min_raise_to"], min(int(namt or 0), max_to))
                    if na == "call" and to_call <= 0:
                        na = "check"
                    if na == "check" and to_call > 0:
                        na = "fold"
                    decisions.append({"invested": h["start_stacks"][seat] - stacks[seat],
                                      "street": street, "pre_raises": pre_raises, "to_call": to_call, "pot": contrib,
                                      "old": (a, amt), "new": (na, namt if na == "raise" else (to_call if na == "call" else 0)),
                                      "first": not decisions, "stack": stacks[seat], "bet": bets[seat]})
                if a == "fold":
                    folded[seat] = True
                elif a == "call":
                    stacks[seat] -= amt
                    bets[seat] += amt
                    contrib += amt
                elif a == "raise":
                    add = amt - bets[seat]
                    stacks[seat] -= add
                    bets[seat] = amt
                    contrib += add
                    if amt - current >= min_inc:
                        min_inc = amt - current
                    current = amt
                    raises += 1
                    if street == "preflop":
                        pre_raises += 1
                history.append({"seat": seat, "street": street, "action": a, "amount": amt})
        shown = {k: h["hole"][k] for k in (h.get("showdown") or {}) if k in h["hole"]}
        winners = [{"seat": e[1], "amount": e[2], "hand": e[3]} for e in h["events"] if e[0] == "win"]
        if hasattr(agent, "on_hand_end"):
            agent.on_hand_end({"type": "hand_end", "hand_number": h["n"], "board": list(h["board"]), "shown": shown,
                               "winners": winners, "stacks": [2000 + r for r in h["results"]], "history": history})
        out.append((h, decisions))
    return d, out


def kind(dec, which):
    a, amt = dec[which]
    if dec["street"] == "preflop":
        if a == "raise":
            base = "open" if dec["pre_raises"] == 0 else ("3bet" if dec["pre_raises"] == 1 else "4bet+")
            return ("jam-" if amt >= 800 else "") + base
        if a == "call":
            return "limp" if dec["pre_raises"] == 0 and dec["to_call"] <= BB else ("call-shove" if dec["to_call"] >= 600 else "call")
        return a
    if a == "raise":
        frac = (amt - dec["bet"] - dec["to_call"]) / max(1, dec["pot"] + dec["to_call"])
        size = "small" if frac < 0.5 else ("mid" if frac <= 1.05 else "overbet")
        return ("raise-" if dec["to_call"] > 0 else "bet-") + size
    return a


def fmt_hand(h, hero, n):
    out = []
    for ev in h["events"]:
        if ev[0] == "board":
            out.append("| %s |" % " ".join(ev[2][-3:] if ev[1] == "flop" else ev[2][-1:]))
        elif ev[0] == "act":
            out.append("%s:%s%s" % ("H" if ev[1] == hero else str(ev[1]),
                                    {"fold": "f", "check": "x", "call": "c", "raise": "r"}[ev[2]],
                                    ev[3] if ev[2] in ("raise", "call") else ""))
    sd = " ".join("%s=%s" % (k, "".join(v)) for k, v in h["hole"].items() if k != str(hero))
    return "#%d %+.1fbb %s pos%d | %s%s" % (h["n"], h["results"][hero] / BB, "".join(h["hole"][str(hero)]),
                                           (hero - h["button"]) % n, " ".join(out), (" || " + sd) if sd else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--show", nargs="*", type=int, default=[])
    a = ap.parse_args()
    for log in a.logs:
        d, res = replay(a.bot, log)
        hero, n = d["seat"], len(d["players"])
        N = len(res)
        first = defaultdict(lambda: [0, 0])
        allk = defaultdict(lambda: [0, 0])
        agree = tot = 0
        for h, decs in res:
            for dec in decs:
                ko, kn = kind(dec, "old"), kind(dec, "new")
                tag = dec["street"] if dec["street"] != "preflop" else "preflop"
                allk[(tag, ko)][0] += 1
                allk[(tag, kn)][1] += 1
                if dec["first"]:
                    first[ko][0] += 1
                    first[kn][1] += 1
                tot += 1
                agree += dec["old"][0] == dec["new"][0]
        print("\n==== %s on %s: %d hands, %d decision points, same action type as the live bot %.0f%%" % (
            os.path.relpath(a.bot), d["ref"], N, tot, 100.0 * agree / max(1, tot)))
        print("first preflop decision (%% of hands)      live bot   this bot")
        for k in sorted(first, key=lambda k: -first[k][0] - first[k][1]):
            print("  %-34s %7.1f %10.1f" % (k, 100.0 * first[k][0] / N, 100.0 * first[k][1] / N))
        print("all decision points (counts)             live bot   this bot")
        for k in sorted(allk, key=lambda k: (["preflop", "flop", "turn", "river"].index(k[0]), -allk[k][0] - allk[k][1])):
            print("  %-8s %-25s %7d %10d" % (k[0], k[1], allk[k][0], allk[k][1]))
        same = [0, 0.0]
        foldd = [0, 0.0, 0.0]
        other = defaultdict(lambda: [0, 0.0])
        for h, decs in res:
            net = h["results"][hero] / BB
            div = next((x for x in decs if x["old"][0] != x["new"][0]), None)
            if div is None:
                same[0] += 1
                same[1] += net
            elif div["new"][0] == "fold":
                foldd[0] += 1
                foldd[1] += net
                foldd[2] -= div["invested"] / BB
            else:
                k = "%s: live %s -> this bot %s" % (div["street"], kind(div, "old"), kind(div, "new"))
                other[k][0] += 1
                other[k][1] += net
        print("counterfactual read (bb, over %d hands):" % N)
        print("  same line as the live bot      : %4d hands, live result %+8.1f" % (same[0], same[1]))
        print("  this bot folds where live did not: %4d hands, live result %+8.1f -> this bot %+8.1f  (%+.1f bb/100)" % (
            foldd[0], foldd[1], foldd[2], (foldd[2] - foldd[1]) / N * 100))
        tot_o = sum(v[1] for v in other.values())
        print("  other deviations (outcome unknown): %4d hands, live result %+8.1f" % (sum(v[0] for v in other.values()), tot_o))
        for k, v in sorted(other.items(), key=lambda kv: kv[1][1])[:10]:
            print("      %-52s %4d hands, live %+8.1f" % (k, v[0], v[1]))
        for num in a.show:
            for h, decs in res:
                if h["n"] == num:
                    print("\n" + fmt_hand(h, hero, n))
                    for dec in decs:
                        print("    %-8s pot %5d to_call %5d   live: %-14s this bot: %s" % (
                            dec["street"], dec["pot"], dec["to_call"], "%s %s" % dec["old"], "%s %s" % dec["new"]))


if __name__ == "__main__":
    main()
