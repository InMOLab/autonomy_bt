## Table 2: Boundary chattering under mechanism ablation.

R_f = 150, R_L = 500. Runs with at least one chattering episode among 50 seeds; parentheses give the total boundary crossings during those episodes. Solver All = grace + reset + commit + iso; All - commit disables commit.

| Algorithm | Proxy None | Proxy iso | Proxy adopt | Proxy Both | Relay None | Relay iso | Solver None | Solver All - commit | Solver All |
|---|---|---|---|---|---|---|---|---|---|
| Hungarian | 13 (2000) | 0 | 12 (1067) | 0 | 13 (835) | 0 | 29 (10612) | 16 (1183) | 0 |
| CBBA | 6 (340) | 0 | 0 | 0 | 0 | 0 | 32 (25856) | 7 (4398) | 0 |
| GRAPE | 5 (560) | 2 (95) | 1 (4) | 1 (4) | 0 | 0 | 42 (8511) | 41 (6306) | 0 |

Completed missions (of 50) in the same configurations:

| Algorithm | Proxy None | Proxy iso | Proxy adopt | Proxy Both | Relay None | Relay iso | Solver None | Solver All - commit | Solver All |
|---|---|---|---|---|---|---|---|---|---|
| Hungarian | 50 | 50 | 50 | 50 | 50 | 50 | 20 | 21 | 50 |
| CBBA | 50 | 50 | 50 | 50 | 50 | 50 | 10 | 25 | 50 |
| GRAPE | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 | 50 |

## Supporting numbers

All eleven configurations: runs with chattering (crossings inside episodes) and completed missions.

| Design | Rules | cbba | grape | hungarian |
|---|---|---|---|---|
| Leader-as-proxy | none | 6 (340) · done 50/50 | 5 (560) · done 50/50 | 13 (2000) · done 50/50 |
| Leader-as-proxy | iso | 0 · done 50/50 | 2 (95) · done 50/50 | 0 · done 50/50 |
| Leader-as-proxy | adopt | 0 · done 50/50 | 1 (4) · done 50/50 | 12 (1067) · done 50/50 |
| Leader-as-proxy | both ◆ | 0 · done 50/50 | 1 (4) · done 50/50 | 0 · done 50/50 |
| Leader-as-relay | none | 0 · done 50/50 | 0 · done 50/50 | 13 (835) · done 50/50 |
| Leader-as-relay | +iso ◆ | 0 · done 50/50 | 0 · done 50/50 | 0 · done 50/50 |
| Leader-as-solver | none | 32 (25856) · done 10/50 | 42 (8511) · done 50/50 | 29 (10612) · done 20/50 |
| Leader-as-solver | no grace (reset+commit) | 0 · done 50/50 | 0 · done 50/50 | 0 · done 50/50 |
| Leader-as-solver | no reset (grace+commit) | 0 · done 48/50 | 0 · done 50/50 | 0 · done 50/50 |
| Leader-as-solver | no commit (grace+reset+iso) | 7 (4398) · done 25/50 | 41 (6306) · done 50/50 | 16 (1183) · done 21/50 |
| Leader-as-solver | all ◆ (grace+reset+commit+iso) | 0 · done 50/50 | 0 · done 50/50 | 0 · done 50/50 |

Leader-as-solver rows: duplicate-claim tick share (mean), completion time and travel relative to all three rules.

```
cbba      none                       dup 0.219  done 10/50  time vs ◆ +30.4% (n=10)  travel vs ◆ +33.6%
cbba      no grace (reset+commit)    dup 0.682  done 50/50  time vs ◆ +1.1% (n=50)  travel vs ◆ +7.4%
cbba      no reset (grace+commit)    dup 0.449  done 48/50  time vs ◆ +1.7% (n=48)  travel vs ◆ -1.6%
cbba      no commit (grace+reset+iso) dup 0.286  done 25/50  time vs ◆ +0.4% (n=25)  travel vs ◆ -4.0%
cbba      all ◆ (grace+reset+commit+iso) dup 0.564  done 50/50  time vs ◆ +0.0% (n=50)  travel vs ◆ +0.0%
grape     none                       dup 0.998  done 50/50  time vs ◆ +0.7% (n=50)  travel vs ◆ -0.5%
grape     no grace (reset+commit)    dup 0.998  done 50/50  time vs ◆ +0.0% (n=50)  travel vs ◆ +0.0%
grape     no reset (grace+commit)    dup 0.998  done 50/50  time vs ◆ +0.0% (n=50)  travel vs ◆ +0.0%
grape     no commit (grace+reset+iso) dup 0.998  done 50/50  time vs ◆ +0.8% (n=50)  travel vs ◆ -0.0%
grape     all ◆ (grace+reset+commit+iso) dup 0.998  done 50/50  time vs ◆ +0.0% (n=50)  travel vs ◆ +0.0%
hungarian none                       dup 0.535  done 20/50  time vs ◆ +26.5% (n=20)  travel vs ◆ +40.5%
hungarian no grace (reset+commit)    dup 0.912  done 50/50  time vs ◆ +0.4% (n=50)  travel vs ◆ +7.8%
hungarian no reset (grace+commit)    dup 0.788  done 50/50  time vs ◆ +5.8% (n=50)  travel vs ◆ +1.6%
hungarian no commit (grace+reset+iso) dup 0.495  done 21/50  time vs ◆ -0.1% (n=21)  travel vs ◆ -1.3%
hungarian all ◆ (grace+reset+commit+iso) dup 0.846  done 50/50  time vs ◆ +0.0% (n=50)  travel vs ◆ +0.0%
```

Leader-as-proxy rows: completion time and travel relative to no rule (mean per-seed ratio - 1).

```
cbba      hybrid_iso    time +0.2%  travel +0.2%
cbba      hybrid_adopt  time +0.5%  travel -0.1%
cbba      hybrid_rules  time +0.4%  travel +0.3%
grape     hybrid_iso    time +0.0%  travel +0.1%
grape     hybrid_adopt  time +0.0%  travel +0.1%
grape     hybrid_rules  time +0.0%  travel +0.1%
hungarian hybrid_iso    time -2.0%  travel +0.2%
hungarian hybrid_adopt  time -0.3%  travel +0.1%
hungarian hybrid_rules  time -2.0%  travel +0.2%
```
