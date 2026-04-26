#!/bin/bash
# Run main.py (BT runner) for N robots in parallel.
# Usage: ./run_bt_runners.sh [NUM_ROBOTS] [CONFIG_NAME]
#   NUM_ROBOTS:   number of robots to launch (default: 10)
#   CONFIG_NAME:  config filename under scenarios/simple/configs/ (default: grape.yaml)
#
# Run from the project root:
#   bash scenarios/simple/scripts/run_bt_runners.sh
#   bash scenarios/simple/scripts/run_bt_runners.sh 3
#   bash scenarios/simple/scripts/run_bt_runners.sh 3 greedy.yaml

NUM_ROBOTS=${1:-10}
CONFIG_NAME=${2:-grape.yaml}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
CONFIG="$ROOT_DIR/scenarios/ros2/webots_fire_suppression/configs/$CONFIG_NAME"

PIDS=()

cleanup() {
    echo ""
    echo "[run_bt_runners] Stopping all BT runners..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    wait
    echo "[run_bt_runners] All stopped."
}
trap cleanup INT TERM

echo "[run_bt_runners] Launching $NUM_ROBOTS BT runner(s)..."
for i in $(seq 1 "$NUM_ROBOTS"); do
    python3 "$ROOT_DIR/main.py" --config="$CONFIG" --ns "/Fire_UGV_$i" &
    PIDS+=($!)
    echo "  Fire_UGV_$i  PID=${PIDS[-1]}"
done

echo "[run_bt_runners] All started. Press Ctrl+C to stop all."
wait
