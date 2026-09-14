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
| [`test_integration.py`](test_integration.py) | **Automated Test Runner** | All-in-one test script that boots `mock_server.py`, `esp8266_sim.py`, and `fab-agon-emulator`, verifies AT negotiation and TCP streaming, tests bidirectional payloads (`@ping` -> `@pong`), and restores SD card configuration. |
| [`esp8266_sim.py`](esp8266_sim.py) | **Coprocessor Simulator** | Creates a virtual serial PTY, implements the Espressif ESP-AT v1.7.x firmware command set, manages transparent streaming mode (`CIPMODE=1`), proxies raw data over real TCP sockets, and detects Hayes `+++` escape sequences. |
| [`mock_server.py`](mock_server.py) | **Test TCP Server** | Lightweight test server that listens on port 65432, remaining completely silent until the client sends `@ping\n`, and responds with `@pong\n`. |
| [`run_emulator.sh`](run_emulator.sh) | **Interactive Launcher** | Starts `esp8266_sim.py` and automatically launches `fab-agon-emulator` linked to the simulated PTY. |

---

## Architecture

```
+-------------------------------------------------+
|               Fab Agon Emulator                 |
|       (eZ80 UART1: openstream.bin / OS)         |
+------------------------+------------------------+
                         |
        Virtual PTY: /dev/ttys00X (or /tmp/agon-uart1)
                         |
                         v
+------------------------+------------------------+
|                 esp8266_sim.py                  |
|  - Espressif ESP-AT v1.7.4.0 command engine     |
|  - Transparent streaming proxy (CIPMODE=1)      |
|  - Hayes '+++' escape detector (1.0s guards)    |
+------------------------+------------------------+
                         |
                 Host TCP Socket
                         |
                         v
+------------------------+------------------------+
|             Remote Server Host                  |
|        (mock_server.py or TRS-NET.py)           |
+-------------------------------------------------+
```

---

## Method 1: Automated Integration Test (Recommended)

An end-to-end automated test script is provided in [`test_integration.py`](test_integration.py). It handles the full lifecycle automatically:

1. Backs up the emulator's `sdcard/autoexec.txt`.
2. Installs the latest `openstream.bin` to `sdcard/mos/openstream.bin`.
3. Configures `autoexec.txt` to invoke `openstream.bin 127.0.0.1 65432`.
4. Starts `mock_server.py` in the background.
5. Starts `esp8266_sim.py` with PTY symlink `/tmp/agon-uart1`.
6. Launches `fab-agon-emulator` connected to the virtual PTY.
7. Verifies the AT command sequence (`AT`, `ATE0`, `AT+CIPCLOSE`, `AT+CIPMODE=0`, `AT+CIPMUX=0`, `AT+CIPMODE=1`, `AT+CIPSTART`, `AT+CIPSEND`).
8. Verifies socket connection on `mock_server.py`.
9. Transmits `@ping\n` through the transparent stream and validates `@pong\n` response.
10. Shuts down processes and restores the original `autoexec.txt`.

### Running the Automated Test

```bash
cd tools/esp8266-emulator
./test_integration.py
```

Optional arguments:
* `--emulator /path/to/fab-agon-emulator`: Specify custom emulator binary path (defaults to standard repo location or PATH).
* `--port 65432`: Customize the mock TCP port.
* `--timeout 10.0`: Customize the handshake timeout.

### Expected Output

```text
============================================================
  openstream & ESP8266 Simulator Integration Test
============================================================
Emulator Binary: /Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator
TCP Port:        65432
SDCard Dir:      /Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/sdcard
------------------------------------------------------------
[*] Starting Mock TCP Server...
[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...
[*] Launching Fab Agon Emulator (--uart1-baud 0)...
[*] Waiting for openstream AT handshake and TCP connection...
[*] Testing bidirectional stream payload (@ping -> @pong)...
[+] Successfully received reply over UART1 stream: b'pong\n'
[*] Terminating emulator and test services...
[+] Restored original autoexec.txt.
------------------------------------------------------------
                    TEST SUMMARY
------------------------------------------------------------
[*] AT Command Negotiation:    PASS
[*] TCP Socket Connection:      PASS
[*] MOS openstream Execution:   PASS
[*] Transparent Data Streaming: PASS
============================================================
[+] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!
```

---

## Method 2: Manual Interactive Testing

For interactive testing in the emulator window with manual MOS commands:

### Step 1: Build & Copy `openstream.bin`

Compile `openstream.bin` and copy it to the emulator's `sdcard/mos/` folder:

```bash
cd /Users/richardlucente/development/git/agon-net-utils/openstream
make clean && make
cp bin/openstream.bin /Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/sdcard/mos/
```

### Step 2: Start Mock Server (Terminal 1)

```bash
cd /Users/richardlucente/development/git/agon-net-utils/tools/esp8266-emulator
./mock_server.py --port 65432
```

The server will print:
```text
[*] Mock TCP server listening on 0.0.0.0:65432
[*] Waiting for client connection (e.g. from openstream / TRS-OS)...
```

### Step 3: Launch Simulator & Emulator (Terminal 2)

```bash
cd /Users/richardlucente/development/git/agon-net-utils/tools/esp8266-emulator
./run_emulator.sh
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

---

## Technical Details & Emulator Specifics

1. **eZ80 Debug Port 0x30 Mirroring:**
   [`fab-agon-emulator`](https://github.com/tomm/fab-agon-emulator) echoes any byte written to eZ80 I/O port `0x30` (`out0 (0x30), a`) straight to host stdout. `openstream` uses this feature to mirror console messages directly to the host terminal running the emulator.

2. **UART1 Polling vs Interrupts:**
   The emulator implements eZ80 UART1 register I/O (`UART1_RBR`, `UART1_THR`, `UART1_LSR`, `UART1_IER`), but does **not** generate the eZ80 UART1 hardware receive interrupt (`vector 0x1A`). As a result, software running in the emulator must poll the UART1 Data Ready (`DR`) flag in `UART1_LSR` using non-blocking calls (`mos_ugetc_nb()`), which directly access the hardware registers.

3. **Silence-Based UART Flushing:**
   Because `fab-agon-emulator`'s internal UART emulation throttles RX delivery with a `receive_cooldown` timer (~347 µs between bytes at 115,200 baud), `flush_uart()` enforces a 50 ms silence threshold (`sysvar_time` delta) to guarantee all pending serial bytes are completely drained from host buffers.
