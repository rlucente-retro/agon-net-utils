# agon-net-utils

Network utilities for the **Olimex Agon Light 2** (Zilog eZ80F92) running Quark MOS, specifically supporting network coprocessor workflows with the **Olimex MOD-WIFI-ESP8266** module on UART1.

## Utilities

| Directory | Binary | Description |
| :--- | :--- | :--- |
| [`openstream/`](openstream/) | `openstream.bin` | Connects to a remote TCP host and puts the ESP8266 into transparent streaming mode (`CIPMODE=1`), preserving the link for subsequent OS bootloaders (e.g. `OSboot.bin` for TRS-OS). |

## Building

Each utility directory contains its own `Makefile` using the [AgonDev SDK](https://github.com/Agon-Development-Community/agondev). 

To build:

```bash
cd openstream
make
```
