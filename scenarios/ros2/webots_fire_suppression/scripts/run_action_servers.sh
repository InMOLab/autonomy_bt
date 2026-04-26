#!/bin/bash
# Run nav_action_server.py for N robots in parallel.
# Usage: ./run_action_servers.sh [NUM_ROBOTS]
#   NUM_ROBOTS: number of robots to launch (default: 10)
#
# Run from the project root:
#   bash scenarios/simple/scripts/run_action_servers.sh
#   bash scenarios/simple/scripts/run_action_servers.sh 3

NUM_ROBOTS=${1:-10}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
NAV_SERVER="$ROOT_DIR/scenarios/ros2/webots_fire_suppression/action_servers/nav_action_server.py"

PIDS=()

cleanup() {
    echo ""
    echo "[run_action_servers] Stopping all nav_action_servers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    wait
    echo "[run_action_servers] All stopped."
}
trap cleanup INT TERM

echo "[run_action_servers] Launching $NUM_ROBOTS nav_action_server(s)..."
for i in $(seq 1 "$NUM_ROBOTS"); do
    python3 "$NAV_SERVER" --ns "/Fire_UGV_$i" &
    PIDS+=($!)
    echo "  Fire_UGV_$i  PID=${PIDS[-1]}"
done

echo "[run_action_servers] All started. Press Ctrl+C to stop all."
wait
