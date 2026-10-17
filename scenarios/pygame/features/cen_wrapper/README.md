# Scenario: hybrid centralised/decentralised MRTA (cen_wrapper)

Experiments for a leader whose communication range covers only part of the team. The team runs
one decentralised MRTA plugin (CBBA with full bundle reset / GRAPE / Distributed Hungarian), and the
leader is used in one of three ways:

1. **Leader-as-proxy** (the proposed method) — the leader runs `CentralisationWrapper(AssignTask)`:
   the decentralised plugin is executed once per in-range follower, on a proxy of that follower, and
   the result is broadcast via `TeachBT`. Connected followers apply it (`ApplyCenTask`), broadcast
   their proxy's protocol message when they are at the boundary (`EmitProxyMessage`) and relay what
   disconnected followers say (`RelayMessages scope="outside"`); disconnected followers run the
   plugin themselves.
2. **Leader-as-relay** — the leader only forwards follower messages (`RelayMessages scope="all"
   nested="1"`); every follower runs the plugin.
3. **Leader-as-solver** — the leader runs a dedicated centralised solver (`AssignCenTask`: `SGA` /
   `CenGRAPE` / `Hungarian`) and its plan has priority.

With no leader in range (or leader radius 0) all three reduce to the plain decentralised algorithm
(**Dec-only**). All nodes live in `plugins/cen_wrapper/bt_nodes.py`.

## How to Run

The experiments of the paper (runners, data, analysis and how to reproduce every table and figure) are in
`experiments/`; see `experiments/README.md`. Each yaml under `configs/` can also be run on its own:

| | static | dynamic/global | dynamic/partial |
|---|---|---|---|
| Movement | Halt (no motion) | Move + execute task | Move + execute task |
| Leader / Follower radius | 2000 / 2000 | 2000 / 2000 | **1000** / 2000 (experiments override both) |
| Purpose | Allocation snapshot | Full coverage with motion + global convergence gate | Hybrid: leader covers part of the map |

Per-mode 9-yaml grid (3 algorithms × 3 modes — same filenames in each folder):

| Algorithm | Dec-only | Leader-as-proxy | Leader-as-solver |
|---|---|---|---|
| CBBA      | `cbba.yaml`          | `cenwrapper_cbba.yaml`      | `sga.yaml`        |
| GRAPE     | `grape.yaml`         | `cenwrapper_grape.yaml`     | `cen_grape.yaml`  |
| Hungarian | `dec_hungarian.yaml` | `cenwrapper_hungarian.yaml` | `hungarian.yaml`  |

```bash
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/<MODE>/<ALGO>/<YAML>
# e.g.
python3 main.py --config scenarios/pygame/features/cen_wrapper/configs/dynamic/partial/grape/cenwrapper_grape.yaml
```

Interactive keys during a run: `L` toggles the leader (despawn / respawn);
`Space` / `P` pauses; `Esc` / `Q` quits.

## BT Structure

The final trees of the three designs are in this folder; variants are in subfolders. A variant's name gives the
component it removes (`_no_<component>`; `_no_rules` = every rule removed).

| File | Role |
|---|---|
| `bt_leader_proxy.xml` | Leader-as-proxy leader — `CentralisationWrapper(AssignTask)` (merged message export) + `TeachBT` |
| `bt_follower_proxy.xml` | Leader-as-proxy follower — `ApplyCenTask`, `EmitProxyMessage`, `RelayMessages scope="outside"`; rules adopt (`AdoptProxyState`) + iso (`KeepPlanWhenIsolated`) |
| `bt_leader_relay.xml` | Leader-as-relay leader — `RelayMessages scope="all" nested="1"` |
| `bt_follower_relay.xml` | Leader-as-relay follower — `UnpackRelayedMessages` + `AssignTask`; rule iso |
| `bt_leader_solver.xml` | Leader-as-solver leader — `AssignCenTask` (`SGA` / `CenGRAPE` / `Hungarian`, rule grace: `keep_departed`) + `TeachBT` |
| `bt_follower_solver.xml` | Leader-as-solver follower, CBBA / Hungarian — plan forwarding, filtering of plan-claimed tasks, relay; rules reset (`ResetProtocolState`), commit (`CommitToPlan`), iso |
| `bt_follower_solver_grape.xml` | Leader-as-solver follower, GRAPE — as above without plan forwarding, filtering and relay (coalitions may share tasks) |
| `bt_ablation/` | dynamic variants with rules removed (Table 2): `bt_follower_proxy_no_{rules,adopt,iso}`, `bt_follower_relay_no_rules`, `bt_leader_solver_no_grace`, `bt_follower_solver[_grape]_no_{rules,reset,commit}` |
| `bt_static/` | static trees (robots halt once assigned; Section 5.2, Table 1): `bt_leader_proxy` (without merged export) and `_no_inbound`, `_no_outbound`, `_no_inbound_no_outbound`; `bt_follower_proxy`; `bt_follower_relay`; `bt_leader_solver` (without grace); `bt_follower_solver` and `_no_relay`, `_no_plan`, `_no_relay_no_plan`; `bt_follower_dec` (plain decentralised follower) |
| `bt_archived/` | earlier designs and variants not used by the experiments (designated relaying, full-mesh relay, plan forwarding only, ...), and the full-coverage followers that are the defaults of `configs/dynamic/global/` |

Every leader BT that produces a plan finishes with `TeachBT`, which broadcasts `central_plan`
on the leader's outbox for the followers' `ApplyCenTask` to consume.
