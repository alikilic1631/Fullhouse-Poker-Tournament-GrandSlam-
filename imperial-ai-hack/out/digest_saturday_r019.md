# saturday/r019 — hero seat 6 (Durahim 1453), 1000 hands, **+18.4 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 2 | Astra La Vista | +27 | 22% | 15% | 2.4% | 2.6 | 29% |
| 3 | Anker Batteries | +20 | 24% | 20% | 5.0% | 1.6 | 26% |
| 6* | Durahim 1453 | +18 | 23% | 18% | 2.8% | 1.5 | 14% |
| 1 | kaiserbot | +17 | 21% | 11% | 1.5% | 1.5 | 26% |
| 0 | Gherkers | +13 | 26% | 19% | 7.6% | 4.2 | 18% |
| 4 | GamesGone | -37 | 30% | 18% | 1.1% | 2.9 | 30% |
| 5 | YSL_TWIZZY | -59 | 18% | 14% | 1.3% | 0.7 | 33% |

**Hero by position (bb/100):** BB -59 (n=143), CO -40 (n=143), SB -39 (n=143), HJ +23 (n=143), EP1 +38 (n=143), EP2 +72 (n=142), BTN +134 (n=143)

**Biggest losses:**
- hand 635: 9h Ks | board 8h Kc 2d 9c 4c | -100.0 bb | vs Astra La Vista Three of a Kind
- hand 714: Ah Qh | board Th 4d 5d Td | -51.5 bb
- hand 462: Kh Td | board 9s Th 3d 8h 6s | -36.5 bb | vs kaiserbot Straight, GamesGone Pair
- hand 463: Ts Js | board Jh 4c Qd 2d Qc | -36.5 bb
- hand 158: Kd Ah | board 5h 3s 4s 8h | -34.0 bb
- hand 910: Kh Ad | board - | -21.8 bb
- hand 567: Jh As | board Qh Jd 4h 9s 3c | -16.2 bb | vs GamesGone Two Pair
- hand 144: Qs Ah | board Tc 7h 5c 9d | -16.1 bb

**Biggest wins:**
- hand 280: Kh Jh | board 9h 4h Qd Td 9c | +120.2 bb | vs GamesGone Two Pair
- hand 298: Jh Jc | board 9s 7d 5h 3s Js | +101.5 bb | vs GamesGone Pair
- hand 133: As Js | board Ks 2s Ts 5s 4h | +101.5 bb | vs kaiserbot Flush
- hand 42: Ah Ad | board 6d Ac Kh 7s 5s | +101.5 bb | vs Gherkers Pair

**Chips hero lost into pots won by:** Astra La Vista 224 bb, GamesGone 224 bb, kaiserbot 181 bb, Gherkers 134 bb

**Replay through v10/bot.py:**
```
lop  fold                          776        776
  preflop  open                          155        155
  preflop  call                           53         53
  preflop  3bet                           21         21
  preflop  jam-3bet                        3          3
  preflop  check                           3          3
  preflop  4bet+                           3          3
  preflop  jam-4bet+                       1          1
  flop     check                          46         41
  flop     fold                           38         39
  flop     call                           36         38
  flop     bet-mid                        21         23
  flop     bet-small                      19         19
  flop     bet-overbet                     5          8
  flop     raise-mid                       7          4
  turn     fold                           25         27
  turn     check                          20         19
  turn     call                           16         14
  turn     bet-mid                        11         12
  turn     bet-small                       4          5
  turn     bet-overbet                     4          3
  turn     raise-overbet                   1          1
  turn     raise-mid                       1          1
  river    check                          13         13
  river    fold                           11         11
  river    bet-mid                         3          3
  river    bet-small                       3          3
  river    call                            2          2
  river    bet-overbet                     1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  977 hands, live result    +70.9
  this bot folds where live did not:    6 hands, live result   -119.5 -> this bot    -49.0  (+7.0 bb/100)
  other deviations (outcome unknown):   17 hands, live result   +232.3
      flop: live bet-mid -> this bot check                    1 hands, live    -36.5
      flop: live fold -> this bot call                        5 hands, live    -19.6
      turn: live fold -> this bot call                        1 hands, live     -5.2
      turn: live check -> this bot bet-mid                    1 hands, live     -2.5
      flop: live check -> this bot bet-small                  4 hands, live    +76.6
      flop: live raise-mid -> this bot call                   3 hands, live    +98.3
      flop: live check -> this bot bet-mid                    2 hands, live   +121.2
```
