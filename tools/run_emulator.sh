#!/usr/bin/env bash
#
# run_emulator.sh - Launch Fab Agon Emulator with MOD-WIFI-ESP8266 Simulator
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EMULATOR_DEFAULT="/Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator"

if [ -n "$1" ] && [ -x "$1" ]; then
    EMU_BIN="$1"
elif [ -x "$EMULATOR_DEFAULT" ]; then
    EMU_BIN="$EMULATOR_DEFAULT"
elif which fab-agon-emulator >/dev/null 2>&1; then
    EMU_BIN="$(which fab-agon-emulator)"
else
    echo "Error: fab-agon-emulator executable not found."
    echo "Usage: $0 [/path/to/fab-agon-emulator]"
    exit 1
fi

echo "Using emulator binary: $EMU_BIN"
echo "Starting ESP8266 simulator and bridging to UART1..."

exec python3 "$SCRIPT_DIR/esp8266_sim.py" --verbose --launch "$EMU_BIN"
