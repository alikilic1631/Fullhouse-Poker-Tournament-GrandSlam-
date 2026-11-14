# saturday/r007 — hero seat 0 (Durahim 1453), 1000 hands, **+25.0 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 2 | Gherkers | +88 | 32% | 27% | 6.4% | 1.6 | 39% |
| 1 | Phil AIvey | +83 | 26% | 20% | 4.6% | 1.0 | 48% |
| 4 | Chinese people can fly | +67 | 32% | 9% | 5.0% | 1.3 | 29% |
| 5 | Jump Street | +67 | 22% | 13% | 5.3% | 1.2 | 40% |
| 7 | Red | +50 | 26% | 17% | 4.2% | 3.6 | 54% |
| 0* | Durahim 1453 | +25 | 15% | 12% | 6.4% | 2.0 | 37% |
| 6 | SmartBGerBot | +24 | 10% | 7% | 1.2% | 0.8 | 37% |
| 3 | ediz_slow | -403 | 72% | 32% | 28.0% | 2.9 | 60% |

**Hero by position (bb/100):** BTN -180 (n=125), EP1 -165 (n=125), CO -91 (n=125), SB +62 (n=125), BB +102 (n=125), EP2 +133 (n=125), EP3 +160 (n=125), HJ +178 (n=125)

**Biggest losses:**
- hand 136: Ad Ah | board Js 8s 7c 6d Kc | -100.0 bb | vs ediz_slow Two Pair
- hand 332: Jd Js | board As Kh 2s 5d Th | -100.0 bb | vs ediz_slow Pair
- hand 338: 8d 8c | board 9s Ac Ts 4d 5h | -100.0 bb | vs ediz_slow Pair
- hand 419: Qh Ad | board Ks Jd 5s Ts 7s | -100.0 bb | vs ediz_slow Flush
- hand 427: Jd Js | board Kc 7h Jh 7c Kh | -100.0 bb | vs Red Full House
- hand 622: Qc Qs | board Ad 7d 4h As Js | -100.0 bb | vs ediz_slow Two Pair, Red Three of a Kind
- hand 732: 6d 6h | board 5h Td 5s Jh Ks | -100.0 bb | vs ediz_slow Three of a Kind
- hand 737: Ad Th | board Ks 9d Td 6h 5s | -100.0 bb | vs ediz_slow Pair

**Biggest wins:**
- hand 841: Qh Ah | board 6s Qs Qd 8c 8s | +216.2 bb | vs ediz_slow Two Pair, Jump Street Two Pair
- hand 359: Jc Ad | board 2s As 6s 4h 7s | +201.5 bb | vs Phil AIvey Pair, ediz_slow Pair
- hand 771: 8d Ah | board 8h 8s 5s 4c 2s | +107.0 bb | vs ediz_slow Two Pair
- hand 393: Qd Kc | board 3h Kd 9h 9s 2h | +104.5 bb | vs ediz_slow Two Pair

**Chips hero lost into pots won by:** ediz_slow 1329 bb, Red 228 bb, Chinese people can fly 182 bb, Phil AIvey 137 bb

**Replay through v2/bot.py:**
```
      5          5
  preflop  call-shove                      5          5
  preflop  check                           3          3
  flop     fold                           25         25
  flop     call                           18         20
  flop     check                          16         20
  flop     bet-mid                        19         15
  flop     bet-overbet                     8         10
  flop     bet-small                       9          7
  flop     raise-small                     4          4
  flop     raise-overbet                   2          1
  flop     raise-mid                       1          0
  turn     fold                           13         14
  turn     check                          11         10
  turn     call                            6          6
  turn     bet-mid                         4          5
  turn     raise-small                     2          1
  turn     bet-overbet                     0          1
  turn     bet-small                       1          0
  river    check                           9          8
  river    fold                            7          7
  river    call                            2          2
  river    bet-small                       2          2
  river    bet-mid                         1          1
  river    bet-overbet                     0          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  983 hands, live result   +431.2
  this bot folds where live did not:    2 hands, live result   -120.4 -> this bot    -57.9  (+6.3 bb/100)
  other deviations (outcome unknown):   15 hands, live result    -61.1
      turn: live check -> this bot bet-mid                    1 hands, live    -29.9
      flop: live call -> this bot raise-small                 1 hands, live    -22.2
      flop: live check -> this bot bet-small                  1 hands, live    -19.8
      turn: live bet-mid -> this bot check                    1 hands, live    -19.7
      turn: live fold -> this bot call                        1 hands, live     -7.8
      flop: live check -> this bot bet-mid                    1 hands, live     -5.0
      flop: live fold -> this bot call                        1 hands, live     -4.0
      flop: live bet-mid -> this bot check                    4 hands, live     -1.4
      flop: live raise-overbet -> this bot call               1 hands, live     +5.5
      flop: live raise-mid -> this bot call                   1 hands, live    +15.2
```
