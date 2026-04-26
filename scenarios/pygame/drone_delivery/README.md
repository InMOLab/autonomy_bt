# Scenario: Drone Delivery

## Overview

A drone delivery scenario where multiple drones pick up packages from pickup points and deliver them to drop-off locations across a city. Each drone is driven by a Behaviour Tree that handles task allocation, pickup navigation, delivery execution, and autonomous gathering when all tasks are complete. Dynamic task generation spawns new delivery requests during the simulation.

## How to Run

```bash
cd autonomy_bt
python3 main.py --config scenarios/pygame/drone_delivery/configs/config.yaml
```

## Configuration

| Config | MRTA Algorithm | Description |
|--------|---------------|-------------|
| `configs/config.yaml` | CBBA | Consensus-based bundle algorithm for multi-task assignment |

The config also supports GRAPE and FirstClaimGreedy (commented out in the YAML).

Key parameters:
- **Agents**: 10 drones, max speed 1.0
- **Tasks**: 20 delivery tasks with dynamic generation (20 tasks every 1500 seconds, up to 3 generations)
- **Communication radius**: 500
- **Rendering**: Pygame screen with city background, drone sprites, and pickup/dropoff point assets

## Behaviour Tree

```
ReactiveSequence
├── LocalSensingNode
└── ReactiveFallback
    ├── ReactiveSequence
    │   ├── DecisionMakingNode       ← Allocate nearest unassigned task
    │   └── ReactiveFallback
    │       ├── ReactiveSequence
    │       │   ├── CheckingitemsNode    ← Check if pickup needed
    │       │   └── DeliveryexecutingNode ← Navigate to pickup, then delivery
    │       └── ReactiveSequence
    │           ├── RightplacecheckingNode
    │           └── DropoffexecutingNode  ← Execute final drop-off
    ├── ReactiveSequence
    │   ├── CheckingnomoreTask       ← No tasks remaining?
    │   └── GatheringNode            ← Gather all drones to center point
    └── ExplorationNode              ← Random exploration while waiting
```

## Test Verification

- The pygame window shows a city map with drones, pickup points, and drop-off points.
- Drones navigate to pickup locations, collect packages, and fly to delivery points.
- Completed deliveries are tracked; new tasks appear dynamically.
- When all tasks are done, drones gather at the center of the screen (700, 500).
- CSV results are saved to the `output/` folder when saving options are enabled.
