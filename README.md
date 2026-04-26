# autonomy_bt

A Python-based modular Behaviour Tree framework for single-robot and multi-robot autonomy. Supports both pygame simulation and ROS 2 real-robot deployment.

## Features

- **Core BT Engine**: Sequence, Fallback, Parallel, ReactiveSequence, ReactiveFallback
- **Platform Support**: pygame (simulation) and ROS 2 (real robots / Webots)
- **MRTA Plugins**: GRAPE, CBBA, CBAA, Greedy, Hungarian (pluggable task allocation)

## Quick Start

```bash
# Pygame simulation (no ROS required)
python3 main.py --config scenarios/pygame/simple/configs/grape.yaml

# ROS 2 (requires turtlesim running)
python3 main.py --config scenarios/ros2/turtle_catcher/configs/config_turtlesim.yaml
```

## Project Structure

```
autonomy_bt/
├── core/                  ← BT engine (platform-independent)
├── platforms/
│   ├── pygame/            ← Pygame simulation platform
│   └── ros2/              ← ROS 2 platform
├── plugins/
│   └── mrta/              ← Multi-Robot Task Allocation algorithms
├── scenarios/             ← Example scenarios
└── main.py                ← Entry point
```

## Scenarios

### Pygame Scenarios

| Scenario | Description | How to Run |
|----------|-------------|------------|
| [Simple](scenarios/pygame/simple/README.md) | Multi-robot task allocation with 4 MRTA algorithms | `python3 main.py --config scenarios/pygame/simple/configs/grape.yaml` |
| [Harbor Logistics](scenarios/pygame/harbor_logistics/README.md) | AGV container transport with A* path planning | `python3 main.py --config scenarios/pygame/harbor_logistics/configs/config.yaml` |
| [Drone Delivery](scenarios/pygame/drone_delivery/README.md) | Drone pickup/delivery with dynamic task generation | `python3 main.py --config scenarios/pygame/drone_delivery/configs/config.yaml` |
| [Collaborative Transport](scenarios/pygame/collaborative_transport/README.md) | Multi-robot cooperative transport (MT-MR) | `python3 main.py --config scenarios/pygame/collaborative_transport/configs/config.yaml` |

### ROS 2 Scenarios

| Scenario | Description | Simulator |
|----------|-------------|-----------|
| [Turtle Catcher](scenarios/ros2/turtle_catcher/README.md) | Single-robot pursuit in turtlesim | turtlesim |
| [Webots Fire Suppression](scenarios/ros2/webots_fire_suppression/README.md) | Multi-robot fire suppression with MRTA | Webots |

## Requirements

```bash
pip install -r requirements.txt
# For ROS 2 scenarios: ROS 2 Humble
```

## Note

This project is a unified refactoring of [space-simulator](https://github.com/inmo-jang/space-simulator) and [py_bt_ros](https://github.com/inmo-jang/py_bt_ros).

## Citations

Please cite this work in your papers!

- [Inmo Jang, *"SPACE: A Python-based Simulator for Evaluating Decentralized Multi-Robot Task Allocation Algorithms"*, arXiv:2409.04230 [cs.RO], 2024](https://arxiv.org/abs/2409.04230)

## License

[GNU GPLv3](LICENSE)
