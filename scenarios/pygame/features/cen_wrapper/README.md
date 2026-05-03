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
/ `scenarios`). Three structural cleanups vs. the cendec original:

- **dec-side plugins** (`cbba`, `grape`, `dec_hungarian`) reuse the
  shared `plugins/mrta/*` implementations — no cen_wrapper-local copies
  any more. CBBA and Distributed Hungarian use the shared classes
  directly. GRAPE uses a local `plugins/grape.py` (a thin subclass of
  the shared GRAPE that overrides `_initial_time_stamp` /
  `_new_time_stamp` to return `agent_id`) — this makes the d-mutex
  tiebreak deterministic, which is required for the 3-way equivalence
  experiment to converge to the same nash equilibrium across all three
  modes.
- **cen-side plugins** (`sga`, `cen_grape`, `hungarian`) are refactored
  from BT action nodes into plain plugin classes loaded via
  `decision_making.cen_plugin`. They are dispatched by a single
  `AssignCenTask` BT node — exact mirror of how `AssignTask` dispatches
  the dec-side plugin via `decision_making.plugin`. This collapses the
  three former `bt_leader_{sga,cengrape,hungarian}.xml` files into one
  `bt_leader.xml`.
- A few wrapper-internal behaviours (per-agent `decision_maker`,
  syncing target follower's `messages_received` from the leader's
  blackboard view inside `CentralisationWrapper`) are kept local to
  this scenario.

## How to Run

```bash
cd autonomy_bt

# ── Static mode ───────────────────────────────────────────────────
# CBBA (10 agents, 50 tasks, max_tasks_per_agent = 5)
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/cbba.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/cenwrapper_cbba.yaml
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/static/cbba/sga.yaml

# GRAPE (40 agents, 10 tasks)
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
real-time seconds, or after `TIMEOUT_SEC = 5`s — see
`sim/sim.py::_check_static_termination`); the dynamic folder leaves the
simulation running for visual demo / dynamic-task-generation experiments.

Key shared parameters:
- **CBBA setup** (`CBBA_N10_M50_MT5`): 10 followers, 50 tasks,
  `max_tasks_per_agent = 5`, `task_reward_discount_factor = 0.999`.
- **GRAPE setup** (`GRAPE_N40_M10`): 40 followers, 10 tasks (all three
  GRAPE yamls share the same setup for 3-way equivalence comparison).
- **Hungarian setup** (`HUNGARIAN_N12_M12`): 12 followers, 12 tasks
  (square assignment).
- **Communication**: per-type `communication_radius` —
  `Leader = 2000` (effectively global), `Follower = 2000` (fully connected).
- **Random seed**: `1` (fixed for reproducibility across the three setups).
- **`simulation.message_snapshot: true`**: enables BTRunner's tick-start
  peer-message snapshot so the sequential agent loop simulates parallel
  execution. Required for the 3-way equivalence experiment (the
  CentralisationWrapper's per-target dec-plugin invocation needs all
  followers to see the same peer view in a tick).

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

The static configs verify the paper's Proposition 1 ("Allocation
Equivalence" — pure-dec, wrapper, and centralised baseline should
produce the same allocation). Verified across 4 random seeds via
`_static_smoke.py`:

| Algorithm | dec ↔ wrapper ↔ baseline |
|-----------|---------------------------|
| **CBBA**      | **3-way identical** ✓ |
| **Hungarian** | **3-way identical** ✓ |
| **GRAPE**     | **3-way identical** ✓ (with deterministic `time_stamp = agent_id`) |

GRAPE 3-way equivalence requires two ingredients:
1. **`simulation.message_snapshot: true`** — without it, the sequential
   `BTRunner` agent loop creates within-tick cascade where agent N+1
   reads agent N's just-updated message, breaking parallel-execution
   semantics. The wrapper / cen_grape modes don't suffer from this
   (they iterate in their own controlled loop), but pure-dec does.
2. **Deterministic d-mutex** via `plugins/grape.py` (the local subclass)
   — the shared GRAPE samples `time_stamp ~ U(0,1)` on each switch,
   making the d-mutex tiebreak random. Under fully-connected
   communication, all agents converge on `evolution_number` together,
   so `time_stamp` decides who wins; with random tie-breaks each mode
   reaches a different nash equilibrium. Setting `time_stamp = agent_id`
   makes the highest-id agent always win, matching `cen_grape.CenGRAPE`'s
   priority order.

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
├── plugins/                            # cen-side plugins + GRAPE local subclass
│   ├── grape.py                        # dec GRAPE subclass — overrides time_stamp hooks for deterministic d-mutex (3-way equivalence)
│   ├── sga.py                          # cen Sequential Greedy — used by AssignCenTask via `decision_making.cen_plugin`
│   ├── cen_grape.py                    # cen GRAPE
│   └── hungarian.py                    # cen Hungarian
├── sim/
│   ├── sim.py                          # Sim(BaseSim) — leader toggle, static-mode termination, custom CSV saver
│   ├── agent.py                        # Agent + generate_agents (per-type BT XML pattern)
│   └── task.py                         # Task + generate_tasks (+1000 task-seed offset, matching cendec)
└── test/
    └── static_smoke.py                 # 3-way equivalence smoke test (CBBA / GRAPE / Hungarian × 3 modes × N seeds)
```

## Yaml keys (cen_wrapper-specific)

| key | description |
|---|---|
| `decision_making.plugin` | Dotted path to the **dec** plugin class. CBBA / Hungarian use the shared `plugins.mrta.{cbba.cbba.CBBA, hungarian.dec_hungarian.DistributedHungarian}`. GRAPE uses the local `scenarios.pygame.features.cen_wrapper.plugins.grape.GRAPE` (deterministic time_stamp subclass for 3-way equivalence). Loaded by `AssignTask` (used inside `CentralisationWrapper` on the leader, and as the follower-side fallback when not connected to leader). |
| `decision_making.cen_plugin` | Dotted path to the **cen** plugin class — one of `scenarios.pygame.features.cen_wrapper.plugins.{sga.SGA, cen_grape.CenGRAPE, hungarian.Hungarian}`. Loaded by `AssignCenTask` (only used by `bt_leader.xml`, i.e. centralised-baseline yamls — `sga.yaml`, `cen_grape.yaml`, `hungarian.yaml`). |
| `decision_making.CBBA` / `GRAPE` / `Hungarian` | Per-algorithm parameter sub-block (e.g. `task_reward_discount_factor`, `social_inhibition_factor`, ...). Read by the corresponding plugin at module-load time. |
| `agents.types.Leader.quantity` | Set to 0 for pure-dec yamls, 1 for wrapper / centralised-baseline yamls. |
| `agents.types.{Leader,Follower}.behavior_tree_xml` | Per-type BT XML. Followers use `bt_follower_static.xml` (static mode) or `bt_follower.xml` (dynamic mode); Leaders use `bt_leader.xml` (centralised baseline — uses `cen_plugin`) or `bt_leader_wrapper.xml` (CentralisationWrapper — uses `plugin`). |
| `agents.types.{Leader,Follower}.communication_radius` | Per-type radius. There is **no** global `agents.communication_radius` — `BaseAgent` falls back to `0` (global) at module load. |
| `simulation.mode` | `static` triggers the wall-clock stability check in `sim/sim.py`; `dynamic` lets the run continue indefinitely. |
| `simulation.message_snapshot` | `true` enables BTRunner's tick-start peer-message snapshot (parallel-execution emulation). Required for 3-way equivalence; default is `false` (cascade is faster for high-contention scenarios elsewhere, e.g. `simple/grape.yaml`). |
| `case_name` / `setup` | Used by the custom `ResultSaver` to name CSVs as `{case_name}_seed{seed}_{type}.csv` and to subdir the static-mode allocation snapshots under `output/assignments/{setup}/`. |

## Test Verification

- The pygame window opens with followers (triangles), tasks (circles),
  and — when `Leader.quantity > 0` — a single Leader agent surrounded
  by its `leader_communication_radius_circle`.
- In static mode the simulation runs ~2–6 seconds of wall clock,
  prints `Assignments stable for ...s` (or a timeout message at 5s),
  saves the allocation snapshot under `output/assignments/{setup}/`,
  and exits.
- Pressing `L` during a wrapper / baseline run despawns the Leader and
  forces the followers to fall back to the local `AssignTask` branch.
  Pressing `L` again respawns the Leader.
- All 9 static yamls produce 3-way matching assignments across 4
  random seeds, verified by the smoke test below.

## Smoke test

3-way equivalence smoke test (CBBA / GRAPE / Hungarian × 3 modes per
algorithm × N seeds):

```bash
# Default — 1 seed (random_seed=1)
python scenarios/pygame/features/cen_wrapper/test/static_smoke.py

# Rigorous — 4 seeds (1, 2, 3, 4)
python scenarios/pygame/features/cen_wrapper/test/static_smoke.py --seeds=4
```

Output: per-algorithm SUMMARY with `[OK ALL SEEDS MATCH]` (3-way
identical across all seeds) or `[X]` (mismatch — divergent rows
shown).
