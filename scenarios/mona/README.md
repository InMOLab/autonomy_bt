# MONA-aware scenarios

This directory hosts scenarios that integrate with **MONA** (ESP32-based
mobile robot) hardware via UDP G/STOP commands, ESP-NOW P2P relay, and
WhyCode overhead-camera localisation.

A MONA-aware scenario is **a subset of pygame scenarios** that opt into
the MONA platform: it inherits `MonaSim` and `MonaAgent` (instead of
`BaseSim` / `BaseAgent`), and supports four operation modes
(`full_simulation` / `puppet` / `p2p` / `offboard`) selected by yaml's
`mona.mode` key.

## Available scenarios

| Path | Description |
|------|-------------|
| [`basic/`](basic/) | Default 4-agent / 100-task CBBA demo at the four corners of the arena. The minimal MONA scenario; serves as a regression check and a starting template for new MONA adaptations. |

(Future MONA-adapted scenarios — e.g. `collaborative_transport`,
`harbor_logistics` — go in here as siblings of `basic/`.)

## Running

```sh
python main.py --config scenarios/mona/<scenario>/configs/<mode>.yaml
```

For end-to-end setup (camera calibration, marker generation, firmware
flashing, ROS 2 bridge), see the README inside each scenario folder
(e.g. [`basic/README.md`](basic/README.md)).

---

## Adding a new MONA-aware scenario

To MONA-ify an existing pygame scenario at `scenarios/pygame/<name>/`:

```
scenarios/mona/<name>/
├── default_bt.xml                  # copy from scenarios/pygame/<name>/
├── bt_nodes.py                     # re-export + MONA-specific nodes
├── sim/
│   ├── sim.py                      # class Sim(MonaSim): pass
│   ├── agent.py                    # Agent(MonaAgent) — task_colors injection
│   └── task.py                     # re-export from scenarios/pygame/<name>/
├── configs/
│   ├── full_simulation.yaml        # mona.mode: full_simulation
│   ├── puppet.yaml                 # mona.mode: puppet, robots: ...
│   ├── p2p.yaml                    # mona.mode: p2p, robots: ...
│   └── offboard.yaml               # mona.mode: offboard, robots: ...
├── Arduino/                        # firmware (puppet / p2p / offboard)
└── README.md
```

**Minimal code**:

```python
# sim/sim.py
from platforms.mona.mona_sim import MonaSim
class Sim(MonaSim): pass
```

```python
# sim/agent.py
from platforms.mona.mona_agent import MonaAgent
from scenarios.mona.<name>.sim.task import task_colors

class Agent(MonaAgent):
    def __init__(self, agent_id, position, tasks_info, rotation=0):
        super().__init__(agent_id, position, tasks_info, rotation,
                         task_colors=task_colors)
```

```python
# sim/task.py — re-export pygame version if Task definition is unchanged
from scenarios.pygame.<name>.sim.task import *  # noqa: F401,F403
```

```python
# bt_nodes.py — re-export pygame nodes + MONA-specific nodes
from scenarios.pygame.<name>.bt_nodes import *  # noqa: F401,F403
from platforms.mona.bt_nodes_mona import *      # noqa: F401,F403
```

```yaml
# configs/<mode>.yaml — base on scenarios/pygame/<name>/configs/<X>.yaml,
# then add the mona block and switch scenario.environment:
platform: pygame
scenario:
  environment: scenarios.mona.<name>      # not scenarios.pygame.<name>
mona:
  mode: <full_simulation | puppet | p2p | offboard>
  robots: [...]                            # for puppet / p2p / offboard
agents:
  body_radius: 40                          # WhyCode-calibrated
  max_speed: 0.85                          # MONA-calibrated
  max_accel: 0.05
  max_angular_speed: 0.025
  ...                                      # rest unchanged
```

**Convention**: dynamics (`max_speed` / `max_accel` / `max_angular_speed`)
should be the real-MONA calibrated values across all four modes so the
modes are directly comparable. Real-robot motion ignores them anyway —
ESP32 firmware decides motor PWM and gains itself; the host only sends
`(angle_deg, distance_mm)` G commands.

`MonaSim` resolves the scenario's Task / Agent classes from
`config['scenario']['environment']` automatically — no changes needed in
`platforms/mona/` to add a new scenario.

---

## Supporting modules

The MONA platform glue lives under `platforms/mona/`:

| File | Role |
|------|------|
| `mona_sim.py` | `MonaSim(BaseSim)` — wall-clock display, MonaComm wiring, WhyCon UDP listener, real-robot keyboard handler. Reads `mona.mode` from yaml and exposes `(motion_enabled, comm_enabled, whycon_enabled, body_radius)` flags. |
| `mona_agent.py` | `MonaAgent(BaseAgent)` — rotation-shim controller + optional UDP motion + optional TCP↔ESP32 P2P bridge. `body_radius` and motion enablement derive from `mona.mode` automatically. |
| `mona_client.py` | UDP client. Sends `G <angle_deg> <distance_mm>\n` and `STOP\n`. |
| `mona_comm.py` | TCP+JSON connection manager. Sends compressed CBBA broadcasts to ESP32 and reads back peer messages. |
| `bt_nodes_mona.py` | BT nodes shared across all MONA scenarios: `MoveToTarget`, `ExecuteTask`, `Explore`, `Idle`, `IsTaskCompleted`, `IsArrivedAtTarget`. |
| `ros2_bridge/marker_to_simulator.py` | Standalone ROS 2 node bridging WhyCode markers → simulator UDP. Run as `python -m platforms.mona.ros2_bridge.marker_to_simulator`. |
