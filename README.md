# agon-net-utils

Network utilities for the **Olimex Agon Light 2** (Zilog eZ80F92) running Quark MOS, specifically supporting network coprocessor workflows with the **Olimex MOD-WIFI-ESP8266** module on UART1.

## Utilities

| Directory | Binary / Script | Description |
| :--- | :--- | :--- |
| [`openstream/`](openstream/) | `openstream.bin` | Connects to a remote TCP host and puts the ESP8266 into transparent streaming mode (`CIPMODE=1`), preserving the link for subsequent OS bootloaders (e.g. `OSboot.bin` for TRS-OS). |
| [`tools/esp8266-emulator/`](tools/esp8266-emulator/) | `esp8266_sim.py` | Virtual serial PTY coprocessor simulator for testing network tools in `fab-agon-emulator` without physical hardware. |

## Building

Each utility directory contains its own `Makefile` using the [AgonDev SDK](https://github.com/Agon-Development-Community/agondev). 

To build `openstream`:

```bash
cd openstream
make
```

The compiled binary will be placed at `openstream/bin/openstream.bin`.

---

## Testing

A complete simulation environment and automated test suite for [Fab Agon Emulator](https://github.com/tomm/fab-agon-emulator) is available under [`tools/esp8266-emulator/`](tools/esp8266-emulator/).

### Run Automated Integration Test

To verify the full network pipeline locally without physical hardware:

```bash
cd tools/esp8266-emulator
./test_integration.py
```

This automated runner:
1. Boots a mock TCP server on port 65432.
2. Initializes the MOD-WIFI-ESP8266 coprocessor simulator on a virtual PTY (`/tmp/agon-uart1`).
3. Launches `fab-agon-emulator` linked to the PTY.
4. Executes `openstream` inside MOS and validates the complete AT command handshake (`AT`, `ATE0`, `CIPMUX`, `CIPMODE=1`, `CIPSTART`, `CIPSEND`).
5. Establishes a transparent TCP connection to the mock server.
6. Tests bidirectional payload transmission (`@ping` -> `@pong`).
7. Shuts down cleanly and restores the emulator's SD card configuration.

See [`tools/esp8266-emulator/README.md`](tools/esp8266-emulator/README.md) for full documentation on manual interactive testing and emulator configuration.

