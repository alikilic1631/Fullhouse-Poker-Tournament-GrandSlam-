# saturday/r011 — hero seat 5 (Durahim 1453), 1000 hands, **+68.6 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 3 | Attention Is All In | +185 | 53% | 48% | 5.3% | 2.5 | 30% |
| 0 | Mohil'sPokerBot | +119 | 27% | 10% | 4.9% | 2.3 | 35% |
| 5* | Durahim 1453 | +69 | 18% | 16% | 11.8% | 1.4 | 38% |
| 1 | matcha mille crêpes cake | +28 | 22% | 15% | 6.4% | 0.8 | 70% |
| 2 | Resonance Qt | +4 | 30% | 19% | 4.5% | 1.4 | 31% |
| 4 | GamesGone | -42 | 28% | 9% | 5.6% | 1.6 | 33% |
| 6 | ediz_slow | -363 | 79% | 31% | 22.1% | 2.2 | 51% |

**Hero by position (bb/100):** HJ -100 (n=143), EP2 -87 (n=143), BB -50 (n=143), SB +2 (n=143), BTN +139 (n=143), EP1 +277 (n=142), CO +300 (n=143)

**Biggest losses:**
- hand 107: Jc Jh | board Td 9s 5h Kh 9d | -100.0 bb | vs ediz_slow Two Pair
- hand 226: Qh Ad | board 5c 2s 9c Ah 3h | -100.0 bb | vs ediz_slow Straight
- hand 251: Ac Qs | board Qc Kh 6c Th 9c | -100.0 bb | vs ediz_slow Pair
- hand 286: Kc Qs | board 6c Qc 3c 8c Jh | -100.0 bb | vs Mohil'sPokerBot Flush
- hand 299: 9c 9d | board 6h As 5h 3d 7c | -100.0 bb | vs ediz_slow Pair
- hand 340: As Qd | board 4c Kc 3h Td 6c | -100.0 bb | vs ediz_slow Two Pair
- hand 348: As Qh | board 4d 9d Js Kh 2s | -100.0 bb | vs ediz_slow Pair
- hand 351: 8c 8h | board 7h 6c 4s Qs Jc | -100.0 bb | vs GamesGone Pair, ediz_slow Pair

**Biggest wins:**
- hand 739: As 8s | board 7s 3h 4d Jh 8d | +204.5 bb | vs matcha mille crêpes cake High Card, ediz_slow Pair
- hand 261: 6s 6h | board 3c Qs 5h 8h Td | +200.0 bb | vs matcha mille crêpes cake High Card, ediz_slow High Card
- hand 56: As Ah | board Jh Tc 5d Qh 2c | +108.0 bb | vs GamesGone Pair
- hand 897: As Ac | board 6h 3s 3d Qd Ah | +105.0 bb | vs Mohil'sPokerBot Full House

**Chips hero lost into pots won by:** ediz_slow 1288 bb, GamesGone 363 bb, Attention Is All In 161 bb, Mohil'sPokerBot 150 bb

**Replay through v5/bot.py:**
```
   2.0        2.0
  jam-3bet                               1.7        1.7
  check                                  0.4        0.4
all decision points (counts)             live bot   this bot
  preflop  fold                          823        823
  preflop  3bet                           83         83
  preflop  open                           63         63
  preflop  call                           42         42
  preflop  jam-3bet                       17         17
  preflop  jam-4bet+                      13         13
  preflop  call-shove                     10         10
  preflop  4bet+                           5          5
  preflop  check                           4          4
  flop     fold                           32         33
  flop     call                           26         26
  flop     check                          22         25
  flop     bet-small                      16         11
  flop     bet-mid                        12         15
  flop     bet-overbet                     6          5
  flop     raise-mid                       3          2
  turn     fold                           16         16
  turn     call                            6          7
  turn     check                           5          7
  turn     bet-mid                         6          4
  turn     bet-overbet                     2          2
  turn     bet-small                       1          1
  turn     raise-small                     1          0
  river    fold                            4          4
  river    check                           3          3
  river    call                            2          2
  river    bet-small                       1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  984 hands, live result   +827.2
  this bot folds where live did not:    4 hands, live result    -60.5 -> this bot    -27.3  (+3.3 bb/100)
  other deviations (outcome unknown):   12 hands, live result    -80.7
      turn: live bet-mid -> this bot check                    2 hands, live    -97.5
      flop: live fold -> this bot call                        3 hands, live    -16.1
      flop: live bet-small -> this bot check                  4 hands, live    -12.3
      flop: live check -> this bot bet-mid                    1 hands, live     +5.0
      flop: live raise-mid -> this bot call                   1 hands, live    +19.1
      turn: live raise-small -> this bot call                 1 hands, live    +21.1
```
