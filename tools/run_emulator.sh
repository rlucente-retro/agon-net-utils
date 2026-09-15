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

# Ensure latest compiled binaries are synced to emulator sdcard/mos
EMU_DIR="$(dirname "$EMU_BIN")"
if [ -d "$EMU_DIR/sdcard" ]; then
    mkdir -p "$EMU_DIR/sdcard/mos"
    if [ -f "$REPO_ROOT/bin/openstream.bin" ]; then
        cp "$REPO_ROOT/bin/openstream.bin" "$EMU_DIR/sdcard/mos/"
    fi
    if [ -f "$REPO_ROOT/bin/closestream.bin" ]; then
        cp "$REPO_ROOT/bin/closestream.bin" "$EMU_DIR/sdcard/mos/"
    fi
fi

# Resolve Python interpreter (prefer virtual environment if present)
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python3" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
elif [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif which python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(which python3)"
else
    PYTHON_BIN="python"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/esp8266_sim.py" --verbose --launch "$EMU_BIN"
