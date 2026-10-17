# Experiments for "Hybrid Centralised–Decentralised MRTA under Limited Leader Communication Range"

This folder holds the scripts and data behind the simulation results of the paper (Section 5). The numbered folders are
used in order: run the experiments (01), which write their data (02); analyse the data (03), which writes the results (04).

```
experiments/
  01_scripts/    experiment runners (each run is one headless simulation; results are appended to a CSV in 02_data/)
  02_data/       result CSVs, one per runner (the data of the paper)
  03_analysis/   scripts that turn the CSVs into the paper's tables and figure
  04_results/    the analysis output, one Markdown file per analysis script (from 02_data/)
  02_data/rerun_261011/, 04_results/rerun_261011/   a full rerun of every runner with this code on 2026-10-11, and its analysis
  99_archived/   earlier experiments and data that the paper does not use (kept for the record; see the end)
```

## Overview

| Paper | Runner (`01_scripts/`) | Data (`02_data/`) | Analysis (`03_analysis/`) → result (`04_results/`) |
|---|---|---|---|
| §5.2, first paragraph: full-coverage equivalence (150 static instances) | `run_sec52_full_coverage.py` | `sec52_full_coverage.csv` | `sec52_full_coverage.py` → `.md` |
| §5.2, Table 1: static boundary conflicts under mechanism ablation | `run_table1_static_conflicts.py` | `table1_seeds.json`, `table1_proxy_ablation.csv`, `table1_relay_deconly.csv`, `table1_solver.csv`, `table1_solver_slots.csv` | `table1_static_conflicts.py` → `.md` |
| §5.2, Table 2: boundary chattering under mechanism ablation | `run_table2_chattering.py` | `table2_chattering.csv` | `table2_chattering.py` → `.md` |
| §5.3, Figure 3: Leader-as-proxy vs decentralised-only | `run_fig3_proxy_vs_deconly.py` | `fig3_proxy_vs_deconly.csv` | `fig3_proxy_vs_deconly.py` → `.md` |
| §5.3, Tables 3 and 4: vs Solver and Relay; communication | `run_table3_table4_dynamic.py` (+ Figure 3's runs) | `table3_table4_dynamic.csv`, `fig3_proxy_vs_deconly.csv` | `table3_table4_dynamic.py` → `.md` |

Shared code: `01_scripts/common.py` (config files, designs and their behaviour trees, teams, metrics), `_campaign.py`
(parallel, resumable campaign driver), `_run_single.py` (one dynamic run), `_run_static.py` (one static run);
`03_analysis/_report.py` (data folder, writing the output to `04_results/`).

## Requirements and how to run

- Python 3.10 with `pygame`, `numpy`, `scipy`, `pandas` (the `py310` conda environment of this project).
- **Runners** must be started from `webots/src/autonomy_bt/`, because they import the simulator (`core/`,
  `platforms/pygame/`) and the shared plugins (`plugins/`) relative to that folder. In the commands below,
  `S=scenarios/pygame/features/cen_wrapper/experiments/01_scripts`.
- Runners are **resumable**: a run whose key (seed, algorithm, design, radii, ...) is already in its CSV in `02_data/`
  is skipped. To regenerate a CSV, move the file away first. The numeric argument of a runner is the number of parallel
  workers (default 14; Table 1: 8). A full rerun of everything takes about 4.5 hours with 14 workers.
- **Analysis** scripts read `02_data/` and can be run from anywhere, e.g. `python 03_analysis/table1_static_conflicts.py`.
  Each prints its result and writes the same text to `04_results/<script name>.md`: first the paper's table or figure
  with the paper's rows, columns and values, then "Supporting numbers" (counts, confidence intervals and other numbers
  quoted in the text). The environment variables `DATA_DIR` and `RESULTS_DIR` change the two folders.

## Common setting (paper §5.1)

- Arena 1400 × 1000, leader fixed at (700, 500), robot speed 0.5 per tick, reward λ^(d/v) / |C|^α with λ = 0.999.
- Teams in every experiment: CBBA 15 followers / 60 tasks, bundle 4, full bundle reset, tasks in [40, 1300] × [40, 700];
  Hungarian 15 / 15; GRAPE 40 / 10 (`DENSE_TEAM`, `DENSE_TASK_REGION`, `team_of()` in `common.py`).
- Seeds: dynamic experiments and the full-coverage test use seeds 1–50. Table 1 uses the 50 seeds in
  `02_data/table1_seeds.json` (with 15 followers at R_f = R_L = 500: the first 45 seeds whose follower graph is connected
  without the leader, then the first 5 whose team graph is connected only through the leader).
- Design labels in the CSVs (`system` column) and the behaviour trees they use (XML files in `cen_wrapper/`):

| Paper | CSV label | Leader BT | Follower BT |
|---|---|---|---|
| Leader-as-proxy (adopt + iso) | `hybrid_rules` | `bt_leader_proxy.xml` | `bt_follower_proxy.xml` |
| Leader-as-relay (+ iso) | `relay_hold` | `bt_leader_relay.xml` | `bt_follower_relay.xml` |
| Leader-as-solver (grace + reset + commit + iso) | `solver_commit` | `bt_leader_solver.xml` | `bt_follower_solver.xml` (GRAPE: `bt_follower_solver_grape.xml`) |
| Dec-only | `hybrid_rules` with `leader_radius` 0 | as Leader-as-proxy | as Leader-as-proxy |

  These are the final trees, at the top level of `cen_wrapper/`. The variants of Table 2 (`hybrid`, `hybrid_iso`,
  `hybrid_adopt`, `relay`, `solver`, `solver_nograce`, `solver_noreset`, `solver_nocommit`) use the trees in
  `cen_wrapper/bt_ablation/`, named after the component they remove (e.g. `bt_follower_proxy_no_adopt.xml`;
  `_no_rules` = every rule removed). The static runs (Section 5.2, Table 1) use `cen_wrapper/bt_static/`, where robots
  halt once assigned. All are listed in `DYNAMIC_SYSTEMS`, `STATIC_SYSTEMS` and `ABLATION_LEADER_BT` of `common.py` and
  in the runners. The BT nodes
  (CentralisationWrapper, EmitProxyMessage, AdoptProxyState, KeepPlanWhenIsolated, ResetProtocolState, ...) are in
  `webots/src/autonomy_bt/plugins/cen_wrapper/bt_nodes.py`.

## Section 5.2 — Design validation

### Full-coverage equivalence (first paragraph of §5.2)

Static, every communication radius 2000 (every robot reaches every other one), seeds 1–50, three algorithms: 150
instances. Each instance is run three times, and the final allocation of Leader-as-proxy is compared with the other two:

| CSV `mode` | Design | Trees | Radii |
|---|---|---|---|
| `wrapper` | Leader-as-proxy | `bt_static/bt_leader_proxy.xml`, `bt_static/bt_follower_proxy.xml` | R_L = R_f = 2000 |
| `dec` | fully connected decentralised execution (no leader) | `bt_static/bt_follower_dec.xml` | R_f = 2000 |
| `baseline` | Leader-as-solver (SGA / Hungarian / centralised GRAPE) | `bt_static/bt_leader_solver.xml`, `bt_static/bt_follower_solver.xml` (GRAPE: `bt_static/bt_follower_dec.xml`) | R_L = R_f = 2000 |

A run ends when the allocation has not changed for 300 ticks (cap 6000 ticks).

```
python $S/run_sec52_full_coverage.py 14        # -> 02_data/sec52_full_coverage.csv (450 runs, about 7 min)
```

`04_results/sec52_full_coverage.md`: per algorithm, the instances where proxy equals Dec-only and where proxy equals the
solver (paper: 50 / 50 each); supporting: converged runs and the mean tick of the last allocation change.

### Table 1 — static boundary conflicts

Static, R_L = R_f = 500, CBBA and Hungarian, the 50 seeds of `table1_seeds.json`.

```
python $S/run_table1_static_conflicts.py proxy         # Leader-as-proxy: Neither / In / Out / Both -> table1_proxy_ablation.csv
python $S/run_table1_static_conflicts.py relay_dec     # Leader-as-relay and Dec-only               -> table1_relay_deconly.csv
python $S/run_table1_static_conflicts.py solver        # Leader-as-solver, both slots (Both)         -> table1_solver.csv
python $S/run_table1_static_conflicts.py solver_slots  # Leader-as-solver: Neither / In / Plan       -> table1_solver_slots.csv
```

The `proxy` step ends by the simulator's own static rule (allocation unchanged for 1 s of real time, after 1 s, cap
30 s); the other steps end when the allocation has not changed for 300 ticks (cap 6000).

`04_results/table1_static_conflicts.md`: Table 1 (mean final conflicts per group, seeds with a conflict in parentheses);
supporting: total conflicts per group and the Leader-as-solver conflict types.

### Table 2 — boundary chattering

Dynamic, R_f = 150, R_L = 500, seeds 1–50, eleven design/rule combinations × three algorithms.

```
python $S/run_table2_chattering.py 14          # -> 02_data/table2_chattering.csv
```

`04_results/table2_chattering.md`: Table 2 (runs with at least one chattering episode, crossings inside those episodes in
parentheses) and the completed missions quoted in its note; supporting: all eleven configurations, and completion time
and travel of the ablated configurations. A chattering episode is at least four range crossings by one follower with
consecutive gaps below ten ticks (`_run_single.py`).

## Section 5.3 — Dynamic comparison

### Figure 3 — Leader-as-proxy vs decentralised-only

Dynamic, R_f ∈ {150, 500}, R_L ∈ {0, 150, 325, 500, 750} (R_L = 0 is Dec-only), seeds 1–50.

```
python $S/run_fig3_proxy_vs_deconly.py 14      # -> 02_data/fig3_proxy_vs_deconly.csv
```

`04_results/fig3_proxy_vs_deconly.md`: the plotted values of panels (a) travel (all seeds) and (b) completion time (seeds
completed by both), as mean per-seed ratio proxy / Dec-only with the 95% error bar; supporting: the confidence
intervals, numbers of seed pairs, completed missions and chattering.

### Tables 3 and 4 — vs Leader-as-solver and Leader-as-relay; communication

Dynamic, R_f ∈ {150, 325, 500}, R_L ∈ {150, 325, 500, 750}, seeds 1–50. Leader-as-proxy at R_f 150 and 500 comes from
Figure 3's runs; this runner adds proxy at R_f 325 and all Relay and Solver runs.

```
python $S/run_fig3_proxy_vs_deconly.py 14      # if not done yet
python $S/run_table3_table4_dynamic.py 14      # -> 02_data/table3_table4_dynamic.csv
```

`04_results/table3_table4_dynamic.md`: Table 3 (mean per-seed ratios of travel, all seeds, and completion time, seeds
completed by both) and Table 4 (ratio of mean fields broadcast per tick, followers + leader); supporting: completed runs,
the differences with 95% confidence intervals, proxy / Dec-only, chattering and team utility.

## 99_archived/

`99_archived/scripts/` and `99_archived/data/` hold everything that is not used by the paper: earlier experiment
designs and their data, earlier versions of the final campaigns, trial and check runs, debugging scripts (`inspect/`),
run logs and the scripts of the supplementary pygame videos (`scripts/videos/`). They also keep the development versions
of the final runners and data under their original names (the `v2_*` files). The files in `01_scripts/` and `02_data/`
were renamed from them on 2026-10-10, without changing any run setting; Table 1's data files keep only the rows the
paper uses (the 50 seeds and the four conditions). The earlier full-coverage data (`v2_exp5a_static_full_coverage*.csv`)
used other teams (CBBA 10 / 50, Hungarian 12 / 12) and was replaced by `sec52_full_coverage.csv`. The archived scripts
refer to the old folder names, so they will not run from `99_archived/` without path changes.
