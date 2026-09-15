# closestream - Close Transparent TCP Stream for Agon Light 2

`closestream` is a native Agon Light 2 MOS utility that tears down active transparent streaming links on the **Olimex MOD-WIFI-ESP8266** module (UART1) and returns the modem to standard AT command mode (`CIPMODE=0`).

It is the counterpart to [`openstream`](../openstream/).

---

## Features

* **Stream Escape (`+++`):** Safely escapes transparent streaming mode by enforcing 1.1s pre- and post-guard silence intervals around the Hayes `+++` escape code.
* **Connection Teardown:** Closes any dangling TCP connections (`AT+CIPCLOSE`).
* **Mode Reset:** Disables transparent mode (`AT+CIPMODE=0`) and disables local echo (`ATE0`), leaving the ESP8266 ready for normal AT command usage.
* **Clean Handover:** Flushes residual UART characters and closes the MOS UART1 driver (`mos_uclose()`) upon completion.

---

## Building

Requires the [AgonDev SDK](https://github.com/Agon-Development-Community/agondev):

```bash
cd closestream
make clean
make
```

The resulting executable binary will be generated at `bin/closestream.bin`.

---

## Installation

Copy `bin/closestream.bin` to the `/mos/` directory of your Agon Light 2 microSD card. Placing it in `/mos/` ensures it is available from any working directory across all Quark MOS versions.

---

## Usage

```text
closestream
```

### Examples

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
