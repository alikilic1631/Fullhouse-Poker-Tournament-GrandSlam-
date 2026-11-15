# v11: what changed from v10, and the evidence

v11 is `v10/bot.py` with switchable changes; every switch is a `V11_*` constant near the top. It was built Saturday 14 Nov 2026 from the 36-round diagnosis in `../DIAGNOSIS_v17.md`.

## Changes that are ON

| Switch | What it does | Why (real-log evidence) |
|---|---|---|
| `BET_P` = (0, .60, .56, .47) | Population bet-when-checked-to priors set to the values measured in R19–R54 | v10's priors were .55/.48/.39 |
| `V11_MDF_ALWAYS` | The river minimum-defence floor works against every opponent, not just unknown ones | v10's floor fired in 3 of 180 river calls; our heads-up river calls won 66–71% when the bot estimated 49% |
| `V11_RIVER_CATCH` | Heads-up river, facing a bet of at most 0.6 pot, with top pair or better: call instead of fold | The field's small river bets are 26–37% air |
| `V11_PRICE_GUARD` = 0.25 | The stack-off and one-pair guards only fire when the price is at least 25% of the final pot | v10 folded AA, QQ and a full house getting 4–5:1 (R53 h350, R40 h323, R35 h771) |
| `V11_JAM_FIX` + `V11_PF_VPEN` = 0.04 | A re-jam over **our** raise, heads-up with no third raiser, uses the opponent's re-raise rate with a 25% floor, not his open-shove rate. Looser shove calls (lower variance penalty, cap scaled to the jammer's measured width) apply only in clean heads-up spots. Multiway spots keep v10's logic. | v10 read every re-jam as AA-only and folded KK, QQ ×9 and AK ×10 |
| `V11_3BET_DEF` | New counter: how often each opponent 3-bets *our* opens. Against wide 3-bettors (modelled range ≥ 12% of hands) v11 continues wider (in position up to hp 0.20). It 4-bet-bluffs only against measured 4-bet folders (≥ 4 observations, fold ≥ 65%). | FisherMen (Sunday tablemate) 3-bets our opens 29% and folds 83% to 4-bets |
| `V11_FLOP_RZ` = 0.85 | On the flop, call EV for weak pairs or air without a flush draw or open-ended straight draw is multiplied by 0.85 | Thin flop calls cost −2.4 bb/100; those hands realise 0.64–0.75 of their equity |
| `V11_MC_DL` 5 ms, `V11_UPD_DL` 3 ms, `V11_OVERHEAD` 1 ms, 9 ms Monte Carlo skip | Time budgets for the real 25 ms limit. The bank counter includes transport time. Monte Carlo is skipped if a decision is already 9 ms in. | On the server v10 got about 60 of 440 Monte Carlo samples, and 4–6% of range updates were skipped |

## Changes that are OFF (kept in the code, tested and rejected)

| Switch | Result |
|---|---|
| `V11_TFL` (global softening of range updates) | Made v11 call too much: +0.6 bb/100 with it vs +3.9 without (same deals); alone −2.6 ±1.0 |
| `V11_HONESTY` (per-opponent river air share) | Its pure-air gate blocked profitable top-pair bluff-catches: +3.9 with it vs +6.3 without (same deals) |

## Test results for the final file (SHA-256 `ec58f8579e6e4bee…`, 88,146 bytes)

All tests are paired against v10 on identical deals, in bb/100 with all-in luck removed.

| Test | v11 minus v10 |
|---|---|
| `duel.py` Sunday table, unseen deals 201–230 × 8 seats | **+6.6 ±1.0** (z 6.7) |
| `duel.py` Sunday table, unseen deals 301–330 × 8 seats | **+5.9 ±0.9** (z 6.3) |
| `duel.py --field 6`, random 7-seat tables (seeds 401+) | **+5.0 ±1.4** (z 3.4) |
| `simreal.py`, the 36 real line-ups | **+5.7 ±1.2** |
| `replaydiff.py`, 46,342 real decisions | EXACT +1.19, APPROX −0.10; agreement with live 97.1% |
| Biggest per-opponent gain at the Sunday table | **FisherMen +2.2 ±0.5** (our main rival for 2nd; their own result −15.3 → −18.6) |
| `timing.py`, 6 load processes, 3 rounds | 0 timeouts, 0 errors, 0 bank-outs; p99 2.5 ms, max 6.5 ms; projected server think 3.5 s mean, 4.8 s worst of 10 s |
| Official `local_sim.py`, 2 rounds | 0 timeouts, 0 errors |
| Fuzz, 120 tables, 34,487 decisions, all betting structures | 0 exceptions, 0 fallbacks, 0 invalid actions |

**Expectation:** the bench overstates absolute levels, and for calling changes roughly 2×. Expect about **+3 to +5 bb/100** in real play.

## Independent review (3 reviewers, Saturday 22:00–22:45)

| Lens | Verdict | Main checks |
|---|---|---|
| Robustness/timing | **ship** | 70k fuzz hands at 2–8 seats, all betting structures, slowdowns up to 40× and Python 3.11/3.13. 0 exceptions, 0 invalid actions, 0 `_safe` fallbacks. Suggested the 9 ms Monte Carlo skip (applied). |
| Poker logic | **ship** | Confirmed the two earlier draft bugs (one-pair jams caused by tempering; folding KK because of the raiser-behind rule) are gone in the final state, and that keeping tempering and honesty OFF is right. |
| Correctness | **ship after fixes** | Helpers matched brute force on 200k deals; `_learn` bookkeeping verified against an independent re-implementation. |

**Fixes applied after review:**
1. **Wide-3-bettor gate:** it now uses the measured width of his 3-bet range (`self.w3`, recorded before the 0.015 floor and the showdown mixing). Before, the inflated range mass made the gate fire in 73% of 3-bet spots, including against honest 3-bettors.
2. **River extensions:** the MDF extension and river catch apply only when facing a **single bet**, never a river raise. River raisers at our table hold top-20% hands 87% of the time.

**Left as is (minor):**
- the conservative 3-bet-vs-jam predictor;
- the b4 counter also counting openers caught between a 3-bet and a cold 4-bet (tiny exposure);
- optionally bluffing more 4-bets against FisherMen (`u <= 0.75`), which the bench cannot test.

## Time limits: margin validation (final file SHA-256 `a736257a…`)

**Two hard caps added after the release run.** They don't change any decision locally (replay identical within noise: EXACT +1.02, APPROX −0.10, agreement 97.1%).
- `V11_MC_SKIP` = 7 ms: skip the Monte Carlo if the decision is already 7 ms in.
- `V11_HARD_DL` = 10 ms: return the already-computed check/call/fold and skip the bet/raise search.

| Test | Limit used | Result |
|---|---|---|
| Official engine (subprocess, real transport), 6 busy load processes, 4 rounds | **10 ms per decision and 5 s bank** (real: 25 ms / 10 s) | **0 misses** in 4,931 decisions, max 3.1 ms |
| Same, earlier run of 3 rounds | 10 ms / 5 s | 1 miss in 3,718 decisions (one 23 ms machine stall; did not repeat) |
| Same, real limits, 3 rounds | 25 ms / 10 s | 0 misses, max 6.5 ms |
| Emulated slow server: bot clock sped up 6–12× (`timing_shadow.py`), Sunday table and a multiway-heavy table, + 2 ms transport | 25 ms | 99.9% of decisions under: v11 12.7–19.0 ms vs v10 16.4–27.2 ms. v11's tail is shorter than v10's at every speed. |
| Projected bank use per round (emulated 6–12×, + 1.5 ms per decision transport) | 10 s | 3.0–4.9 s; the bot also degrades itself at 4.0 / 5.5 / 7.0 s of counted time |

**Limits of this check:** zero misses cannot be guaranteed. The live v10's only identifiable miss was a preflop decision that needs under 1 ms of compute, i.e. a server-side stall. Every team had misses on Saturday (the top teams 38–80 over 54 rounds), at negligible cost (~0.05 bb/100). What is bounded is v11's own thinking time.

## v11.1 (SHA-256 `a635c437…`): timing safety and final-table scaling, same play

The previous file is kept as `v11/bot_a736257a.py`, and as `~/Desktop/bot_v11_backup.py`.

| Change | Why |
|---|---|
| Monte Carlo deadline 5 → **3.5 ms** (still 1.7× v10); skip 7 → **5.5 ms**; hard cap 10 → **8 ms**; update cut-off 3 → **2.5 ms** | The timing auditor showed v11's worst case at the real server speed was ~2 ms closer to the limit than v10's, so a server stall could cause slightly more misses. Now its worst case is at or below v10's. |
| Bank thresholds (4.0 / 5.5 / 7.0 s) scale with `info["hands"]` / 1000, capped at 5 | In a 5,000-hand final with a proportionally bigger bank, v11 would have throttled itself after ~2,000 hands. Rounds of 1,000 hands are unchanged (scale 1.0). |

**Validation:**

| Test | Result |
|---|---|
| Paired duel v11.1 vs v11 | **+0.2 ±0.6**: identical play |
| v11.1 vs v10, unseen deals 601–630 | **+7.0 ±0.9** (z 7.5) |
| Real-log replay vs v10 | EXACT +0.97, APPROX −0.10, agreement 97.1% (same as v11) |
| Emulated slow server, Sunday table, K = 6 / 10 / 12 | Max incl. 2 ms transport 8.7 / 11.2 / 13.3 ms (v10: 8.1 / 20.3 / 17.9) |
| Emulated slow server, multiway table, K = 6 / 10 / 12 | Max 9.1 / 11.5 / 26.7 ms (the 26.7 is one machine stall; p99.9 19.2 vs v10 21.9) |
| Independent timing auditor (adversarial tables, v11 with 10 ms cap) | Max 13.1 ms at K = 10–12; own compute reaches 25 ms only at K ≈ 28–30 |
| Official engine, 5,000-hand table, 50 s bank | 0 timeouts, 0 errors |
| Strict official run, 10 ms / 5 s bank, 6 load processes | 1 timeout in 5,005 decisions (one 31 ms machine stall under load ~10; v10 had a 19 ms stall in the same run) |
| Fuzz, 34,495 decisions | 0 exceptions, 0 invalid actions |

## Teammate bots compared (Sunday table, paired, deals 201–230 × 8 seats)

| Bot | vs v11 (bb/100) | Notes |
|---|---|---|
| `efe_bots/efe_bot_4.py` | **−8.5 ±2.2** (z −3.9) | VPIP 31 / PFR 26; about 6× v11's thinking time |
| `efe_bots/efe_bot_1.py` | **−15.9 ±2.2** (z −6.7) | 2 decisions over 25 ms locally (16–20 live misses per round on Saturday) |
| `efe_bots/original_ali_bot.py` | not runnable | needs eval7 / numpy / data files |

## How to turn a change off

Edit its `V11_*` constant and re-run the checks in `../testbench/README.md`, section 3.
