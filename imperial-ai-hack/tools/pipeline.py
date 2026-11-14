#!/usr/bin/env python3
"""Fast JSON pipeline: Desktop round dumps -> hands/ -> one-screen digest.

    python3 tools/pipeline.py              # ingest new Desktop *.json rounds, print digest of new ones
    python3 tools/pipeline.py --all        # digest every round in hands/
    python3 tools/pipeline.py --watch      # poll Desktop every 3 s, process files the moment they land
    python3 tools/pipeline.py --replay v2/bot.py   # also replay each new round through a bot
    python3 tools/pipeline.py --src ~/Downloads --glob 'sat*_r*.json'

Outputs (in out/):
    digest_<round>.md   per-round summary (hero result, opponent table, worst hands)
    field.md            pooled opponent stats across ALL rounds in hands/ (field_stats.py)
    latest.md           the most recent digest, copy-paste friendly for chat
Stdlib only. Files are de-duplicated by content hash (state in out/.seen.json), and a file
that is still being written (invalid JSON / size changing) is skipped until it is stable.
"""
import argparse, glob, hashlib, json, os, shutil, subprocess, sys, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDS, OUT = os.path.join(ROOT, "hands"), os.path.join(ROOT, "out")
SEEN = os.path.join(OUT, ".seen.json")
BB = 20


def sha(p):
    return hashlib.sha1(open(p, "rb").read()).hexdigest()


def load_seen():
    try:
        return json.load(open(SEEN))
    except Exception:
        return {}


def stable_json(p):
    """Return parsed JSON if the file is complete and no longer growing, else None."""
    try:
        s1 = os.path.getsize(p); time.sleep(0.15)
        if s1 != os.path.getsize(p) or s1 == 0:
            return None
        d = json.load(open(p))
        return d if isinstance(d, dict) and "hands" in d else None
    except Exception:
        return None


def ingest(src, pattern):
    """Copy new/changed Desktop rounds into hands/. Returns list of hands/ paths that are new."""
    os.makedirs(HANDS, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    seen, new = load_seen(), []
    for p in sorted(glob.glob(os.path.join(os.path.expanduser(src), pattern))):
        h = sha(p)
        if seen.get(os.path.basename(p)) == h:
            continue
        d = stable_json(p)
        if d is None:
            print("  skip (incomplete / not a round file): " + os.path.basename(p)); continue
        dst = os.path.join(HANDS, os.path.basename(p))
        shutil.copy2(p, dst); seen[os.path.basename(p)] = h; new.append(dst)
    json.dump(seen, open(SEEN, "w"))
    return new


def position(rel, n):
    names = ["BTN", "SB", "BB"] + ["EP%d" % k for k in range(1, n - 4)] + ["HJ", "CO"]
    return names[rel] if rel < len(names) else "?"


def seat_stats(d):
    """VPIP / PFR / 3bet / AF / WTSD / bb100 for every seat in one round."""
    n, H = len(d["players"]), d["hands"]
    S = [defaultdict(float) for _ in range(n)]
    for h in H:
        raises_pf = 0; street = "preflop"; vp = set(); pf = set(); seen_pf = set(); sd = set(); saw_flop = set()
        for ev in h["events"]:
            if ev[0] == "board":
                street = ev[1]; continue
            if ev[0] != "act":
                continue
            _, s, a, _ = ev
            if street == "preflop":
                seen_pf.add(s)
                if a == "raise":
                    raises_pf += 1; vp.add(s); pf.add(s)
                    if raises_pf >= 2: S[s]["3b"] += 1
                elif a == "call":
                    vp.add(s)
                if raises_pf >= 1 and a in ("fold", "call", "raise"): S[s]["f3o"] += 1  # opps to face-raise
            else:
                saw_flop.add(s)
                if a == "raise": S[s]["agg"] += 1
                elif a == "call": S[s]["call"] += 1
        for s in range(n):
            S[s]["hands"] += 1
            S[s]["vpip"] += s in vp; S[s]["pfr"] += s in pf; S[s]["flop"] += s in saw_flop
            S[s]["won"] += h["results"][s]
        for s in (h.get("showdown") or {}):
            S[int(s)]["sd"] += 1
    return S


def digest(path, replay_bot=None, top=8):
    d = json.load(open(path)); H = d["hands"]; hero = d["seat"]; names = d["players"]; N = len(H)
    S = seat_stats(d)
    hero_bb = sum(h["results"][hero] for h in H) / BB / N * 100
    L = ["# %s — hero seat %d (%s), %d hands, **%+.1f bb/100**" % (d["ref"], hero, names[hero], N, hero_bb), ""]
    L += ["| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for s in sorted(range(len(names)), key=lambda i: -S[i]["won"]):
        x = S[s]; hh = x["hands"]
        af = "%.1f" % (x["agg"] / x["call"]) if x["call"] else ("inf" if x["agg"] else "-")
        L.append("| %d%s | %s | %+.0f | %.0f%% | %.0f%% | %.1f%% | %s | %.0f%% |" % (
            s, "*" if s == hero else "", names[s], x["won"] / BB / hh * 100,
            100 * x["vpip"] / hh, 100 * x["pfr"] / hh, 100 * x["3b"] / hh, af,
            100 * x["sd"] / x["flop"] if x["flop"] else 0))
    # hero by position
    pos = defaultdict(list)
    for h in H:
        pos[position((hero - h["button"]) % len(names), len(names))].append(h["results"][hero] / BB)
    L += ["", "**Hero by position (bb/100):** " + ", ".join(
        "%s %+.0f (n=%d)" % (k, sum(v) / len(v) * 100, len(v)) for k, v in sorted(pos.items(), key=lambda kv: sum(kv[1]) / len(kv[1])))]
    # worst / best hero hands
    ranked = sorted(H, key=lambda h: h["results"][hero])
    def line(h):
        hole = " ".join(h["hole"].get(str(hero), [])); b = " ".join(h["board"])
        opp = {names[int(k)]: (v if isinstance(v, str) else " ".join(map(str, v))) for k, v in (h.get("showdown") or {}).items() if int(k) != hero}
        return "- hand %d: %s | board %s | %+.1f bb%s" % (h["n"], hole, b or "-", h["results"][hero] / BB,
                                                     (" | vs " + ", ".join("%s %s" % kv for kv in opp.items())) if opp else "")
    L += ["", "**Biggest losses:**"] + [line(h) for h in ranked[:top]]
    L += ["", "**Biggest wins:**"] + [line(h) for h in ranked[::-1][:top // 2]]
    # who gave / took chips from hero at showdown-ish: net transfer by opponent is not in the
    # data directly, so show who won the pots hero lost.
    taken = defaultdict(int)
    for h in H:
        if h["results"][hero] < 0:
            for s, r in enumerate(h["results"]):
                if s != hero and r > 0: taken[s] += min(r, -h["results"][hero])
    if taken:
        L += ["", "**Chips hero lost into pots won by:** " + ", ".join(
            "%s %.0f bb" % (names[s], v / BB) for s, v in sorted(taken.items(), key=lambda kv: -kv[1])[:4])]
    if replay_bot:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "replay.py"), replay_bot, path],
                           capture_output=True, text=True, timeout=300)
        L += ["", "**Replay through %s:**" % replay_bot, "```", (r.stdout or r.stderr).strip()[-2500:], "```"]
    return "\n".join(L) + "\n"


def run_all(new_paths, replay_bot):
    os.makedirs(OUT, exist_ok=True)
    last = None
    for p in new_paths:
        md = digest(p, replay_bot)
        name = os.path.splitext(os.path.basename(p))[0]
        open(os.path.join(OUT, "digest_%s.md" % name), "w").write(md)
        last = md
        print(md)
    if last:
        open(os.path.join(OUT, "latest.md"), "w").write(last)
    allr = sorted(glob.glob(os.path.join(HANDS, "*.json")))
    if allr:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "field_stats.py")] + allr,
                           capture_output=True, text=True)
        open(os.path.join(OUT, "field.md"), "w").write("# Pooled field stats (%d rounds)\n\n```\n%s\n```\n" % (len(allr), r.stdout))
        print("-> out/field.md updated (%d rounds pooled)" % len(allr))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="~/Desktop"); ap.add_argument("--glob", default="saturday_r*.json")
    ap.add_argument("--all", action="store_true"); ap.add_argument("--watch", action="store_true")
    ap.add_argument("--replay", metavar="BOT"); ap.add_argument("--interval", type=float, default=3.0)
    a = ap.parse_args()
    if a.watch:
        print("watching %s/%s every %.0fs — Ctrl-C to stop" % (a.src, a.glob, a.interval))
        while True:
            new = ingest(a.src, a.glob)
            if new:
                print("new: " + ", ".join(os.path.basename(p) for p in new)); run_all(new, a.replay)
            time.sleep(a.interval)
    new = ingest(a.src, a.glob)
    if a.all:
        new = sorted(glob.glob(os.path.join(HANDS, "*.json")))
    if not new:
        print("nothing new (use --all to re-digest everything in hands/)"); return
    run_all(new, a.replay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
