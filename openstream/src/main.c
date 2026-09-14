/*
 * openstream - Open transparent TCP stream on MOD-WIFI-ESP8266 for Agon Light 2
 *
 * Usage: openstream <host_or_ip> <port>
 *
 * Configures the ESP8266 on UART1 into transparent transmission mode (CIPMODE=1)
 * and connects to a remote TCP server (e.g. a socket-modified TRS-NET.py for TRS-OS).
 * Upon receiving the '>' prompt, exits cleanly to MOS, leaving the transparent
 * link ready for the operating system loader (e.g. OSboot.bin).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <agon/mos.h>

#define BUFFER_SIZE 128

// MOS sysvar_time is at offset 0x00 and ticks in centiseconds (10ms intervals)
// Note: sysvar_time is incremented by 2 every VBLANK (100 centiseconds per second).
static volatile uint8_t *sysvars = NULL;

static inline uint24_t get_ticks(void) {
    return *(volatile uint24_t *)(sysvars + 0x00);
}

// Convert milliseconds to MOS centisecond ticks (rounding up)
#define MS_TO_TICKS(ms) (((uint24_t)(ms) + 9) / 10)

// Writes character directly to eZ80 debug port 0x30 (echoed to host stdout by emulator)
static void debug_putc(char c) {
    __asm__ volatile (
        "ld a, %0\n\t"
        "out0 (0x30), a\n\t"
        :
        : "r" (c)
        : "a"
    );
}

static void debug_print(const char *s) {
    while (*s) {
        debug_putc(*s++);
    }
}

#define LOG_MSG(...) do { \
    char _log_buf[BUFFER_SIZE]; \
    snprintf(_log_buf, sizeof(_log_buf), __VA_ARGS__); \
    printf("%s", _log_buf); \
    debug_print(_log_buf); \
} while(0)

static void wait_ms(uint24_t ms) {
    uint24_t ticks = MS_TO_TICKS(ms);
    uint24_t start = get_ticks();
    while ((uint24_t)(get_ticks() - start) < ticks) {
        // busy wait on system timer
    }
}

static void send_esp(const char *cmd) {
    while (*cmd) {
        mos_uputc(*cmd++);
        for (volatile int i = 0; i < 100; i++);
    }
}

// Drain UART1 until a continuous 50ms silence interval occurs
static void flush_uart(void) {
    uint24_t start = get_ticks();
    while ((uint24_t)(get_ticks() - start) < MS_TO_TICKS(50)) {
        if (mos_ugetc_nb() >= 0) {
            start = get_ticks();
        }
    }
}

// Scans UART1 for "OK" (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (returns -1)
static int wait_for_ok(uint24_t timeout_ms) {
    uint24_t timeout_ticks = MS_TO_TICKS(timeout_ms);
    uint24_t start_tick = get_ticks();
    char line[BUFFER_SIZE];
    uint8_t len = 0;

    while ((uint24_t)(get_ticks() - start_tick) < timeout_ticks) {
        int c = mos_ugetc_nb();
        if (c < 0) {
            continue;
        }

        if (c == '\r') {
            continue;
        }

        if (c == '\n') {
            if (len == 0) {
                continue;
            }
            line[len] = '\0';
            len = 0;

            if (strcmp(line, "OK") == 0) {
                return 1;
            }
            if (strstr(line, "ERROR") != NULL ||
                strstr(line, "FAIL") != NULL ||
                strstr(line, "Fail") != NULL) {
                return 0;
            }
            continue;
        }

        if (len < (BUFFER_SIZE - 1)) {
            line[len++] = (char)c;
        }
    }
    return -1; // timeout
}

// Scans UART1 for TCP connection result:
// Returns 1 on success (CONNECT or ALREADY CONNECTED)
// Returns 0 on failure (CONNECT FAIL, CLOSED, ERROR, DNS Fail)
// Returns -1 on timeout
static int wait_for_connect(uint24_t timeout_ms) {
    uint24_t timeout_ticks = MS_TO_TICKS(timeout_ms);
    uint24_t start_tick = get_ticks();
    char line[BUFFER_SIZE];
    uint8_t len = 0;

    while ((uint24_t)(get_ticks() - start_tick) < timeout_ticks) {
        int c = mos_ugetc_nb();
        if (c < 0) {
            continue;
        }

        if (c == '\r') {
            continue;
        }

        if (c == '\n') {
            if (len == 0) {
                continue;
            }
            line[len] = '\0';
            len = 0;

            // Check failure conditions FIRST to avoid substring false positives on "CONNECT FAIL"
            if (strstr(line, "FAIL") != NULL || strstr(line, "Fail") != NULL) {
                return 0;
            }
            if (strstr(line, "ERROR") != NULL || strstr(line, "CLOSED") != NULL) {
                return 0;
            }

            // Check success conditions
            if (strstr(line, "CONNECT") != NULL || strstr(line, "ALREADY CONNECTED") != NULL) {
                return 1;
            }
            continue;
        }

        if (len < (BUFFER_SIZE - 1)) {
            line[len++] = (char)c;
        }
    }
    return -1; // timeout
}

// Scans UART1 for '>' prompt from AT+CIPSEND (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (returns -1)
static int wait_for_prompt(uint24_t timeout_ms) {
    uint24_t timeout_ticks = MS_TO_TICKS(timeout_ms);
    uint24_t start_tick = get_ticks();
    char line[BUFFER_SIZE];
    uint8_t len = 0;

    while ((uint24_t)(get_ticks() - start_tick) < timeout_ticks) {
        int c = mos_ugetc_nb();
        if (c < 0) {
            continue;
        }

        // The transparent prompt '>' is emitted without a trailing newline
        if (c == '>') {
            return 1;
        }

        if (c == '\r') {
            continue;
        }

        if (c == '\n') {
            if (len == 0) {
                continue;
            }
            line[len] = '\0';
            len = 0;

            if (strstr(line, "ERROR") != NULL ||
                strstr(line, "FAIL") != NULL ||
                strstr(line, "Fail") != NULL) {
                return 0;
            }
            continue;
        }

        if (len < (BUFFER_SIZE - 1)) {
            line[len++] = (char)c;
        }
    }
    return -1; // timeout
}

static void escape_stream_mode(void) {
    // 1.1s pre-guard silence (110 centiseconds)
    wait_ms(1100);
    flush_uart();
    // Raw +++ escape string without CRLF
    send_esp("+++");
    // 1.1s post-guard silence (110 centiseconds)
    wait_ms(1100);
    flush_uart();
}

static int prepare_esp(void) {
    flush_uart();

    // 1. Probe if module is in AT command mode
    send_esp("AT\r\n");
    if (wait_for_ok(500) != 1) {
        LOG_MSG("Notice: Module not responding. Attempting stream escape...\n");
        escape_stream_mode();
        send_esp("AT\r\n");
        if (wait_for_ok(1500) != 1) {
            LOG_MSG("Error: ESP8266 module not responding on UART1 (115200 baud).\n");
            return 0;
        }
        LOG_MSG("Notice: Recovered module to command mode.\n");
    }

    // 2. Disable local character echo
    send_esp("ATE0\r\n");
    wait_for_ok(500);
    flush_uart();

    // 3. Close any active connection to prevent "link is builded" error on CIPMUX change
    send_esp("AT+CIPCLOSE\r\n");
    wait_for_ok(500); // Discard response (OK or ERROR)
    flush_uart();

    // 4. Reset to non-transparent mode first
    send_esp("AT+CIPMODE=0\r\n");
    if (wait_for_ok(500) != 1) {
        LOG_MSG("Error: Failed to reset CIPMODE=0.\n");
        return 0;
    }
    flush_uart();

    // 5. Configure single-connection mode (required for transparent streaming)
    send_esp("AT+CIPMUX=0\r\n");
    if (wait_for_ok(1000) != 1) {
        LOG_MSG("Error: Failed to set single-connection mode (CIPMUX=0).\n");
        return 0;
    }
    flush_uart();

    // 6. Enable transparent transmission mode
    send_esp("AT+CIPMODE=1\r\n");
    if (wait_for_ok(1000) != 1) {
        LOG_MSG("Error: Failed to enable transparent mode (CIPMODE=1).\n");
        return 0;
    }
    flush_uart();

    return 1;
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        LOG_MSG("Usage: openstream <host_or_ip> <port>\n");
        LOG_MSG("Example: openstream 192.168.1.50 65432\n");
        LOG_MSG("         openstream server.local 65432\n");
        return 1;
    }

    char host[BUFFER_SIZE];
    strncpy(host, argv[1], sizeof(host) - 1);
    host[sizeof(host) - 1] = '\0';

    int port = atoi(argv[2]);
    if (port <= 0 || port > 65535) {
        LOG_MSG("Error: Invalid port '%s' (must be 1-65535).\n", argv[2]);
        return 1;
    }

    sysvars = (volatile uint8_t *)mos_sysvars();

    UART settings;
    settings.baudRate = 115200;
    settings.dataBits = 8;
    settings.stopBits = 1;
    settings.parity = 0;
    settings.flowcontrol = 0;
    settings.eir = 0;

    if (mos_uopen(&settings) != 0) {
        LOG_MSG("Error: Failed to open UART1 (interface locked).\n");
        return 1;
    }

    if (!prepare_esp()) {
        flush_uart();
        mos_uclose();
        return 1;
    }

    char cmd[BUFFER_SIZE];
    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%d\r\n", host, port);
    LOG_MSG("Connecting to %s:%d...\n", host, port);
    send_esp(cmd);

    int conn_res = wait_for_connect(10000);
    if (conn_res <= 0) {
        LOG_MSG("Error: Connection to %s:%d failed.\n", host, port);
        send_esp("AT+CIPCLOSE\r\n");
        wait_for_ok(500);
        send_esp("AT+CIPMODE=0\r\n");
        wait_for_ok(500);
        flush_uart();
        mos_uclose();
        return 1;
    }

    flush_uart();

    // Enter transparent transmission mode
    send_esp("AT+CIPSEND\r\n");
    if (wait_for_prompt(3000) != 1) {
        LOG_MSG("Error: Failed to enter transparent streaming mode (no '>' prompt).\n");
        escape_stream_mode();
        send_esp("AT+CIPCLOSE\r\n");
        wait_for_ok(500);
        send_esp("AT+CIPMODE=0\r\n");
        wait_for_ok(500);
        flush_uart();
        mos_uclose();
        return 1;
    }

    // Wait briefly (50ms) and flush any residual prompt characters
    wait_ms(50);
    flush_uart();

    // Detach MOS interrupt handler from UART1 so MOS does not capture stream data
    mos_uclose();

    LOG_MSG("Streaming mode active on UART1 (115200 8-N-1).\n");
    LOG_MSG("Link established. Ready for TRS-OS.\n");
    return 0;
}
