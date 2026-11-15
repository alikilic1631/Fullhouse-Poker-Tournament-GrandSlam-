#!/usr/bin/env python3
"""timing.py - run a bot under the official limits, optionally with extra CPU load, and count the misses.

    python3 timing.py --bot ../v10/bot.py --rounds 2                 # official limits, no extra load
    python3 timing.py --bot ../v10/bot.py --rounds 2 --load 6        # same with 6 busy-loop processes running
    python3 timing.py --bot X.py --table "Kojack,AAST,supernut,Red,Anton,SARS"   # clone opponents (when built)
    python3 timing.py --bot X.py --house --seats 8                   # kit house bots, like local_sim.py
    python3 timing.py --bot X.py --ref ../v10/bot.py --rounds 3 --load 6   # candidate AND v10 on identical tables

Local numbers are much faster than the server: the live v10 used 3.18 s of thinking per round on the server
(max 4.27 s, 13 timeouts in 36 rounds, real logs R19-R54) but only ~0.6 s/round here with no extra load and
~1.4 s with --load 6. So judge a candidate RELATIVE to v10: --ref times the reference on the identical tables
right after each round (same opponents, seat, cards, load) and projects the candidate's server think time as
live-v10 think x (candidate think / reference think).

Machinery: the kit's own engine/players.py SubprocessPlayer (what local_sim.py and the tournament use): every
bot runs in its own process (engine/bot_runner.py), 25 ms per decision including the pipe round trip, a 10 s
thinking bank per round; a late answer is auto-played (check, else fold), an empty bank auto-plays every
remaining decision. A thin subclass only (a) adds environment variables for clone opponents
(CLONE_PROFILE=<profile path>, CLONE_SEED) because the kit passes a minimal environment, and (b) records the
dealer-measured time of every decision for percentiles.

Opponents: --opponents auto (default) = clones when testbench/clone_agent.py, clone.py and
profiles/index.json exist (each clone in its own process via clone_agent.py), otherwise the kit house bots
(examples/*.py) as local_sim.py fills empty seats. Table: --table/--table-file names, else --field N clones
sampled per round weighted by hands observed (default 6, a 7-seat table like Sunday); house bots fill
--seats - 1 seats at random.

--load K starts K busy-loop processes (each in its own process group) for the whole run and always kills
them afterwards (try/finally, SIGINT/SIGTERM handlers, atexit; each loop also exits by itself if this
script dies or after --max-load-seconds). The run ends with a check that no child process is left.

Per round it prints and saves (out/timing_<bot>_load<K>.json): our timeouts, errors, bank-outs, think
seconds (sum of dealer-measured decision times, the number local_sim calls 'think s/rd'), bank used, mean /
p50 / p90 / p99 / max decision ms, decisions over 10 / 20 ms, chips, and opponents' timeouts/errors.
Python 3.9+ standard library only.
"""
import argparse
import atexit
import json
import os
import random
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.dirname(ROOT)
KIT = os.path.join(PROJECT, "imperial-ai-hack-pokerbots-kit")
PROFILES_DIR = os.path.join(HERE, "profiles")
INDEX_PATH = os.path.join(PROFILES_DIR, "index.json")
CLONE_AGENT = os.path.join(HERE, "clone_agent.py")
CLONE_PY = os.path.join(HERE, "clone.py")
OUT_DIR = os.path.join(HERE, "out")
OUR_TEAM = "Durahim 1453"
BB = 20

if KIT not in sys.path:
    sys.path.insert(0, KIT)
from engine import FixedHandsTable  # noqa: E402
from engine import players as kit_players  # noqa: E402
from engine.players import SubprocessPlayer  # noqa: E402
import local_sim  # noqa: E402  (the kit's simulator: house bot list, load check)


class TimedPlayer(SubprocessPlayer):
    """The kit's SubprocessPlayer + extra environment variables + per-decision timing record."""

    def __init__(self, bot_path, extra_env=None, label=None, **kw):
        super().__init__(bot_path, **kw)
        self.extra_env = dict(extra_env or {})
        self.label = label or os.path.basename(bot_path)
        self.lat_ms = []

    def _spawn(self):
        # identical to engine/players.py SubprocessPlayer._spawn except for env.update(self.extra_env)
        if self.stderr_path == "inherit":
            stderr = None
        elif self.stderr_path:
            stderr = open(self.stderr_path, "ab")
        else:
            stderr = subprocess.DEVNULL
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1"}
        if os.name == "nt":
            for key in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP"):
                if key in os.environ:
                    env[key] = os.environ[key]
        env.update(self.extra_env)
        self.proc = subprocess.Popen(
            [sys.executable, "-I", kit_players.RUNNER, self.bot_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            cwd=os.path.dirname(self.bot_path), env=env,
            preexec_fn=kit_players._limit_resources if os.name == "posix" else None,
        )
        if stderr not in (None, subprocess.DEVNULL):
            stderr.close()
        self._start_io()

    def act(self, state):
        dead0, bank0, tm0, to0 = self.dead, self.stats.bank_out, self.stats.total_ms, self.stats.timeouts
        out = super().act(state)
        if not dead0 and self.stats.bank_out == bank0:
            self.lat_ms.append(self.stats.total_ms - tm0)
        return out

    def bank_left(self):
        return self.bank


# ---------------------------------------------------------------------------------------- CPU load
_BUSY = r"""
import os, time
ppid = os.getppid()
end = time.time() + %d
n = 0
while True:
    n += 1
    if not n & 0x3FFFF:
        if os.getppid() != ppid or time.time() > end:
            break
"""
_LOAD = []


def start_load(k, max_seconds):
    for _ in range(k):
        p = subprocess.Popen([sys.executable, "-c", _BUSY % max_seconds], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        _LOAD.append(p)
    return list(_LOAD)


def stop_load():
    killed = 0
    for p in _LOAD:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)       # own session: pgid == pid
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    p.kill()
                except Exception:
                    pass
            killed += 1
        try:
            p.wait(timeout=5)
        except Exception:
            pass
    alive = sum(1 for p in _LOAD if p.poll() is None)
    n = len(_LOAD)
    _LOAD.clear()
    return n, killed, alive


def _on_signal(signum, frame):
    raise KeyboardInterrupt("signal %d" % signum)


def child_processes():
    """(pid, command) of processes whose parent is this script (should be none at the end)."""
    try:
        txt = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return None
    me = os.getpid()
    out = []
    for ln in txt.splitlines():
        parts = ln.split(None, 2)
        if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) == me:
            if parts[2:] and parts[2].startswith("ps "):
                continue
            out.append((int(parts[0]), parts[2] if len(parts) > 2 else ""))
    return out


# ---------------------------------------------------------------------------------------- opponents
def slugify(name):
    return re.sub(r"[^a-z0-9]", "_", name.lower())


def clones_available():
    return all(os.path.isfile(p) for p in (CLONE_AGENT, CLONE_PY, INDEX_PATH))


def load_index():
    with open(INDEX_PATH) as fh:
        return json.load(fh)


def resolve_team(index, name):
    key = name.strip()
    if key in index:
        return key
    low = {k.lower(): k for k in index}
    if key.lower() in low:
        return low[key.lower()]
    slugs = {(v.get("slug") or slugify(k)): k for k, v in index.items()}
    for cand in (slugify(key), key):
        if cand in slugs:
            return slugs[cand]
    raise SystemExit("unknown team %r (see profiles/index.json)" % name)


def weighted_sample(rng, names, weights, k):
    pool = [x for x in names if weights.get(x, 0) > 0] or list(names)
    if k > len(pool):
        raise SystemExit("--field %d but only %d teams have profiles" % (k, len(pool)))
    out = []
    for _ in range(k):
        tot = sum(weights.get(x, 1.0) for x in pool)
        u = rng.random() * tot
        acc = 0.0
        for i, x in enumerate(pool):
            acc += weights.get(x, 1.0)
            if u <= acc:
                break
        out.append(pool.pop(i))
    return out


def read_table_file(path):
    with open(path) as fh:
        txt = fh.read()
    try:
        obj = json.loads(txt)
        if isinstance(obj, list):
            return [str(x) for x in obj]
    except ValueError:
        pass
    return [ln.strip() for ln in txt.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


# ---------------------------------------------------------------------------------------- main
# The live bot on the real server (real logs R19-R54, site version 17 = imperial-ai-hack/v10/bot.py, 36 rounds,
# 'round' metadata of hands/saturday_r019..r054.json): think seconds per round mean 3.18, min 2.17, max 4.27;
# 13 timeouts in 36 rounds (9 rounds with >= 1, at most 3); no errors, no bank-outs.
LIVE_V10 = {"rounds": 36, "think_mean_s": 3.18, "think_max_s": 4.27, "timeouts": 13}


def round_config(r, args, kind, index, fixed, house, rng):
    """Opponents (label, file, env), our seat and the deck seed of round r: identical for --bot and --ref."""
    if kind == "clones":
        w = {k: float(v.get("hands", 0) or 0) for k, v in index.items()}
        teams = [k for k in sorted(index) if k != OUR_TEAM and index[k].get("kind", "team") != "pool"]
        opps = list(fixed) if fixed is not None else weighted_sample(rng, teams, w, args.field)
        spec = [(t, CLONE_AGENT, {"CLONE_PROFILE": os.path.join(PROFILES_DIR, (index[t].get("slug") or slugify(t))
                                                                 + ".json"),
                                  "CLONE_SEED": str(args.seed * 1000 + r)}) for t in opps]
        for t, _, env in spec:   # clone_agent.py silently falls back to field.json on a bad path: fail loudly here
            if not os.path.isfile(env["CLONE_PROFILE"]):
                sys.exit("missing profile for %r: %s" % (t, env["CLONE_PROFILE"]))
    else:
        spec = [(os.path.basename(p)[:-3], p, {}) for p in (rng.choice(house) for _ in range(max(1, args.seats - 1)))]
    n = len(spec) + 1
    return {"opps": spec, "seat": (args.seed + r) % n, "deck_seed": rng.random()}


def play_round(r, path, label, cfg, args, show):
    opp_players = [TimedPlayer(fp, extra_env=env, label=lab, timeout_ms=args.timeout, bank_ms=args.bank * 1000)
                   for lab, fp, env in cfg["opps"]]
    hero = TimedPlayer(path, label=label, timeout_ms=args.timeout, bank_ms=args.bank * 1000,
                       stderr_path="inherit" if show else None)
    seat = cfg["seat"]
    players = list(opp_players)
    players.insert(seat, hero)
    la0 = os.getloadavg()[0]
    t0 = time.time()
    try:
        res = FixedHandsTable(players, hands=args.hands, seed=cfg["deck_seed"]).play()
    finally:
        for p in players:
            p.close()
    wall = time.time() - t0
    st = hero.stats
    lat = hero.lat_ms
    return {
        "bot": label, "round": r + 1, "seat": seat, "seats": len(players), "opponents": [p.label for p in opp_players],
        "chips": res["chips"][seat], "bb100": res["chips"][seat] / BB / args.hands * 100,
        "decisions": st.decisions, "timeouts": st.timeouts, "errors": st.errors,
        "error_samples": st.error_samples, "bank_out": st.bank_out,
        "think_s": st.total_ms / 1000.0, "bank_used_s": args.bank - max(0.0, hero.bank_left()),
        "mean_ms": st.total_ms / max(1, len(lat)), "p50_ms": pct(lat, 0.50), "p90_ms": pct(lat, 0.90),
        "p99_ms": pct(lat, 0.99), "max_ms": st.max_ms, "over_10ms": sum(1 for x in lat if x > 10),
        "over_20ms": sum(1 for x in lat if x > 20), "wall_s": wall, "loadavg_start": la0,
        "loadavg_end": os.getloadavg()[0],
        "opp_timeouts": {p.label: p.stats.timeouts for p in opp_players if p.stats.timeouts},
        "opp_errors": {p.label: p.stats.errors for p in opp_players if p.stats.errors},
        "opp_bank_out": {p.label: p.stats.bank_out for p in opp_players if p.stats.bank_out},
        "opp_max_ms": max((p.stats.max_ms for p in opp_players), default=0.0),
    }


def print_round(rec, nrounds):
    print("%-10s round %d/%d seat %d/%d: timeouts %d errors %d bank-out %d | think %.2fs (bank used %.2fs) | "
          "ms mean %.2f p50 %.2f p90 %.2f p99 %.2f max %.1f | >10ms %d >20ms %d | %+d chips | %.0fs wall,"
          " load %.1f->%.1f" % (rec["bot"][:10], rec["round"], nrounds, rec["seat"], rec["seats"], rec["timeouts"],
                                rec["errors"], rec["bank_out"], rec["think_s"], rec["bank_used_s"], rec["mean_ms"],
                                rec["p50_ms"], rec["p90_ms"], rec["p99_ms"], rec["max_ms"], rec["over_10ms"],
                                rec["over_20ms"], rec["chips"], rec["wall_s"], rec["loadavg_start"],
                                rec["loadavg_end"]), flush=True)
    if rec["error_samples"]:
        print("  first error:\n" + rec["error_samples"][0])
    if rec["opp_timeouts"] or rec["opp_errors"]:
        print("  opponents: timeouts %s errors %s" % (rec["opp_timeouts"], rec["opp_errors"]))


def summarise(rounds):
    tot = {k: sum(x[k] for x in rounds) for k in ("decisions", "timeouts", "errors", "bank_out", "over_10ms",
                                                   "over_20ms")}
    return dict(tot, rounds=len(rounds), worst_think_s=max((x["think_s"] for x in rounds), default=0.0),
                mean_think_s=sum(x["think_s"] for x in rounds) / max(1, len(rounds)),
                worst_bank_used_s=max((x["bank_used_s"] for x in rounds), default=0.0),
                max_ms=max((x["max_ms"] for x in rounds), default=0.0),
                worst_p99_ms=max((x["p99_ms"] for x in rounds), default=0.0),
                verdict="OK" if not (tot["timeouts"] or tot["errors"] or tot["bank_out"]) else "PROBLEMS")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog="See the module docstring for details.")
    ap.add_argument("--bot", required=True, help="bot file to time (class Agent)")
    ap.add_argument("--ref", help="also time this reference bot (e.g. ../v10/bot.py) on the identical tables right "
                                  "after each round, and project the server think time from v10's live numbers")
    ap.add_argument("--rounds", type=int, default=2, help="rounds (tables) to play, default 2")
    ap.add_argument("--hands", type=int, default=1000, help="hands per round (tournament: 1000)")
    ap.add_argument("--load", type=int, default=0, help="extra busy-loop processes during the run (default 0)")
    ap.add_argument("--opponents", choices=["auto", "clones", "house"], default="auto",
                    help="auto = clones when clone_agent.py/clone.py/profiles exist, else kit house bots")
    ap.add_argument("--house", action="store_true", help="same as --opponents house")
    ap.add_argument("--table", help="comma-separated team names (clone opponents)")
    ap.add_argument("--table-file", help="file with one team name per line (clone opponents)")
    ap.add_argument("--field", type=int, default=6, help="clone opponents sampled per round (default 6)")
    ap.add_argument("--seats", type=int, default=7, help="table size with house bots (default 7)")
    ap.add_argument("--timeout", type=float, default=25.0, help="ms per decision (tournament: 25)")
    ap.add_argument("--bank", type=float, default=10.0, help="thinking bank seconds per round (tournament: 10)")
    ap.add_argument("--seed", type=int, default=1, help="seed for seating, field sampling and cards")
    ap.add_argument("--max-load-seconds", type=int, default=0,
                    help="hard stop for the busy loops (default: 600 s per round + 300)")
    ap.add_argument("--show-prints", action="store_true", help="let our bot's print() output through")
    ap.add_argument("--name", help="output name: out/timing_<name>.json")
    args = ap.parse_args()

    bot = os.path.abspath(args.bot)
    ref = os.path.abspath(args.ref) if args.ref else None
    for pth in [bot] + ([ref] if ref else []):
        if not os.path.isfile(pth):
            sys.exit("no such bot file: %s" % pth)
    kind = "house" if args.house else args.opponents
    if kind == "auto":
        kind = "clones" if clones_available() else "house"
    if kind == "clones" and not clones_available():
        sys.exit("clone opponents need %s, %s and %s" % (CLONE_AGENT, CLONE_PY, INDEX_PATH))

    def label(pth):
        b = os.path.basename(pth)
        return os.path.basename(os.path.dirname(pth)) if b == "bot.py" else b[:-3]
    lab = label(bot)
    rlab = label(ref) if ref else None
    if ref and rlab == lab:
        rlab = "ref_" + rlab
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", args.name or "%s_load%d" % (lab, args.load))

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass
    atexit.register(stop_load)

    for pth in [bot] + ([ref] if ref else []):
        local_sim.check_loads(pth)        # the kit's own "does it start" check (exits with the traceback)
    index = load_index() if kind == "clones" else None
    fixed = None
    if kind == "clones":
        if args.table:
            fixed = [resolve_team(index, x) for x in args.table.split(",") if x.strip()]
        elif args.table_file:
            fixed = [resolve_team(index, x) for x in read_table_file(args.table_file)]
        if fixed is not None and not 1 <= len(fixed) <= 7:
            sys.exit("give 1-7 opponents")
    house = [os.path.join(local_sim.HERE, p) for p in local_sim.HOUSE]
    rng = random.Random(args.seed)
    max_load_s = args.max_load_seconds or (600 * args.rounds * (2 if ref else 1) + 300)

    print("timing %s%s: %d rounds x %d hands, %s opponents, limits %.0f ms / %.0f s bank, extra load %d busy "
          "processes, %d cores, load avg %.1f" % (lab, (" (+ reference %s on identical tables)" % rlab) if ref else "",
                                                  args.rounds, args.hands, kind, args.timeout, args.bank, args.load,
                                                  os.cpu_count() or 0, os.getloadavg()[0]))
    rounds = {lab: [], rlab: []} if ref else {lab: []}
    t_all = time.time()
    load_report = (0, 0, 0)
    try:
        if start_load(args.load, max_load_s):
            time.sleep(0.5)
        for r in range(args.rounds):
            cfg = round_config(r, args, kind, index, fixed, house, rng)
            for pth, lb in [(bot, lab)] + ([(ref, rlab)] if ref else []):
                rec = play_round(r, pth, lb, cfg, args, args.show_prints and pth == bot)
                rounds[lb].append(rec)
                print_round(rec, args.rounds)
    finally:
        load_report = stop_load()
    left = child_processes()
    summ = {lb: summarise(rs) for lb, rs in rounds.items()}
    for lb, sm in summ.items():
        print("\n%s | %s: %d rounds, %d decisions: timeouts %d, errors %d, bank-outs %d | think s/round worst %.2f "
              "mean %.2f (bank %.0f s) | worst p99 %.2f ms, max %.1f ms, >10ms %d, >20ms %d" % (
                  sm["verdict"], lb, sm["rounds"], sm["decisions"], sm["timeouts"], sm["errors"], sm["bank_out"],
                  sm["worst_think_s"], sm["mean_think_s"], args.bank, sm["worst_p99_ms"], sm["max_ms"],
                  sm["over_10ms"], sm["over_20ms"]), end="")
    print()
    projection = None
    if ref and summ[rlab]["mean_think_s"] > 0:
        ratio = summ[lab]["mean_think_s"] / summ[rlab]["mean_think_s"]
        projection = {"think_ratio_vs_ref": ratio, "projected_server_think_mean_s": LIVE_V10["think_mean_s"] * ratio,
                      "projected_server_think_worst_s": LIVE_V10["think_max_s"] * ratio,
                      "assumes_ref_is_live_v10": True, "live_v10": LIVE_V10}
        print("think ratio %s / %s = %.2f -> if %s is the live v10: projected server think %.1f s/round mean, %.1f s "
              "worst (live v10: %.2f mean, %.2f worst, %d timeouts in %d rounds; bank %.0f s)" % (
                  lab, rlab, ratio, rlab, projection["projected_server_think_mean_s"],
                  projection["projected_server_think_worst_s"], LIVE_V10["think_mean_s"], LIVE_V10["think_max_s"],
                  LIVE_V10["timeouts"], LIVE_V10["rounds"], args.bank))
    print("cleanup: %d load processes started, %d alive after cleanup | child processes left: %s | %.0fs" % (
        load_report[0], load_report[2], (len(left) if left is not None else "unknown"), time.time() - t_all))
    if left:
        print("leftover children:", left)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "timing_%s.json" % name)
    with open(path, "w") as fh:
        json.dump({"config": {"bot": bot, "ref": ref, "rounds": args.rounds, "hands": args.hands, "load": args.load,
                              "opponents": kind, "table": args.table, "field": args.field, "seats": args.seats,
                              "timeout_ms": args.timeout, "bank_s": args.bank, "seed": args.seed,
                              "cores": os.cpu_count(), "created": time.strftime("%Y-%m-%d %H:%M:%S")},
                   "summary": summ[lab], "verdict": summ[lab]["verdict"], "ref_summary": summ.get(rlab),
                   "projection": projection, "live_v10": LIVE_V10,
                   "cleanup": {"load_processes": load_report[0], "load_alive_after_cleanup": load_report[2],
                               "child_processes_left": (len(left) if left is not None else None)},
                   "rounds": rounds[lab], "ref_rounds": rounds.get(rlab)}, fh, indent=1)
    print("saved %s" % path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as exc:
        print("\ninterrupted (%s); load processes and bot processes were stopped" % (exc,))
        sys.exit(130)
