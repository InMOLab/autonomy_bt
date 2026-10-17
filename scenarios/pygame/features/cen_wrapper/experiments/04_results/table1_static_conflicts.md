## Table 1: Static boundary conflicts under mechanism ablation.

R_L = R_f = 500. Mean final conflicts over the n seeds of the group, with the number of seeds having at least one conflict in parentheses. Proxy: In = inbound relay, Out = outbound emission. Solver: In = relay, Plan = plan forwarding.

| Algorithm | Connectivity (n) | Proxy Neither | Proxy In | Proxy Out | Proxy Both | Solver Neither | Solver In | Solver Plan | Solver Both | Relay Full | Dec-only Full |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Hungarian | Follower-connected (45) | 3.04 (45) | 1.62 (37) | 2.11 (44) | 0 (0) | 3.04 (45) | 3.07 (45) | 0.82 (34) | 0 (0) | 0 (0) | 0 (0) |
| Hungarian | Leader-dependent (5) | 3.20 (5) | 2.00 (5) | 2.20 (5) | 0 (0) | 3.20 (5) | 3.20 (5) | 1.00 (4) | 0.80 (3) | 0 (0) | 2.00 (5) |
| CBBA | Follower-connected (45) | 12.02 (45) | 8.84 (45) | 5.98 (45) | 0 (0) | 12.02 (45) | 12.04 (45) | 2.73 (42) | 0 (0) | 0 (0) | 0 (0) |
| CBBA | Leader-dependent (5) | 13.20 (5) | 9.80 (5) | 7.20 (5) | 0 (0) | 13.20 (5) | 13.60 (5) | 3.40 (5) | 3.60 (5) | 0 (0) | 6.20 (5) |

## Supporting numbers

Total conflicts (seeds with at least one conflict / seeds), for all 50 seeds and per group.

| Design | Condition | CBBA all 50 | CBBA 45 | CBBA 5 | Hungarian all 50 | Hungarian 45 | Hungarian 5 |
|---|---|---|---|---|---|---|---|
| Leader-as-proxy | neither | 607 (50/50) | 541 (45/45) | 66 (5/5) | 153 (50/50) | 137 (45/45) | 16 (5/5) |
| Leader-as-proxy | inbound relay only | 447 (50/50) | 398 (45/45) | 49 (5/5) | 83 (42/50) | 73 (37/45) | 10 (5/5) |
| Leader-as-proxy | outbound emission only | 305 (50/50) | 269 (45/45) | 36 (5/5) | 106 (49/50) | 95 (44/45) | 11 (5/5) |
| Leader-as-proxy | both | 0 (0/50) | 0 (0/45) | 0 (0/5) | 0 (0/50) | 0 (0/45) | 0 (0/5) |
| Leader-as-solver | neither | 607 (50/50) | 541 (45/45) | 66 (5/5) | 153 (50/50) | 137 (45/45) | 16 (5/5) |
| Leader-as-solver | relay only | 610 (50/50) | 542 (45/45) | 68 (5/5) | 154 (50/50) | 138 (45/45) | 16 (5/5) |
| Leader-as-solver | plan forwarding only | 140 (47/50) | 123 (42/45) | 17 (5/5) | 42 (38/50) | 37 (34/45) | 5 (4/5) |
| Leader-as-solver | both | 18 (5/50) | 0 (0/45) | 18 (5/5) | 4 (3/50) | 0 (0/45) | 4 (3/5) |
| Leader-as-relay | - | 0 (0/50) | 0 (0/45) | 0 (0/5) | 0 (0/50) | 0 (0/45) | 0 (0/5) |
| Dec-only | - | 31 (5/50) | 0 (0/45) | 31 (5/5) | 10 (5/50) | 0 (0/45) | 10 (5/5) |

Leader-as-solver: conflict types, unassigned tasks and convergence (all 50 seeds).

| Algorithm | Slots | cen_dec | dec_dec_same | dec_dec_split | cen_cen | Unassigned | Converged | Median convergence tick |
|---|---|---|---|---|---|---|---|---|
| cbba | neither | 600 | 0 | 7 | 0 | 621 | 50/50 | 4 |
| hungarian | neither | 151 | 0 | 2 | 0 | 156 | 50/50 | 2 |
| cbba | relay only | 608 | 0 | 2 | 0 | 610 | 50/50 | 4 |
| hungarian | relay only | 154 | 0 | 0 | 0 | 154 | 50/50 | 2 |
| cbba | plan forwarding only | 0 | 0 | 140 | 0 | 142 | 50/50 | 8 |
| hungarian | plan forwarding only | 0 | 0 | 42 | 0 | 43 | 50/50 | 3 |
| cbba | both | 0 | 0 | 18 | 0 | 18 | 50/50 | 8 |
| hungarian | both | 0 | 0 | 4 | 0 | 4 | 50/50 | 4 |
