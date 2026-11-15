#!/usr/bin/env python3
"""duel.py - paired duplicate comparison of a candidate bot against the live bot.

    python3 duel.py --cand ../candidates/X/bot.py --field 6                   # 20 seeds x 7 seats (default)
    python3 duel.py --cand X.py --table "Kojack,AAST,supernut,Red,Anton,SARS" --seeds 20 --rotations 7
    python3 duel.py --cand X.py --table-file my_table.txt --hands 1000 --procs 6
    python3 duel.py --cand X.py --opponents zoo --table "lag,nit,maniac,station_cap,tag_charts,ref_tag"
    python3 duel.py --list                       # opponents available in the active source
    python3 duel.py --selftest                   # determinism check of the bench itself (~1 min)
    python3 duel.py --cand X.py --table-file tables/sunday.txt --adaptive   # ADAPTIVE clones (clone_adapt.py,
                                                 # adaptive/params.json); without --adaptive: the static clones as before

How a duel is played
  For every deal seed s (--seeds, starting at --seed0) one table is built: our bot plus the opponents
  (--table / --table-file, or --field N = N teams sampled for that seed, weighted by hands observed in the
  real logs; our own team and the pooled profiles 'field'/'donor' are never sampled but can be named in
  --table). The same seed always gives the same table, so separate runs of different candidates line up.
  For every rotation k our bot sits at seat k (seats spread evenly when
  --rotations < seats), the opponents keep the same cyclic order around it. Each (s, k) is played twice
  with the official kit engine (FixedHandsTable, in process: 2,000 chips reset every hand, blinds 10/20,
  no side pots, --hands hands): once with the candidate in our seat, once with the baseline (default
  imperial-ai-hack/v10/bot.py, the live bot). Both runs of a pair get
    * the same deck sequence and starting button: the engine RNG only drives the button draw and the
      shuffles (FixedHandsTable never calls it elsewhere); a digest of every shuffled deck is compared;
    * fresh opponents built with the same seed (clone.make_agent(profile, s), or a zoo bot), so while the
      table history is identical they act identically. Checked on every pair: the first event where the
      two runs differ must be one of OUR actions ("violations" counts the cases where it was not).
  The deck sequence depends only on s, so across the rotations of a seed we play every seat's cards.
  Each bot file is loaded fresh for every table (a new module, like the fresh process of a real round).
  The parent reads the candidate, the baseline, clone.py and the profiles ONCE and the workers execute that
  snapshot, so files edited during a run cannot mix versions; their SHA-1s are saved in the output.

What is reported (bb/100 = chips / 20 / hands * 100)
  raw        actual chips.
  adj        all-in adjusted: a hand that was all-in before the river with >= 2 players at showdown scores
             our equity share of the pot at the moment of the last action (exact when <= 2 cards were to
             come, 1,500-sample Monte Carlo preflop) minus what we put in, instead of the real runout
             (the same rule as hh.py's luck for the real logs).
  diff       candidate minus baseline per (seed, rotation) pair; SE = stdev of the pair differences /
             sqrt(pairs). 'seed-clustered SE' averages the rotations of each seed first (rotations share a
             deck, so they are not independent); trust the larger of the two.
  per opponent  our chips split by opponent with a zero-sum rule per hand (our gain is taken from the
             losers in proportion to their losses, our loss goes to the winners in proportion to their
             wins; printed on all-in adjusted results, where every showdown seat of an all-in hand is
             scored by equity so the split stays zero-sum), plus each opponent's own raw result there.
  by position   contribution of each position to the total adj bb/100 (rows add up to the adj line).
  Every breakdown difference has its own SE across pairs: read small per-opponent gaps as noise.
  how our hands end (won uncontested / showdown won or chopped / showdown lost / folded), VPIP, PFR,
  saw flop, WTSD, and timing: wall seconds per 1,000 hands, our think seconds per 1,000 hands, slowest
  decision, peak worker memory.
  The engine is run in process and does NOT enforce the 25 ms / 10 s limits unless --limits is given
  (use timing.py for the official-limits check).

Output: a compact summary on stdout and out/duel_<name>.json (config, summary, breakdowns, checks, and
one record per pair for further analysis).

Opponents (--opponents auto|clones|zoo; auto = clones when testbench/clone.py and
testbench/profiles/index.json both exist, otherwise the zoo bots imperial-ai-hack/zoo/*.py as a fallback;
--opponents zoo forces the fallback). A clone is clone.make_agent(profile_dict, seed); a zoo opponent is
the module's Agent() (seed unused; zoo bots reseed their dice every hand from seat, hand number and hole
cards, so they are deterministic too). The zoo is far softer than the real field (v10 +255 bb/100 there
vs +19 live): use it only to check that the bench runs.

Reference numbers (Nov 14 ~21:45, final calibrated clones; details in testbench/README.md):
  --field 6, 20 seeds x 7 rotations x 1,000 hands (140 pairs, ~1 min):
    v10 vs v10  diff -0.5 +- 1.0 raw, -1.1 +- 0.9 adj  (null test; v10 itself +31 raw / +34 adj, live +19)
    v0  vs v10  diff -15.3 +- 3.1 raw, -19.5 +- 2.6 adj (z -7.1)
  Sunday table (--table-file tables/sunday.txt), 30 seeds x 8 rotations (240 pairs, ~70 s):
    v10 vs v10  diff +0.4 +- 0.6 raw, +0.6 +- 0.6 adj  (null test; v10 itself +17 raw / +16 adj)
  Absolute levels are optimistic (simreal.py: v10 +34 vs +19.5 real on its own real tables): trust differences.

Adaptive opponents (--adaptive [PARAMS], default adaptive/params.json; README "Adaptive mode"): clones built by
clone_adapt.make_agent, which learn within the table from the hand_end summaries (bettors' bet frequency and shown
big bets -> fold rate facing their bets; openers' fold-to-3-bet -> exploitative 3-bets for the teams measured doing
it; 3-bettors' 3-bet frequency -> fold to their 3-bets; 3-bet range ordered by strength vs 4-bets) plus a static
calibrated extra fold rate against OUR seat's bets (params "hero_level"; --no-hero-level switches it off). The
clone and parameter texts are snapshotted like clone.py; determinism and pairing are unchanged.

Python 3.9+ standard library only. Workers never load the 55-round cache; each job builds its own tables.
"""
import argparse
import gc
import glob
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import statistics
import sys
import time
import traceback
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                   # imperial-ai-hack
PROJECT = os.path.dirname(ROOT)
KIT = os.path.join(PROJECT, "imperial-ai-hack-pokerbots-kit")  # the official tournament engine
ZOO_DIR = os.path.join(ROOT, "zoo")
PROFILES_DIR = os.path.join(HERE, "profiles")
INDEX_PATH = os.path.join(PROFILES_DIR, "index.json")
CLONE_PY = os.path.join(HERE, "clone.py")
CLONE_ADAPT_PY = os.path.join(HERE, "clone_adapt.py")
ADAPT_PARAMS = os.path.join(HERE, "adaptive", "params.json")
OUT_DIR = os.path.join(HERE, "out")
DEFAULT_BASE = os.path.join(ROOT, "v10", "bot.py")
OUR_TEAM = "Durahim 1453"
BB = 20
START = 2000
LIMIT_S = 0.025      # official per-decision limit
BANK_S = 10.0        # official thinking bank per round

for _p in (HERE, KIT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from engine.game import FixedHandsTable  # noqa: E402
from engine.bot_runner import normalise  # noqa: E402

POS_ORDER = ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO", "BTN", "SB", "BB"]
_POS_AFTER_BB = {
    0: [], 1: ["UTG"], 2: ["UTG", "CO"], 3: ["UTG", "HJ", "CO"], 4: ["UTG", "MP", "HJ", "CO"],
    5: ["UTG", "UTG+1", "MP", "HJ", "CO"], 6: ["UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO"],
}


def positions(n, button, sb_seat, bb_seat):
    """Position label per seat (same labels as hh.positions)."""
    out = [None] * n
    if n == 2:
        out[sb_seat], out[bb_seat] = "BTN", "BB"
        return out
    out[button], out[sb_seat], out[bb_seat] = "BTN", "SB", "BB"
    rest = [s for s in ((bb_seat + k) % n for k in range(1, n)) if out[s] is None]
    for s, lab in zip(rest, _POS_AFTER_BB.get(len(rest), ["P%d" % i for i in range(len(rest))])):
        out[s] = lab
    return out


def slugify(name):
    return re.sub(r"[^a-z0-9]", "_", name.lower())


def label_of(path):
    path = os.path.abspath(path)
    base = os.path.basename(path)
    if base == "bot.py":
        return os.path.basename(os.path.dirname(path))
    return base[:-3] if base.endswith(".py") else base


_BOT_CODE = {}      # path -> source text snapshot taken by the parent (workers get it via _init_worker)


def load_module(path, tag):
    """Import a bot file as a brand-new module object (like the fresh process of a real round). If the parent
    took a snapshot of the file, the snapshot text is executed, so editing the file during a run is harmless.
    The module is registered in sys.modules under a unique name until drop_module()."""
    name = "duel_%s_%d" % (tag, time.perf_counter_ns())
    code = _BOT_CODE.get(path)
    if code is None:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    else:
        import types
        mod = types.ModuleType(name)
        mod.__file__ = path
        sys.modules[name] = mod
        exec(compile(code, path, "exec"), mod.__dict__)
    return mod


def drop_module(mod):
    """Free a bot module: break its function<->globals cycles, undo a gc.freeze() it may have done."""
    sys.modules.pop(getattr(mod, "__name__", None), None)
    try:
        mod.__dict__.clear()
    except Exception:
        pass
    try:
        gc.unfreeze()
    except AttributeError:
        pass
    gc.collect()


# ---------------------------------------------------------------------------------------- opponents
class ZooSource:
    """Fallback opponents: imperial-ai-hack/zoo/*.py archetype bots (class Agent)."""
    kind = "zoo"

    def __init__(self):
        self.paths = {os.path.basename(p)[:-3]: p for p in sorted(glob.glob(os.path.join(ZOO_DIR, "*.py")))}
        self._mods = {}

    def names(self):
        return sorted(self.paths)

    def field_names(self):
        return self.names()

    def weights(self):
        return {n: 1.0 for n in self.paths}

    def freeze(self, names):
        pass

    def fingerprint(self):
        return {"zoo_dir": ZOO_DIR}

    def resolve(self, name):
        key = name.strip()
        if key.endswith(".py"):
            key = os.path.basename(key)[:-3]
        if key in self.paths:
            return key
        low = {k.lower(): k for k in self.paths}
        if key.lower() in low:
            return low[key.lower()]
        raise KeyError("unknown zoo opponent %r (have: %s)" % (name, ", ".join(self.names())))

    def make(self, name, seed):
        mod = self._mods.get(name)
        if mod is None:
            mod = self._mods[name] = load_module(self.paths[name], "zoo_" + name)
        return mod.Agent()


class CloneSource:
    """Opponent clones built from real-log profiles: testbench/clone.py + testbench/profiles/*.json.

    The parent process reads clone.py, index.json and every profile the run needs ONCE (a snapshot) and
    hands the texts to the workers, so files being rewritten during a run cannot mix two versions."""
    kind = "clones"

    def __init__(self, snapshot=None, adaptive=None):
        """adaptive: None (static clones) or (params_path, no_hero_level[, components_off]) -> clone_adapt.py + params."""
        if snapshot is None:
            with open(INDEX_PATH) as fh:
                idx = fh.read()
            with open(CLONE_PY) as fh:
                code = fh.read()
            snapshot = {"index": idx, "code": code, "profiles": {}}
            if adaptive:
                with open(CLONE_ADAPT_PY) as fh:
                    snapshot["adapt_code"] = fh.read()
                with open(adaptive[0]) as fh:
                    prm = json.load(fh)
                if adaptive[1]:
                    prm["hero_level"] = {"note": "switched off (--no-hero-level)"}
                off = list(adaptive[2]) if len(adaptive) > 2 and adaptive[2] else []
                if off:
                    import types
                    amod = types.ModuleType("clone_adapt_variant")
                    exec(compile(_variant_source(snapshot["adapt_code"]), CLONE_ADAPT_PY, "exec"), amod.__dict__)
                    prm = amod.variant(prm, off)
                snapshot["adapt_params"] = json.dumps(prm, sort_keys=True)
                snapshot["adapt_path"] = os.path.abspath(adaptive[0])
                snapshot["adapt_no_hero_level"] = bool(adaptive[1])
                snapshot["adapt_off"] = off
        self.snap = snapshot
        self.index = json.loads(snapshot["index"])
        self._clone = None
        self._adapt = None
        self._adapt_params = None
        self.adaptive = bool(snapshot.get("adapt_code"))

    def names(self):
        return sorted(self.index)

    def field_names(self):
        """Real teams only: pooled profiles (kind 'pool', e.g. 'field', 'donor') and our own team are left out
        of --field sampling (name them in --table to use them)."""
        return sorted(n for n, v in self.index.items() if v.get("kind", "team") != "pool" and n != OUR_TEAM)

    def freeze(self, names):
        for n in names:
            if n not in self.snap["profiles"]:
                with open(self.profile_path(n)) as fh:
                    self.snap["profiles"][n] = fh.read()

    def fingerprint(self):
        sha = lambda t: hashlib.sha1(t.encode()).hexdigest()[:12]  # noqa: E731
        out = {"clone_py_sha1": sha(self.snap["code"]), "index_sha1": sha(self.snap["index"]),
               "profiles_sha1": {n: sha(t) for n, t in sorted(self.snap["profiles"].items())}}
        if self.adaptive:
            out["clone_adapt_py_sha1"] = sha(self.snap["adapt_code"])
            out["adapt_params_sha1"] = sha(self.snap["adapt_params"])
            out["adapt_params_path"] = self.snap.get("adapt_path")
            out["adapt_no_hero_level"] = self.snap.get("adapt_no_hero_level")
            out["adapt_components_off"] = self.snap.get("adapt_off")
        return out

    def weights(self):
        out = {}
        for n, v in self.index.items():
            try:
                out[n] = float(v.get("hands", 0) or 0)
            except Exception:
                out[n] = 0.0
        return out

    def resolve(self, name):
        key = name.strip()
        if key in self.index:
            return key
        low = {k.lower(): k for k in self.index}
        if key.lower() in low:
            return low[key.lower()]
        slugs = {(v.get("slug") or slugify(k)): k for k, v in self.index.items()}
        if slugify(key) in slugs:
            return slugs[slugify(key)]
        if key in slugs:
            return slugs[key]
        raise KeyError("unknown team %r (python3 duel.py --list shows the %d profiles)" % (name, len(self.index)))

    def profile_path(self, name):
        slug = self.index[name].get("slug") or slugify(name)
        return os.path.join(PROFILES_DIR, slug + ".json")

    def make(self, name, seed, hero_seat=None):
        if self._clone is None:
            import types
            mod = types.ModuleType("clone")
            mod.__file__ = CLONE_PY
            sys.modules["clone"] = mod          # so helpers that 'import clone' get this same snapshot
            exec(compile(self.snap["code"], CLONE_PY, "exec"), mod.__dict__)
            self._clone = mod
            if self.adaptive:
                amod = types.ModuleType("clone_adapt")
                amod.__file__ = CLONE_ADAPT_PY
                sys.modules["clone_adapt"] = amod   # its 'import clone' resolves to the snapshot registered above
                exec(compile(self.snap["adapt_code"], CLONE_ADAPT_PY, "exec"), amod.__dict__)
                self._adapt = amod
                self._adapt_params = json.loads(self.snap["adapt_params"])
        self.freeze([name])
        if self.adaptive:
            return self._adapt.make_agent(json.loads(self.snap["profiles"][name]), seed, self._adapt_params, hero_seat)
        return self._clone.make_agent(json.loads(self.snap["profiles"][name]), seed)  # fresh dict every table


def _variant_source(code):
    """The COMPONENTS table and variant() of clone_adapt.py's source (applied in the parent without importing clone)."""
    start = code.index("COMPONENTS = {")
    end = code.index("def null_params():")
    return "import json\n" + code[start:end]


def clones_available():
    return os.path.isfile(CLONE_PY) and os.path.isfile(INDEX_PATH)


def make_source(kind, adaptive=None):
    if kind == "auto":
        kind = "clones" if clones_available() else "zoo"
    if kind == "clones":
        if not clones_available():
            sys.exit("clone opponents need %s and %s" % (CLONE_PY, INDEX_PATH))
        return CloneSource(adaptive=adaptive)
    if adaptive:
        sys.exit("--adaptive needs the clone opponents")
    return ZooSource()


_SOURCE = {}


def get_source(kind, adaptive=None):
    if kind == "auto":
        kind = "clones" if clones_available() else "zoo"
    if kind not in _SOURCE:
        _SOURCE[kind] = make_source(kind, adaptive)
    return _SOURCE[kind]


def _init_worker(snapshot, bot_code=None):
    """Pool initializer: workers use the parent's snapshot of clone.py, the profiles and the bot files."""
    if snapshot is not None:
        _SOURCE["clones"] = CloneSource(snapshot)
    if bot_code:
        _BOT_CODE.update(bot_code)


# ---------------------------------------------------------------------------------------- engine glue
class DeckRecorder(random.Random):
    """The engine's RNG. Records a digest of every shuffled deck, to prove paired runs saw the same cards."""

    def __init__(self, seed):
        super().__init__(seed)
        self.digest = hashlib.sha1()
        self.shuffles = 0

    def shuffle(self, x, *a, **k):
        super().shuffle(x, *a, **k)
        self.digest.update(bytes(c & 255 for c in x) if all(isinstance(c, int) for c in x) else repr(x).encode())
        self.shuffles += 1


class Seat:
    """Engine seat adapter around an in-process agent (like tools/gauntlet.py's Seat).

    The hero gets a private JSON copy of every state/summary (what the platform's pipe delivers), so a bot
    that mutates its input cannot touch the engine or the opponents. Exceptions become None (the engine
    then checks or folds, as on the platform). With limits=True the official 25 ms / 10 s rules are applied
    to the hero (a slow answer is discarded and auto-played) using in-process timing.
    """

    def __init__(self, agent, name, hero=False, limits=False):
        self.agent, self.name, self.hero, self.limits = agent, name, hero, limits
        self.errors = 0
        self.first_error = None
        self.think = 0.0
        self.decisions = 0
        self.max_s = 0.0
        self.slow = 0          # decisions over 25 ms
        self.timeouts = 0      # only with limits
        self.bank_out = 0      # only with limits
        self.bank = BANK_S

    def _err(self):
        self.errors += 1
        if self.first_error is None:
            self.first_error = traceback.format_exc(limit=6)[-2500:]

    def start_table(self, seat, info):
        if hasattr(self.agent, "on_table_start"):
            try:
                self.agent.on_table_start(dict(info))
            except Exception:
                self._err()

    def act(self, state):
        if self.hero:
            state = json.loads(json.dumps(state))
            if self.limits and self.bank <= 0:
                self.decisions += 1
                self.bank_out += 1
                return None
        t0 = time.perf_counter()
        try:
            out = normalise(self.agent.act(state))
        except Exception:
            self._err()
            out = None
        dt = time.perf_counter() - t0
        if self.hero:
            self.decisions += 1
            self.think += dt
            if dt > self.max_s:
                self.max_s = dt
            if dt > LIMIT_S:
                self.slow += 1
            if self.limits:
                self.bank -= min(dt, LIMIT_S)
                if dt > LIMIT_S:
                    self.timeouts += 1
                    return None
        return out

    def hand_end(self, summary):
        if not hasattr(self.agent, "on_hand_end"):
            return
        if self.hero:
            summary = json.loads(json.dumps(summary))
        t0 = time.perf_counter()
        try:
            self.agent.on_hand_end(summary)
        except Exception:
            self._err()
        if self.hero:
            self.think += time.perf_counter() - t0


# ---------------------------------------------------------------------------------------- analysis
_EQ_CACHE = {}
_evalx = None


def equity_shares(holes, board):
    """Pot share of each hand over the remaining runouts (testbench/evalx.py, as hh.py's luck uses)."""
    global _evalx
    key = (tuple(tuple(h) for h in holes), tuple(board))
    v = _EQ_CACHE.get(key)
    if v is None:
        if _evalx is None:
            import evalx as _ev
            _evalx = _ev
        v = _evalx.equities([[_evalx.card(c) for c in h] for h in holes], [_evalx.card(c) for c in board],
                            samples=1500)
        if len(_EQ_CACHE) > 20000:
            _EQ_CACHE.clear()
        _EQ_CACHE[key] = v
    return v


def new_stats():
    return {
        "hands": 0, "chips": 0, "adj": 0.0, "allin_hands": 0, "allin_luck": 0.0,
        "pos": {},                     # label -> [hands, chips, adj]
        "vs": defaultdict(float),      # opponent name -> our chips from him (zero-sum split, raw)
        "vs_adj": defaultdict(float),  # the same split of the all-in adjusted results
        "vs_hands": defaultdict(int),  # opponent name -> hands played at the same table
        "opp_chips": defaultdict(int), # opponent name -> his own chips
        "end": {"uncontested": [0, 0], "sd_won": [0, 0], "sd_lost": [0, 0], "folded": [0, 0]},
        "vpip": 0, "pfr": 0, "saw_flop": 0, "wtsd": 0,
    }


def _split(acc, res, hero, names, r):
    """Zero-sum split of our result r over the opponents: a gain is taken from the losers in proportion to
    their losses, a loss goes to the winners in proportion to their wins (res sums to zero)."""
    if not r:
        return
    n = len(res)
    if r > 0:
        tot = -sum(x for x in res if x < 0)
        if tot > 1e-9:
            for j in range(n):
                if j != hero and res[j] < 0:
                    acc[names[j]] += r * (-res[j]) / tot
    else:
        tot = sum(x for x in res if x > 0)
        if tot > 1e-9:
            for j in range(n):
                if j != hero and res[j] > 0:
                    acc[names[j]] += r * res[j] / tot


def analyse(log, hero, names, st):
    """Fold one table's hand records (engine record=True) into the stats dict `st` for seat `hero`."""
    n = len(names)
    for rec in log:
        ev = rec["events"]
        start = rec["stacks"]
        end = rec["end"]
        wins = [0] * n
        for e in ev:
            if e[0] == "win":
                wins[e[1]] += e[2]
        res = [end[i] - start[i] for i in range(n)]
        r = res[hero]
        st["hands"] += 1
        st["chips"] += r
        # all-in adjustment
        adj = float(r)
        adj_res = res
        sd = rec.get("showdown") or {}
        if str(hero) in sd and len(sd) >= 2:
            last_act = -1
            boards = []
            for i, e in enumerate(ev):
                if e[0] == "act":
                    last_act = i
                elif e[0] == "board":
                    boards.append((i, e[2]))
            if any(i > last_act for i, _ in boards):
                prior = [b for i, b in boards if i < last_act]
                board_at = prior[-1] if prior else []
                seats = sorted(int(k) for k in sd)
                eqs = equity_shares([rec["hole"][str(s)] for s in seats], board_at)
                pot = sum(wins)
                adj_res = list(res)          # every showdown seat scored by equity: still sums to zero
                for s_, q in zip(seats, eqs):
                    adj_res[s_] = q * pot - (start[s_] - end[s_] + wins[s_])
                adj = adj_res[hero]
                st["allin_hands"] += 1
                st["allin_luck"] += r - adj
        st["adj"] += adj
        # position
        posts = [e for e in ev if e[0] == "post"]
        lab = positions(n, rec["button"], posts[0][1], posts[1][1])[hero]
        p = st["pos"].setdefault(lab, [0, 0, 0.0])
        p[0] += 1
        p[1] += r
        p[2] += adj
        # zero-sum split of our result over the opponents (raw and all-in adjusted)
        _split(st["vs"], res, hero, names, r)
        _split(st["vs_adj"], adj_res, hero, names, adj)
        for j in range(n):
            if j != hero:
                st["vs_hands"][names[j]] += 1
                st["opp_chips"][names[j]] += res[j]
        # how the hand ended for us, preflop habits
        street = 0
        fold_st = None
        vp = pr = False
        for e in ev:
            if e[0] == "board":
                street += 1
            elif e[0] == "act" and e[1] == hero:
                if e[2] == "fold":
                    fold_st = street
                elif street == 0 and e[2] in ("call", "raise"):
                    vp = True
                    if e[2] == "raise":
                        pr = True
        folded = fold_st is not None
        st["vpip"] += vp
        st["pfr"] += pr
        if street >= 1 and (fold_st is None or fold_st >= 1):
            st["saw_flop"] += 1
        if str(hero) in sd:
            st["wtsd"] += 1
            k = "sd_won" if r >= 0 else "sd_lost"      # a chop (r == 0) counts as not lost
        elif folded:
            k = "folded"
        else:
            k = "uncontested"
        st["end"][k][0] += 1
        st["end"][k][1] += r
    return st


def first_divergence(log_a, log_b, hero):
    """First event where two paired runs differ. ok=True when it is one of OUR actions (expected)."""
    for ra, rb in zip(log_a, log_b):
        if ra["hole"] != rb["hole"] or ra["button"] != rb["button"]:
            return {"hand": ra["n"], "ok": False, "why": "different cards or button"}
        ea, eb = ra["events"], rb["events"]
        if ea == eb:
            continue
        j = 0
        while j < len(ea) and j < len(eb) and ea[j] == eb[j]:
            j += 1
        xa = ea[j] if j < len(ea) else None
        xb = eb[j] if j < len(eb) else None
        ok = (xa is not None and xb is not None and xa[0] == "act" and xb[0] == "act"
              and xa[1] == hero and xb[1] == hero)
        return {"hand": ra["n"], "ok": ok, "event": j, "cand": xa, "base": xb,
                "why": "" if ok else "first difference is not an action of our seat"}
    if len(log_a) != len(log_b):
        return {"hand": min(len(log_a), len(log_b)) + 1, "ok": False, "why": "different hand counts"}
    return None


# ---------------------------------------------------------------------------------------- one job
def run_table(job, which):
    """Play one table with `which` ('cand' or 'base') in our seat. Returns (stats, log, seat_objs, meta)."""
    src = get_source(job["source"])
    path = job[which]
    mod = load_module(path, which)
    hero_seat = job["hero_seat"]
    opp_seats = []
    for name in job["opps"]:
        if getattr(src, "adaptive", False):
            opp_seats.append(Seat(src.make(name, job["seed"], hero_seat), name))
        else:
            opp_seats.append(Seat(src.make(name, job["seed"]), name))
    hero = Seat(mod.Agent(), label_of(path), hero=True, limits=job["limits"])
    players = list(opp_seats)
    players.insert(hero_seat, hero)
    names = [p.name for p in players]
    names[hero_seat] = "<us>"
    rng = DeckRecorder(job["engine_seed"])
    table = FixedHandsTable(players, hands=job["hands"], record=True, rng=rng)
    t0 = time.perf_counter()
    res = table.play()
    wall = time.perf_counter() - t0
    if sum(res["chips"]) != 0:
        raise RuntimeError("chips do not sum to zero: %r" % res["chips"])
    log = res["log"]
    st = analyse(log, hero_seat, names, new_stats())
    if res["chips"][hero_seat] != st["chips"]:
        raise RuntimeError("hand records do not add up to the engine total")
    opp_err = {}
    for p in opp_seats:
        if p.errors:
            e = opp_err.setdefault(p.name, {"errors": 0, "first": p.first_error})
            e["errors"] += p.errors
    meta = {
        "wall_s": wall, "think_s": hero.think, "decisions": hero.decisions, "max_ms": hero.max_s * 1000,
        "slow": hero.slow, "timeouts": hero.timeouts, "bank_out": hero.bank_out,
        "errors": hero.errors, "first_error": hero.first_error, "opp_errors": opp_err,
        "deck": rng.digest.hexdigest()[:16] + ":%d:%d" % (rng.shuffles, log[0]["button"] if log else -1),
    }
    del table, players, opp_seats, hero
    drop_module(mod)
    return st, log, meta


def run_job(job):
    """Play one (seed, rotation) pair: candidate and baseline on identical tables."""
    t0 = time.perf_counter()
    try:
        out = {"seed": job["seed"], "rot": job["rot"], "hero_seat": job["hero_seat"], "opps": job["opps"]}
        order = ("cand", "base") if job["idx"] % 2 == 0 else ("base", "cand")   # alternate, no order bias
        logs = {}
        for which in order:
            st, log, meta = run_table(job, which)
            logs[which] = log
            st["vs"] = dict(st["vs"])
            st["vs_adj"] = dict(st["vs_adj"])
            st["vs_hands"] = dict(st["vs_hands"])
            st["opp_chips"] = dict(st["opp_chips"])
            out[which] = {"stats": st, "meta": meta}
        out["deck_same"] = out["cand"]["meta"]["deck"] == out["base"]["meta"]["deck"]
        out["divergence"] = first_divergence(logs["cand"], logs["base"], job["hero_seat"])
        out["job_s"] = time.perf_counter() - t0
        return out
    except Exception:
        return {"seed": job["seed"], "rot": job["rot"], "failed": traceback.format_exc(limit=8)}


# ---------------------------------------------------------------------------------------- planning
def rotation_seats(n, rotations):
    rotations = max(1, min(rotations, n))
    return sorted({int(round(j * n / rotations)) % n for j in range(rotations)})


def weighted_sample(rng, names, weights, k):
    pool = [x for x in names if weights.get(x, 0) > 0] or list(names)
    if k > len(pool):
        raise SystemExit("--field %d but only %d opponents are available" % (k, len(pool)))
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


def plan(args, src):
    fixed = None
    if args.table:
        fixed = [x for x in (t.strip() for t in args.table.split(",")) if x]
    elif args.table_file:
        fixed = read_table_file(args.table_file)
    if fixed is not None:
        try:
            fixed = [src.resolve(x) for x in fixed]
        except KeyError as exc:
            sys.exit(exc.args[0])
        if not 1 <= len(fixed) <= 7:
            sys.exit("a table seats 2-8 bots: give 1-7 opponents (got %d)" % len(fixed))
    field = args.field if fixed is None else None
    if field is not None and not 1 <= field <= 7:
        sys.exit("--field must be 1..7")
    weights = src.weights()
    pool = src.field_names()
    jobs = []
    for i in range(args.seeds):
        s = args.seed0 + i
        opps = list(fixed) if fixed is not None else weighted_sample(random.Random(s * 7907 + 13), pool,
                                                                    weights, field)
        n = len(opps) + 1
        for k in rotation_seats(n, args.rotations):
            jobs.append({"idx": len(jobs), "seed": s, "rot": k, "hero_seat": k, "opps": opps,
                         "engine_seed": s * 1000003 + 7, "hands": args.hands, "cand": args.cand,
                         "base": args.base, "source": src.kind, "limits": args.limits})
    return jobs


# ---------------------------------------------------------------------------------------- statistics
def mean_se(xs):
    xs = list(xs)
    if not xs:
        return float("nan"), float("nan")
    if len(xs) == 1:
        return xs[0], float("nan")
    return statistics.mean(xs), statistics.stdev(xs) / math.sqrt(len(xs))


def bb100(chips, hands):
    return chips / BB / hands * 100.0 if hands else 0.0


def summarise(results, args, src, elapsed):
    ok = [r for r in results if "failed" not in r]
    failed = [r for r in results if "failed" in r]
    ok.sort(key=lambda r: (r["seed"], r["rot"]))
    out = {"pairs": len(ok), "failed": len(failed)}
    if not ok:
        return out, failed

    def per_pair(which, key):
        return [bb100(r[which]["stats"][key], r[which]["stats"]["hands"]) for r in ok]

    summ = {}
    for key in ("chips", "adj"):
        tag = "raw" if key == "chips" else "adj"
        c, b = per_pair("cand", key), per_pair("base", key)
        d = [x - y for x, y in zip(c, b)]
        by_seed = defaultdict(list)
        for r, x in zip(ok, d):
            by_seed[r["seed"]].append(x)
        seed_means = [statistics.mean(v) for v in by_seed.values()]
        cm, cse = mean_se(c)
        bm, bse = mean_se(b)
        dm, dse = mean_se(d)
        _, dse_cl = mean_se(seed_means)
        summ[tag] = {"cand": cm, "cand_se": cse, "base": bm, "base_se": bse, "diff": dm, "diff_se": dse,
                     "diff_se_seed_clustered": dse_cl, "z": dm / max(dse, dse_cl) if dse == dse and dse_cl == dse_cl
                     and max(dse, dse_cl) > 0 else None}
    out["summary"] = summ

    # aggregates per side
    agg = {}
    for which in ("cand", "base"):
        a = {"hands": 0, "chips": 0, "adj": 0.0, "allin_hands": 0, "allin_luck": 0.0, "pos": defaultdict(lambda: [0, 0, 0.0]),
             "vs": defaultdict(float), "vs_adj": defaultdict(float), "vs_hands": defaultdict(int),
             "opp_chips": defaultdict(int),
             "end": defaultdict(lambda: [0, 0]), "vpip": 0, "pfr": 0, "saw_flop": 0, "wtsd": 0,
             "wall": [], "think": [], "max_ms": 0.0, "slow": 0, "timeouts": 0, "bank_out": 0, "errors": 0,
             "first_error": None, "opp_errors": defaultdict(int), "opp_first_error": {}}
        for r in ok:
            s, m = r[which]["stats"], r[which]["meta"]
            for k in ("hands", "chips", "adj", "allin_hands", "allin_luck", "vpip", "pfr", "saw_flop", "wtsd"):
                a[k] += s[k]
            for lab, v in s["pos"].items():
                for i in range(3):
                    a["pos"][lab][i] += v[i]
            for o, v in s["vs"].items():
                a["vs"][o] += v
            for o, v in s["vs_adj"].items():
                a["vs_adj"][o] += v
            for o, v in s["vs_hands"].items():
                a["vs_hands"][o] += v
            for o, v in s["opp_chips"].items():
                a["opp_chips"][o] += v
            for k, v in s["end"].items():
                a["end"][k][0] += v[0]
                a["end"][k][1] += v[1]
            per1k = 1000.0 / max(1, s["hands"])
            a["wall"].append(m["wall_s"] * per1k)
            a["think"].append(m["think_s"] * per1k)
            a["max_ms"] = max(a["max_ms"], m["max_ms"])
            for k in ("slow", "timeouts", "bank_out", "errors"):
                a[k] += m[k]
            if m["first_error"] and not a["first_error"]:
                a["first_error"] = m["first_error"]
            for o, e in m["opp_errors"].items():
                a["opp_errors"][o] += e["errors"]
                a["opp_first_error"].setdefault(o, e["first"])
        agg[which] = a

    H = agg["cand"]["hands"]
    # per-pair differences, for standard errors of the breakdowns
    opp_d = defaultdict(lambda: {"raw": [], "adj": []})
    pos_d = defaultdict(lambda: {"raw": [], "adj": []})
    for r in ok:
        c, b = r["cand"]["stats"], r["base"]["stats"]
        for o, hn in c["vs_hands"].items():
            opp_d[o]["raw"].append(bb100(c["vs"].get(o, 0.0) - b["vs"].get(o, 0.0), hn))
            opp_d[o]["adj"].append(bb100(c["vs_adj"].get(o, 0.0) - b["vs_adj"].get(o, 0.0), hn))
        for lab in set(c["pos"]) | set(b["pos"]):
            cv, bv = c["pos"].get(lab, [0, 0, 0.0]), b["pos"].get(lab, [0, 0, 0.0])
            pos_d[lab]["raw"].append(bb100(cv[1] - bv[1], c["hands"]))
            pos_d[lab]["adj"].append(bb100(cv[2] - bv[2], c["hands"]))
    out["per_opponent"] = {}
    for o in sorted(set(agg["cand"]["vs_hands"]) | set(agg["base"]["vs_hands"])):
        row = {}
        for which in ("cand", "base"):
            a = agg[which]
            hh_ = a["vs_hands"].get(o, 0)
            row[which] = {"hands": hh_, "our_chips": round(a["vs"].get(o, 0.0), 1),
                          "our_bb100_at_his_tables": bb100(a["vs"].get(o, 0.0), hh_),
                          "our_adj_bb100_at_his_tables": bb100(a["vs_adj"].get(o, 0.0), hh_),
                          "his_chips": a["opp_chips"].get(o, 0), "his_bb100": bb100(a["opp_chips"].get(o, 0), hh_)}
        row["diff_our_bb100"] = row["cand"]["our_bb100_at_his_tables"] - row["base"]["our_bb100_at_his_tables"]
        row["diff_our_bb100_se"] = mean_se(opp_d[o]["raw"])[1]
        row["diff_our_adj_bb100"] = (row["cand"]["our_adj_bb100_at_his_tables"]
                                     - row["base"]["our_adj_bb100_at_his_tables"])
        row["diff_our_adj_bb100_se"] = mean_se(opp_d[o]["adj"])[1]
        row["pairs"] = len(opp_d[o]["raw"])
        out["per_opponent"][o] = row
    out["by_position"] = {}
    labs = sorted(set(agg["cand"]["pos"]) | set(agg["base"]["pos"]),
                  key=lambda x: POS_ORDER.index(x) if x in POS_ORDER else 99)
    for lab in labs:
        row = {}
        for which in ("cand", "base"):
            v = agg[which]["pos"].get(lab, [0, 0, 0.0])
            row[which] = {"hands": v[0], "chips": v[1], "adj": round(v[2], 1),
                          "bb100_in_pos": bb100(v[1], v[0]), "share_of_total_bb100": bb100(v[1], agg[which]["hands"]),
                          "adj_share_of_total_bb100": bb100(v[2], agg[which]["hands"])}
        row["diff_share_bb100"] = row["cand"]["share_of_total_bb100"] - row["base"]["share_of_total_bb100"]
        row["diff_share_bb100_se"] = mean_se(pos_d[lab]["raw"])[1]
        row["diff_adj_share_bb100"] = (row["cand"]["adj_share_of_total_bb100"]
                                       - row["base"]["adj_share_of_total_bb100"])
        row["diff_adj_share_bb100_se"] = mean_se(pos_d[lab]["adj"])[1]
        out["by_position"][lab] = row
    out["outcomes"] = {}
    for which in ("cand", "base"):
        a = agg[which]
        hs = max(1, a["hands"])
        o = {k: {"per100": 100.0 * v[0] / hs, "bb100": bb100(v[1], hs), "hands": v[0], "chips": v[1]}
             for k, v in a["end"].items()}
        o["vpip_pct"] = 100.0 * a["vpip"] / hs
        o["pfr_pct"] = 100.0 * a["pfr"] / hs
        o["saw_flop_pct"] = 100.0 * a["saw_flop"] / hs
        o["wtsd_pct_of_flops"] = 100.0 * a["wtsd"] / max(1, a["saw_flop"])
        o["allin_adjusted_hands_per1000"] = 1000.0 * a["allin_hands"] / hs
        o["allin_luck_bb100"] = bb100(a["allin_luck"], hs)
        out["outcomes"][which] = o
    out["timing"] = {}
    for which in ("cand", "base"):
        a = agg[which]
        out["timing"][which] = {
            "wall_s_per_1000_hands_mean": statistics.mean(a["wall"]), "wall_s_per_1000_hands_max": max(a["wall"]),
            "think_s_per_1000_hands_mean": statistics.mean(a["think"]),
            "think_s_per_1000_hands_max": max(a["think"]), "max_decision_ms": a["max_ms"],
            "decisions_over_25ms": a["slow"], "timeouts_with_limits": a["timeouts"],
            "bank_out_with_limits": a["bank_out"], "errors": a["errors"], "first_error": a["first_error"],
            "opponent_errors": dict(a["opp_errors"]), "opponent_first_error": a["opp_first_error"],
        }
    out["timing"]["elapsed_s"] = elapsed
    out["timing"]["peak_worker_rss_mb"] = peak_child_rss_mb()
    out["timing"]["job_s_mean"] = statistics.mean(r["job_s"] for r in ok)
    divs = [r["divergence"] for r in ok]
    viol = [dict(r["divergence"], seed=r["seed"], rot=r["rot"]) for r in ok if r["divergence"] and not r["divergence"]["ok"]]
    first = [d["hand"] for d in divs if d]
    by_seed_deck = defaultdict(set)
    for r in ok:
        by_seed_deck[r["seed"]].add(r["cand"]["meta"]["deck"])
    out["checks"] = {
        "deck_identical_in_every_pair": all(r["deck_same"] for r in ok),
        "pairs_with_different_decks": sum(1 for r in ok if not r["deck_same"]),
        "deck_identical_across_rotations_of_a_seed": all(len(v) == 1 for v in by_seed_deck.values()),
        "opponent_determinism_violations": len(viol), "violations": viol[:20],
        "pairs_fully_identical": sum(1 for d in divs if d is None),
        "first_divergent_hand_median": statistics.median(first) if first else None,
        "first_divergent_hand_min": min(first) if first else None,
    }
    out["agg_hands"] = H
    return out, failed


# ---------------------------------------------------------------------------------------- printing
def fmt_se(m, se):
    if se != se:
        return "%+7.1f" % m
    return "%+7.1f +-%5.1f" % (m, se)


def print_report(rep, args, src, cand_lab, base_lab):
    s = rep["summary"]
    print("\n== duel: %s (cand) vs %s (base) | opponents: %s | %d pairs x %d hands%s" % (
        cand_lab, base_lab, src.kind + (" ADAPTIVE" if getattr(src, "adaptive", False) else ""), rep["pairs"],
        args.hands, (" | %d FAILED" % rep["failed"]) if rep["failed"] else ""))
    print("%-5s %20s %20s %26s %10s" % ("", "cand bb/100", "base bb/100", "diff (cand-base) +-SE", "clust.SE"))
    for tag in ("raw", "adj"):
        r = s[tag]
        cl = r["diff_se_seed_clustered"]
        print("%-5s %20s %20s %26s %10s" % (tag, fmt_se(r["cand"], r["cand_se"]), fmt_se(r["base"], r["base_se"]),
                                          fmt_se(r["diff"], r["diff_se"]), ("%.1f" % cl) if cl == cl else "n/a"))
    z = s["adj"]["z"]
    if z is not None:
        verdict = "cand better" if z > 2 else ("cand worse" if z < -2 else "no clear difference")
        print("adj z = %+.2f (diff / larger SE): %s" % (z, verdict))
    c = rep["checks"]
    print("checks: decks identical in all pairs: %s | across rotations: %s | opponent-determinism violations: %d"
          " | identical pairs %d, first divergence at hand %s (median)" % (
              c["deck_identical_in_every_pair"], c["deck_identical_across_rotations_of_a_seed"],
              c["opponent_determinism_violations"], c["pairs_fully_identical"], c["first_divergent_hand_median"]))
    print("\nper opponent: our all-in adjusted bb/100 at tables with him (zero-sum split; per hand with him) | his own"
          " raw bb/100")
    print("%-26s %7s %9s %9s %16s %8s %8s" % ("opponent", "hands", "cand", "base", "diff +-SE", "his(c)", "his(b)"))
    rows = sorted(rep["per_opponent"].items(), key=lambda kv: kv[1]["diff_our_adj_bb100"])
    for o, r in rows:
        print("%-26s %7d %+9.1f %+9.1f %16s %+8.1f %+8.1f" % (
            o[:26], r["cand"]["hands"], r["cand"]["our_adj_bb100_at_his_tables"],
            r["base"]["our_adj_bb100_at_his_tables"], fmt_se(r["diff_our_adj_bb100"], r["diff_our_adj_bb100_se"]),
            r["cand"]["his_bb100"], r["base"]["his_bb100"]))
    print("\nby position: contribution to the total all-in adjusted bb/100 (rows sum to the adj line)")
    print("%-6s %9s %9s %16s" % ("pos", "cand", "base", "diff +-SE"))
    for lab, r in rep["by_position"].items():
        print("%-6s %+9.1f %+9.1f %16s" % (lab, r["cand"]["adj_share_of_total_bb100"], r["base"]["adj_share_of_total_bb100"],
                                          fmt_se(r["diff_adj_share_bb100"], r["diff_adj_share_bb100_se"])))
    print("\nhow our hands end (per 100 hands: count, bb/100)      cand                 base")
    oc = rep["outcomes"]
    for k, lab in (("uncontested", "won uncontested"), ("sd_won", "showdown won/chop"), ("sd_lost", "showdown lost"),
                   ("folded", "folded")):
        a, b = oc["cand"].get(k), oc["base"].get(k)
        print("  %-22s %22s %22s" % (lab, "%5.1f  %+8.1f" % (a["per100"], a["bb100"]) if a else "-",
                                     "%5.1f  %+8.1f" % (b["per100"], b["bb100"]) if b else "-"))
    for k, lab in (("vpip_pct", "VPIP %"), ("pfr_pct", "PFR %"), ("saw_flop_pct", "saw flop %"),
                   ("wtsd_pct_of_flops", "WTSD % of flops"), ("allin_adjusted_hands_per1000", "all-in adj hands/1000"),
                   ("allin_luck_bb100", "all-in luck bb/100")):
        print("  %-22s %22.1f %22.1f" % (lab, oc["cand"][k], oc["base"][k]))
    t = rep["timing"]
    print("\ntiming (in process): wall s/1000 hands cand %.2f base %.2f | our think s/1000 hands cand %.2f (max %.2f)"
          " base %.2f (max %.2f) | slowest decision cand %.1f ms base %.1f ms | >25ms: %d / %d | elapsed %.0fs" % (
              t["cand"]["wall_s_per_1000_hands_mean"], t["base"]["wall_s_per_1000_hands_mean"],
              t["cand"]["think_s_per_1000_hands_mean"], t["cand"]["think_s_per_1000_hands_max"],
              t["base"]["think_s_per_1000_hands_mean"], t["base"]["think_s_per_1000_hands_max"],
              t["cand"]["max_decision_ms"], t["base"]["max_decision_ms"], t["cand"]["decisions_over_25ms"],
              t["base"]["decisions_over_25ms"], t["elapsed_s"]))
    print("peak worker memory: %s MB" % t.get("peak_worker_rss_mb"))
    for which in ("cand", "base"):
        if t[which]["errors"]:
            print("\n%s raised %d exceptions; first:\n%s" % (which, t[which]["errors"], t[which]["first_error"]))
        if t[which]["opponent_errors"]:
            print("\nopponent exceptions during %s runs: %s" % (which, t[which]["opponent_errors"]))
            for o, tb in list(t[which]["opponent_first_error"].items())[:2]:
                print("--- %s ---\n%s" % (o, tb))


# ---------------------------------------------------------------------------------------- driver
def peak_child_rss_mb():
    """Largest resident memory of any finished worker process (MB), or None."""
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return round(v / (1024.0 * 1024.0) if sys.platform == "darwin" else v / 1024.0, 1)
    except Exception:
        return None


def snapshot_bots(jobs):
    out = {}
    for p in sorted({j["cand"] for j in jobs} | {j["base"] for j in jobs}):
        with open(p) as fh:
            out[p] = fh.read()
    return out


def execute(jobs, procs, src, quiet=False):
    src.freeze(sorted({n for j in jobs for n in j["opps"]}))
    snapshot = src.snap if src.kind == "clones" else None
    bot_code = snapshot_bots(jobs)
    _BOT_CODE.update(bot_code)          # the in-process path (procs <= 1) uses the same snapshot
    results = []
    t0 = time.time()
    last = [0.0]

    def progress(force=False):
        now = time.time()
        if quiet or not (force or now - last[0] >= 10 or len(results) == len(jobs)):
            return
        last[0] = now
        print("  %d/%d pairs done, %.0fs" % (len(results), len(jobs), now - t0), flush=True)

    if procs <= 1:
        for j in jobs:
            results.append(run_job(j))
            progress()
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        pool = ctx.Pool(min(procs, len(jobs)), maxtasksperchild=12, initializer=_init_worker,
                        initargs=(snapshot, bot_code))
        try:
            for res in pool.imap_unordered(run_job, jobs):
                results.append(res)
                progress()
            pool.close()
        except BaseException:
            pool.terminate()
            raise
        finally:
            pool.join()
    return results, time.time() - t0


def compact_pair(r):
    if "failed" in r:
        return {"seed": r["seed"], "rot": r["rot"], "failed": r["failed"]}
    o = {"seed": r["seed"], "rot": r["rot"], "hero_seat": r["hero_seat"], "opps": r["opps"],
         "deck_same": r["deck_same"], "divergence": r["divergence"], "job_s": round(r["job_s"], 2)}
    for which in ("cand", "base"):
        s, m = r[which]["stats"], r[which]["meta"]
        o[which] = {"hands": s["hands"], "chips": s["chips"], "adj": round(s["adj"], 1),
                    "raw_bb100": round(bb100(s["chips"], s["hands"]), 2),
                    "adj_bb100": round(bb100(s["adj"], s["hands"]), 2), "allin_hands": s["allin_hands"],
                    "vs": {k: round(v, 1) for k, v in s["vs"].items()},
                    "vs_adj": {k: round(v, 1) for k, v in s["vs_adj"].items()},
                    "opp_chips": s["opp_chips"], "wall_s": round(m["wall_s"], 3), "think_s": round(m["think_s"], 3),
                    "max_ms": round(m["max_ms"], 2), "errors": m["errors"], "deck": m["deck"]}
    return o


def selftest(args):
    """Determinism of the bench: (1) a deterministic hero vs itself must give identical logs;
    (2) two different heroes must first differ at one of OUR actions, with identical decks."""
    src = get_source(args.opponents)
    zoo = ZooSource()
    det = zoo.paths["tag_charts"]
    print("selftest with %s opponents" % src.kind)
    a = argparse.Namespace(**vars(args))
    a.table, a.table_file, a.seeds, a.rotations, a.hands, a.limits = None, None, 2, 2, args.selftest_hands, False
    if args.table or args.table_file:
        a.table, a.table_file = args.table, args.table_file
    a.field = None if (a.table or a.table_file) else 6
    ok_all = True
    for title, cand, base, want_identical in (
            ("same deterministic hero (zoo tag_charts) twice -> logs must be identical", det, det, True),
            ("different heroes (zoo nit vs zoo maniac) -> first difference must be ours", zoo.paths["nit"],
             zoo.paths["maniac"], False),
            ("v10 vs v10 (internal Monte Carlo randomness) -> first difference must be ours", DEFAULT_BASE,
             DEFAULT_BASE, False)):
        a.cand, a.base = cand, base
        jobs = plan(a, src)
        res, el = execute(jobs, min(args.procs, len(jobs)), src, quiet=True)
        bad = [r for r in res if "failed" in r]
        for r in bad:
            print(r["failed"])
        good = [r for r in res if "failed" not in r]
        decks = all(r["deck_same"] for r in good)
        viol = [r["divergence"] for r in good if r["divergence"] and not r["divergence"]["ok"]]
        ident = sum(1 for r in good if r["divergence"] is None)
        same_chips = all(r["cand"]["stats"]["chips"] == r["base"]["stats"]["chips"] for r in good)
        passed = not bad and decks and not viol and (ident == len(good) and same_chips if want_identical else True)
        ok_all &= passed
        print("  [%s] %s\n         pairs %d, identical decks %s, identical logs %d/%d, violations %d, first divergence"
              " hands %s (%.0fs)" % ("PASS" if passed else "FAIL", title, len(good), decks, ident, len(good), len(viol),
                                     [r["divergence"]["hand"] if r["divergence"] else None for r in good], el))
        for v in viol[:3]:
            print("         violation:", v)
    print("selftest %s" % ("PASSED" if ok_all else "FAILED"))
    return ok_all


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog="Full description: the docstring at the top of duel.py.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cand", help="candidate bot file (class Agent)")
    ap.add_argument("--base", default=DEFAULT_BASE, help="baseline bot file (default: the live bot v10/bot.py)")
    g = ap.add_argument_group("table (pick one; default --field 6 = 7-seat tables like Sunday)")
    g.add_argument("--table", help='comma-separated opponent names, e.g. "Kojack,AAST,Red" (zoo: "lag,nit,...")')
    g.add_argument("--table-file", help="file with one opponent name per line (or a JSON list)")
    g.add_argument("--field", type=int, default=None, help="sample N opponents per seed, weighted by hands observed")
    ap.add_argument("--opponents", choices=["auto", "clones", "zoo"], default="auto",
                    help="opponent source (auto: clones if clone.py and profiles/index.json exist, else zoo)")
    ap.add_argument("--seeds", type=int, default=20, help="deal seeds (default 20)")
    ap.add_argument("--seed0", type=int, default=1, help="first deal seed (default 1)")
    ap.add_argument("--rotations", type=int, default=99, help="seats our bot rotates through per seed (default: all)")
    ap.add_argument("--hands", type=int, default=1000, help="hands per table (default 1000, the tournament round)")
    ap.add_argument("--procs", type=int, default=6, help="worker processes (default 6, max sensible 6 on this machine)")
    ap.add_argument("--limits", action="store_true", help="apply 25 ms / 10 s to our bot with in-process timing")
    ap.add_argument("--name", help="output name: out/duel_<name>.json (default from the bot file names)")
    ap.add_argument("--list", action="store_true", help="list the opponents of the active source and exit")
    ap.add_argument("--selftest", action="store_true", help="run the determinism self-test and exit")
    ap.add_argument("--selftest-hands", type=int, default=300, help=argparse.SUPPRESS)
    ap.add_argument("--adaptive", nargs="?", const=ADAPT_PARAMS, default=None, metavar="PARAMS",
                    help="ADAPTIVE clones (clone_adapt.py) with these parameters (default adaptive/params.json); "
                         "default off = the static clones")
    ap.add_argument("--no-hero-level", action="store_true",
                    help="with --adaptive: switch off the calibrated static extra fold rate against our seat")
    ap.add_argument("--adaptive-off", default="", metavar="LIST",
                    help="with --adaptive: comma list of components to switch off (sensitivity checks): postflop, "
                         "shown, hero, exploit3, fold3, union, light4 (clone_adapt.COMPONENTS)")
    args = ap.parse_args()
    if (args.no_hero_level or args.adaptive_off) and not args.adaptive:
        ap.error("--no-hero-level / --adaptive-off need --adaptive")
    off = [x.strip() for x in args.adaptive_off.split(",") if x.strip()]
    adaptive = (os.path.abspath(args.adaptive), args.no_hero_level, off) if args.adaptive else None
    if adaptive and not os.path.isfile(adaptive[0]):
        sys.exit("no adaptive parameter file %s (python3 adaptive_fit.py writes it)" % adaptive[0])

    src = get_source(args.opponents, adaptive)
    if args.list:
        w = src.weights()
        field = set(src.field_names())
        print("%s opponents (%d; '*' = sampled by --field, weight = hands observed):" % (src.kind, len(w)))
        for nme in sorted(w, key=lambda x: -w[x]):
            extra = getattr(src, "index", {}).get(nme, {})
            print("  %s %-28s weight %-7g %s" % ("*" if nme in field else " ", nme, w[nme],
                                                 extra.get("rule", "") if isinstance(extra, dict) else ""))
        return
    if args.selftest:
        sys.exit(0 if selftest(args) else 1)
    if not args.cand:
        ap.error("--cand is required")
    args.cand = os.path.abspath(args.cand)
    args.base = os.path.abspath(args.base)
    for p in (args.cand, args.base):
        if not os.path.isfile(p):
            sys.exit("no such bot file: %s" % p)
        try:
            load_module(p, "check").Agent   # fail fast on a broken file
        except Exception:
            sys.exit("cannot load %s:\n%s" % (p, traceback.format_exc(limit=4)))
    gc.enable()   # the check-load above may have disabled gc in the parent; keep the parent clean
    if args.field is None and not args.table and not args.table_file:
        args.field = 6
    procs = max(1, min(args.procs, 6))
    jobs = plan(args, src)
    cand_lab, base_lab = label_of(args.cand), label_of(args.base)
    name = args.name or (cand_lab if args.base == os.path.abspath(DEFAULT_BASE) else "%s_vs_%s" % (cand_lab, base_lab))
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    tables = sorted({tuple(j["opps"]) for j in jobs})
    print("duel %s vs %s: %s opponents, %d seeds x %d rotations = %d pairs (%d tables of %d hands), %d procs" % (
        cand_lab, base_lab, src.kind + (" (ADAPTIVE%s%s)" % (", no hero level" if args.no_hero_level else "",
                                                             (", off: " + ",".join(off)) if off else "")
                                        if adaptive else ""),
        args.seeds, len(jobs) // max(1, args.seeds), len(jobs), 2 * len(jobs), args.hands, procs))
    if len(tables) == 1:
        print("table: us + " + ", ".join(tables[0]))
    else:
        print("%d different tables (--field %d), e.g. us + %s" % (len(tables), args.field, ", ".join(tables[0])))
    results, elapsed = execute(jobs, procs, src)
    rep, failed = summarise(results, args, src, elapsed)
    for f in failed[:3]:
        print("\nFAILED pair seed %d rot %d:\n%s" % (f["seed"], f["rot"], f["failed"]))
    if not rep.get("pairs"):
        sys.exit("no pair finished")
    print_report(rep, args, src, cand_lab, base_lab)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "duel_%s.json" % name)
    doc = {"config": {"cand": args.cand, "base": args.base, "opponents": src.kind,
                      "adaptive": ({"params": adaptive[0], "no_hero_level": adaptive[1], "components_off": adaptive[2]}
                                   if adaptive else None),
                      "seeds": args.seeds,
                      "seed0": args.seed0, "rotations": args.rotations, "hands": args.hands, "procs": procs,
                      "table": args.table, "table_file": args.table_file, "field": args.field, "limits": args.limits,
                      "created": time.strftime("%Y-%m-%d %H:%M:%S"), "opponent_files": src.fingerprint(),
                      "bot_sha1": {k: hashlib.sha1(v.encode()).hexdigest()[:12] for k, v in _BOT_CODE.items()
                                   if k in (args.cand, args.base)}},
           "report": rep, "pairs": [compact_pair(r) for r in sorted(results, key=lambda r: (r["seed"], r["rot"]))]}
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, default=float)
    print("\nsaved %s" % path)


if __name__ == "__main__":
    main()
