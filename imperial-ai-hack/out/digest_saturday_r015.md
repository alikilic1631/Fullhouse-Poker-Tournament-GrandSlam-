# saturday/r015 — hero seat 2 (Durahim 1453), 1000 hands, **-28.4 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 | Kojack | +54 | 26% | 22% | 4.1% | 1.9 | 23% |
| 4 | Equity Engine | +28 | 32% | 20% | 1.4% | 3.5 | 20% |
| 3 | supernut | -10 | 17% | 12% | 1.1% | 4.8 | 14% |
| 1 | Jump Street | -13 | 29% | 21% | 4.6% | 2.3 | 29% |
| 2* | Durahim 1453 | -28 | 28% | 22% | 3.7% | 2.3 | 18% |
| 5 | YSL_TWIZZY | -31 | 18% | 12% | 3.2% | 1.2 | 33% |

**Hero by position (bb/100):** BB -148 (n=167), BTN -28 (n=166), SB -10 (n=167), HJ -3 (n=167), EP1 +9 (n=167), CO +10 (n=166)

**Biggest losses:**
- hand 224: 9c Kc | board Kh 6h 7d 5h Tc | -100.0 bb | vs Jump Street Flush
- hand 557: 6c 4c | board 8d 7c 5s Th 5d | -100.0 bb | vs Equity Engine Full House
- hand 687: Qd 3h | board 3c 6c Js Qh Jc | -47.5 bb | vs Kojack Two Pair
- hand 159: Th Jh | board 3d 8h Qh 2s | -29.8 bb
- hand 56: Js Jh | board 5h 4c 4h | -29.5 bb
- hand 699: Qc 9c | board 9d Kd Qh Ac Js | -19.8 bb
- hand 394: Jc Ac | board 2h 5c 8s 6s | -19.4 bb
- hand 74: 6d 6c | board Qd 2s 2h Ks 3c | -18.8 bb | vs Jump Street Two Pair

**Biggest wins:**
- hand 866: Qc Qd | board 3d Ts 2h 8d 6c | +103.0 bb | vs Jump Street Pair
- hand 130: 5c Ac | board 8c 7d 7c 5s 7s | +65.7 bb | vs Jump Street Full House, Equity Engine Three of a Kind
- hand 248: Jd Js | board 6c 4d 9c 6s 6h | +60.5 bb | vs YSL_TWIZZY Three of a Kind
- hand 935: Qh Th | board Qd Qc Kd 5c Td | +34.6 bb | vs supernut Two Pair

**Chips hero lost into pots won by:** Equity Engine 383 bb, Jump Street 316 bb, Kojack 270 bb, YSL_TWIZZY 125 bb

**Replay through v6/bot.py:**
```
    186        186
  preflop  call                           61         61
  preflop  3bet                           27         27
  preflop  jam-3bet                        7          7
  preflop  4bet+                           3          3
  flop     check                          42         40
  flop     bet-mid                        41         41
  flop     fold                           34         42
  flop     call                           26         19
  flop     bet-small                      12         12
  flop     bet-overbet                    10         12
  flop     raise-mid                       4          3
  turn     check                          33         32
  turn     fold                           30         29
  turn     call                           15         16
  turn     bet-mid                        14         16
  turn     bet-small                       7          6
  turn     bet-overbet                     1          1
  turn     raise-mid                       1          1
  river    check                          20         20
  river    fold                           17         17
  river    bet-small                       6          6
  river    bet-mid                         4          4
  river    call                            3          3
  river    raise-small                     1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  972 hands, live result   -223.6
  this bot folds where live did not:   10 hands, live result    -53.0 -> this bot    -36.3  (+1.7 bb/100)
  other deviations (outcome unknown):   18 hands, live result     -7.7
      flop: live bet-mid -> this bot check                    2 hands, live    -26.5
      flop: live bet-small -> this bot check                  1 hands, live    -15.4
      flop: live call -> this bot raise-mid                   1 hands, live    -10.1
      turn: live fold -> this bot call                        1 hands, live     -8.0
      flop: live check -> this bot bet-mid                    4 hands, live     -6.2
      flop: live fold -> this bot call                        2 hands, live     -4.7
      flop: live check -> this bot bet-overbet                1 hands, live     +3.0
      flop: live raise-mid -> this bot call                   1 hands, live     +7.4
      turn: live check -> this bot bet-mid                    3 hands, live    +20.1
      turn: live bet-mid -> this bot check                    2 hands, live    +32.8
```
