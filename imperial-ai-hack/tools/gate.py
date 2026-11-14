#!/usr/bin/env python3
"""Regression gate: only replace the live bot with a candidate that is measurably better.

    python3 tools/gate.py path/to/new_bot.py                 # vs the current bot.py
    python3 tools/gate.py new_bot.py --baseline v0/bot.py --rounds 30

Checks, in order:
  1. static   : parses as Python 3.12, standard-library imports only, under 150 KB
  2. strength : paired comparison vs the baseline on identical tables in three fields
                (mixed zoo, tough, tight). FAIL if significantly worse anywhere;
                PASS needs a significant gain in at least one field.
  3. timing   : real 10 ms / 10 s limits in subprocesses, then a simulated slower sandbox
                (4 ms / 4 s): no errors, no bank-outs, think time <= 3 s per round.
Exit code 0 only on PASS.
"""
import argparse
import ast
import glob
import os
import statistics
import subprocess
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gauntlet import BB, KIT, ROOT, name_of, play  # noqa: E402

FIELDS = {
    "mixed": None,
    "tough": ["ref_tag", "ref_lag", "tag_charts", "lag", "mc_threshold", "pot_odds", "nit",
              "trapper", "barreler"],
    "tight": ["nit", "tag_charts", "ref_tag", "tight_aggressive", "fit_or_fold", "shove_tight",
              "cbet_fold", "trapper"],
}
LOOSE_TABLE = ["maniac", "station_any", "shove_loose", "lag", "ref_lag", "limp_caller", "barreler"]
STDLIB_OK = set(sys.stdlib_module_names)
BANNED = {"os", "sys", "socket", "subprocess", "threading", "multiprocessing", "urllib",
          "http", "pathlib", "shutil", "ctypes", "asyncio", "signal"}


def static_check(path):
    problems = []
    src = open(path).read()
    size = len(src.encode())
    if size > 150_000:
        problems.append("file is %d bytes (limit here 150,000; hard limit 200,000)" % size)
    try:
        tree = ast.parse(src, feature_version=(3, 12))
    except SyntaxError as e:
        return ["does not parse as Python 3.12: %s" % e], size
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [n.name.split(".")[0] for n in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [(node.module or "").split(".")[0]]
        for m in mods:
            if m not in STDLIB_OK:
                problems.append("imports non-stdlib module %r" % m)
            elif m in BANNED:
                problems.append("imports %r (no files, network or processes in the sandbox)" % m)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("print", "open", "exec", "eval"):
            problems.append("calls %s() at line %d" % (node.func.id, node.lineno))
    if not any(isinstance(n, ast.ClassDef) and n.name == "Agent" for n in tree.body):
        problems.append("no top-level class Agent")
    return problems, size


def strength(cand, base, rounds, seed, jobs):
    zoo = sorted(glob.glob(os.path.join(ROOT, "zoo", "*.py")))
    house = sorted(glob.glob(os.path.join(KIT, "examples", "*.py")))
    out = {}
    with Pool(jobs) as pool:
        for k, (fname, only) in enumerate(FIELDS.items()):
            field = [p for p in zoo + house if only is None or name_of(p) in only]
            jobsl = [(r, [c], field, 8, 1000, seed + k) for r in range(rounds) for c in (cand, base)]
            res = {}
            errs = {cand: 0, base: 0}
            for r, o, _ in pool.map(play, jobsl, chunksize=1):
                for c, st in o.items():
                    res.setdefault(c, {})[r] = st["chips"] / BB / 1000 * 100
                    errs[c] += st["errors"]
            d = [res[cand][r] - res[base][r] for r in range(rounds)]
            out[fname] = (statistics.mean(res[cand].values()), statistics.mean(res[base].values()),
                          statistics.mean(d), statistics.stdev(d) / len(d) ** 0.5, errs[cand])
    return out


def sim(path, opponents, rounds, seed, extra=()):
    cmd = [sys.executable, "local_sim.py", path] + [os.path.join(ROOT, "zoo", o + ".py") for o in opponents]
    cmd += ["--rounds", str(rounds), "--seed", str(seed)] + list(extra)
    txt = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True).stdout
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.startswith("bot ") and i + 1 < len(lines):
            f = lines[i + 1].split()
            return {"bb100": float(f[-5]), "timeouts": int(f[-4]), "errors": int(f[-3]),
                    "bank_out": int(f[-2]), "think": float(f[-1]), "raw": txt}
    return {"bb100": 0.0, "timeouts": -1, "errors": -1, "bank_out": -1, "think": 99.0, "raw": txt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--baseline", default=os.path.join(ROOT, "bot.py"))
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--skip-timing", action="store_true")
    a = ap.parse_args()
    cand, base = os.path.abspath(a.candidate), os.path.abspath(a.baseline)
    fails, gains = [], 0

    problems, size = static_check(cand)
    print("1. static   : %d bytes, %s" % (size, "ok" if not problems else "; ".join(problems)))
    fails += problems

    print("2. strength : %s vs baseline %s, %d paired rounds per field" % (
        os.path.relpath(cand, ROOT), os.path.relpath(base, ROOT), a.rounds))
    for fname, (mc, mb, d, se, errs) in strength(cand, base, a.rounds, a.seed, a.jobs).items():
        z = d / se if se else 0.0
        verdict = "better" if z > 2 else ("WORSE" if z < -2 else "no clear difference")
        print("     %-6s candidate %+8.1f  baseline %+8.1f  diff %+7.1f +- %-5.1f  %s" % (
            fname, mc, mb, d, se, verdict))
        gains += z > 2
        if z < -2:
            fails.append("significantly worse than baseline on the %s field" % fname)
        if errs:
            fails.append("%d exceptions in act()/on_hand_end() on the %s field" % (errs, fname))
    if not gains:
        fails.append("no significant gain over the baseline in any field")

    if not a.skip_timing:
        for label, opp, extra, max_to in (
                ("real limits, house bots", [], (), 1),
                ("real limits, loose table", LOOSE_TABLE, (), 1),
                ("slow sandbox 4 ms / 4 s", LOOSE_TABLE, ("--timeout", "4", "--bank", "4"), 3)):
            s = sim(cand, opp, 5, a.seed, extra)
            ok = s["errors"] == 0 and s["bank_out"] == 0 and 0 <= s["timeouts"] <= max_to and s["think"] <= 3.0
            print("3. timing   : %-26s timeouts %d  errors %d  bank out %d  think %.1f s/rd  %s" % (
                label, s["timeouts"], s["errors"], s["bank_out"], s["think"], "ok" if ok else "FAIL"))
            if not ok:
                fails.append("timing gate failed (%s)" % label)

    if fails:
        print("\nFAIL - keep the baseline:\n  - " + "\n  - ".join(fails))
        sys.exit(1)
    print("\nPASS - the candidate is safe to promote over the baseline.")


if __name__ == "__main__":
    main()
