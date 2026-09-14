# openstream - Transparent TCP Streaming Utility for Agon Light 2

`openstream` is a native Agon Light 2 MOS utility that configures the **Olimex MOD-WIFI-ESP8266** module (on UART1) into transparent streaming mode (`CIPMODE=1`) and connects to a remote TCP server (such as a socket-enabled `TRS-NET.py` server for TRS-OS).

Upon receiving the streaming prompt (`>`), `openstream` cleanly closes the MOS UART1 driver and returns to the MOS command line, leaving the transparent TCP socket active and ready for the operating system loader (`OSboot.bin`).

---

## Features

* **Transparent Passthrough Mode (`CIPMODE=1`):** Switches the ESP8266 from ASCII AT command mode to raw bidirectional TCP streaming at 115,200 baud (8-N-1).
* **Self-Healing Stream Recovery:** Automatically detects if the module is stuck in an active streaming mode (e.g., following a CPU hardware reset or previous crash). Enforces 1.0s Hayes silence guard times around `+++`, tears down dangling sockets, and returns the modem to command mode before establishing the new stream.
* **Direct IP & Domain Addressing:** Accepts raw IPv4 addresses or standard DNS domain names, leveraging the ESP8266's internal LwIP DNS resolver over Wi-Fi.
* **Clean Handover Hygiene:** Immediately after the `>` prompt is confirmed, residual UART characters are flushed and `mos_uclose()` is called to detach the MOS interrupt handler. Zero stray characters or newlines are transmitted over UART1 upon exit.

---

## Building

Requires the [AgonDev SDK](https://github.com/Agon-Development-Community/agondev):

```bash
cd openstream
make clean
make
```

The resulting executable binary will be generated at `bin/openstream.bin`.

---

## Installation

Copy `bin/openstream.bin` to the `/mos/` directory of your Agon Light 2 microSD card. Placing it in `/mos/` ensures it is co-located with `OSboot.bin` and available from any working directory across all Quark MOS versions.

---

## Usage

```text
openstream <host_or_ip> <port>
```

### Examples

Connect to a remote `TRS-NET.py` server listening on TCP port 65432:

```text
MOS> openstream 192.168.1.50 65432
```

Connect using a domain name or local mDNS hostname (resolved over Wi-Fi by the ESP8266):

```text
MOS> openstream trsbox.local 65432
```

---

## Typical Workflow for TRS-OS

The only existing reference server for TRS-OS remote virtual disks is `TRS-NET.py`. Note that standard `TRS-NET.py` was originally written for direct serial cable (COM port) connections and must be separately modified to accept TCP socket connections. The modified server should wait silently for client initiation (`@ping\n`) before transmitting data.

```text
MOS> netman                  ; Connect to Wi-Fi (if not already auto-connected)
MOS> ping 192.168.1.50       ; Verify IP reachability to server host
MOS> openstream 192.168.1.50 65432
MOS> OSboot.bin              ; Boot TRS-OS (TRS-OS sends @ping over UART1 to initiate)
```

---

## Testing with Fab Agon Emulator

To test `openstream` locally without physical hardware, an ESP8266 coprocessor simulator and automated integration test suite are provided under [`tools/esp8266-emulator/`](../tools/esp8266-emulator/).

### Automated End-to-End Test

Run the full automated test suite (boots mock server, simulator, and emulator, runs `openstream`, tests streaming `@ping` $\to$ `@pong`, and restores SD card configuration):

```bash
cd ../tools/esp8266-emulator
./test_integration.py
```

See [`tools/esp8266-emulator/README.md`](../tools/esp8266-emulator/README.md) for full documentation on manual interactive testing and emulator configuration.
