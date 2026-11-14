# FullHouse Poker AI — Final Submission

## Submission file
- **Path:** `submission/submission_v15_6.zip` (`.zip` containing `bot.py` + `data/equity_tables.npz` + `data/rio_index.npz`)
- **Zip size:** 171,316 bytes (well under the 250 MB total limit)
  - `bot.py`: 77,348 bytes / 2,230 lines (comments + docstrings stripped)
  - `data/equity_tables.npz`: 89,184 bytes
  - `data/rio_index.npz`: 4,784 bytes
- **Zip SHA-256:** `06ca2c5d0124500dbb085dce9438dbb822901c27ebfad0d75bc077802e0f020a`
- **bot.py SHA-256:** `679f535287184ffe533dc353f99d466eb713160f1e134faf8c1fbf48e3c761df`
- **Version:** **v15.6** (= v15.5 + RIO_INDEX as nut_danger amplifier upstream of K).
  Canonical commented source at `fullhouse-engine/bots/v15_6/bot.py` (110,647 bytes /
  2,763 lines). Stripped submission paired-bench byte-identical to source.
- **Dependencies:** stdlib (`os, re, time, math, random, hashlib`) + `eval7` +
  **`numpy`** (Patch 8 explicitly permits numpy). No scipy/sklearn/treys/flask/joblib.

## D2/finals patch chain (v14 → v15 → v15.5)
- **v14 (D2 patch):** preflop overcommit fix (deep AKs flat-call vs 4-bet, tighter
  preflop all-in calling) + GPT-refined stack-off governor chain (Patches A–E).
- **v15:** Patch I (deep MC on critical decisions, 50k iter, 1.5s budget) +
  Patch J (precomputed equity tables in `data/`, ~87 KB, 4 tables).
- **v15.5 (this submission):** Patch K (multi-candidate EV simulation at runtime
  using opponent's observed stats — no offline training, no distribution shift).
  K fires when commit ≥ 40%, runs 5000-iter MC per candidate with strict 500ms
  total budget. Patch I's budget reduced 1.5s → 1.0s when K will fire so total
  decision stays under 1.85s. K_FIRED ~1.4/match, K_TIMED_OUT 0, K_CHANGED_ACTION
  91% of fires.

## D2 patch (v14-final) — preflop overcommit fix + stack-off governor chain
After analyzing 46 real qualifier matches in `prevmatches/`, the dominant leak was
**preflop over-commitment**: 92% of big-loss hands (235/257) had their punt-street =
preflop; 101 hands of deep preflop all-ins averaging **−18,362 chips/hand**
(cumulative −1,854,619 chips lost to one bucket). The real qualifier field 4-bets /
5-bet-shoves far more often than our local synthetic field; v13's deep 5-bet shove
with AKs (and the all-in-call thresholds) ran into value over and over.

Two surgical changes (canonical source at `bots/v14/bot.py`):
1. **Deep-stack 4-bet response** (`preflop_decision` line 592 + HU equivalent line 516):
   when `eff_bb > 30` and facing a real 4-bet (not min/small), **AKs flat-calls
   instead of 5-bet-jamming**. KK+ still shoves. Preserves implied odds, postflop
   handles the spot.
2. **Tighter all-in calling** (`preflop_allin_equity_decision`): base `rf` raised
   1.10 → 1.25 (env-tunable `PRE_AI_FOLD=0.15`). Need ~15% more equity edge before
   calling a preflop shove.

Validation:
- Paired-bench v13 (A) vs v14 (B) on held-out 5-bot field (25 seeds × 400 hands):
  median Δ = 0, 1 win / 0 losses, **no regression**.
- field_sim primary (40 tables × 400 hands, seed 2000): robust_score 25,008 → **25,687**
  (+679); cumulative +748,724 → **+827,620** (+10.5%); **punts (<-7000) 11 → 8**
  (mechanism-correct: fewer preflop punts).
- field_sim seed 3000: identical (patch fires rarely in local field). At-worst neutral.
- Mechanism is directly justified by the qualifier hand-history evidence, not by
  out-of-sample tuning.

### Layer 2 — GPT-refined stack-off governor chain (5 patches)
The preflop fix alone covered the 92% of big-loss hands that were preflop, but not
the postflop stack-off pattern. The governor chain extends defense to postflop:

1. **PATCH B — Worse-Hands-That-Call test** (raises/all-ins only): when a raise
   relies on fold equity (hero is weak made / air on postflop), downgrade to call/fold.
2. **PATCH D — Trap-line dampener**: detect check-raise / call-then-raise patterns
   in villain's action sequence; if score ≥ 3 and hero isn't nutted, downgrade.
3. **PATCH A — Nut-disadvantage stack-off governor**: when commit ≥ 40% of stack,
   compute board-and-villain-line danger score; if danger ≥ 2 and hero is
   marginal (TP / overpair / two-pair / set on dangerous board), downgrade.
4. **PATCH C — Street-specific commitment threshold paired with danger**: required
   equity for 40%+ commit = base (flop 0.62 / turn 0.58 / river 0.52) + 0.04 ×
   danger, capped at 0.85.
5. **PATCH E — Selective river MDF** (river only, blocker required, never overrides
   A/C vetoes, only flips fold → call): bluff-catch when villain shows bluff
   propensity > 0.30 AND we hold a relevant blocker.

All governors fire **after** the existing strategy returns a concrete action and
**before** legality mapping. Always active — no env switch.

### Validation gates (user-specified)
| Gate | Result | Status |
|---|---|---|
| Robustness 0/0/0, p99 ≤ 1.2s | 6035/6035, max 61.83 ms | ✅ |
| Upside preservation ≥ 0.85 | ratio **1.06** (47,164 / 44,369) | ✅ |
| solver_approximator HU neutral or better | median Δ = 0, mean Δ = −144 (≫ −1500) | ✅ |
| Held-out enemy zoo median ≥ −1500 | **+3,046** | ✅ |
| Held-out mean | **+4,961** | ✅ |
| Held-out p5 (worst case) | **+2,828** (−10,000 → −7,172) | ✅ |

### Trade-off honestly reported
field_sim primary (40 tables, seed 2000) regresses by **−6,632 robust** vs v13.
This is *not* in the user's revert criteria. The cause is field_sim's heavy
weighting of passive callers (tight_value, call_station, fit_or_fold = ~19%
combined) — vs them, our refined raise-restraint costs thin value. **The real
qualifier field is closer to the held-out distribution (aggressive + tight
value) than to field_sim's passive-heavy mix.** The trade-off (give up some
thin value vs passives to stop stacking off vs aggressives) is the trade-off
the qualifier hand-history evidence justifies.

### Governor firing rates per match (~408 decisions/match)
PATCH B 13.6 · PATCH D 1.2 · PATCH A 1.3 · PATCH C 0.5 · PATCH E 0.07. Rates
align with the design intent (B does most of the work suppressing low-equity
raises; A/C/D/E catch the specific high-risk stack-off patterns).

## Submit (per `submission/SUBMISSION.md`)
1. (Recommended) re-validate locally:
   ```bash
   source ~/anaconda3/etc/profile.d/conda.sh && conda activate fullhouse
   cd "/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/fullhouse-engine"
   python sandbox/validator.py ../submission/bot.py      # expect ✅ PASSED
   ```
2. Go to **https://portal.fullhousehackathon.com** and upload
   `submission/bot.py` (or paste its contents; `pbcopy < submission/bot.py`).
3. **Deadline: 31 May 2026, 23:59 UTC.** Re-uploads allowed; only the most recent counts.
   Bot ID is stable across qualifier → patch window → finals.

## Final verification (this session)
- `validator.py` → ✅ PASSED (all 4 scripted spots).
- `fuzz.py --n 6000` → 6035/6035 passed, 0 crashes / 0 timeouts / 0 illegal; max decide 43 ms.
- Final subprocess matches (vs shark seed 9999; vs aggressor seed 1234) → 0 errors.
  These confirm **safety and packaging correctness** under the real engine path;
  EV/performance was established earlier by paired-seed and field-mix validation
  (see SUBMISSION_REPORT.md Patch-19 / Phase-2 / Precision-audit sections, not by
  any single 2-seed match).
- Patch-15 audit: imports clean, no dangerous calls, single file < 5 MB.

## Final version composition (v0 → v13)
- **v0** — "cannot die" safety baseline (always legal action)
- **v1** — positional preflop ranges (hand-authored blueprint)
- **v2** — postflop strategy table (infoset → action-prob vector, nested fallback)
- **v3** — multiway tightening (Layer 1, rules)
- **v3.5** — size-aware preflop defense vs non-standard raise sizes
- **v4** — Bayesian opponent stats (weak priors) + bounded λ-perturbation (Patch 1/6)
- **v5** — eval7 adaptive-MC equity + equity-vs-range + multiway Layer 2
- **v6** — deterministic mix-sampling + bet-size bucketing (Patch 9/10)
- **v7** — irregular adversarial bet sizing (orthogonal vs the modal LLM field)
- **v8** — blocker-aware river overrides
- **v9** — heads-up branch (wider ranges, SB=button)
- **v12** — content-neutral hardening (score-aware last ~50 hands + time-budget guard)
- **v13** — failure-mode fix: tightens marginal turn/river call-downs vs
  value-heavy *non-flagged* opponents (`RIVER_FOLD=0.50`), gated OFF vs flagged bluffers.
  Beats v12 on field-mix primary (robust +25,008 vs +24,024) and held-out (+2,025, w4/l0).
- **v14 (SHIPPED)** — D2 patch-window: deep-stack AKs flat-calls vs 4-bet (no more
  blind 5-bet jam); preflop all-in calling needs +15% more equity edge. Targets the
  101-hand / −1.85M chip preflop-overcommit leak observed in 46 qualifier matches.
  Field_sim primary robust +679, punts 11 → 8; held-out no regression.

## Disciplined negative results (each got a specific level of evaluation)
- **v10 (LR bet-sizing)** — FULL BUILD + validation. Rejected: paired held-out −2,164;
  field-mix robust regressed +18,968 → +16,930. Redundant with v4 perturbation +
  wrong target (P(fold) ≠ best action). Retained in `bots/v10/` as paper trail.
- **v11 (river LP)** — GATED OUT before build ("only if all gates clean"; v10 failure +
  same redundancy hypothesis).
- **B2 (push/fold Nash tables)** — FULL BUILD: chip-EV Nash solver + 100% chart-validated
  monotone table (`training/solve_push_fold.py`) + integration into `bots/v14/` + paired
  bench + instrumented branch-firing check. **REVERTED**: paired vs `short_stack_jammer`
  B−A = exactly 0 on all 30 seeds; the precision audit confirms hero first-in <15bb
  decisions occur 22 / 11,221 = **0.196% (0.55/match)** — fixed blinds (no escalation,
  100bb start) leave the branch with ~no surface area. Math correct; spot doesn't exist.
- **A3 (river-HU range-estimated equity)** — FIRING PROBE ONLY (not built). Spot itself
  occurs 4.20/match (common), but the strict observation gate (cbet_obs≥30 AND
  bluff_obs≥30) yields **0 of 168 eligible spots** — across 16,000 hands the maximum
  cbet observations on any opponent was 27, so 6-max + 400-hand rotation cannot
  accumulate enough opp data. Bottleneck = the observation gate, not spot frequency.
  Relaxed gates (cbet≥5) still yield only 1.75/match, below the >3/match threshold to
  reconsider building. See `A3_PATCH_WINDOW_SPEC.md`.

## Patch-window readiness (D2)
- `V13_WEAKNESS_CATALOG.md` — D1 parametric weakness discovery (diagnostic).
- `PATCH_WINDOW.md` — 5-step D1→D2 workflow + decision tree + pre-built Adj-A/B/C recipes.
- `A3_PATCH_WINDOW_SPEC.md` — pre-built A3 spec + trigger conditions + gates.
- `analytics/field_analysis.py` — field profiler (selftest-verified; adapt `normalize_record`).
- `sandbox/loss_analyzer.py` — loss-by-spot leak finder.
- `sandbox/field_sim.py` — field-mix metric (re-tune `FIELD_DISTRIBUTION` from D1).
- `sandbox/weakness_discovery.py`, `sandbox/pushfold_freq_probe.py`,
  `sandbox/a3_freq_probe.py` — diagnostic probes.
- `bots/v10/` + `training/train_lr.py` — v10 LR ready to re-deploy if D1 shows a
  round-sizing, fold-y field.
- `bots/v14/` + `training/solve_push_fold.py` — B2 push/fold ready if blinds escalate.

## Key takeaways
- The edge over the modal LLM-built field comes from: multiway tightening, irregular
  bet sizing, the heads-up branch, bounded opponent-stat perturbation, blocker-aware
  river play, size-aware preflop defense, and the v13 value-respect call-down fix.
- v10, v11, B2, and A3 each got the level of evaluation justified by prior evidence —
  full build+validation (v10, B2), gate-out before build (v11), or firing-rate probe
  (A3). The rule held throughout: *trust the gates, ship only what's validated.*
