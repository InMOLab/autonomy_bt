# MONA · letter_show

Demo scenario: 9 MONA robots draw the letters of
`R O B O T I C S  A N D  A U T O M A T I O N`, one letter at a time,
using 9 task pixels per letter. Each letter is completed → short
wall-clock dwell → next letter is generated in-place. Two operation
modes share the **same algorithm setup, BT XML, agent dynamics, and
letter sequence** — only the external systems wired in differ.

The scenario layers two extras on top of `mona/basic`:
- a **2-phase BT** (GRAPE picks a sub-cluster of pixels, then CBBA or
  Hungarian picks one pixel inside it), and
- per-agent **battery** (drains with distance moved; high-battery
  agents are preferred for tasks).

---

## Mode comparison

| Mode | Task allocation | Motion (UDP G/STOP) | Localisation |
|------|---|---|---|
| `full_simulation` | autonomy_bt | sim | sim |
| `puppet` | autonomy_bt | **MONA** | **WhyCon** |

`p2p` and `offboard` are not implemented for letter_show in this
release; they can be added the same way as `mona/basic` if needed.

---

## Algorithm flow (Behaviour Tree, 2-phase)

```
ReactiveSequence
├── GatherLocalInfo         # CBBA + GRAPE channels + super_tasks_info
├── AssignSuperTask         # Phase 1 — GRAPE: which sub-cluster of the letter
├── RebalanceGroups         # Post Phase 1 — surplus → deficit (one-shot latch)
├── AssignTask              # Phase 2 — yaml-driven (CBBA or Hungarian)
└── ReactiveFallback
    ├── IsArrivedAtTarget
    └── MoveToTarget
```

Phase 1 GRAPE latches on the blackboard once **every** agent has held
a stable assigned super-task for `super_task_dwell_seconds` (default
1.0 s). Subsequent ticks short-circuit Phase 1.

---

## Scenario-specific entities

| Name | Role |
|---|---|
| `SuperTask` (`sim/super_task.py`) | A "group" of pixel-tasks belonging to one letter (or a sub-region of one). Drawn as a semi-transparent rectangle overlay. Treated as a task by GRAPE (`task_id` / `position` / `amount` exposed as aliases). |
| `battery` (Agent attribute) | 0–100 %, drains with distance (3 % per 1000 px). Feeds GRAPE's `battery_ratio × urgency_factor` term so high-battery agents are preferred. Also used by `RebalanceGroups` when moving an agent from a surplus to a deficit super-task. |

---

## Scenario-local plugin subclasses

To keep letter_show's tweaks isolated from the global plugins:

```
scenarios/mona/letter_show/plugins/
├── grape.py            # GRAPE subclass — reset() + battery-aware compute_utility
├── cbba.py             # CBBA subclass — skip None time_stamp (channel-swap artefact)
└── dec_hungarian.py    # Distributed Hungarian subclass — super-task scoping + defensive guards
```

`bt_nodes.py`'s `AssignSuperTask` imports the local GRAPE directly.
`AssignTask` (Phase 2) loads `decision_making.plugin` from yaml at
import time, so the local subclass and the global plugin can be
toggled freely.

---

## Files

```
scenarios/mona/letter_show/
├── default_bt.xml              # shared BT (identical across modes)
├── bt_nodes.py                 # AssignSuperTask, RebalanceGroups, AssignTask, GatherLocalInfo
├── configs/
│   ├── full_simulation.yaml
│   └── puppet.yaml
├── sim/
│   ├── sim.py                  # Sim(MonaSim) — super-tasks, replace-on-arrive, battery records
│   ├── agent.py                # Agent(MonaAgent) — battery state + super-task colouring
│   ├── task.py                 # Task — fixed_amounts + per-super-task draw shape
│   └── super_task.py           # SuperTask entity (visual cluster + GRAPE aliases)
├── plugins/
│   ├── grape.py
│   ├── cbba.py
│   └── dec_hungarian.py
├── Arduino/
│   └── SPACE_MONA_puppet.ino
└── README.md                   # this file
```

Supporting modules under `platforms/mona/` are shared with `mona/basic`
— see [`mona/basic/README.md`](../basic/README.md) for the full table.

---

## Installation

Identical to `mona/basic`. Follow Sections 1 (autonomy_bt), 2 (WhyCode,
puppet only), and 3 (MONA firmware, puppet only) of
[`mona/basic/README.md`](../basic/README.md#installation). Use
`scenarios/mona/letter_show/Arduino/SPACE_MONA_puppet.ino` as the
firmware for puppet mode.

---

## How to Execute

```sh
python main.py --config scenarios/mona/letter_show/configs/full_simulation.yaml
# or
python main.py --config scenarios/mona/letter_show/configs/puppet.yaml
```

`puppet` mode follows the same Startup order (Steps 1–5) as
[`mona/basic`](../basic/README.md#startup-order): camera node →
WhyCode node → marker bridge → autonomy_bt.

---

## yaml keys (letter_show-specific)

| key | description |
|---|---|
| `mona.mode` | `full_simulation` or `puppet`. |
| `decision_making.plugin` | Phase-2 algorithm. Defaults to `scenarios.mona.letter_show.plugins.cbba.CBBA`. Switch to `...dec_hungarian.DistributedHungarian` to use Hungarian instead. |
| `decision_making.GRAPE` | Phase-1 GRAPE parameters (`cost_weight_factor`, `social_inhibition_factor`, `initialize_partition`, `reinitialize_partition_on_completion`). |
| `decision_making.CBBA` / `Hungarian` | Per-algorithm Phase-2 parameters. |
| `agents.fixed_positions` / `fixed_angles` / `fixed_batteries` | Initial pose and battery for each of the 9 agents. |
| `super_tasks.groups` | Task indices belonging to each super-task. For the initial `R` letter this is `[0,1,2]` (stem) + `[3..8]` (bump + leg). |
| `tasks.fixed_positions` / `fixed_amounts` | First letter's (R) 9 pixel positions and amounts. |
| `tasks.dynamic_task_generation.generations` | List of subsequent letters' pixel positions. The bundled yaml ships 21 generations: `O B O T I C S A N D A U T O M A T I O N`. |
| `tasks.dynamic_task_generation.delay_seconds` | Wall-clock dwell after every agent arrives, before the next letter is generated. |
| `tasks.super_task_dwell_seconds` | Phase-1 convergence latch: every agent must hold a stable super-task assignment for this long (wall clock) before Phase 1 stops re-running. |
| `agents.body_radius` | MONA physical footprint in simulator pixels. Adjust together with the WhyCode camera calibration. |
| `agents.max_speed` / `max_accel` / `max_angular_speed` | Rotation-shim controller dynamics (sim only; in puppet mode the ESP32 firmware decides motor PWM and gains itself). |
| `simulation.rendering_options.agent_battery` | If True, draws a vertical battery bar to the left of each agent. |

