# saturday/r012 — hero seat 2 (Durahim 1453), 1000 hands, **-28.9 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 5 | aydine | +72 | 22% | 13% | 1.6% | 2.8 | 18% |
| 4 | Claudebot | +17 | 22% | 17% | 1.6% | 1.2 | 29% |
| 6 | Poke | +11 | 15% | 10% | 2.0% | 1.1 | 27% |
| 0 | Equity Engine | -3 | 28% | 20% | 1.0% | 3.0 | 26% |
| 3 | Astra La Vista | -23 | 20% | 14% | 2.6% | 3.2 | 33% |
| 2* | Durahim 1453 | -29 | 24% | 20% | 3.3% | 1.4 | 23% |
| 1 | Mohil'sPokerBot | -45 | 21% | 17% | 6.1% | 2.6 | 30% |

**Hero by position (bb/100):** SB -150 (n=143), CO -93 (n=142), HJ -56 (n=143), BTN -33 (n=143), EP2 +11 (n=143), BB +37 (n=143), EP1 +80 (n=143)

**Biggest losses:**
- hand 100: Ah Jd | board 8h 5c Th 9c 2s | -100.0 bb | vs Claudebot Pair
- hand 502: 6d 6h | board 3s 3h 7c 7h 2d | -100.0 bb | vs Equity Engine Two Pair
- hand 904: Kd Kc | board 8d 5d 8c Ad 7s | -100.0 bb | vs aydine Two Pair
- hand 320: Ac Ad | board Qc 9d 7h Qh 9c | -55.2 bb
- hand 411: Ac Tc | board 8d 3d Ah 7d | -47.5 bb
- hand 664: 9d 9c | board Ts 4s 4h Ah 2h | -43.5 bb | vs Poke Two Pair
- hand 175: Ks Qc | board Ts 7s Qh 9s Jd | -41.6 bb
- hand 553: Qc 8d | board Jc 8c 5c 6c 4h | -36.9 bb | vs aydine Flush

**Biggest wins:**
- hand 809: Ks 2s | board 6s Tc 2h 2c 5h | +100.5 bb | vs Equity Engine Two Pair
- hand 58: Js Qc | board 7c 9d 8d Td 3c | +92.8 bb | vs Equity Engine Pair
- hand 570: As Ad | board 4s Td 8d 2c Qd | +90.5 bb | vs Mohil'sPokerBot Pair
- hand 928: Jc Tc | board Td 8h As Th 2h | +72.0 bb | vs Mohil'sPokerBot Two Pair

**Chips hero lost into pots won by:** aydine 306 bb, Equity Engine 286 bb, Claudebot 256 bb, Astra La Vista 202 bb

**Replay through v5/bot.py:**
```
     46         46
  preflop  3bet                           22         22
  preflop  jam-3bet                        6          6
  preflop  4bet+                           5          5
  flop     check                          44         39
  flop     call                           37         43
  flop     fold                           34         31
  flop     bet-mid                        23         27
  flop     bet-small                      12         13
  flop     raise-mid                       8          5
  flop     bet-overbet                     6          6
  turn     check                          34         33
  turn     fold                           30         29
  turn     call                           12         14
  turn     bet-mid                        10          8
  turn     bet-small                       5          7
  turn     bet-overbet                     3          4
  turn     raise-mid                       2          2
  turn     raise-small                     2          1
  river    check                          23         22
  river    fold                            8          8
  river    call                            7          7
  river    bet-small                       4          4
  river    bet-overbet                     2          2
  river    bet-mid                         0          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  971 hands, live result   -182.3
  this bot folds where live did not:    4 hands, live result   -129.6 -> this bot    -35.4  (+9.4 bb/100)
  other deviations (outcome unknown):   25 hands, live result    +22.4
      flop: live bet-mid -> this bot check                    1 hands, live    -55.2
      flop: live check -> this bot bet-small                  4 hands, live    -30.1
      flop: live fold -> this bot call                        5 hands, live    -23.5
      turn: live bet-mid -> this bot check                    1 hands, live    -16.2
      turn: live fold -> this bot call                        2 hands, live    -12.2
      turn: live check -> this bot bet-small                  2 hands, live    -11.4
      turn: live check -> this bot bet-mid                    1 hands, live     +5.8
      flop: live raise-mid -> this bot call                   4 hands, live    +10.6
      turn: live bet-small -> this bot check                  1 hands, live    +18.8
      flop: live bet-small -> this bot check                  1 hands, live    +45.1
```
