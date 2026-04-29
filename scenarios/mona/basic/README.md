# MONA · basic

The default MONA test scenario: 4 agents at the four corners of the
arena allocating 100 randomly-placed tasks via CBBA (or GRAPE / Greedy
via the commented-out blocks). Four operation modes share the **same
algorithm setup, BT XML, agent dynamics, and task layout** — only the
external systems wired in differ. This makes the four modes directly
comparable.

---

## Mode comparison

| Mode | Task allocation | Motion (UDP G/STOP) | P2P (TCP↔ESP-NOW) | Localisation |
|------|---|---|---|---|
| `full_simulation` | autonomy_bt | sim | sim (in-process) | sim |
| `puppet` | autonomy_bt | **MONA** | sim (in-process) | **WhyCon** |
| `p2p` | autonomy_bt | sim | **MONA** | sim |
| `offboard` | autonomy_bt | **MONA** | **MONA** | **WhyCon** |

`MonaSim` reads `mona.mode` from the yaml and activates the right
combination at startup.

---

## yaml differences across modes

| key | full_simulation | puppet | p2p | offboard |
|---|---|---|---|---|
| `mona.mode` | `full_simulation` | `puppet` | `p2p` | `offboard` |
| `mona.robots` | absent | required | required | required |
| `mona.udp_port` (WhyCon listener) | — | `9999` | (unused) | `9999` |

Everything else (`agents:`, `tasks:`, `simulation:`, `decision_making:`)
is **identical** across the four files. The `agents.max_speed` /
`max_accel` / `max_angular_speed` are calibrated to real-MONA dynamics
so the simulated rotation-shim controller matches the physical robot's
motion profile. (These values are unused when `mona.mode` activates
real-robot motion — ESP32 firmware decides motor PWM and gains itself;
the host only sends `(angle_deg, distance_mm)`.)

---

## Files

```
scenarios/mona/basic/
├── default_bt.xml              # shared BT (identical across modes)
├── bt_nodes.py                 # 1-line re-export from platforms/mona/bt_nodes_mona
├── configs/
│   ├── full_simulation.yaml
│   ├── puppet.yaml
│   ├── p2p.yaml
│   └── offboard.yaml
├── sim/
│   ├── sim.py                  # class Sim(MonaSim): pass
│   ├── agent.py                # Agent(MonaAgent) — task_colors injection
│   └── task.py                 # Task definition
├── Arduino/
│   ├── SPACE_MONA_puppet.ino
│   ├── SPACE_MONA_p2p.ino
│   └── SPACE_MONA_offboard.ino
└── README.md                   # this file
```

Supporting modules (under `platforms/mona/`):

| File | Role |
|------|------|
| `mona_sim.py` | `MonaSim(BaseSim)` — wall-clock display, MonaComm wiring, WhyCon UDP listener, real-robot keyboard handler. |
| `mona_agent.py` | `MonaAgent(BaseAgent)` — rotation-shim controller + optional UDP motion + optional TCP↔ESP32 P2P bridge. `body_radius` and motion enablement derive from `mona.mode` automatically. |
| `mona_client.py` | UDP client. Sends `G <angle_deg> <distance_mm>\n` and `STOP\n` to a single MONA. |
| `mona_comm.py` | TCP+JSON connection manager. Sends compressed CBBA broadcasts to ESP32 and reads back peer messages. |
| `bt_nodes_mona.py` | BT nodes shared across all four modes: `MoveToTarget`, `ExecuteTask`, `Explore`, `Idle`, `IsTaskCompleted`, `IsArrivedAtTarget`. |
| `ros2_bridge/marker_to_simulator.py` | Standalone ROS 2 node. Subscribes to `/whycode_node/markers`, converts metres → simulator pixels, forwards `{agent_id, x, y, yaw}` to UDP `127.0.0.1:9999`. **Required for puppet / offboard.** Run as `python -m platforms.mona.ros2_bridge.marker_to_simulator`. |

---

## Installation

> **Prerequisites**
> - Ubuntu 24.04
> - [ROS 2 Jazzy](https://docs.ros.org/en/jazzy/Installation.html) installed and sourced (puppet / offboard only)
> - Python 3.10+
> - Arduino IDE 1.8+ (puppet / p2p / offboard only)

### 1. autonomy_bt

```sh
git clone --recurse-submodules https://github.com/InMOLab/autonomy_bt.git
cd autonomy_bt
pip install -r requirements.txt
```

### 2. WhyCode (ROS 2) — puppet / offboard only

```sh
mkdir -p ~/whycon_ws/src
cd ~/whycon_ws/src
git clone https://github.com/Chaeyoung1011/whycon-ros.git
sudo apt install libopencv-dev
cd ~/whycon_ws
colcon build --packages-select whycode_interfaces
colcon build --packages-select whycode
source ~/whycon_ws/install/setup.bash
```

### 3. MONA Firmware (Arduino) — puppet / p2p / offboard only

**3-1.** Install Arduino IDE 1.8+ and add ESP32 board support:
- File → Preferences → Additional Board Manager URLs:
  `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
- Tools → Board → Boards Manager: search `esp32` (Espressif Systems) → Install
- Tools → Board → **ESP32 Wrover Module**

**3-2.** Install libraries via Tools → Manage Libraries:

| Library | Purpose |
|---|---|
| `Adafruit LSM9DS1` | IMU |
| `Adafruit MCP23008` | GPIO expander |
| `Adafruit NeoPixel` | LED |
| `Adafruit Unified Sensor` | Sensor abstraction |
| `ArduinoJson` | JSON parsing (p2p / offboard) |

**3-3.** For each robot, edit the top of the corresponding `.ino`:

```cpp
const char* SSID     = "YourWiFiSSID";
const char* PASSWORD = "YourWiFiPassword";
const String SELF_ID = "0";   // unique per robot: 0, 1, 2, ...
```

Then connect via USB and upload the firmware matching your target mode:

| Mode | Firmware path |
|---|---|
| puppet | `scenarios/mona/basic/Arduino/SPACE_MONA_puppet.ino` |
| p2p | `scenarios/mona/basic/Arduino/SPACE_MONA_p2p.ino` |
| offboard | `scenarios/mona/basic/Arduino/SPACE_MONA_offboard.ino` |

---

## How to Execute

### Preparation (puppet / offboard only — once per camera/robot setup)

**P-1. Generate WhyCode markers**

```sh
cd ~/whycon_ws/src/whycon-ros/whycode-generator
make
./whycode_gen <id_bits>      # e.g. ./whycode_gen 7
```

The chosen `id_bits` **must match the `id_bits:=` arg used when
launching the WhyCode node**. Marker IDs are mapped to agent IDs by
`marker_to_agent` inside `platforms/mona/ros2_bridge/marker_to_simulator.py`
(default: marker `1..12` → agent `0..11`). Print and cut the markers.

**P-2. Attach markers** to the top of each MONA so they are clearly
visible from the overhead camera.

**P-3. Camera calibration (one-time)**

```sh
sudo apt install ros-jazzy-camera-calibration

# Launch the camera node first (Step 1 below), then:
source /opt/ros/jazzy/setup.bash
ros2 run camera_calibration cameracalibrator \
  --size 8x6 --square 0.025 \
  --ros-args -r image:=/image_raw_decoded -r camera:=/camera
```

Move the checkerboard until all bars turn green, then **Calibrate →
Save → Commit**. Output saved to
`~/.ros/camera_info/<camera_name>.yaml`, referenced by
`camera_info_url:=` in the gscam launch.

---

### Startup order

> `full_simulation` and `p2p` do **not** require Steps 1–4. Jump
> directly to [Step 5](#step-5-run-autonomy_bt).

**Step 1. Camera node (gscam)**

```sh
source /opt/ros/jazzy/setup.bash
source ~/whycon_ws/install/setup.bash
ros2 run gscam gscam_node --ros-args \
  -p gscam_config:="v4l2src device=/dev/video0 io-mode=2 ! image/jpeg,framerate=30/1,width=1920,height=1080 ! jpegdec ! videoconvert ! video/x-raw,format=BGR" \
  -p frame_id:=camera \
  -p camera_name:="1080p_usb_camera:_1080p_usb_cam" \
  -p camera_info_url:=file:///home/<user>/.ros/camera_info/1080p_usb_camera:_1080p_usb_cam.yaml \
  -p sync_sink:=false \
  -r /camera/image_raw:=/image_raw_decoded \
  -r /camera/camera_info:=/camera_info
```

**Step 2. WhyCode node**

```sh
source /opt/ros/jazzy/setup.bash
source ~/whycon_ws/install/setup.bash
ros2 launch whycode whycode.launch \
  img_base_topic:=/image_raw_decoded \
  info_topic:=/camera_info \
  marker_diameter:=0.158 num_markers:=100 \
  id_bits:=7 id_samples:=720 hamming_dist:=1
```

**Step 3. (Optional) RViz2**

```sh
source /opt/ros/jazzy/setup.bash
source ~/whycon_ws/install/setup.bash
ros2 run rviz2 rviz2
```

**Step 4. Marker → simulator bridge**

```sh
cd ~/autonomy_bt
source /opt/ros/jazzy/setup.bash
source ~/whycon_ws/install/setup.bash
python -m platforms.mona.ros2_bridge.marker_to_simulator
```

**Step 5. Run autonomy_bt**

```sh
cd ~/autonomy_bt
python main.py --config scenarios/mona/basic/configs/<mode>.yaml
# <mode> = full_simulation | puppet | p2p | offboard
```

**What to edit in each yaml before running on real hardware**

- `mona.robots[*].host` — IP of each MONA (firmware prints its IP on boot via Serial).
- `mona.robots[*].port` — TCP/UDP port (default 8080; matching firmware constant).
- `mona.udp_port` — port the Sim's WhyCon listener binds to; matches the UDP target in `marker_to_simulator.py`.
- `agents.body_radius` — MONA physical footprint in simulator pixels; adjust together with WhyCode camera calibration.
- Don't change `agents.max_*` unless you're tuning the simulation profile (real-robot motion ignores them anyway).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Agents stay at initial position in puppet / offboard | `marker_to_simulator.py` not running, `mona.udp_port` mismatch, or marker not visible. Look for `[MonaSim] WhyCon UDP listening on 0.0.0.0:9999`. |
| `MonaAgent N` does not print `Connected to ...` line | `mona.mode` doesn't activate motion (only puppet / offboard do), or this `agent_id` has no entry under `mona.robots`. |
| MONA receives `G ...` but does not move | Wi-Fi disconnect / wrong `SELF_ID` / motor power. Check Arduino Serial output. |
| In p2p, peers never appear in `agents_nearby` | TCP connect to ESP32 failing; verify `mona.robots[*].host:port` and use the **p2p** firmware variant. |
| `AttributeError: module ... bt_nodes has no attribute 'ReactiveFallback'` | Stale `__pycache__`. `find . -name __pycache__ -exec rm -rf {} +`. |

---

## Citations
- [Inmo Jang, *"SPACE: A Python-based Simulator for Evaluating Decentralized Multi-Robot Task Allocation Algorithms"*, arXiv:2409.04230, 2024](https://arxiv.org/abs/2409.04230)
