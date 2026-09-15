#!/usr/bin/env bash
#
# run_emulator.sh - Launch Fab Agon Emulator with MOD-WIFI-ESP8266 Simulator
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default relative path to emulator binary (relative to repository root)
DEFAULT_EMULATOR="../fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator"

# Resolution order:
# 1. Command-line argument: ./run_emulator.sh /path/to/fab-agon-emulator
# 2. FAB_AGON_EMULATOR environment variable
# 3. DEFAULT_EMULATOR relative path (relative to repo root)
# 4. System PATH (fab-agon-emulator)

if [ -n "$1" ] && [ -x "$1" ]; then
    EMU_BIN="$1"
elif [ -n "$FAB_AGON_EMULATOR" ] && [ -x "$FAB_AGON_EMULATOR" ]; then
    EMU_BIN="$FAB_AGON_EMULATOR"
elif [ -x "$REPO_ROOT/$DEFAULT_EMULATOR" ]; then
    EMU_BIN="$(cd "$REPO_ROOT" && cd "$(dirname "$DEFAULT_EMULATOR")" && pwd)/$(basename "$DEFAULT_EMULATOR")"
elif which fab-agon-emulator >/dev/null 2>&1; then
    EMU_BIN="$(which fab-agon-emulator)"
else
    echo "Error: fab-agon-emulator executable not found."
    echo "Set FAB_AGON_EMULATOR=/path/to/fab-agon-emulator or pass path as argument:"
    echo "Usage: $0 [/path/to/fab-agon-emulator]"
    exit 1
fi

echo "Using emulator binary: $EMU_BIN"
echo "Starting ESP8266 simulator and bridging to UART1..."

exec python3 "$SCRIPT_DIR/esp8266_sim.py" --verbose --launch "$EMU_BIN"
