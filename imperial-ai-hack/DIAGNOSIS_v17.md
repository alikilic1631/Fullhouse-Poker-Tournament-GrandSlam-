# Why v17 falls short, and how to fix it

Diagnosis of the live bot (site v17 = `imperial-ai-hack/v10/bot.py`, SHA-256 `226c2ab4bbfb…`), Saturday 14 Nov 2026.

**Data:** the 36 rounds v17 played, R19–R54 (36,000 hands).

**Method:** one validated hand parser. Results sum to zero in every hand, and our per-round totals equal the site's.

**Analysts:** 11 ran independently: results decomposition, preflop, postflop, winners and extraction, big pots, versions and timing, two code readers, over-folding, under-folding, and loss anatomy. Several replayed real decisions through an instrumented copy of the bot.

**Units:** bb/100 over 36,000 hands unless stated otherwise.

## 1. Is it luck? No.

- All-in luck over the 36 rounds averaged −57 chips per round, and the cards we were dealt averaged +14. Both are about zero.
- Removing all-in luck for every player at each table, v17 finishes top 2 in **7 of 36** rounds; it finished top 2 in 8 of 36 for real.
- When we miss the top 2, the luck-free shortfall to 2nd place is a median of **~4,900 chips per round, about 24 bb/100**.
- Luck explains about 40% of the chips lost in our 11 losing rounds and 16% of round-to-round swings. It does not explain the gap.

## 2. Where the gap is: winning, not losing

| | v17 | Top-7 teams, same tables |
|---|---|---|
| Luck-adjusted bb/100 | +19.5 | +55.4 |
| Pots won uncontested as the aggressor | +42.3 | +74.7 (**−32.4**, biggest gap) |
| Losses at showdown (bluff-catches, failed bluffs, value beaten) | −13.4 | −36.9 (we lose *less*) |
| Investing then folding (preflop + postflop) | −49.3 | −48.9 (equal) |
| Big pots (≥1,000 chips) | at par | at par |
| Heads-up showdowns | +42.6 | +42.8 |

v17 loses no more than the winners; it **wins far fewer pots and gets less value**. All of its profit came from weak teams ("donors"), and it extracts only **44–58%** of what a top team takes from the *same* donor in the *same* round.

Excluding the two mega-donor bots that are gone now, our edge was only **+8.7 ±5 bb/100**.

## 3. Why. Five causes, each tied to the code

### 3.1 The range model talks the bot out of good hands on the turn and river (largest; ≈ +4 to +8 bb/100)

**Mechanism.**
- `_po_upd` (`bot.py:651–702`) narrows an opponent to "the top X% of what's left" for **every** bet or call, street after street.
- The bet rates are unconditional (`BET_P` line 277; prior air share `BLUFF_SH` line 278).
- In this field a player who bets the flop keeps betting: they bet the turn 78% of the time after a flop bet, against 32% otherwise. Three bets are therefore not three independent signals.
- Example, R33 h680: AQ is top pair, top kicker. It beats 58% of the modelled range before the turn bet, 23% after it, and 8% after a ⅓-pot river bet, so the bot folds.

**Evidence** (four independent measurements, both halves of the day):
- On heads-up river calls the bot estimated 0.49 equity; it actually won **0.66–0.71** (n≈175–182).
- We fold **61%** to river bets; top teams fold 35–38%.
- The field's small river bets are often bluffs: ≤⅓ pot 37% air, 0.35–0.55 pot 26%, 0.55–0.8 pot 17%. Only bets of 0.8 pot or more are honest (3–5% air).

**Safety net that does not work.** The river "minimum defence" floor (`bot.py:1034`) only applies while an opponent is unknown (`o.g < 0.5`, about the first 40 actions). It fired in 3 of 180 river calls. The strong-hand floor (`993–999`) is too weak: a full house got equity 0.169 (R35 h771).

**What to change.**
- **Modification:** temper the postflop updates (`t → 0.3 + 0.7·t`), set `BET_P` to the measured (0, .60, .56, .47), and make the MDF floor always on.
  - Replayed on our real river decisions together with the guard fix in 3.3, this gives **+5.6 ±1.2 bb/100**: +3.9 in R19–36, +7.2 in R37–54, +5.7 excluding R41.
- **Missing piece:** the bot never learns from postflop showdowns how often each opponent bluffs. It does this preflop (`_uninf`, `sd_r`), but postflop uses one fixed air share for everyone. The rates differ a lot:

  | Opponent type | Shown air when betting |
  |---|---|
  | Tight-passive | 8% |
  | TAG | 21% |
  | LAG | 31–44% |

### 3.2 It bets the turn and river far too rarely when checked to (biggest pot-winning gap)

| Heads-up, checked to | v17 | Top teams |
|---|---|---|
| River bet frequency | **26%** | 61% |
| Turn bet frequency | 45% | 70% |
| Fold-out rate | 59% | 60% (same) |
| Win rate when river bets are called | 73% | 54% (we only bet the nuts) |

Why:
- **The same range pessimism** makes thin value look like a bluff: `weak = uh < cut` (`bot.py:1204`). We bet top pair on only 43% of rivers.
- **Hard rules delete bets.** On 90% of river checks with no pair, the bot's own EV preferred a bet and a rule removed it:
  - bluff cap (0, .55, .38, .28) × 0.4 multiway × 0.6 facing a bet × the trust gate (`bot.py:1093–1103`);
  - bluffs no bigger than 0.75 pot (`bot.py:1216`);
  - big-bet guard (`bot.py:1202`);
  - margin of 0.03–0.08 pot (`bot.py:1229`).

**Guardrails: not aggression for its own sake.**
- Our ⅓-pot bluffs get only 25–30% folds against a break-even of 25%, so they are pointless.
- Bets of 0.55 pot or more get **63–68%** folds against a break-even of 40–50%.
- The bot's fold model is overconfident. For ⅓-pot bets it predicts 57% folds; the real rate is 34%. Its predicted call rates span 0.05–0.74; the real ones span 0.18–0.56.
- A natural experiment in the logs, where the bot's hash decides bet vs check, showed that **simply loosening the bluff cap gained nothing** (−0.2 ±0.3 bb/100, small n).

So the order is: value first (calibrate), bigger sizes, then targeted bluffs only against opponents measured to fold.

### 3.3 Two bugs that fold monster hands (≈ +3 to +6 bb/100 together)

**a. The stack-off guard ignores the price** (`bot.py:1044`). Value **+1.7–2.2**; the one-pair guard at line 1046 has the same flaw. It folded:
- QQ with model equity 0.745 at a 16% price (R40 h323);
- AA facing 648 into 2,764 (R53 h350);
- a full house (R35 h771);
- AQ, QQ and AK getting 4–5:1 after about 1,300 chips were already in.

**b. The all-in range is built from "shoves per hand"** (`bot.py:567–570`, plus the variance penalty at 1307). A villain who shoves 0.3% of hands is treated as holding AA-only whenever he re-jams. Value **+1.3 to +4.0**.
- We folded KK (R46 h507, modelled equity 0.23), QQ nine times and AK ten times to 4-bet and 5-bet jams.
- In big heads-up preflop pots we fold AA–QQ 24% of the time.
- The counters that should drive this already exist (`d3`/`d4`) but are unused here.
- A related inconsistency: the 3-bet EV assumes we call a jam that the shove guard then folds (`bot.py:1457–1465` vs `1312`).

### 3.4 Preflop: a fixed rule folds to 3-bets 74%, and the strong bots learn it

- `bot.py:1402` continues against a 3-bet only with the top 7%, **whoever** 3-bets. `bot.py:1477` bans 4-bet bluffs.
- Pooled, that is roughly right, because most of the field 3-bets tight.
- Adaptive bots learn it within the round:

  | Team | 3-bets our opens | 3-bets other openers |
  |---|---|---|
  | Attention | 36% | 12% |
  | FisherMen | 37.5% | 11% (rising 22% → 52% during the round) |
  | Anton | 36% | 24% |

**At our Sunday table:**
- **Anton** 3-bets our opens 30% of the time with junk shown (J9s, A4o, Q8o, J7o, Q2o), but his all-ins are honest (57 of 71 shown were top-10% hands).
- **Attention** 3-bets us 15% of the time with trash shown (K7o, 42o, 73o, T2o) and folds 62% to 4-bets.
- **Jump Street, Phil AIvey, GamesGone and ND** 3-bet and jam almost only with premiums, so folding to them is correct.

**What to change.** Missing piece: a per-opponent "3-bets *vs our opens*" counter; today the bot uses the 3-bettor's rate against anyone. Modification: make the continue range and 4-bet bluffs depend on that counter. Value about +1–3, more at our table.

### 3.5 The time budget was written for 10 ms; the real limit is 25 ms but the server is 4–10× slower (≈ +0.6–1.9 bb/100)

- Monte Carlo stops at 2.1 ms (`bot.py:968`) and range updates are skipped after 1.3 ms (`bot.py:653`).
- On the server, heads-up flop equity gets about 100–150 of 440 samples.
- Two-villain pots fall back to a crude percentile method 45% of the time; three or more villains, 96–100%. Example: R30 h3, AA called a three-way turn jam for −2,000 that the full model folds.
- 4.8% of opponents' postflop actions never update their range.
- Real think time is only 2.2–4.3 s of the 10 s bank. About 1.8 ms per decision is transport time that the bot's `spent` counter does not see.
- Modification: raise the deadlines about 3× and count transport in the bank.

### Smaller items

- Thin flop calls with weak pairs or air against tight bettors: **−2.4 bb/100**. One realization factor (0.96 / 0.90) is used for every hand, so weak hands are overrated and draws underrated (`bot.py:1022–1024`).
- Under-extraction from tight-passive players like ND: top teams make **+13.5 bb/100 per such seat** and we make +1.4. They get paid big pots with two pair or better by second pair; we build big value pots 2.4× less often (our big river bets win 97.7%, too strong).

## 4. Not the problem: leave alone

- Big pots and all-ins (at par).
- Heads-up showdowns.
- Flop folds.
- Opening ranges and sizes. The field rarely folds to steals: all fold only 16–34% of the time, so pure steals lose 1.2–1.8 bb.
- Investing then folding (we pay *less* than the top teams).
- Learning speed (the opponent model is trusted after about 35 hands).
- Value 3-bets and 4-bets: they are the preflop profit engine.
- Timeouts (13 in 36 rounds; negligible).

## 5. Proposals (for discussion)

| Package | What | Kind | Est. value* | Risk |
|---|---|---|---|---|
| **A. Fix the misreads** | Temper range updates + measured `BET_P`; MDF floor always on; price-aware stack-off and one-pair guards; jam-range fix (condition on `d3`/`d4`, floor about 25% of range) + smaller preflop variance penalty; time budgets about 3× + count transport; flop realization by hand class | modifications | **+6 to +10** | low: mostly constants and one-line guard conditions; makes the bot call more, not bluff more |
| **B. Aggression where the data pays** | Calibrate the fold model (50/50 blend with measured call rates; measured `FOLD_P`; lower `UB[0]`/`UB[1]`); thin river value with top pair heads-up; value overbets from `uh ≥ 0.8`; big value against passive callers (ND); bluffs only at 0.55–1.0 pot against opponents measured to fold ≥ 55%; no ⅓-pot bluffs | modifications | +2 to +5 | medium: needs the duplicate test |
| **C. Opponent-specific 3-bet defence** | New counter "3-bets vs our opens"; widen calls and value 4-bets against wide 3-bettors (Anton, Attention); 4-bet bluffs only against measured 4-bet folders | missing piece + modification | +1 to +3 (more at our table) | low-medium |
| **D. Postflop showdown learning** | Per-opponent bluff share by street and size from shown hands, replacing fixed `BLUFF_SH` | missing piece | overlaps A | more code |

\*Estimates come from different analysts and **do not add up**. Package A's first two items were replayed on our real river decisions: +5.6 ±1.2.

**Recommended order:** A, then C, then B. Every change goes through:
1. the replay diff on the 36 real rounds;
2. the paired duplicate test against copies of our six Sunday tablemates;
3. a timing check under CPU load;

before the 09:00 upload.

## 6. Sunday table (official draw, republished 20:46)

**Format:** one stage of **36 rounds**, 4 tables, top 2 per table go through. This replaces the 20:30 draw (18 rounds, 5 tables).

**Our table (table 3, 8 seats).** bb/100 is luck-adjusted, from our R19–R54 tables. Head-to-head is per 100 hands both seated (+ = they win from us).

| Seed | Team | Saturday | bb/100 at our tables | Style | 3-bets our opens | Their 3-bet vs our 4-bet | Head-to-head |
|---|---|---|---|---|---|---|---|
| 3 | The Market Makers | +28.0 | +79 (6k hands) | tight (VPIP 18, PFR 12), strong postflop | 3.9%, honest (JJ, AK, ATs, 88) | fold 25% | +5.2 |
| 6 | FisherMen | +20.6 | +44 (8k) | loose-aggressive (VPIP 30, PFR 25); preflop jams 2.2% of hands | **29%, wide** (A8s, KJo, Q9o, K5o shown) | **fold 83%** | +5.4 |
| 11 | **Durahim 1453** | +13.9 | +19.5 | | | | |
| 14 | Claudebot | +13.3 | +27 (6k) | tight, aggressive postflop | 3.2%, honest | fold 10% | +1.5 |
| 19 | Jump Street | +5.7 | +20 (7k) | solid | 8.6%, honest (all premium) | fold 40% | +2.5 |
| 22 | matcha mille crêpes cake | +3.3 | +27 (4k) | tight; **jams 1.2% of hands, wide** (A2s, A6s, KTo, ATo, Q9s shown) | 4.3% | fold 21% | +2.4 |
| 27 | 85p | −13.1 | −20 (8k) | nit (VPIP 14) | 5.5% | fold 66% | −2.0 |
| 30 | Joca | −26.5 | −31 (2k) | tight-passive (AF 0.9) | 0.4% | | −0.6 |

**What this means.**
- The Market Makers is the favourite for 1st, so top 2 means **finishing ahead of FisherMen** (and Claudebot, Jump Street and matcha).
- FisherMen 3-bets our opens 29% of the time, against 11% for other openers, ramping up during the round. It then folds 83% to a 4-bet. Our fixed "continue only with the top 7%, no 4-bet bluffs" rule hands chips straight to our main rival. **Package C becomes the top table-specific fix.**
- matcha's jams are wide, so our tight shove-calling range costs EV against them (the jam-range fix in package A helps).
- The donors are only 85p and Joca, both tight. Extraction will be harder than on Saturday.
- The testbench (opponent copies) estimates v10 at about +16 bb/100 at this table. Our real results against these seven teams sum to about −8 ±8, so **expect a harder table than the bench shows**.

## 7. Confirmed by instrumented replay

Three tracers replayed all 36 rounds through logging-only copies of the live bot. The copies match the live actions on 100% of preflop decisions (37,848) and 99.9% of river decisions (1,231). Flop and turn match 85–90%; the difference is Monte Carlo noise.

**Verdict: nothing big is missing.** Every major error comes from an existing component with a wrong rule or constant. The two genuinely missing pieces are:
- postflop learning from showdowns (how often each opponent bluffs);
- a per-opponent count of how often they 3-bet our opens.

**Range stacking, shown directly.** River equity predicted by the bot vs the actual result, by how many times the villain bet:

| Villain bets this hand | Bot predicted | Actual |
|---|---|---|
| 0 | 0.548 | 0.552 |
| 1 | 0.518 | 0.541 |
| 2 | 0.483 | 0.656 |
| 3 or more | 0.405 | **0.809** |

The same model *without* the bet updates is calibrated (0.676 vs 0.636 actual, n=317). Example, R36 h928: AQ, top pair top kicker, goes from beating 89% of the modelled range to 4.5% after two calls and folds.

**River bluffs, a natural experiment.** The bot's own hash randomly decides bet or check in heads-up river spots with no pair. Betting won **+143 chips per spot (SE 45, t=3.2)**; villains folded 74%. That is about **+3.1 ±1.0 bb/100**, positive in both halves. An earlier, smaller and broader test (all streets, n=46/45) found nothing (−0.2 ±0.3), so the evidence supports **river** aggression specifically.

**Light 3-bets.** In 2,107 of the 2,108 spots where the bot's own 3-bet EV beat calling or folding by 0.5 bb, the light-3-bet gate removed the 3-bet. The gate fails mainly because the bot doesn't hold a "blocker" (92% of cases). The gate's own coin-flip experiment: +20.5 chips per spot (SE 42) against the model's +25. Our 3-bets also get 55% folds against 43% predicted.

**Thin flop calls.** The fixed realization factor (0.96 / 0.90) is wrong for most hand types. Actual realization by hand type:

| Hand type | Realization |
|---|---|
| Weak pair | 0.75 |
| Gutshot | 0.69 |
| Air | 0.64 |
| Top pair | 0.92 |
| Strong draw | 1.40 |

A quarter of these losing calls are pure Monte Carlo noise: a call needs only EV > 0, while a raise needs a margin of 3–8% of the pot.

**Time budget.** At the server's inferred speed (about 4× slower than this Mac, judged from how well river decisions match):
- flop and turn Monte Carlo gets a median of about 60 samples instead of 440 (equity SE about 0.064);
- 9.7% of flop decisions get no Monte Carlo at all;
- 4–6% of villains' postflop actions never update their range.
