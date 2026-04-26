# Scenario: Harbor Logistics

## Overview

A harbor container logistics scenario where multiple AGV (Automated Guided Vehicle) agents transport containers from ships to designated delivery locations. Each agent follows a Behaviour Tree that handles ship selection, navigation via A* path planning, container pickup/delivery, and battery management with autonomous charging station visits.

## How to Run

```bash
cd autonomy_bt
python3 main.py --config scenarios/pygame/harbor_logistics/configs/config.yaml
```

## Configuration

| Config | MRTA Algorithm | Description |
|--------|---------------|-------------|
| `configs/config.yaml` | FirstClaimGreedy (MinDist) | Each agent picks the nearest available container task |

The config also supports GRAPE and CBBA (commented out in the YAML).

Key parameters:
- **Agents**: 15 AGVs with battery management (default spending rate: 0.001, task spending rate: 0.01)
- **Tasks**: 200 containers across 2 ships (Ship1 and Ship2)
- **Path planner**: A* algorithm on a grid (size 40), also supports XY and YX planners
- **Charging station**: Located at (1220, 630) with per-agent offset; agents auto-navigate to charge when battery drops below 20%
- **Rendering**: Pygame screen with custom harbor assets (ship sprites, container colors, background)

## Behaviour Tree

```
Sequence
├── Fallback
│   ├── IsBatterySufficient        ← Check battery > 20%
│   └── Sequence
│       ├── Fallback
│       │   ├── IsArrivedAtChargingStation
│       │   └── GoToChargingStation
│       └── ChargeBattery
└── Sequence
    ├── LocalSensingNode
    └── Fallback
        ├── IsFinishedTask
        └── Sequence
            ├── Fallback
            │   ├── IsHoldingItem
            │   └── Sequence
            │       ├── Fallback
            │       │   ├── IsArrivedAtShip
            │       │   └── Sequence
            │       │       ├── DecideShip
            │       │       └── GoToShip
            │       └── PickItem
            ├── Fallback
            │   ├── IsArrivedAtDestination
            │   └── GoToDestination
            └── PlaceItem
```

## Test Verification

- The pygame window displays a harbor environment with ships, containers, and AGVs.
- Agents navigate to ships, pick up colored containers, and deliver them to destination locations.
- Agent sprites change to show the container color they are carrying.
- Battery levels are displayed; agents autonomously return to charging stations when low.
- All 200 container tasks eventually get delivered.
