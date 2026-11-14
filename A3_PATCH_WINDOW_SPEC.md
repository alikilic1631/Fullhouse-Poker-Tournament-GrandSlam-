# A3-via-stats — Patch-Window Deployment Specification

## Status
**DEFERRED to the patch window** (not in the submission). Phase-2 firing probe showed
insufficient firing rate to justify building it pre-submission (see numbers below).
The submission remains **v13** (single-file `submission/bot.py`).

## Why deferred (precision audit evidence)
`sandbox/precision_audit.py` (v13 vs field-mix, 40 tables x 400 hands = 16,000 hands).
The spot itself is reasonably common; the strict observation gate is what blocks A3.

| filter | count | per match |
|---|---|---|
| river HU facing a bet | 292 | 7.30 |
| + bet>20%pot AND pot>1500 (A3-eligible spot) | **168** | **4.20** |
| + opp `cbet_obs` >= 5 (relaxed) | 70 | 1.75 |
| + opp `cbet_obs` >= 15 (mid) | 6 | 0.15 |
| + opp `cbet_obs` >= 30 (strict) | **0** | **0.00** |
| + cbet_obs>=30 AND bluff_obs>=30 (STRICT A3 gate) | **0** | **0.00** |

Per-spot opponent-observation distribution: cbet_obs p50=3, p95=13, **max=27** across all
168 eligible spots. Bluff_obs p50=23, p95=85.

**Bottleneck = the strict observation gate, not spot frequency.** 6-max + 400-hand
rotation simply cannot accumulate 30 cbet observations on a SPECIFIC opponent. At the
relaxed cbet>=5 gate (1.75/match) we are below the >3/match threshold to reconsider
building, and building combo-level range estimation without enough data is the v10
overfit failure mode. (An earlier looser probe reported 0.68/match because it gated on
v13's `aggression` count, which accumulates faster than cbet observations.)

## Trigger conditions for patch-window deployment
Build/ship A3 on D2 ONLY IF the D1 hand histories show ALL of:
- `sandbox/loss_analyzer.py` on our D1 hands shows a **river-HU facing-bet** leak that
  is large cumulatively (> ~5,000 chips/match) and clusters in spots where we DO have
  enough observations on the villain. Re-run `sandbox/precision_audit.py` against the
  D1-tuned `field_sim` distribution; require **either** (a) strict-gate fires/match >= 2
  (cbet_obs>=30 AND bluff_obs>=30), **or** (b) relaxed-gate fires/match >= 3 with the
  estimator gracefully degrading at lower observation counts. (In the v13 baseline run
  the strict gate yields 0 spots in 16,000 hands; deployment requires evidence the
  D1 field structure provides more observations than this -- e.g. persistent opponent
  IDs across matches or fewer effective opponents.)
- Observed showdowns indicate our equity estimate is systematically off (our river
  call/fold EV diverges from realized results by > ~5 pts) — i.e. a *range* estimate
  would actually change decisions, not just confirm them.
- v13 (or the chosen patch base) loses measurably in river-HU spots vs the D1 field.

## Implementation scope (deliberately narrow — copy from the Phase-3 spec)
- **River decisions only** (never flop/turn). **Heads-up only** (multiway → existing path).
- Facing a meaningful bet (> 20% pot) and pot > 1500.
- Villain has >=30 observed actions on the gating stats.
- Combo-level, **prior-blended** range weights (blend opponent stat with population prior
  by confidence = min(1, n_obs/threshold)); bail to the existing equity path if the
  estimated range has < 10 combos or effective-sample-size < 20.
- **Deterministic seeded** weighted MC (seed = md5(hand_id|hero|board)) so paired-seed
  benches stay reproducible; Wilson-CI early stop + ~200ms cap.
- Mandatory diagnostics: fired count, action-change count, ESS distribution, skip reasons.
- NOTE: v13 currently tracks only `fold_to_bet / aggression / shove_frequency /
  bluff_propensity`. A3's flop/turn-action narrowing needs `cbet_freq` (and optionally
  `turn_bet_freq`); either add those trackers in `update_opponent_memory` first, or
  drive the value/bluff split from `bluff_propensity` + `aggression` only.

## Validation gates (ALL must pass before shipping in the patch window)
- **Replay D1 hands**: A3 must change our decision in the observed losing river-HU spots.
- **Activity**: A3 changes the action in >= 25% of its fires (not just confirms), ESS >= 30
  in >= 90% of fires; manual inspection of 5 random fires is strategically sensible.
- **Improve**: paired-seed vs the base, > +500 chips vs `solver_approximator` HU.
- **No regression**: held-out enemy zoo median no worse than -500; field-mix robust
  (primary AND llm_heavy) not regressed; large-pot punt count (< -7000) not increased.
- **Robustness**: 0 crashes/timeouts/invalid; p99 <= 500ms; fuzz 0 new failures.

## Revert criteria during the patch window
- Any validation gate fails; weight collapses onto implausible combos; build+validate
  exceeds ~4 h of D2 time; A3 changes any non-A3 behavior (integration bug); any doubt
  on correctness during manual inspection. **When in doubt, revert — v13 is strong.**

## Patch-window time budget
- D2 priority order: (1) re-tune `field_sim` from D1 archetype frequencies, (2) pick a
  pre-built `PATCH_WINDOW.md` adjustment (Adj-A/B/C) if a clear field signal appears,
  (3) A3 only if the trigger conditions above are met and time remains (max ~4 h).
