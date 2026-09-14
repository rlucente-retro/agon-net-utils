# MOD-WIFI-ESP8266 Simulator for Fab Agon Emulator

The [Fab Agon Emulator](https://github.com/tomm/fab-agon-emulator) emulates the eZ80 CPU and the ESP32 VDP, but does **not** include an internal virtual ESP8266 network coprocessor. Instead, it exposes a host serial bridge option:

```bash
fab-agon-emulator --uart1-device <serial_device> --uart1-baud 115200
```

This toolkit provides a complete virtual ESP8266 network coprocessor environment that connects to `fab-agon-emulator` via a Unix pseudo-terminal (PTY), enabling full local testing of `openstream`, network utilities, and TRS-OS without physical hardware.

---

## Included Tools

| File | Role | Description |
| :--- | :--- | :--- |
| [`esp8266_sim.py`](esp8266_sim.py) | **Coprocessor Simulator** | Creates a virtual serial PTY, implements the Espressif ESP-AT v1.7.x firmware command set, manages transparent streaming mode (`CIPMODE=1`), proxies raw data over real TCP sockets, and detects Hayes `+++` escape sequences. |
| [`mock_server.py`](mock_server.py) | **Test TCP Server** | Lightweight test server that listens on port 65432, remaining completely silent until the client sends `@ping\n`, and responds with `@pong\n`. |
| [`run_emulator.sh`](run_emulator.sh) | **All-in-One Launcher** | Starts `esp8266_sim.py` and automatically launches `fab-agon-emulator` linked to the simulated PTY. |

---

## Architecture

```
+------------------------------------+
|         Fab Agon Emulator          |
|  (eZ80 UART1: openstream.bin/OS)   |
+-----------------+------------------+
                  |
         PTY: /dev/ttys00X (115,200 8-N-1)
                  |
                  v
+-----------------+------------------+
|          esp8266_sim.py            |
|  - ESP-AT v1.7.4.0 command engine  |
|  - Transparent Mode (CIPMODE=1)    |
|  - Hayes '+++' escape guard timers |
+-----------------+------------------+
                  |
           Real TCP Socket
                  |
                  v
+-----------------+------------------+
|     Remote TCP Server Host         |
|  (mock_server.py or TRS-NET.py)    |
+------------------------------------+
```

---

## Quickstart: End-to-End Testing

### 1. Copy `openstream.bin` to the Emulator SD Card

Ensure your compiled `openstream.bin` is placed in the emulator's `sdcard/mos/` or `sdcard/bin/` folder:

```bash
cp /Users/richardlucente/development/git/agon-net-utils/openstream/bin/openstream.bin \
   /Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/sdcard/mos/
```

### 2. Start the Mock Server (Terminal 1)

```bash
cd /Users/richardlucente/development/git/agon-net-utils/tools/esp8266-emulator
./mock_server.py --port 65432
```

### 3. Launch the Simulator & Emulator (Terminal 2)

```bash
cd /Users/richardlucente/development/git/agon-net-utils/tools/esp8266-emulator
./run_emulator.sh
```

### 4. Execute `openstream` inside Agon MOS

In the Fab Agon Emulator window, at the MOS prompt:

```text
MOS> openstream 127.0.0.1 65432
```

You will observe:
1. `esp8266_sim.py` handling `AT`, `ATE0`, `AT+CIPMUX=0`, `AT+CIPMODE=1`, and `AT+CIPSTART`.
2. A successful TCP connection logged in `mock_server.py`.
3. `openstream` confirming:
   ```text
   Streaming mode active on UART1 (115200 8-N-1).
   Link established. Ready for TRS-OS.
   ```
4. Handover to `OSboot.bin` or testing Hayes escape sequences (`+++`) via `closestream`.
