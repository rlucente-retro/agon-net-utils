# agon-net-utils

Network utilities for the **Agon family** (Agon Light, Agon Light 2, etc., based on the Zilog eZ80F92) running Quark MOS, specifically supporting network coprocessor workflows with the **Olimex MOD-WIFI-ESP8266** module on UART1.

---

## Utilities

| Binary / Script | Description |
| :--- | :--- |
| `openstream.bin` | Connects to a remote TCP host and puts the ESP8266 into transparent streaming mode (`CIPMODE=1`), preserving the link for subsequent OS bootloaders (e.g. `OSboot.bin` for TRS-OS). |
| `closestream.bin` | Escapes transparent streaming mode (`+++`), closes active TCP sockets (`AT+CIPCLOSE`), and returns the ESP8266 to standard command mode (`CIPMODE=0`). |
| [`tools/esp8266_sim.py`](tools/esp8266_sim.py) | Virtual serial PTY coprocessor simulator for testing network tools in `fab-agon-emulator` without physical hardware. |

---

## Project Structure

```text
agon-net-utils/
├── src/
│   ├── esp8266.h        # Shared serial, timing, and AT command engine
│   ├── esp8266.c        # Shared implementation (UART1, Hayes escape, restore)
│   ├── openstream.c     # openstream entry point and connection setup
│   └── closestream.c    # closestream entry point and teardown logic
├── bin/                 # Compiled executable binaries (.bin)
├── tools/               # Coprocessor simulator and automated test suite
└── Makefile             # Unified build system
```

---

## Building

Requires the [AgonDev SDK](https://github.com/Agon-Development-Community/agondev):

```bash
make clean && make
```

You can also build an individual utility:

```bash
make openstream
# or
make closestream
```

The resulting binaries will be generated at `bin/openstream.bin` and `bin/closestream.bin`.

---

## Installation

Copy `bin/openstream.bin` and `bin/closestream.bin` to the `/mos/` directory of your Agon microSD card. Placing executables in `/mos/` ensures they are available from any working directory across all Quark MOS versions.

---

## Usage

### `openstream`

Establishes a transparent TCP connection to a remote host and switches the ESP8266 into streaming mode:

```text
openstream <host_or_ip> <port>
```

#### Arguments
* `<host_or_ip>`: Remote server hostname or IPv4 address (e.g. `192.168.1.50` or `myserver.local`).
* `<port>`: Remote TCP port number (`1`-`65535`).

#### Example
```text
openstream 192.168.1.50 65432
```

Expected output:
```text
Connecting to 192.168.1.50:65432...
Streaming mode active on UART1 (115200 8-N-1).
Link established. Ready for TRS-OS.
```

Upon receiving the `>` streaming prompt, `openstream` flushes residual characters, calls `mos_uclose()` to detach the MOS interrupt handler, and returns cleanly to the MOS prompt with the stream active.

---

### `closestream`

Safely tears down an active transparent stream and returns the ESP8266 to AT command mode:

```text
closestream
```

Expected output:
```text
Closing stream and restoring ESP8266 command mode...
Notice: Module not responding. Attempting stream escape...
Notice: Recovered module to command mode.
Stream closed. ESP8266 in command mode.
```

Enforces 1.25s silence guard intervals around the Hayes `+++` escape code, terminates active connections (`AT+CIPCLOSE`), resets to command mode (`AT+CIPMODE=0`), and closes UART1.

---

### TRS-OS Bootloader Integration

A typical `autoexec.txt` configuration on your microSD card to initialize network streaming and launch TRS-OS:

```text
LOAD mos/openstream.bin
RUN . 192.168.1.50 65432
LOAD OSboot.bin
RUN
```

---

## Testing

A complete simulation environment and automated test suite for [Fab Agon Emulator](https://github.com/tomm/fab-agon-emulator) is provided under [`tools/`](tools/).

To verify the full network pipeline locally without physical hardware:

```bash
cd tools
./test_integration.py
```

By default, the tools check for `fab-agon-emulator` in your system `PATH`, via the `FAB_AGON_EMULATOR` environment variable, or at the relative path `../fab-agon-emulator-*/fab-agon-emulator`. You can explicitly provide a custom emulator path with:

```bash
./test_integration.py --emulator /path/to/fab-agon-emulator
# or
export FAB_AGON_EMULATOR=/path/to/fab-agon-emulator
```

This automated runner:
1. Boots a mock TCP server on port 65432.
2. Initializes the MOD-WIFI-ESP8266 coprocessor simulator on a virtual PTY (`/tmp/agon-uart1`).
3. Launches `fab-agon-emulator` linked to the PTY.
4. Validates `openstream` AT negotiation, TCP connection, and bidirectional `@ping` -> `@pong` streaming.
5. Validates `closestream` stream detection, Hayes `+++` escape, socket teardown, and mode reset.
6. Restores original SD card configuration upon completion.

See [`tools/README.md`](tools/README.md) for full documentation on manual interactive testing.
