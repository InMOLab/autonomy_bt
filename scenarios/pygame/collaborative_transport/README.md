# Scenario: Collaborative Transport

## Overview

A multi-robot collaborative transport scenario where groups of agents must cooperate to lift, carry, and place polygon-shaped block tasks into matching slot locations. Each block task requires multiple agents (determined by the polygon's vertex count) to gather at the block, coordinate at vertex positions, lift together, transport to the target slot, and place it down. This is a Multi-Task requiring Multi-Robot (MT-MR) problem.

## How to Run

```bash
cd autonomy_bt
python3 main.py --config scenarios/pygame/collaborative_transport/configs/config.yaml
```

## Configuration

| Config | MRTA Algorithm | Description |
|--------|---------------|-------------|
| `configs/config.yaml` | GRAPE_CT (default) | GRAPE adapted for collaborative transport with waiting time tolerance |

Additional algorithm plugins available (commented out in the YAML):
- **GRAPE_CT_no_minw**: GRAPE-CT variant without minimum waiting factor
- **GRAPE**: Standard GRAPE (game-theoretic partition)
- **CBBA**: Consensus-based bundle algorithm
- **FirstClaimGreedy**: Greedy nearest-first allocation
- **Greedy_not_FC**: Greedy without forced collaboration
- **LJF**: Largest Job First

Key parameters:
- **Agents**: 60 robots, max speed 0.8, global communication (radius 0)
- **Tasks**: 20 block-slot pairs (must be even number), polygon shapes with 5-6 sides
- **Task amounts**: 100-170 (fixed work amount: 35)
- **Waiting time tolerance**: 10 seconds (GRAPE_CT parameter)

## Behaviour Tree

```
ReactiveSequence
├── GatherLocalInfo
└── Sequence
    ├── ReactiveSequence
    │   ├── ReactiveFallback
    │   │   ├── AssignTask              ← Select block task via MRTA
    │   │   └── Explore                 ← Random exploration if no task
    │   └── ReactiveSequence
    │       ├── ReactiveFallback
    │       │   ├── IsArrivedAtBlockTask ← At the block location?
    │       │   └── MoveToBlockTask
    │       ├── ReactiveFallback
    │       │   ├── IsAllAgents          ← All required agents gathered?
    │       │   └── WaitAgents           ← Wait for teammates
    │       └── SelectVertex             ← Pick a vertex position on the block
    ├── ReactiveFallback
    │   ├── IsBlockTaskLifted
    │   └── ReactiveSequence
    │       ├── ReactiveFallback
    │       │   ├── IsArrivedAtVertex
    │       │   └── MoveToVertex
    │       ├── ReactiveFallback
    │       │   ├── IsAllAgentsAtVertex  ← All agents at their vertices?
    │       │   └── WaitAgents
    │       └── LiftBlockTask            ← Cooperatively lift
    └── ReactiveFallback
        ├── IsSlotTaskCompleted
        └── ReactiveSequence
            ├── ReactiveFallback
            │   ├── IsArrivedAtSlotTask
            │   └── MoveToSlotTask
            └── PlaceDownBlockTask       ← Place block into slot
```

## Test Verification

- The pygame window shows agents, polygon block tasks, and corresponding slot positions.
- Agents form coalitions around block tasks (visible by matching colors).
- Multiple agents gather at a block, wait for all teammates, then move to vertex positions.
- Blocks are cooperatively lifted and transported to their matching slot locations.
- Agents with assigned tasks show their color matching the block color.
