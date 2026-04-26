# Scenario: Simple Multi-Robot Task Allocation

## Overview

A basic multi-robot task allocation (MRTA) scenario where multiple agents navigate a 2D space to locate and complete tasks. Each agent is driven by a Behaviour Tree that assigns tasks via a pluggable MRTA algorithm, moves to the target, and executes work until the task is completed. Dynamic task generation periodically spawns new tasks during the simulation.

## How to Run

```bash
cd autonomy_bt

# Greedy (nearest-first allocation)
python3 main.py --config scenarios/pygame/simple/configs/greedy.yaml

# GRAPE (game-theoretic distributed partition)
python3 main.py --config scenarios/pygame/simple/configs/grape.yaml

# CBBA (consensus-based bundle algorithm)
python3 main.py --config scenarios/pygame/simple/configs/cbba.yaml

# Hungarian (distributed Hungarian algorithm)
python3 main.py --config scenarios/pygame/simple/configs/hungarian.yaml
```

## Configuration

| Config | MRTA Algorithm | Description |
|--------|---------------|-------------|
| `configs/greedy.yaml` | FirstClaimGreedy (MinDist) | Each agent independently picks the nearest available task |
| `configs/grape.yaml` | GRAPE | Distributed coalition formation via game-theoretic partition (400 agents, 10 large tasks) |
| `configs/cbba.yaml` | CBBA | Consensus-based bundle algorithm for multi-task assignment |
| `configs/hungarian.yaml` | DistributedHungarian | Distributed Hungarian algorithm with network consensus for optimal task-agent matching |

Key parameters shared across configs:
- **Agents**: 10 (greedy/cbba/hungarian) or 400 (grape), max speed 0.25
- **Tasks**: 100 (greedy/cbba/hungarian) or 10 (grape), with dynamic generation enabled
- **Communication radius**: 500 (150 for grape), 0 = global
- **Rendering**: Pygame screen mode with agent tails and communication topology

## Test Verification

- The pygame window opens showing agents (with IDs) and tasks (circles).
- Agents move toward assigned tasks and reduce their size upon arrival.
- Task completion count increases over time (visible in terminal output).
- Dynamic tasks spawn at configured intervals.
- When `rendering_mode: None` or `Terminal` is set, the simulation runs headlessly and outputs CSV results to the `output/` folder.
