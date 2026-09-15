# MOD-WIFI-ESP8266 Simulator for Fab Agon Emulator

The [Fab Agon Emulator](https://github.com/tomm/fab-agon-emulator) emulates the eZ80 CPU and the ESP32 VDP, but does **not** include an internal virtual ESP8266 network coprocessor. Instead, it exposes a host serial bridge option:

```bash
fab-agon-emulator --uart1-device <serial_device> --uart1-baud 0
```

> [!IMPORTANT]
> **macOS PTY Note:** On macOS / Darwin, virtual pseudo-terminals (PTYs) do not support the `IOSSIOSPEED` ioctl used by Rust's `serialport` crate. Passing a standard baud rate like `115200` causes the emulator to fail with `ENOTTY: Not a typewriter` and fall back to dummy output. Passing `--uart1-baud 0` skips the custom speed ioctl and opens the virtual PTY cleanly.

This toolkit provides a complete virtual ESP8266 network coprocessor environment that connects to `fab-agon-emulator` via a Unix pseudo-terminal (PTY), enabling full local testing of `openstream`, network utilities, and TRS-OS without physical hardware.

---

## Included Tools

| File | Role | Description |
| :--- | :--- | :--- |
| [`test_integration.py`](test_integration.py) | **Automated Test Suite** | Two-stage automated test script that boots `mock_server.py`, `esp8266_sim.py`, and `fab-agon-emulator`, verifies AT negotiation and bidirectional TCP streaming for `openstream` (Stage 1), validates Hayes `+++` escape, socket teardown, and mode reset for `closestream` (Stage 2), and restores SD card configuration. |
| [`esp8266_sim.py`](esp8266_sim.py) | **Coprocessor Simulator** | Creates a virtual serial PTY, implements the Espressif ESP-AT v1.7.x firmware command set, manages transparent streaming mode (`CIPMODE=1`), proxies raw data over real TCP sockets, and detects Hayes `+++` escape sequences with guard silences. |
| [`mock_server.py`](mock_server.py) | **Test TCP Server** | Lightweight test server that listens on port 65432, remaining completely silent until the client sends `@ping\n`, and responds with `@pong\n`. |
| [`run_emulator.sh`](run_emulator.sh) | **Interactive Launcher** | Starts `esp8266_sim.py` and automatically launches `fab-agon-emulator` linked to the simulated PTY. |

---

## Architecture

```
+----------------------------------------------------+
|                Fab Agon Emulator                   |
|       (eZ80 UART1: openstream / closestream / OS)  |
+-------------------------+--------------------------+
                          |
         Virtual PTY: /dev/ttys00X (or /tmp/agon-uart1)
                          |
                          v
+-------------------------+--------------------------+
|                  esp8266_sim.py                    |
|  - Espressif ESP-AT v1.7.4.0 command engine        |
|  - Transparent streaming proxy (CIPMODE=1)         |
|  - Hayes '+++' escape detector (0.9s guard silence)|
+-------------------------+--------------------------+
                          |
                   Host TCP Socket
                          |
                          v
+-------------------------+--------------------------+
|              Remote Server Host                    |
|         (mock_server.py or TRS-NET.py)             |
+----------------------------------------------------+
```

---

## Method 1: Automated Integration Test Suite (Recommended)

An end-to-end automated test runner is provided in [`test_integration.py`](test_integration.py). It validates both utilities across two automated stages:

### Stage 1: `openstream` & Transparent Data Streaming
1. Installs the latest `openstream.bin` to `sdcard/mos/openstream.bin`.
2. Boots `mock_server.py` and `esp8266_sim.py`.
3. Launches `fab-agon-emulator` with `autoexec.txt` invoking `openstream.bin 127.0.0.1 65432`.
4. Validates the AT command sequence (`AT`, `ATE0`, `AT+CIPCLOSE`, `AT+CIPMODE=0`, `AT+CIPMUX=0`, `AT+CIPMODE=1`, `AT+CIPSTART`, `AT+CIPSEND`).
5. Validates incoming TCP connection on `mock_server.py`.
6. Transmits `@ping\n` through the transparent stream and validates `@pong\n` response.

### Stage 2: `closestream` Escape & Teardown
1. Installs the latest `closestream.bin` to `sdcard/mos/closestream.bin`.
2. Configures `autoexec.txt` to invoke `openstream.bin` followed immediately by `closestream.bin`.
3. Launches `fab-agon-emulator`.
4. Validates that `closestream` detects non-responsive stream mode and issues the Hayes `+++` escape code.
5. Validates that `esp8266_sim.py` enforces guard silences and drops back to AT command mode.
6. Validates `AT+CIPCLOSE` socket teardown and disconnection at `mock_server.py`.
7. Validates `AT+CIPMODE=0` mode reset and clean MOS completion.
8. Restores the emulator's original `autoexec.txt`.

### Running the Automated Test

```bash
cd tools
./test_integration.py
```

#### Emulator Resolution & User Overrides

Both `test_integration.py` and `run_emulator.sh` locate the `fab-agon-emulator` binary in the following priority order:

1. **Command-line argument:**
   ```bash
   ./test_integration.py --emulator /path/to/fab-agon-emulator
   ```
2. **Environment variable override (`FAB_AGON_EMULATOR`):**
   ```bash
   export FAB_AGON_EMULATOR=/path/to/fab-agon-emulator
   ./test_integration.py
   ```
3. **Default relative path (`DEFAULT_EMULATOR`):**
   Relative to the repository root directory (`../fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator`).
4. **System `PATH`:**
   Automatically detected if `fab-agon-emulator` is installed in your system PATH.

Optional arguments for `test_integration.py`:
* `--emulator`, `-e`: Path to `fab-agon-emulator` executable.
* `--port`, `-p`: TCP port for mock server (default: `65432`).
* `--timeout`, `-t`: Max handshake timeout in seconds (default: `10.0`).

### Expected Output

```text
============================================================
  openstream & closestream Integration Test Suite
============================================================
Emulator Binary: /path/to/fab-agon-emulator
TCP Port:        65432
SDCard Dir:      /path/to/fab-agon-emulator/sdcard
------------------------------------------------------------

------------------------------------------------------------
  STAGE 1: openstream & Bidirectional Stream Verification
------------------------------------------------------------
[*] Starting Mock TCP Server...
[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...
[*] Launching Fab Agon Emulator (--uart1-baud 0)...
[*] Waiting for openstream AT handshake and TCP connection...
[*] Testing bidirectional stream payload (@ping -> @pong)...
[+] Successfully received reply over UART1 stream: b'pong\n'
[*] Stage 1 AT Negotiation:     PASS
[*] Stage 1 Socket Connection:  PASS
[*] Stage 1 openstream Output:  PASS
[*] Stage 1 Payload Streaming:  PASS

------------------------------------------------------------
  STAGE 2: closestream Escape & Teardown Verification
------------------------------------------------------------
[*] Starting Mock TCP Server...
[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...
[*] Launching Fab Agon Emulator (--uart1-baud 0)...
[*] Waiting for openstream + closestream execution...
[*] Stage 2 Hayes Escape (+++): PASS
[*] Stage 2 Socket Disconnect:  PASS
[*] Stage 2 CIPMODE=0 Reset:    PASS
[*] Stage 2 closestream Output: PASS

[+] Restored original autoexec.txt.

============================================================
                    OVERALL TEST SUMMARY
============================================================
[*] Stage 1 (openstream & streaming):  PASS
[*] Stage 2 (closestream & teardown):  PASS
============================================================
[+] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!
```

---

## Method 2: Manual Interactive Testing

For interactive testing in the emulator window with manual MOS commands:

### Step 1: Build & Copy Binaries

Compile all utilities and copy them to the emulator's `sdcard/mos/` folder:

```bash
make clean && make
cp bin/openstream.bin /path/to/fab-agon-emulator/sdcard/mos/
cp bin/closestream.bin /path/to/fab-agon-emulator/sdcard/mos/
```

### Step 2: Start Mock Server (Terminal 1)

```bash
cd tools
./mock_server.py --port 65432
```

The server will print:
```text
[*] Mock TCP server listening on 0.0.0.0:65432
[*] Waiting for client connection (e.g. from openstream / TRS-OS)...
```

### Step 3: Launch Simulator & Emulator (Terminal 2)

```bash
cd tools
./run_emulator.sh
# Or specify a custom emulator executable:
# ./run_emulator.sh /path/to/fab-agon-emulator
# Or export FAB_AGON_EMULATOR=/path/to/fab-agon-emulator
```

This starts `esp8266_sim.py` in verbose mode and automatically launches `fab-agon-emulator` linked to the allocated PTY with `--uart1-baud 0`.

### Step 4: Run `openstream`

In the emulator window:

```text
openstream 127.0.0.1 65432
```

> [!NOTE]
> If testing via `autoexec.txt` instead of typing interactively, MOS does not perform dynamic star-command resolution for binaries in subdirectories. In `autoexec.txt`, use explicit load syntax:
> ```text
> LOAD mos/openstream.bin
> RUN . 127.0.0.1 65432
> ```

### Step 5: Observe Successful Link Establishment

In the **Emulator Window**:
```text
Connecting to 127.0.0.1:65432...
Streaming mode active on UART1 (115200 8-N-1).
Link established. Ready for TRS-OS.
```

In the **Simulator Terminal (Terminal 2)**:
```text
[18:08:05] AT CMD: 'AT'
[18:08:05] AT CMD: 'ATE0'
[18:08:05] AT CMD: 'AT+CIPCLOSE'
[18:08:05] AT CMD: 'AT+CIPMODE=0'
[18:08:05] AT CMD: 'AT+CIPMUX=0'
[18:08:06] AT CMD: 'AT+CIPMODE=1'
[18:08:06] AT CMD: 'AT+CIPSTART="TCP","127.0.0.1",65432'
[18:08:06] Attempting TCP connection to 127.0.0.1:65432...
[18:08:06] TCP connection established to 127.0.0.1:65432
[18:08:06] AT CMD: 'AT+CIPSEND'
[18:08:06] Entering transparent streaming mode...
```

In the **Mock Server Terminal (Terminal 1)**:
```text
[+] Client connected from 127.0.0.1:61631
[*] Silent mode: Waiting for client '@ping'...
```

### Step 6: Teardown Link with `closestream`

In the emulator window:

```text
closestream
```

In the **Emulator Window**:
```text
Closing stream and restoring ESP8266 command mode...
Notice: Module not responding. Attempting stream escape...
Notice: Recovered module to command mode.
Stream closed. ESP8266 in command mode.
```

In the **Simulator Terminal (Terminal 2)**:
```text
Candidate +++ escape detected, waiting for post-guard silence...
+++ Escape sequence verified! Dropping to AT command mode.
AT CMD: 'AT'
AT CMD: 'ATE0'
AT CMD: 'AT+CIPCLOSE'
TCP socket closed
AT CMD: 'AT+CIPMODE=0'
```

In the **Mock Server Terminal (Terminal 1)**:
```text
[-] Client 127.0.0.1:61631 disconnected.
```

---

## Technical Details & Emulator Specifics

1. **eZ80 Debug Port 0x30 Mirroring:**
   [`fab-agon-emulator`](https://github.com/tomm/fab-agon-emulator) echoes any byte written to eZ80 I/O port `0x30` (`out0 (0x30), a`) straight to host stdout. `openstream` uses this feature to mirror console messages directly to the host terminal running the emulator.

2. **UART1 Polling vs Interrupts:**
   The emulator implements eZ80 UART1 register I/O (`UART1_RBR`, `UART1_THR`, `UART1_LSR`, `UART1_IER`), but does **not** generate the eZ80 UART1 hardware receive interrupt (`vector 0x1A`). As a result, software running in the emulator must poll the UART1 Data Ready (`DR`) flag in `UART1_LSR` using non-blocking calls (`mos_ugetc_nb()`), which directly access the hardware registers.

3. **Silence-Based UART Flushing:**
   Because `fab-agon-emulator`'s internal UART emulation throttles RX delivery with a `receive_cooldown` timer (~347 µs between bytes at 115,200 baud), `flush_uart()` enforces a 50 ms silence threshold (`sysvar_time` delta) to guarantee all pending serial bytes are completely drained from host buffers.
