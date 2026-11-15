# Testbench: is a candidate better than the live bot? (Sunday, uploads reopen 09:00)

Live bot = `imperial-ai-hack/v10/bot.py` (site v17, real rounds R19-R54, +19.2 bb/100 raw, +19.5 luck-adjusted).
Everything here is Python 3.9+ standard library and reads the 55 real round logs. Nothing outside this folder is modified.

**In short:**
- The bench measures **differences** between our own decisions about right: two exact checks against the real logs matched.
- It **does not** predict absolute win rates or the order of teams at our table. Its clones are too soft: v10 makes +34 bb/100 against clones of its real tables versus +19.5 in reality, and the strong teams' clones lose chips they won for real.
- So judge a candidate by its paired difference from v10, mostly through calls and folds, and treat gains that come from betting or showdown value with suspicion.
- **Adaptive mode (`--adaptive`, section 9, opt-in):** clones that react to how we bet and 3-bet, as measured in the logs. Use it for aggression and 3-bet-defence changes. It cuts the level bias from +14 to +9 bb/100; the static bench stays the default.

## 1. Our Sunday table: `tables/sunday.txt`

Source: the public API (`buckets` / `sunday`, published Sat 20:46). Stage 1 is **8 seats, 36 rounds, top 2 advance**.

| Team | Seed | Saturday bb/100 |
|---|---|---|
| The Market Makers | 3 | +28.0 |
| FisherMen | 6 | +20.6 |
| **Durahim 1453 (us)** | 11 | +13.9 |
| Claudebot | 14 | +13.3 |
| Jump Street | 19 | +5.7 |
| matcha mille crêpes cake | 22 | +3.3 |
| 85p | 27 | −13.1 |
| Joca | 30 | −26.5 |

- All 7 opponents have profiles (2,000-8,000 hands each at our Saturday tables).
- `../DIAGNOSIS_v17.md` §6 lists a different, guessed table and 18 rounds; it predates the published buckets.

**v10's real record against these 7 teams (R19-R54, luck-adjusted, chips each one took from us or gave us, per 100 hands with him):**

| | Market Makers | FisherMen | Claudebot | Jump Street | matcha | 85p | Joca | **Sum** |
|---|---|---|---|---|---|---|---|---|
| Real | −5.2 | −0.3 | 0.0 | −1.4 | −3.4 | +1.6 | +0.6 | **−8 ± 8** |
| Bench, same 7 teams | | | | | | | | **+16** |

At this table the clones of The Market Makers and FisherMen *lose* about 10 bb/100; the real teams won +120 and +71 bb/100 at our tables. There is no mega-donor at this table; the weakest are Joca (−26.5 on Saturday) and 85p (−13.1). Expect a much harder table than the bench shows.

## 2. The tools

| Tool | What it answers | Typical time (6 procs) |
|---|---|---|
| `replaydiff.py` | What does the candidate do differently on our **46,342 real decision points** (R19-R54)? It values the first deviation in each hand: **EXACT** when it folds where live continued; **APPROX** when it calls down to a showdown with known cards; otherwise **UNKNOWN** (counted, plus rough estimates that are never added in). | 10-25 s |
| `duel.py` | Paired duplicate simulation: candidate and v10 in the same seat, same cards, same clone opponents. The kit engine runs in-process. It reports the difference ± SE overall, per opponent, per position and by how hands end. `--selftest` checks the bench's determinism in 3 s. | 70 s for the Sunday table at 30 seeds × 8 seats |
| `simreal.py` | Does the bench predict reality? It rebuilds v10's 36 real tables with clones and compares results, per-opponent chip flows and pooled stats with the logs. With `--cand` it also plays a candidate, paired, on those real lineups. | 45-55 s |
| `timing.py` | Official limits through the kit's subprocess player: 25 ms per decision and a 10 s bank. It counts timeouts. `--ref ../v10/bot.py` projects the server think time from v10's live 3.18 s/round. | 5-15 s |
| `profiles.py` | Builds `profiles/<slug>.json` and `index.json` from the logs: spot frequencies, sizes and showdown strength. It keeps the fitted `policy`. | 5 s |
| `clone.py` | `make_agent(profile, seed)`: a deterministic frequency-matching opponent with the tournament interface. | |
| `clone_agent.py` | `class Agent` from `CLONE_PROFILE`. `--make-all --out out/bots` writes wrapper files for `local_sim.py`, because the kit strips the environment. | |
| `calibrate.py` | Refits the clones' strength CDFs and reports target vs achieved per team. **For test runs add `--no-write --name test`**: by default it rewrites `profiles/*.json`, `out/calibration*.txt` and `out/sim/validate/`. | 2 s to 3 min |
| `hh.py`, `evalx.py` | Shared validated log parser and hand evaluator. `python3 hh.py` re-validates all 55 logs with 0 problems in 35 s. | |
| `clone_adapt.py` | Adaptive clones, used only with `duel.py` / `simreal.py --adaptive` (section 9). They react to each seat's bet frequency, shown big bets, fold-to-3-bet and 3-bet frequency. | |
| `adaptive_measure.py`, `adaptive_fit.py`, `adaptive_calibrate.py` | Measure those reactions on the real logs, fit `adaptive/params.json`, then centre it and calibrate the hero level on simulated replays. Run all three in this order. | 7 s, 5 s, 75 s |

Every CLI has `--help`. Outputs go to `out/` as `.txt` and `.json`.

## 3. Checking a candidate (copy-paste)

```bash
cd imperial-ai-hack/testbench   # from the repository root
CAND="../candidates/X/bot.py"        # your file, class Agent

# 1. Real decisions (~20 s). The candidate should differ only where you meant it to, and EXACT/APPROX should not be worse than the base.
#    --time-scale 0.05 only for v10-derived copies (it removes v10's Monte Carlo deadline noise).
python3 replaydiff.py "$CAND" --base ../v10/bot.py --time-scale 0.05

# 2. Sunday table, paired with v10 (~70 s). Look at the "adj ... diff" line and z.
python3 duel.py --cand "$CAND" --table-file tables/sunday.txt --seeds 30 --rotations 8

# 3. Second opinion: the 36 real lineups, other decks and opponents (~55 s)
python3 simreal.py --cand "$CAND" --seeds 4 --no-tally

# 3b. Betting, bluffing, sizing or 3-bet changes: repeat 2 and 3 with ADAPTIVE clones (section 9),
#     then once more with --no-hero-level to see whether the conclusion rests on that calibrated assumption
python3 duel.py --cand "$CAND" --table-file tables/sunday.txt --seeds 30 --rotations 8 --adaptive
python3 simreal.py --adaptive --cand "$CAND" --seeds 4 --no-tally

# 4. Time limits (~15 s; add --load 6 to stress it)
python3 timing.py --bot "$CAND" --ref ../v10/bot.py --table-file tables/sunday.txt --rounds 3

# 5. Final start-up check with the official simulator
cd ../../imperial-ai-hack-pokerbots-kit && python3 local_sim.py "../imperial-ai-hack/candidates/X/bot.py" --rounds 1 --hands 200
```

**Upload only if all of these hold:**
- `duel.py` shows adj z > 2 on the Sunday table and `simreal.py --cand` agrees in sign.
- `replaydiff` shows no unintended changes.
- `timing.py` shows 0 timeouts and a projected server think time well under 10 s.

## 4. Reading the outputs

- **`duel.py`:**
  - The `adj` row is all-in luck-adjusted. `diff (cand-base) +-SE` is what matters; use the larger of the SE and the seed-clustered SE (`z` already does).
  - The "per opponent" and "how our hands end" rows show where the difference comes from. A gain that sits entirely in "showdown won" is the kind the bench overstates.
  - The `checks:` line must read decks identical True and 0 violations.
- **`replaydiff.py`:**
  - Read the `CANDIDATE minus BASE` block and the category table (which streets changed).
  - Calls where live folded on a heads-up river are UNKNOWN, because no cards were shown. Only the separate rough estimate covers them.
- **`simreal.py`:**
  - The `TOTALS` line gives the bias of the bench's level against reality.
  - `PER OPPONENT` shows where the clones are wrong.
  - `CANDIDATE ... adj diff` is the paired difference on the real lineups.
  - `EXACT REAL COUNTERFACTUALS` gives the real answers for the two check copies.

## 5. Noise floor (measured)

| Tool | Run | Result |
|---|---|---|
| `duel.py`, Sunday table | v10 vs v10, 240 pairs (30 seeds × 8 seats) | diff +0.6 ± 0.6 bb/100 (seed-clustered 0.7), z 0.9; median first divergence at hand 44 |
| `duel.py`, `--field 6` | 140 pairs | −1.1 ± 0.9 |
| `simreal.py --cand` | 144 pairs | SE about 0.9-1.4 |
| `replaydiff.py` | v10 against its own logged actions | 98.3% same action, EXACT +1.3 ± 0.4 bb/100 (Monte Carlo noise) |

- **Duel sample sizes:** a +2 bb/100 change needs about 120 pairs to reach z = 2; 240 pairs resolve about ±1.4.
- **Bigger changes are noisier:** v0 vs v10 has SE 2.6 at 140 pairs.
- **replaydiff:** always use `--base ../v10/bot.py` so that noise cancels.

## 6. Does the bench predict reality? (`out/simreal_v10.txt`)

Setup: v10's 36 real tables (R19-R54) rebuilt with clones in the real seats, 6 seeds each. Every team had its own profile, so the `field`/`donor` fallback was never needed.

**Level: biased high.**

| Rounds | Real (luck-adjusted) | Bench | Bias (bench − real) |
|---|---|---|---|
| All 36 | +19.5 ± 4.1 | +34.1 ± 2.1 | +14.6 ± 4.6 (z 3.2), about 1.7× real |
| R19-R29 (mostly out of sample) | | | +21 ± 8 |
| R30-R54 (profiles fitted on them) | | | +12 ± 6 |

- **Per-round ranking:** the correlation between bench and real round results is 0.44. Real per-round noise caps the attainable correlation at about 0.58, so the bench ranks tables about as well as the noise allows.
- **Where the bias sits:** almost entirely at showdown, +56.8 in the bench vs +45.1 real. Every non-showdown outcome agrees within 3 bb/100.
- **Why:**
  - Real opponents fold more to *our* big bets than clones do. Facing our flop bets of 0.8-1.1 pot: 72.7% real vs 65.7% bench. Turn: 80.0% vs 71.3%. Turn bets over 1.1 pot: 71.2% vs 54.2%. Against other opponents' bets the clones fold within about 3pp of reality.
  - Real teams 3-bet our opens more (9.1% vs 7.3% against other openers; clones 7.5% against both) and fold more to our 3-bets (65% vs 58%). Real teams adapt to us; clones are static.
  - Clones of strong teams are much weaker than the teams themselves: The Market Makers +120 real vs +22 bench, FisherMen +71 vs +12, Attention +74 vs +10.
  - Per-opponent flows correlate 0.91 across 42 teams, but only 0.28 without the four teams whose own results go beyond ±100 bb/100 (three maniac donors plus The Market Makers).
- **Pooled opponent frequencies are good:**
  - 38 of 43 stats are within 3pp, mean gap 1.4pp: VPIP 23.5/23.7, PFR 15.7/16.0, 3-bet 7.7/7.9, fold to 3-bet 58.1/58.4, c-bet flop 75.3/74.7, WTSD 28.4/30.5 (real/bench).
  - Clones fold 0-7pp less to big bets on every street.
- **Differences, which is what `duel.py` is used for:** two exact checks against the real logs.

| Copy | Bench, paired on the real lineups | Exact real counterfactual (logs) |
|---|---|---|
| `v10_riverfold`: fold every river bet | −18.2 ± 1.6 | −15.6 ± 2.1 |
| `v10_no3betcall`: never call a 3-bet | −1.0 ± 1.0 | −1.0 ± 1.1 |

Both agree within noise.

**Verdict:**
- Trust `duel.py` for the sign and rough size of changes to our *calling/folding*.
- Do not trust it for absolute levels or for who finishes top 2.
- Be sceptical of gains from *betting more or bigger* (clones pay our value bets too often) and of anything that depends on opponents adapting to us (3-bet wars).

## 7. Improvement proposals and what the bench says

1. **Call small river bets heads-up with top pair or better** (`out/v10_rivercall.py`: river, heads-up, bet ≤ 60% pot, top pair+, call where v10 folds). Recommended; low risk.
   - **Why:** v10's range narrowing talks it out of one-pair hands. Real heads-up river calls won 66-71% while v10 estimated 49% (DIAGNOSIS §3.1). Small river bets in this field are 26-37% air.

   | Check | Result |
   |---|---|
   | `duel.py`, Sunday table | **+5.3 ± 0.8 bb/100** (z 6.9) |
   | `simreal.py`, real lineups | +4.1 ± 0.9 |
   | `duel.py --field 6`, random 7-seat tables | +2.4 ± 1.1 |
   | `replaydiff.py` | exactly 35 river decisions changed in 36,000 hands, all intended; rough estimate +2.3 |
   | `timing.py` | think ratio 1.01 vs v10 |

   - **Realistic expectation: +2 to +3 bb/100.** In the sim the override fires 1.75 times per 1,000 hands versus about 1.0 in the real logs, and the bench overstates showdown value.
2. **Package A of the diagnosis: fix the misreads** (`../DIAGNOSIS_v17.md` §3.1 and §3.3; estimated +6 to +10 bb/100; its first two items replayed on our real river decisions gave +5.6 ± 1.2).
   - **What:** temper the postflop range updates, use the measured `BET_P`, keep the MDF floor always on, make the stack-off and one-pair guards price-aware, and fix the jam range.
   - **Testability:** these make the bot *call more*, which is the class of change the bench reproduces well (riverfold/no3betcall checks).
   - **Not built yet:** there is no candidate file for it. Proposal 1 is the smallest, safe slice of it. Build it as a copy of v10 and run section 3.
3. **Opponent-specific 3-bet defence** (DIAGNOSIS §3.4; continue against 3-bets based on how often that opponent 3-bets *our* opens).
   - **Real evidence:** real teams 3-bet our opens 9.1% vs 7.3% against others; FisherMen 37.5% vs 11%.
   - **The static bench cannot measure it:** static clones never adapt to us. `--adaptive` (section 9) now models the exploiting 3-bettors (FisherMen and others).

Do **not** add folds: every tested folding change lost in both the logs and the bench (riverfold −15.6, no3betcall −1.0, v9's 4-bet folds).

## 8. Limitations

- **Clones are static frequency matchers** (default mode). They have no hand reading and no adaptation to us beyond a tight/wild jammer split. `--adaptive` adds the reactions measured in section 9, but still no hand reading.
  - Strong teams are under-modelled.
  - Maniac donors lose less than in reality, because clones jam from the top of their range.
  - Bet sizes are drawn independently of hand strength.
- **Profiles describe Saturday.** They use R30-R54, or R19-R54 for five teams. Teams may upload new bots on Sunday.
- **Small samples:** Joca has 2,000 hands; Claudebot and Jump Street 3,000. Their profiles lean on smoothing toward the field.
- **In-process runs give v10 no time limit.** Its 2.1 ms Monte Carlo deadline searches more locally than on the server, which is about 5-10× slower. `timing.py` cannot reproduce the server's rare timeouts (13 in 36 live rounds).
- **The real-lineup check is partly in-sample.** The R30-R54 profiles were fitted on those rounds; R19-R29 is the cleaner, and more biased, comparison.
- **Fresh runs differ slightly.** `out/duel_clones_*.json` (`--field 6`) were re-run with the final profiles. Other `out/` files from the builders, and v10's Monte Carlo noise under machine load, make reruns differ slightly. See `opponent_files` / `bot_sha1` in each JSON.

## 9. Adaptive mode (opt-in: `--adaptive`, built Sun 00:00-01:00)

**Why:** the static clones fold to a bet by its size alone and never react to how we play. So the bench gave our pot-size bets too many calls (paying our value bets, starving our bluffs) and never punished folding to 3-bets. That made aggression and 3-bet-defence changes impossible to judge.

```bash
python3 duel.py --cand "$CAND" --base ../v11/bot.py --table-file tables/sunday.txt --seeds 30 --rotations 8 --seed0 201 --adaptive
python3 simreal.py --adaptive --cand "$CAND" --seeds 4 --no-tally      # real line-ups, paired
python3 simreal.py --adaptive                                          # v10 replay + real-vs-sim ADAPTIVE CHECKS
# sensitivity: add --no-hero-level, or --adaptive-off exploit3,fold3,postflop,shown,hero,union,light4
```

- **Static stays the default and is unchanged.**
  - In A/B runs with deterministic zoo heroes (`duel.py` 4 pairs, `simreal.py` 6 tables), the new `duel.py` and `simreal.py` reproduce the old ones bit for bit.
  - `--adaptive` with null parameters (`clone_adapt.null_params()`) reproduces static bit for bit.
  - Pairing and determinism checks still pass (0 violations; `duel.py --selftest --adaptive`).
- **Files:**
  - `clone_adapt.py`: the adaptive clone.
  - `adaptive_measure.py --extract`: decision records from the logs.
  - `adaptive_fit.py`: slopes and per-team fits → `adaptive/params.json`, `out/adaptive_fit.txt`.
  - `adaptive_calibrate.py`: centring and hero level → `out/adaptive_calibrate.txt`.
  - Runs: `out/adaptive/*.log`, `out/duel_adapt_*.json`, `out/simreal_adapt_*.txt/json`.
- **Re-fit order:** `adaptive_measure.py --extract` → `adaptive_fit.py` → `adaptive_calibrate.py`, always all three.

### 9.1 What the logs show (all numbers measured; `out/adaptive_fit.txt`)

"Within" means the same seat in the same round reacting as another seat's record changes. That isolates learning from style differences between teams.

| Question | Answer |
|---|---|
| Are our big bets stronger at showdown than other teams'? | **No**, except overbets. Shown big bets (> 0.55 pot) that were top pair or better: us 65.8% (n 231), others 64.4% (n 3,014). By size: b3 us 46%/40% (flop/turn) vs others 54%/58%; b4 59%/70% vs 65%/79%; b5 (overbets) 100%/100% (n 31/19) vs 68%/88%. |
| Does a team's fold rate follow a bettor's shown big-bet strength? | **Weakly, river only.** Within-seat slope per unit of shown value share: flop +0.06 ± 0.07, turn 0.00 ± 0.10, river +0.31 ± 0.13. |
| Does it follow how often the bettor bets? | **Yes, on every street.** Within-seat slope per unit of bet-when-checked-to frequency: flop −0.32 ± 0.06, turn −0.28 ± 0.07, river −0.17 ± 0.10 (pooled −0.28 ± 0.04). The cross-section across teams agrees (−0.26). Across teams, folds fall by about 21 pp from bettors who bet 25-30% of the time to those who bet 90-95%. |
| Do real teams learn to fold more to us during a round? | **No.** The extra folding against our bets (fold minus the static clone probability) is largest at the start: big bets +14.6 pp (hands 1-50), +17.0 (51-125), +7.9 (126-250), +7.3 (251-500), +6.7 (501-1000). Against other teams' bets: +3.0, +4.3, −0.8, +0.4, −0.1. |
| How much of the extra folding against us do learnable signals explain? | About 2-3 pp of +10 pp (flop pot-size) and +15 pp (turn pot-size). Our bet frequency is lower than average (turn 0.43 vs 0.53, river 0.24 vs 0.45). W$SD and the win rate of shown big bets add nothing consistent. |
| Do teams 3-bet openers who fold to 3-bets? | **Yes, strongly.** Against OTHER teams' opens, by the opener's running fold-to-3-bet (about 0.48 → 0.72): FisherMen 7% → 40%, Attention 4% → 49%, Resonance Qt 3% → 36%, AAST 6% → 31%, Anker 5% → 27%, Anton 18% → 43%. Most teams are flat (85p 5% → 5%). |
| Do openers fold more to rare 3-bettors? | **Yes.** Within-seat slope −0.91 ± 0.13 per unit of the 3-bettor's 3-bet frequency. Our 3-bets: real fold 61.5% vs 52-53% static cell; the slope explains +6.6 of +8.5 pp. |
| Do exploiting 3-bettors fold more to 4-bets? | **Yes, against us.** Fold to our 4-bets vs others': FisherMen 89% (n 37) vs 80% (n 86), AAST 81% vs 53%, Attention 92% vs 60%, Anker 79% vs 59%. Exception: Anton 46% vs 50%. |

### 9.2 The model (`clone_adapt.py` docstring, `adaptive/params.json`)

1. **Folding facing a single postflop bet:** `p_F + k_bet·(bettor's shrunk bet frequency − ref) + k_shown·(shown-value deviation − ref) + hero_level` if the bettor is our seat. Calls and raises are scaled down; the weakest calls become folds.
   - k_bet = −0.32 / −0.28 / −0.28 (flop/turn/river).
   - k_shown = 0 / 0 / +0.31.
   - References are centred on the clones' own population, so their pooled fold rates stay on their profiles.
2. **Exploitative 3-betting:** `logit R' = logit R + c_team + A_team·max(0, f_opener − 0.55)`, where f_opener is the opener's fold-to-3-bet, shrunk to 0.577 (m3 8).
   - Fitted per team; teams are kept only if A ≥ 3 SE and the model reproduces their real rate against our opens.
   - Adaptive teams (A): FisherMen 24.7; Resonance Qt 13.7; Attention 13.4; AAST 13.1; Anker 12.8; Gherkers 9.5; Anton 8.8; Lehman 6.7; gamblerlove 2.9; supernut 2.6.
   - Every other team is static, including all Sunday opponents except FisherMen.
   - Extra 3-bets come 83% from the hands just below the calling range and 17% from the top of the calls.
3. **Fold to a 3-bet:** `p_F + k3·(3-bettor's shrunk 3-bet frequency − ref)`, k3 = −0.91.
4. **Facing a 4-bet after a 3-bet:** the light 3-bets fold first. After a widened 3-bet (w = adapted / profile rate) the continue share is (1 − p_F)/w.
5. **hero_level:** a static, calibrated extra fold probability when the bettor is our seat.
   - Per street, size buckets b1/b3/b4/b5: flop −3.9/−1.6/+5.5/+3.0; turn −6.5/−5.5/+7.4/+8.4; river −2.5/−6.0/0/0 (river b4/b5 have fewer than 30 real decisions).
   - Calibrated on v10's 36 real line-ups, seeds 101-106, and shrunk by n/(n + 50).
   - **This is an assumption, not a mechanism:** real teams fold more to OUR pot-size bets and overbets, and less to our small ones, from hand 1 on, for a reason the logs do not reveal.
   - `--no-hero-level` switches it off; check that a conclusion survives without it.

### 9.3 Validation (v10 on its 36 real line-ups, seeds 1-6 = not the calibration seeds; `out/simreal_adapt_v10.txt`)

| Check | Real (logs) | Static bench | Adaptive bench |
|---|---|---|---|
| Fold facing OUR flop bet 0.8-1.1 pot (b4) | 72.7% (n 538) | 65.2% | **72.5%** |
| ... turn b4 | 80.0% (n 195) | 70.7% | **78.3%** |
| ... flop / turn > 1.1 pot (b5) | 75.8% (248) / 71.2% (80) | 69.4 / 54.4 | 75.1 / 65.8 |
| ... flop / turn 0.55-0.8 pot (b3) | 58.6% (435) / 60.7% (219) | 57.5 / 68.5 | 57.3 / 61.9 |
| ... flop / turn <= 0.35 pot (b1) | 28.9% (453) / 37.2% (183) | 29.7 / 37.0 | 28.8 / 38.1 |
| ... river b1 / b3 (b4, b5 have n < 30) | 58.1% (74) / 66.2% (68) | 53.1 / 70.3 | 53.7 / 70.2 |
| Fold facing OTHER teams' bets (16 cells with n >= 200): mean abs. gap | | 2.1 pp | 2.2 pp |
| 3-bet facing OUR opens / others' opens | 9.1% (18,572) / 7.3% | 7.5 / 7.9 | **9.1 / 7.3** |
| FisherMen 3-bet facing our opens (by quarter) | 37.7% (374): 23/38/39/52 | 14.9: 13/17/15/15 | 29.8: 16/34/35/36 |
| Attention / Resonance Qt / AAST / Anton | 35.5 / 28.7 / 29.8 / 34.3 | 20.3 / 13.5 / 17.5 / 23.6 | 33.7 / 26.1 / 31.1 / 35.0 |
| Anker / Lehman / Claudebot (Claudebot static) | 21.6 / 13.5 / 3.1 | 11.9 / 7.6 / 7.2 | 15.3 / 9.0 / 7.4 |
| Market Makers / Jump Street / matcha / 85p | 4.6 / 9.5 / 4.6 / 5.5 | 5.3 / 7.8 / 4.9 / 4.4 | 5.4 / 7.9 / 4.9 / 4.4 |
| Opener folds to OUR 3-bet / to others' | 65.2% (821) / 57.4% | 58.4 / 58.3 | 62.4 / 59.6 |
| FisherMen / AAST fold to OUR 4-bet | 100% (24) / 81% (21) | 82.8 / 54.0 | 93.9 / 76.9 |
| Opponent stats within 3 pp (43 pooled stats) | | 38/43, mean 1.4 pp | 38/43, mean 1.3 pp |
| **(c) Level bias of v10** (bench minus real +19.5 +- 4.1) | | +14.3 +- 4.6 (README +14.6) | **+8.9 +- 4.6** |
| ... R30-R54 / R19-R29 | | +10.9 / +22.1 | +5.9 / +15.8 |
| ... per-round correlation with reality (noise ceiling) | | 0.46 (0.54) | 0.50 (0.61) |
| ... showdown bb/100 (where the bias sits) | +45.1 | +56.5 | +53.0 |
| **(b) Fold every river bet** (out/v10_riverfold.py) | **-15.6 +- 2.1** exact | -18.2 +- 1.6 | **-17.0 +- 1.4** |
| **(b) Never call a 3-bet** (out/v10_no3betcall.py) | **-1.0 +- 1.1** exact | -1.0 +- 1.0 | **-4.5 +- 1.0**; exploit3 off: +0.5 +- 1.0 |
| **(d) v11 vs v10, Sunday table, deals 201-230 x 8 seats** | | +6.6 +- 1.0 | **+11.3 +- 1.0** (z 9.3); no hero level +11.5 +- 1.1 |
| ... deals 301-330 x 8 seats | | +5.9 +- 0.9 | **+10.4 +- 1.1** (z 9.5) |
| v10's own bb/100 at the Sunday table (deals 201-230) | (section 1: real flows vs these 7 teams sum to -8 +- 8) | +17.0 | +9.0 (no hero level +12.1) |

- **Measured mechanisms only** (`--no-hero-level`, `out/simreal_adapt_v10_nohl.txt`):
  - bias +11.0 +- 4.6, correlation 0.50;
  - fold facing our flop / turn b4: 67.1 / 71.7 (real 72.7 / 80.0); flop / turn b1: 33.3 / 43.5 (real 28.9 / 37.2);
  - 3-bets facing our opens: 9.1. The preflop side needs no hero level.
- **Never-call-a-3-bet differs from the exact counterfactual by design.** The exact counterfactual keeps every opponent action as it was. On the adaptive bench, the copy folds to 86% of 3-bets (v10 74%), so the exploiting teams 3-bet it more: FisherMen 61.5%, AAST 48%, Anton 49% of its opens (v10: 29.8 / 31.1 / 35.0). With that reaction switched off (`--adaptive-off exploit3`), the bench gives +0.5 +- 1.0, in line with the exact -1.0 +- 1.1.
- **The v11 gain grows on the adaptive bench mostly at FisherMen's tables:** +5.7 +- 0.7 per 100 hands with him, vs +2.2 +- 0.5 static. The FisherMen clone exploits v10's 74% fold-to-3-bet; v11's wider defence denies it. The gain is spread over the opening positions.


### 9.4 How to read adaptive results

- **Noise floor:** v10 vs v10, Sunday table, deals 201-230 x 8 seats: -0.7 +- 0.6 bb/100 (z -1.0). That matches static (+0.6 +- 0.6). Opponent-determinism violations: 0.
- **Use the adaptive bench for** changes to betting frequency, bluffs, bet sizes, 3-betting and 3-bet defence. Its reactions are measured, and the fold level against v10's bets is calibrated.
- **Keep using** `replaydiff.py` and static `duel.py` for calling and folding changes. The exact counterfactuals cannot see adaptation, so for preflop folding changes expect the adaptive bench to be MORE negative (never-call-3-bets: -4.5 adaptive vs -1.0 exact).
- **Check that a conclusion survives:**
  - `--no-hero-level`, which drops the calibrated static fold correction against our seat;
  - where relevant, `--adaptive-off exploit3`, which separates the opponents' exploitation from the change itself.
- **FisherMen under-exploits v10 in the bench** (29.8% vs 37.7% 3-bets against our opens). The clone's response is fitted: given v10's real fold history it reproduces the real 23/41/44/59% by quarter. But in the bench v10 folds less to 3-bets at those tables (73.6% vs 77.7%, 47.5 vs 57.2 3-bets per round), so FisherMen's estimate of us stays lower (0.69 vs 0.74 by the last quarter). Gains from better 3-bet defence are therefore, if anything, understated.
- **Level:** the bias drops from +14.3 to +8.9 bb/100 and is still mostly at showdown (+53.0 vs +45.1 real). Absolute levels and the order of teams remain unreliable.

**Extra: v12 on the adaptive bench** (Sunday table x 8 seats, vs v11; `out/adaptive/run_v12_adaptive.out`, `out/adaptive/run_v12_s301.out`)

| Candidate vs v11 | Static bench, deals 201-230 (out/ablate/v12_summary.txt) | Adaptive, deals 201-230 | Adaptive, deals 301-330 | Adaptive, no hero level, deals 201-230 |
|---|---|---|---|---|
| v12 (all switches) | +0.1 +- 0.8 | **+1.8 +- 0.8** (z 2.1) | **+2.0 +- 0.8** (z 2.5) | +1.7 +- 0.9 (z 1.6) |
| B1 fold blend only | -0.7 +- 0.7 | -0.6 +- 0.7 | | |
| B2 value overbets only | -0.8 +- 0.6 | -0.0 +- 0.6 | | |
| B3 HU bluffs only | +0.3 +- 0.6 | +1.3 +- 0.7 (z 1.9) | +1.3 +- 0.7 (z 1.9) | |
| B5 light 3-bets only | -0.3 +- 0.6 | +0.6 +- 0.6 | +1.0 +- 0.7 (z 1.5) | +1.1 +- 0.7 (z 1.7) |

- v12's adaptive edge sits in hands won uncontested: +50.1 vs +44.6 bb/100, with showdown and folded results slightly worse. That is the bluff channel the static bench under-rewarded.
- Both deal sets agree. Pooled over the 480 pairs (simple inverse-variance average of the two runs): v12 +1.9 +- 0.6, B3 +1.3 +- 0.5, B5 +0.8 +- 0.5. B2 and B1 show nothing on either bench.

**Not modelled / known gaps:**
- Hand reading.
- Reactions to our shown bluffs on the flop and turn: the logs show none (within-seat slope about 0).
- Real teams' extra folding against our pot-size bets is reproduced only as the static hero level.
- River bets against us of 0.8 pot or more: fewer than 30 real decisions, left uncalibrated (river b5: 67.9% bench vs 83.3% real, n 24).
- Static per-team mismatches remain:
  - Claudebot 3-bets our opens 3.1% for real but 7.4% in the bench;
  - ediz_slow, SmartBGerBot and clanker fold to only 0-9% of our 4-bets for real (n 16-45), vs 7-29% for their clones;
  - Anton does not fold more to our 4-bets for real (46%), but the light-3-bet rule gives it 61%.
- Profiles still describe Saturday.

