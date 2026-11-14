#!/usr/bin/env python3
"""Analyse a real round downloaded with fetch_hands.py:  python3 tools/real_report.py hands/x.json [--hands N]"""
import json, sys
from collections import defaultdict
BB = 20
def analyse(path, top=18):
    d = json.load(open(path)); H = d["hands"]; hero = d["seat"]; names = d["players"]; n = len(names)
    N = len(H)
    print("\n================ %s  hero seat %d (%s), %d hands, hero %+.1f bb/100" % (d["ref"], hero, names[hero], N, sum(h["results"][hero] for h in H) / BB / N * 100))
    lines = defaultdict(lambda: defaultdict(list)); scen = defaultdict(list); pos = defaultdict(list)
    st = [defaultdict(int) for _ in range(n)]
    losers = []
    for h in H:
        net = h["results"][hero] / BB
        btn = h["button"]; rel = (hero - btn) % n
        P = ["BTN", "SB", "BB"] + ["EP%d" % k for k in range(1, n - 4)] + ["HJ", "CO"]
        pos[P[rel] if rel < len(P) else "?"].append(net)
        seq = []; raises = 0; street = "preflop"; folded = False; flop = False; facing = False
        seen_pf = set(); lvl = 20; first_raiser = None; cbettor = None
        for ev in h["events"]:
            if ev[0] == "board":
                street = ev[1]; facing = False
                if street == "flop": flop = True
                continue
            if ev[0] != "act": continue
            _, seat, a, amt = ev
            s = st[seat]
            if street == "preflop":
                if seat not in seen_pf:
                    seen_pf.add(seat); s["hands"] += 1
                    if a in ("call", "raise"): s["vpip"] += 1
                    if a == "raise": s["pfr"] += 1
                if raises == 0:
                    s["uo_n"] += 1
                    if a == "raise": s["uo_r"] += 1
                    elif a == "call": s["uo_l"] += 1
                elif raises == 1 and lvl < 800:
                    s["fr_n"] += 1
                    if a == "raise": s["fr_r"] += 1
                    elif a == "call": s["fr_c"] += 1
                elif lvl < 800:
                    s["f3_n"] += 1
                    if a == "raise": s["f3_r"] += 1
                    elif a == "call": s["f3_c"] += 1
                if lvl >= 800:
                    s["fs_n"] += 1
                    if a != "fold": s["fs_c"] += 1
                if a == "raise" and amt >= 800: s["shove"] += 1
                if seat == hero:
                    if a == "raise": seq.append(("jam" if amt >= 800 else "") + ("open" if raises == 0 else ("3bet" if raises == 1 else "4bet+")))
                    elif a == "call": seq.append("limp" if raises == 0 else ("callshove" if amt >= 600 else "call"))
                    elif a == "fold": folded = True
                if a == "raise":
                    raises += 1; lvl = amt
                    if first_raiser is None: first_raiser = seat
            else:
                if facing:
                    s["fb_n"] += 1
                    if a == "fold": s["fb_f"] += 1
                    elif a == "raise": s["fb_r"] += 1
                else:
                    s["cb_n"] += 1
                    if a == "raise": s["cb_b"] += 1
                if a == "raise": facing = True
                if seat == hero and a == "fold": folded = True
        if seq:
            res = "folded pre" if (folded and not flop) else ("saw flop" if flop or h.get("showdown") else "won pre")
            lines[" > ".join(seq)][res].append(net)
        sd = bool(h.get("showdown")) and str(hero) in h["showdown"]
        if not seq: key = "no voluntary chips"
        elif not flop and not h.get("showdown"): key = "preflop only: " + ("folded" if folded else "won")
        elif sd: key = "showdown"
        elif folded: key = "postflop: we folded"
        else: key = "postflop: they folded"
        scen[key].append(net)
        losers.append((net, h))
    print("\n%-8s %6s %9s" % ("pos", "hands", "bb/100")); [print("%-8s %6d %+9.1f" % (k, len(v), sum(v) / len(v) * 100)) for k, v in pos.items()]
    print("\n%-28s %6s %9s %10s" % ("outcome", "hands", "bb each", "bb/100")); [print("%-28s %6d %+9.2f %+10.1f" % (k, len(v), sum(v) / len(v), sum(v) / N * 100)) for k, v in sorted(scen.items(), key=lambda kv: sum(kv[1]))]
    print("\n%-24s %5s %8s %8s | %-16s %-16s %-16s" % ("hero preflop line", "hands", "bb each", "bb/100", "won pre", "folded pre", "saw flop"))
    tot = lambda dd: sum(sum(v) for v in dd.values())
    for k in sorted(lines, key=lambda k: tot(lines[k])):
        dd = lines[k]; c = sum(len(v) for v in dd.values())
        cell = lambda key: ("%4d %+7.1f" % (len(dd[key]), sum(dd[key]) / len(dd[key]))) if dd.get(key) else "   -"
        print("%-24s %5d %+8.2f %+8.1f | %-16s %-16s %-16s" % (k, c, tot(dd) / c, tot(dd) / N * 100, cell("won pre"), cell("folded pre"), cell("saw flop")))
    print("\n%-26s %5s %5s %5s %6s %6s | %7s %7s %7s | %8s %7s | %7s %7s" % ("player", "VPIP", "PFR", "limp", "3bet%", "shove%", "vs3b:F", "vs3b:C", "vs3b:R", "callshv", "(n)", "bet%", "foldbet"))
    for i in range(n):
        s = st[i]; hn = max(1, s["hands"])
        pct = lambda a, b: ("%5.0f" % (100 * s[a] / s[b])) if s[b] else "    -"
        f3n = s["f3_n"]
        print("%-26s %5.0f %5.0f %5s %6s %6.1f | %7s %7s %7s | %8s %7d | %7s %7s %s" % (names[i][:26], 100 * s["vpip"] / hn, 100 * s["pfr"] / hn, pct("uo_l", "uo_n"), pct("fr_r", "fr_n"), 100 * s["shove"] / hn,
              ("%5.0f" % (100 * (f3n - s["f3_r"] - s["f3_c"]) / f3n)) if f3n else "    -", pct("f3_c", "f3_n"), pct("f3_r", "f3_n"), pct("fs_c", "fs_n"), s["fs_n"], pct("cb_b", "cb_n"), pct("fb_f", "fb_n"), "<== US" if i == hero else ""))
    losers.sort(key=lambda x: x[0])
    print("\n---- %d biggest losing hands" % top)
    for net, h in losers[:top]:
        btn = h["button"]
        out = []
        for ev in h["events"]:
            if ev[0] == "post": continue
            if ev[0] == "board": out.append("| %s %s |" % (ev[1], " ".join(ev[2][-3:] if ev[1] == "flop" else ev[2][-1:])))
            elif ev[0] == "act":
                tag = "H" if ev[1] == hero else str(ev[1])
                out.append("%s:%s%s" % (tag, {"fold": "f", "check": "x", "call": "c", "raise": "r"}[ev[2]], ev[3] if ev[2] in ("raise", "call") else ""))
        sd = " ".join("%s=%s" % ("H" if k == str(hero) else k, "".join(v)) for k, v in (h.get("showdown") or {}).items())
        print("#%-4d %+7.1fbb hero %s pos=%d | %s || shown: %s" % (h["n"], net, "".join(h["hole"].get(str(hero), [])), (hero - btn) % n, " ".join(out), sd))
if __name__ == "__main__":
    for p in sys.argv[1:]: analyse(p)
