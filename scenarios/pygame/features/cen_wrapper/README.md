# Scenario: CentralisationWrapper (cen_wrapper)

## Overview

A feature-demo scenario for the **CentralisationWrapper** Behaviour Tree
decorator — a single drop-in node that lets the *same* decentralised MRTA
plugin (CBBA, GRAPE, Distributed Hungarian) run either fully decentralised
on each follower, or centrally on a Leader that broadcasts the result
back. Each algorithm is tested across three setups:

1. **Pure decentralised** — every follower runs the algorithm itself.
2. **CentralisationWrapper** — a Leader runs the same plugin once on
   behalf of all connected followers, achieves consensus, then broadcasts
   the allocation via `TeachBT` → `ApplyCenTask`.
3. **Centralised baseline** — a hand-written central algorithm
   (`SGA` for CBBA-side, `Hungarian` for the Hungarian-side, `CenGRAPE`
   for the GRAPE-side) running on the Leader as a comparison reference.

This scenario is a port of `space-simulator-cendec/scenarios/features/cenwrapper/`
into the autonomy_bt 4-layer structure (`core` / `platforms` / `plugins`
/ `scenarios`). The student's algorithm logic is preserved as-is —
only import paths are rewired, plus two structural cleanups specific to
this port:

- **cen-side plugins** (`sga`, `cen_grape`, `hungarian`) are refactored
  from BT action nodes into plain plugin classes loaded via
  `decision_making.cen_plugin`. They are now dispatched by a single
  `AssignCenTask` BT node — exact mirror of how `AssignTask` dispatches
  the dec-side plugin via `decision_making.plugin`. This collapses the
  three former `bt_leader_{sga,cengrape,hungarian}.xml` files into one
  `bt_leader.xml`.
- A few wrapper-internal behaviours (per-agent `decision_maker`, message
  accumulation in `GatherLocalInfo`) are kept local to this scenario to
  avoid touching shared modules.

## How to Run

```bash
cd autonomy_bt

# ── Static mode ───────────────────────────────────────────────────
# CBBA (10 agents, 50 tasks, max_tasks_per_agent = 5)
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/cbba.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/cenwrapper_cbba.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/sga.yaml

# GRAPE (12 agents, 48 tasks)
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/grape/grape.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/grape/cenwrapper_grape.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/grape/cen_grape.yaml

# Hungarian (12 agents, 12 tasks)
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/hungarian/dec_hungarian.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/hungarian/cenwrapper_hungarian.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/hungarian/hungarian.yaml

# ── Dynamic mode ──────────────────────────────────────────────────
# Same nine yamls under configs/dynamic/{cbba,grape,hungarian}/
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/dynamic/cbba/cenwrapper_cbba.yaml
```

## Configuration

| Algorithm | Pure-dec yaml | CentralisationWrapper yaml | Centralised baseline yaml |
|-----------|---------------|----------------------------|---------------------------|
| CBBA      | `cbba.yaml` (Leader q=0)   | `cenwrapper_cbba.yaml`     | `sga.yaml`        |
| GRAPE     | `grape.yaml` (Leader q=0)  | `cenwrapper_grape.yaml`    | `cen_grape.yaml`  |
| Hungarian | `dec_hungarian.yaml` (q=0) | `cenwrapper_hungarian.yaml`| `hungarian.yaml`  |

Each yaml lives under `configs/<mode>/<algorithm>/` where `<mode>` is
`static` or `dynamic`. The static folder is the equivalence-test setup
(simulation terminates once allocations are stable for `STABILITY_SEC`
real-time seconds, or after `TIMEOUT_SEC = 2.5`s — see
`sim/sim.py::update_simulation`); the dynamic folder leaves the
simulation running for visual demo / dynamic-task-generation experiments.

Key shared parameters:
- **CBBA setup** (`CBBA_N10_M50_MT5`): 10 followers, 50 tasks,
  `max_tasks_per_agent = 5`, `task_reward_discount_factor = 0.999`.
- **GRAPE setup** (`GRAPE_N12_M48`): 12 followers, 48 tasks. Note
  `cen_grape.yaml` uses a different `GRAPE_N40_M10` setup because that
  baseline is a separate ablation, not a 1:1 comparison.
- **Hungarian setup** (`HUNGARIAN_N12_M12`): 12 followers, 12 tasks
  (square assignment). 
- **Communication**: per-type `communication_radius` —
  `Leader = 2000` (effectively global), `Follower = 2000` (fully connected).
- **Random seed**: `1` (fixed for reproducibility across the three setups).

## Behaviour Trees

The scenario uses **4 BT XMLs** total — two follower variants (dynamic /
static) and two leader variants (centralised baseline / wrapper):

### Follower BT — static mode (`bt_follower_static.xml`)

```
Parallel
├── GatherLocalInfo
├── ReactiveFallback
│   ├── ReactiveSequence            ← Leader-driven branch
│   │   ├── IsConnectedWithLeader
│   │   └── ApplyCenTask            ← Apply Leader's broadcast result
│   └── AssignTask                  ← Fallback: run dec plugin locally
└── Sequence
    ├── IsTaskAssigned
    └── Halt                        ← Stay still in static mode
```

The dynamic-mode variant (`bt_follower.xml`) replaces the bottom Halt
sequence with a `MoveToTarget` / `IsArrivedAtTarget` / `ExecuteTask`
chain.

### Leader BT — CentralisationWrapper variant (`bt_leader_wrapper.xml`)

```
Parallel
├── GatherLocalInfo
├── CentralisationWrapper           ← Decorator: simulates child for
│   └── AssignTask                  ←   each connected follower in turn
└── TeachBT                         ← Broadcast aggregated allocation
```

`AssignTask` loads the *dec* plugin (`decision_making.plugin`) — CBBA
/ GRAPE / DistributedHungarian.

### Leader BT — centralised baseline (`bt_leader.xml`)

```
Parallel
├── GatherLocalInfo
├── AssignCenTask                   ← Loads cen plugin from yaml
└── TeachBT                         ← Broadcast aggregated allocation
```

`AssignCenTask` loads the *cen* plugin (`decision_making.cen_plugin`)
— `SGA` / `CenGRAPE` / `Hungarian`. Same node, different yaml selects
the algorithm, mirroring how `AssignTask` ↔ `decision_making.plugin`
works on the dec side.

### `AssignCenTask` ↔ `ApplyCenTask` 짝맞춤

| 노드 | 역할 |
|---|---|
| `AssignCenTask` | **Leader** — runs centralised algorithm, writes `task_allocations` to blackboard |
| `TeachBT`       | **Leader** — broadcasts the allocation to followers |
| `ApplyCenTask`  | **Follower** — receives broadcast, sets own `assigned_task_id` |

## Static-Mode Equivalence (current state)

The static configs are designed to verify the paper's Proposition 1
("Allocation Equivalence" — pure-dec, wrapper, and centralised baseline
should produce the same allocation). Current observation, identical
between the original cendec repo and this port:

| Algorithm | dec ↔ wrapper ↔ baseline |
|-----------|---------------------------|
| Hungarian | **3-way identical** ✓     |
| CBBA      | **3-way identical** ✓ (with `Follower.communication_radius = 2000`, i.e. fully connected) |
| GRAPE     | pure-dec ↔ cen_grape (centralised) identical; wrapper diverges on agents 0 ↔ 2 (swap)  |

CBBA 가 fully connected (radius=2000) 일 때만 3-way 일치하는 건 학생
yaml 의 `Follower.communication_radius=150` 셋팅이 fully connected 가정을
깨고 있었기 때문이에요 (이를 통일해서 정렬). GRAPE 의 wrapper 만 0↔2
swap 으로 갈라지는 건 알고리즘의 sequential simulation 특성으로 보임 —
별도 조사 항목.

The numerical outputs of this port match cendec's outputs **byte-for-byte
on all 9 yamls** (validated via `_static_smoke.py`).

## Files

```
scenarios/pygame/features/cen_wrapper/
├── README.md                           # this file
├── bt_nodes.py                         # cen_wrapper-specific actions + conditions + CentralisationWrapper decorator
├── bt_follower.xml                     # follower BT — dynamic mode
├── bt_follower_static.xml              # follower BT — static mode
├── bt_leader.xml                       # Leader BT — centralised baseline (loads cen_plugin)
├── bt_leader_wrapper.xml               # Leader BT — CentralisationWrapper (loads dec plugin via AssignTask)
├── configs/
│   ├── static/{cbba,grape,hungarian}/   # 9 yamls — equivalence tests
│   └── dynamic/{cbba,grape,hungarian}/  # 9 yamls — runtime / visual demo
├── plugins/
│   ├── cbba.py                         # dec CBBA  — used by AssignTask via `decision_making.plugin`
│   ├── grape.py                        # dec GRAPE
│   ├── dec_hungarian.py                # dec Distributed Hungarian
│   ├── sga.py                          # cen Sequential Greedy — used by AssignCenTask via `decision_making.cen_plugin`
│   ├── cen_grape.py                    # cen GRAPE
│   └── hungarian.py                    # cen Hungarian
└── sim/
    ├── sim.py                          # Sim(BaseSim) — leader toggle, static-mode termination, custom CSV saver
    ├── agent.py                        # Agent + generate_agents (per-type BT XML pattern)
    └── task.py                         # Task + generate_tasks (+1000 task-seed offset, matching cendec)
```

## Yaml keys (cen_wrapper-specific)

| key | description |
|---|---|
| `decision_making.plugin` | Dotted path to the **dec** plugin class — one of `scenarios.pygame.features.cen_wrapper.plugins.{cbba.CBBA, grape.GRAPE, dec_hungarian.DistributedHungarian}`. Loaded by `AssignTask` (used inside `CentralisationWrapper` on the leader, and as the follower-side fallback when not connected to leader). |
| `decision_making.cen_plugin` | Dotted path to the **cen** plugin class — one of `scenarios.pygame.features.cen_wrapper.plugins.{sga.SGA, cen_grape.CenGRAPE, hungarian.Hungarian}`. Loaded by `AssignCenTask` (only used by `bt_leader.xml`, i.e. centralised-baseline yamls — `sga.yaml`, `cen_grape.yaml`, `hungarian.yaml`). |
| `decision_making.CBBA` / `GRAPE` / `Hungarian` | Per-algorithm parameter sub-block (e.g. `task_reward_discount_factor`, `social_inhibition_factor`, ...). Read by the corresponding plugin at module-load time. |
| `agents.types.Leader.quantity` | Set to 0 for pure-dec yamls, 1 for wrapper / centralised-baseline yamls. |
| `agents.types.{Leader,Follower}.behavior_tree_xml` | Per-type BT XML. Followers use `bt_follower_static.xml` (static mode) or `bt_follower.xml` (dynamic mode); Leaders use `bt_leader.xml` (centralised baseline — uses `cen_plugin`) or `bt_leader_wrapper.xml` (CentralisationWrapper — uses `plugin`). |
| `agents.types.{Leader,Follower}.communication_radius` | Per-type radius. There is **no** global `agents.communication_radius` — `BaseAgent` falls back to `0` (global) at module load. |
| `simulation.mode` | `static` triggers the wall-clock stability check in `sim/sim.py`; `dynamic` lets the run continue indefinitely. |
| `case_name` / `setup` | Used by the custom `ResultSaver` to name CSVs as `{case_name}_seed{seed}_{type}.csv` and to subdir the static-mode allocation snapshots under `output/assignments/{setup}/`. |

## Test Verification

- The pygame window opens with followers (triangles), tasks (circles),
  and — when `Leader.quantity > 0` — a single Leader agent surrounded
  by its `leader_communication_radius_circle`.
- In static mode the simulation runs ~2–6 seconds of wall clock,
  prints `Assignments stable for ...s` (or a timeout message), saves
  the allocation snapshot under `output/assignments/{setup}/`, and
  exits.
- Pressing `L` during a wrapper / baseline run despawns the Leader and
  forces the followers to fall back to the local `AssignTask` branch.
  Pressing `L` again respawns the Leader.
- All 9 static yamls produce assignments that match cendec
  byte-for-byte (verified by `_static_smoke.py`).
