# saturday/r018 — hero seat 1 (Durahim 1453), 1000 hands, **-14.8 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 | Gherkers | +117 | 38% | 25% | 4.6% | 2.0 | 22% |
| 6 | supernut | +66 | 21% | 16% | 1.5% | 1.0 | 30% |
| 2 | GamesGone | +31 | 26% | 14% | 2.7% | 1.7 | 27% |
| 4 | Joca | -7 | 4% | 0% | 0.3% | 1.8 | 62% |
| 3 | The Market Makers | -9 | 19% | 12% | 4.5% | 1.8 | 26% |
| 1* | Durahim 1453 | -15 | 19% | 16% | 7.5% | 3.8 | 32% |
| 5 | ediz_slow | -185 | 82% | 35% | 17.5% | 2.6 | 39% |

**Hero by position (bb/100):** SB -225 (n=143), EP2 -108 (n=143), BTN -86 (n=143), BB -24 (n=142), EP1 -8 (n=143), HJ +110 (n=143), CO +237 (n=143)

**Biggest losses:**
- hand 75: Ah Jh | board Qs 8s 7d As 3s | -100.0 bb | vs ediz_slow Two Pair
- hand 161: As Kh | board 2s 6d 6c 6s Qh | -100.0 bb | vs ediz_slow Full House
- hand 267: Qd As | board 3h 6c Js 4s Ks | -100.0 bb | vs ediz_slow Pair
- hand 313: 9d 9h | board Kd Js 4h Qh Jd | -100.0 bb | vs ediz_slow Two Pair
- hand 547: 8s 8c | board Kc Jd Kd Ah 3d | -100.0 bb | vs ediz_slow Two Pair
- hand 562: Kc 5h | board 5d Kh 8d 6s Ts | -100.0 bb | vs GamesGone Three of a Kind
- hand 658: Qs Ac | board 3h Tc Ah 9s Qh | -100.0 bb | vs The Market Makers Flush
- hand 766: 9d 9h | board 8c Kd 3c 7c 2d | -100.0 bb | vs GamesGone High Card, ediz_slow Two Pair

**Biggest wins:**
- hand 787: 9d 9c | board 5d 6c Th 3c 5h | +110.4 bb | vs ediz_slow Pair
- hand 416: Tc Td | board 2d Th 9d Js 4d | +110.4 bb | vs ediz_slow Three of a Kind
- hand 927: Ts Ac | board 9h Tc 3c 9s 2d | +104.2 bb | vs ediz_slow Pair
- hand 171: Qc Ac | board 5c Tc 2h 7d 7c | +104.2 bb | vs ediz_slow Two Pair

**Chips hero lost into pots won by:** ediz_slow 1050 bb, Gherkers 211 bb, GamesGone 161 bb, The Market Makers 144 bb

**Replay through v9/bot.py:**
```
   0.3        0.3
  check                                  0.2        0.2
  limp                                   0.2        0.2
all decision points (counts)             live bot   this bot
  preflop  fold                          844        844
  preflop  open                          102        102
  preflop  3bet                           52         52
  preflop  call                           37         37
  preflop  jam-4bet+                      17         17
  preflop  4bet+                           3          3
  preflop  jam-3bet                        3          3
  preflop  check                           2          2
  preflop  limp                            2          2
  flop     bet-mid                        23         25
  flop     fold                           24         19
  flop     check                          20         17
  flop     bet-small                      17         17
  flop     call                           12         18
  flop     bet-overbet                     5          6
  flop     raise-mid                       2          0
  flop     raise-overbet                   0          1
  turn     check                          13         11
  turn     fold                            9          9
  turn     bet-overbet                     5          6
  turn     bet-mid                         4          4
  turn     call                            4          4
  turn     bet-small                       1          2
  river    check                           7          7
  river    bet-mid                         2          2
  river    fold                            2          2
  river    bet-overbet                     1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  989 hands, live result   -178.9
  this bot folds where live did not:    0 hands, live result     +0.0 -> this bot     +0.0  (+0.0 bb/100)
  other deviations (outcome unknown):   11 hands, live result    +31.1
      flop: live fold -> this bot call                        5 hands, live    -18.5
      turn: live check -> this bot bet-mid                    1 hands, live     -3.5
      turn: live check -> this bot bet-small                  1 hands, live     -1.0
      flop: live check -> this bot bet-small                  1 hands, live     +7.5
      flop: live raise-mid -> this bot call                   1 hands, live    +16.5
      flop: live check -> this bot bet-mid                    2 hands, live    +30.1
```
