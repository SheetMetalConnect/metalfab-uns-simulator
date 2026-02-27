#!/bin/bash
# Quick launch script for MetalFab dashboards

echo "MetalFab Dashboard Launcher"
echo "==========================================="
echo

# Check if simulator is running
if ! pgrep -f "metalfab-sim run" > /dev/null; then
    echo "Warning: Simulator not running!"
    echo "  Start it with: metalfab-sim run --level 3"
    echo
    read -p "Press Enter to continue anyway or Ctrl+C to cancel..."
else
    echo "[OK] Simulator is running"
fi

# Check if HiveMQ is running
if ! docker ps | grep hivemq > /dev/null; then
    echo "[FAIL] HiveMQ container not running!"
    echo "  Start it with: docker start hivemq"
    exit 1
else
    echo "[OK] HiveMQ is running"
fi

echo
echo "Opening Factory Overview dashboard..."
open "$(dirname "$0")/eindhoven-premium.html"

echo "[OK] Dashboard opened in browser"
echo
echo "Control the simulator:"
echo "  mosquitto_pub -t 'metalfab-sim/control/level' -m '4'"
echo "  mosquitto_pub -t 'metalfab-sim/control/site/eindhoven' -m '0'"
echo
echo "Monitoring dashboard traffic (Ctrl+C to stop)..."
mosquitto_sub -t "umh/v1/metalfab/eindhoven/+/+/Dashboard/#" -v | while read line; do
    echo "[$(date +%H:%M:%S)] $line"
done
