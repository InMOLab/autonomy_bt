# Scenario: CentralisationWrapper (cen_wrapper)

Demo for the **`CentralisationWrapper`** BT decorator — a single drop-in
node that turns a decentralised MRTA plugin (CBBA / GRAPE / Distributed
Hungarian) into a centralised one. Each algorithm is run in three modes
and the resulting allocations are compared:

1. **dec** — every follower runs the dec plugin itself.
2. **wrapper** — leader runs `CentralisationWrapper(AssignTask)` once,
   broadcasts the result via `TeachBT` → followers' `ApplyCenTask` consume.
3. **baseline** — leader runs a centralised plugin (`SGA` / `CenGRAPE` /
   `Hungarian`) for comparison.

## How to Run

Three movement / connectivity profiles under `configs/`:

| | static | dynamic/global | dynamic/partial |
|---|---|---|---|
| Movement | Halt (no motion) | Move + execute task | Move + execute task |
| Leader / Follower radius | 2000 / 2000 | 2000 / 2000 | **1000** / 2000 |
| Follower BT | `bt_follower_static.xml` | `bt_follower_global.xml` | `bt_follower.xml` |
| Purpose | Equivalence test | Equivalence with motion + global convergence gate | Hybrid: leader covers part of the map, dec runs outside |
| Termination | Auto-exit on stable allocation | `max_simulation_time` | Same |

Per-mode 9-yaml grid (3 algorithms × 3 modes — same filenames in each folder):

| Algorithm | dec | wrapper | baseline |
|---|---|---|---|
| CBBA      | `cbba.yaml`          | `cenwrapper_cbba.yaml`      | `sga.yaml`        |
| GRAPE     | `grape.yaml`         | `cenwrapper_grape.yaml`     | `cen_grape.yaml`  |
| Hungarian | `dec_hungarian.yaml` | `cenwrapper_hungarian.yaml` | `hungarian.yaml`  |

Run a single yaml:
```bash
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/<MODE>/<ALGO>/<YAML>
# e.g.
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/dynamic/global/grape/cenwrapper_grape.yaml
```

Run the automated 9-yaml equivalence check (Exp 1, static mode):
```bash
python3 scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py             # 1 seed (default)
python3 scenarios/pygame/features/cen_wrapper/experiments/scripts/exp1_static_equivalence.py --seeds=4   # rigorous (4 seeds)
```

Interactive keys during a run: `L` toggles the leader (despawn / respawn);
`Space` / `P` pauses; `Esc` / `Q` quits.

## BT Structure

| File | Role |
|---|---|
| `bt_leader.xml`          | leader, baseline mode — `AssignCenTask` loads `cen_plugin` (`SGA` / `CenGRAPE` / `Hungarian`) |
| `bt_leader_wrapper.xml`  | leader, wrapper mode — `CentralisationWrapper(AssignTask)` simulates the dec plugin per follower |
| `bt_follower_static.xml` | follower, static mode — Halt once assigned (Exp 3 baseline: Relay OFF, Forward OFF) |
| `bt_follower_static_relay_only.xml`   | static, Exp 3 ablation — Relay ON, Forward OFF |
| `bt_follower_static_forward_only.xml` | static, Exp 3 ablation — Relay OFF, Forward ON |
| `bt_follower_static_relay.xml`        | static, Exp 3 full — Relay ON, Forward ON (paper proposal) |
| `bt_follower.xml`        | follower, `dynamic/partial` — local `IsTaskAssigned` gate then movement |
| `bt_follower_global.xml` | follower, `dynamic/global` — `IsAllocationConverged` global gate before motion (fair cross-mode comparison) |

Both leader BTs finish with `TeachBT`, which broadcasts `central_plan`
on the leader's outbox for followers' `ApplyCenTask` to consume.




