# openstream - Transparent TCP Streaming Utility for Agon Light 2

`openstream` is a native Agon Light 2 MOS utility that configures the **Olimex MOD-WIFI-ESP8266** module (on UART1) into transparent streaming mode (`CIPMODE=1`) and connects to a remote TCP server (such as `TCP-NET.py` for TRS-OS).

Upon receiving the streaming prompt (`>`), `openstream` cleanly closes the MOS UART1 driver and returns to the MOS command line, leaving the transparent TCP socket active and ready for the operating system loader (`OSboot.bin`).

---

## Features

* **Transparent Passthrough Mode (`CIPMODE=1`):** Switches the ESP8266 from ASCII AT command mode to raw bidirectional TCP streaming at 115,200 baud (8-N-1).
* **Self-Healing Stream Recovery:** Automatically detects if the module is stuck in an active streaming mode (e.g., following a CPU hardware reset or previous crash). Enforces 1.0s Hayes silence guard times around `+++`, tears down dangling sockets, and returns the modem to command mode before establishing the new stream.
* **Local Host Resolution:** Resolves hostname aliases defined in `/Mos/hosts` (or `/mos/hosts`) in addition to raw IPv4 addresses and DNS domain names.
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

Copy `bin/openstream.bin` to your Agon Light 2 microSD card (typically in `/bin` or `/mos`).

---

## Usage

```text
openstream <host_or_ip> <port>
```

### Examples

Connect to a TRS-NET / TCP-NET server running on the local network:

```text
MOS> openstream 192.168.1.50 65432
```

Connect using a `/Mos/hosts` alias:

```text
MOS> openstream trsbox 65432
```

### Typical Workflow for TRS-OS

```text
MOS> netman                  ; Ensure Wi-Fi is connected
MOS> ping 192.168.1.50       ; Confirm server reachability
MOS> openstream 192.168.1.50 65432
MOS> OSboot.bin              ; Boot TRS-OS (TRS-OS sends @ping to initiate)
```
