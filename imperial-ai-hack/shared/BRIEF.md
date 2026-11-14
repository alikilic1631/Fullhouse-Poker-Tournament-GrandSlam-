# Imperial AI Hack — Pokerbots: build brief

The live tournament is running **today**. We need one file, `bot.py`, that wins the most
chips (bb/100) against other teams' bots. This brief is the shared context for everyone
working on it. Paths below are relative to `/Users/mehmet/Desktop/AI Hackathon` (note the
space in the path: always quote it in shell commands).

## 1. Where things are

| path | what |
|---|---|
| `starter-kit/imperial-ai-hack-pokerbots-kit/README.md` | **Official rules + `state` format. Read it first, in full.** |
| `starter-kit/imperial-ai-hack-pokerbots-kit/engine/` | The exact tournament engine (`game.py`, `players.py`, `bot_runner.py`, `cards.py`). Do not modify. |
| `starter-kit/imperial-ai-hack-pokerbots-kit/local_sim.py`, `examples/` | Local simulator and three weak house bots. |
| `grandslam-bot/` | Our previous bot (GrandSlam) from another tournament. `submission/bot.py` is the shipped code, `README.md` / `FAILURE_MODES.md` / `V13_WEAKNESS_CATALOG.md` hold lessons. It needs eval7 + numpy and 2 s per decision, so it **cannot run here** — it is a source of ranges, heuristics and lessons, not a base to patch. |
| `shared/preflop_data.py` | Ready-to-paste, stdlib-only 169x169 preflop equity matrix (17 KB) + class indexing. |
| `shared/BRIEF.md` | This file. |

## 2. Hard constraints (violating any of these loses real chips)

- One file `bot.py`, class `Agent`, **Python 3.12, standard library only**, file **< 200 KB**
  (stay under 150 KB). No network, no file I/O, 512 MB RAM, one CPU core.
- **10 ms per decision, wall clock, including the JSON round trip**, and a **10 s bank per
  round** (1,000 hands) summed over all our decisions. A late answer is auto-played as
  check, else **fold** — a timeout with a strong hand facing a bet throws the pot away.
  Once the bank is empty every remaining decision is check/fold.
- The tournament sandbox CPU is probably **2–3x slower** than this laptop. Budget for it:
  on this machine aim for p99 <= 2.5 ms and max <= 4 ms of our own compute per `act`, and
  <= 3 s of total think time per 1,000-hand round. Use a `time.perf_counter()` deadline
  inside every loop (check it every ~32–64 iterations), never a fixed iteration count
  alone. Track cumulative time spent this round and degrade (fewer samples, then
  table-only play) if a per-round budget (say 6 s) is being approached.
- `on_hand_end` runs in the same process and is processed in order before the next `act`
  message, so slow `on_hand_end` code eats the next decision's 10 ms. Keep it < 0.3 ms.
- Module import and `Agent()` construction each have ~5 s. Building lookup tables at
  import is fine if it takes < 1 s here.
- Consider `gc.disable()`/`gc.freeze()` after table building so a GC pause cannot blow a
  decision; avoid per-decision allocations of reference cycles.
- `act` must **never raise**. Wrap everything; on any exception fall back to a cheap,
  sane action (check if legal; otherwise call only if pot odds are tiny; otherwise fold).
- Errors, crashes, floods of output, or heavy CPU use when it is not our turn get the bot
  stopped and flagged. No `print` in the shipped file.
- Python 3.12 syntax only (this laptop runs 3.14 — do not use newer features).

## 3. The game (what makes this format special)

- No-Limit Hold'em, **7 or 8 bots per table**, 1,000 hands per round, same seven
  opponents all round. A fresh `Agent()` per round: we learn opponents from scratch each
  round, and what we learn lasts 1,000 hands.
- **Every hand starts everyone at 2,000 chips (100 bb), blinds 10/20, no antes.** Nobody
  busts, there is no ICM, no stack management across hands, no tournament survival.
  It is a pure cash game: maximise chip EV on every hand. Risk aversion is only useful
  as protection against our own model error, never for its own sake.
- Score = big blinds won per 100 hands. Folding everything = about -19 bb/100. In the
  practice standings the top bots made +60 to +110 bb/100 and the worst lost -100 to
  -500 bb/100: **the field contains huge donators** (maniacs, shove-bots, stations,
  buggy bots) next to competent bots. Most of the edge is in exploiting the weak bots
  hard while not paying off the strong ones.
- The organisers may switch to pot-limit / fixed-limit or set a raise cap; `state`
  carries `betting`, `raise_cap`, `min_raise_to`, `max_raise_to`. Always clamp raises to
  `[min_raise_to, max_raise_to]` and only raise when `"raise"` is in `legal_actions`.
- Engine facts worth knowing (from `engine/game.py`):
  - `state["pot"]` already includes this street's bets; `state["stacks"]` excludes them;
    `state["bets"]` is per-seat chips in front this street; `to_call` is capped by stack.
  - Raises are "raise to" totals for the street. `{"action": "all_in"}` = raise to
    `max_raise_to` when raising is legal, otherwise a call.
  - `history` is every action this hand: `{"seat", "street", "action", "amount"}` with
    `small_blind`/`big_blind`/`fold`/`check`/`call`/`raise`. A postflop first bet is
    recorded as `raise`. For `call` the amount is chips added.
  - Preflop the first actor is left of the big blind; postflop it is the first live seat
    left of the button. Heads-up-at-the-table never happens (7–8 seats), but pots are
    often heads-up or 3-way postflop.
  - `on_hand_end(summary)` is called for every seat every hand with the **full history**
    and `shown` (hole cards of every player who reached showdown, keyed by seat as a
    string) — this is the main source for opponent modelling, including hands we folded.

## 4. The architecture to implement (Hyperion-style, the user asked for this explicitly)

Hyperion won the Fullhouse 2026 UK final. Its write-up boils down to one rule:
**never alter the core decision logic; alter its inputs.** Four layers:

1. **Decision engine ("GTO core")** — makes every decision from an equity number and
   fixed, opponent-independent thresholds.
   - Preflop: position-correct ranges as *frequency* tables (opens, 3-bets, 4-bets,
     defends per position; e.g. BTN opens ~45%, earliest position far tighter).
   - Postflop equity thresholds (vs the *adjusted* villain range): roughly >= 0.76 value
     bet / raise; >= 0.55 bet for value in position, check out of position; >= 0.42
     pot-odds call; below that fold or a rare steal.
   - River facing a bet: defend near minimum defence frequency,
     `MDF = pot_before_bet / (pot_before_bet + bet)`, so we are not auto-bluffable.
   - C-bet / barrel frequency from continuous board-texture features (paired, monotone,
     connected, high-card): bet dry/paired boards more than wet connected ones. Sizing is
     position- and opponent-aware (bigger value bets vs calling stations).
2. **Opponent model** — per-opponent statistics with Beta priors centred on population
   averages (VPIP, PFR, aggression factor, mean bet size, fold-to-cbet by texture, fold
   to 2nd/3rd barrel, donk and check-raise frequency, showdown strength), plus an
   archetype classifier (balanced, caller/station, pot-odds bot, randomised, rule-based,
   shover, tight-aggressive). Useful signals: fold rate at cheap / medium / expensive
   prices, and the gradient between them (separates "folds because the price is bad"
   from "folds everything").
3. **Exploit bridge** — the only job of the exploit layer is to answer "what range does
   this opponent hold?". It widens or tightens villain's range; it never touches
   thresholds or actions.
   - Station/caller: widen (weak suited/offsuit junk stays in) -> our equity estimate
     moves and thin value bets appear on their own.
   - Nit/folder: tighten — when they continue they have it.
   - Perma-all-in/shover: blend towards a near-random range; their aggression carries
     little information.
   - Maniac: widen their raising range; raises mean less than average.
   - Solid/GTO-like: slight tightening.
   - **Dynamic gating:** below ~20 observed actions from an opponent use the base range
     unchanged; ramp the adjustment in gradually and trust it fully only at ~60+
     observed actions. Gradual activation is what stopped overreaction to small samples.
4. **Range-aware equity engine** — Monte Carlo equity sampling villain hands from the
   adjusted range, not uniformly. Pipeline: identify the aggressor's preflop action
   (open, 3-bet, limp, cold call...) -> pick the base range -> narrow it postflop by the
   number of postflop raises (0: full preflop range; 1: medium-strength+; 2+: strong;
   all-in: strongest), tighter narrowing on wet boards -> apply the exploit adjustment
   -> simulate -> hand equity to layer 1.
   - Special signals: *passive rocket* — a confirmed passive opponent (raises < 10%,
     calls a lot) who suddenly raises gets the strongest tier. *Big bet* — a bet far
     above that opponent's own average size upgrades the range to strong.

Risk controls from the same write-up:
- **Variance penalty:** when a call/bet risks more than ~10% of the effective stack,
  `required_equity = pot_odds + c * risk_pct**2`. Keep `c` small here (chip EV format):
  it is insurance against range-model error in big pots, not risk aversion.
- **SPR-aware commitment:** a sigmoid in stack-to-pot ratio — at low SPR commit with
  less equity, at high SPR demand more before stacking off.
- Hyperion's "match standing" adjustment does **not** apply here (stacks reset every
  hand) — leave it out.

## 5. What to carry over from GrandSlam

- Its preflop range strings (`OPEN`, `VS_OPEN_3BET`, `VS_OPEN_CALL`, blind defence,
  `VS_3BET_*`, size-aware defence widths) are for 6-max; extend to 8-max by adding
  tighter early positions and by using fractions of a ranked 169-hand list.
- Lessons that held up in validation: narrow structural triggers beat broad heuristic
  modulation; cap `all_in` specifically rather than all aggression; be careful stacking
  off preflop in 3-bet+ pots without JJ+/AK **against tight ranges**; respect a river
  card that pairs the board, more so multiway; multiway continuing ranges are much
  stronger than heads-up ones; Beta posteriors with population priors.
- Its unshipped backlog is exactly what the Hyperion bridge provides: per-opponent
  fold-rate tracking by bet size, and a strength model for the villain's calling range.

## 6. Speed: a pure-Python evaluator that fits in 10 ms

eval7 is not available, so equity has to come from a fast table-driven evaluator.
Recommended design (verify, then use or beat it):

- Card int `c = rank*4 + suit` (rank 0..12 for 2..A), same as `engine/cards.py`.
- **Rank key:** `RK[c] = 5 ** rank`. The sum over a hand's cards is unique per rank
  multiset. Precompute `NOFLUSH[key] -> strength int` for every 5-, 6- and 7-card rank
  multiset (about 74k entries, well under 1 s to build, a few MB).
- **Suit key:** `SK[c] = 8 ** suit` (3-bit counter per suit); `FLUSH_SUIT[sum]` (4096
  entries) gives the suit with >= 5 cards or -1. Only then build the 13-bit rank mask of
  that suit and look up `FLUSH[mask]` (8192 entries; best five incl. straight flushes).
  With 7 cards a flush can never coexist with quads or a full house.
- Strength int = `category << 20 | kickers`, comparable with `>`.
- In rollouts, add the board + hole partial sums once and only add the sampled cards per
  iteration: ~0.2–0.4 us per 7-card evaluation, so ~1,500 heads-up flop rollouts or an
  exact river enumeration of a whole range (<= 1,081 combos) fit in ~2 ms here.
- River: enumerate the weighted villain range exactly (no sampling noise). Turn/flop:
  sample (villain combo, runout). Multiway: sample each villain from their own range,
  fewer iterations.
- **Correctness test is mandatory:** compare against `engine.cards.evaluate` ordering on
  at least 200k random 5/6/7-card hands (same ordering, same ties).
- Preflop needs no simulation: use `shared/preflop_data.py` (`PF_EQ[a][b]`, 169x169) to
  get equity of our class vs a weighted villain range in microseconds — ideal for
  calling or folding against open-shoves and 3-bet/4-bet jams with the *measured*
  jamming frequency of that opponent.

## 7. Turning opponent statistics into ranges (the bridge, concretely)

A good default: "villain's range for an action is the top `p` of hands for that action,
where `p` is how often *this* villain takes that action in that spot", shrunk towards the
population prior by the gating weight `g = clamp((n_obs - 20) / 40, 0, 1)`.
Examples: an opponent who open-raises 55% of hands has a top-55% raising range; one who
shoves preflop 30% of the time has a top-30% shoving range (call much wider than vs a
top-4% shover); one who bets the flop 90% of the time when checked to has a nearly
unnarrowed betting range; one who raises postflop 2% of the time has the nuts.
Soft edges (weights, not hard cut-offs) make this robust. Showdown data (`shown`) can
calibrate it: what did they actually hold when they bet big / shoved / called down?

Fold equity for bluffs and thin bets should come from the same model (the share of the
villain's adjusted range that continues, and their measured fold-to-bet by size), so
bluffs appear against folders and disappear against stations without special cases.

## 8. Opponent types to expect and what beats them

- **Stations** (call everything): never bluff; value bet thinner and bigger; 3 streets.
- **Maniacs / random raisers:** call down lighter, let them bluff, 3-bet/4-bet for value
  wider, do not fold decent pairs to noise.
- **Preflop shove-bots:** call with the correct equity range vs their measured shove
  frequency (this is the single biggest source of bb/100 in fields like this), fold the
  rest, do not bluff-raise them.
- **Nits / rule-based TAGs:** steal their blinds relentlessly, c-bet small and often,
  fold when they wake up.
- **"Equity vs random + thresholds" bots** (the typical quickly written bot): they
  over-value weak made hands against strong ranges and fold too much to big bets on
  scary boards; they rarely bluff-raise.
- **Strong adaptive bots:** stay close to the unexploited baseline against them.

Multiway is the norm preflop at an 8-seat table with loose bots: tighten value ranges
with more players, bluff far less into several opponents, and count the dead money.

## 9. Definition of done for any bot file

1. Loads and plays under `python3 local_sim.py <path>` with **0 timeouts, 0 errors,
   0 bank-outs** over >= 10 rounds, and think time well under 3 s per round here.
2. Legal in every structure: also run `--betting pot_limit`, `--betting fixed_limit`,
   `--raise-cap 3`, and 7-seat tables.
3. Evaluator verified against the engine.
4. Positive and large vs the house bots (they are weak; a good bot beats that table by
   several hundred bb/100) **and** not exploitable by simple archetypes (nit, maniac,
   shove-bot, station, equity-threshold bot).
5. Under 150 KB, stdlib only, no prints, no file/network access, Python 3.12 compatible.

Poker results are noisy (std dev roughly 80–120 bb/100 over a single 1,000-hand round).
Do not tune on a handful of rounds: use many hands, fixed seeds, and A/B comparisons on
the same seeds. In-process play (`engine.players.LocalPlayer`) is much faster than
subprocess play for strategy testing; use subprocess play to validate timing.
Other agents are running simulations on this laptop at the same time: run one simulation
at a time, and judge timing by the time measured inside `act`, not only by the
simulator's timeout counter (CPU contention can cause spurious timeouts).
