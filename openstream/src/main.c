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
#include <ctype.h>
#include <agon/mos.h>

#define BUFFER_SIZE 128

static volatile uint8_t *sysvars = NULL;

static inline uint32_t get_ticks_ms(void) {
    return *(volatile uint32_t *)(sysvars + 0x00);
}

static void wait_ms(uint32_t ms) {
    uint32_t start = get_ticks_ms();
    while ((get_ticks_ms() - start) < ms) {
        // busy wait on 1ms system timer
    }
}

static void send_esp(const char *cmd) {
    while (*cmd) {
        mos_uputc(*cmd++);
        for (volatile int i = 0; i < 100; i++);
    }
}

static void flush_uart(void) {
    while (mos_ugetc_nb() != -1);
}


// Scans UART1 for "OK" (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (returns -1)
static int wait_for_ok(uint32_t timeout_ms) {
    uint32_t start_ms = get_ticks_ms();
    int s_ok = 0, s_err = 0, s_fail = 0;

    while ((get_ticks_ms() - start_ms) < timeout_ms) {
        int c = mos_ugetc_nb();
        if (c >= 0) {
            int u = toupper(c);

            if (u == "OK"[s_ok]) {
                s_ok++;
                if (s_ok == 2) return 1;
            } else {
                s_ok = (u == 'O') ? 1 : 0;
            }

            if (u == "ERROR"[s_err]) {
                s_err++;
                if (s_err == 5) return 0;
            } else {
                s_err = (u == 'E') ? 1 : 0;
            }

            if (u == "FAIL"[s_fail]) {
                s_fail++;
                if (s_fail == 4) return 0;
            } else {
                s_fail = (u == 'F') ? 1 : 0;
            }
        }
        for (volatile int i = 0; i < 30; i++);
    }
    return -1;
}

// Scans UART1 for "CONNECT" (returns 1), "CLOSED"/"FAIL"/"ERROR" (returns 0), or timeout (returns -1)
static int wait_for_connect(uint32_t timeout_ms) {
    uint32_t start_ms = get_ticks_ms();
    int s_conn = 0, s_clsd = 0, s_err = 0, s_fail = 0;

    while ((get_ticks_ms() - start_ms) < timeout_ms) {
        int c = mos_ugetc_nb();
        if (c >= 0) {
            int u = toupper(c);

            if (u == "CONNECT"[s_conn]) {
                s_conn++;
                if (s_conn == 7) return 1;
            } else {
                s_conn = (u == 'C') ? 1 : 0;
            }

            if (u == "CLOSED"[s_clsd]) {
                s_clsd++;
                if (s_clsd == 6) return 0;
            } else {
                s_clsd = (u == 'C') ? 1 : 0;
            }

            if (u == "ERROR"[s_err]) {
                s_err++;
                if (s_err == 5) return 0;
            } else {
                s_err = (u == 'E') ? 1 : 0;
            }

            if (u == "FAIL"[s_fail]) {
                s_fail++;
                if (s_fail == 4) return 0;
            } else {
                s_fail = (u == 'F') ? 1 : 0;
            }
        }
        for (volatile int i = 0; i < 30; i++);
    }
    return -1;
}

// Scans UART1 for '>' prompt (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (returns -1)
static int wait_for_prompt(uint32_t timeout_ms) {
    uint32_t start_ms = get_ticks_ms();
    int s_err = 0, s_fail = 0;

    while ((get_ticks_ms() - start_ms) < timeout_ms) {
        int c = mos_ugetc_nb();
        if (c >= 0) {
            if (c == '>') {
                return 1;
            }
            int u = toupper(c);
            if (u == "ERROR"[s_err]) {
                s_err++;
                if (s_err == 5) return 0;
            } else {
                s_err = (u == 'E') ? 1 : 0;
            }

            if (u == "FAIL"[s_fail]) {
                s_fail++;
                if (s_fail == 4) return 0;
            } else {
                s_fail = (u == 'F') ? 1 : 0;
            }
        }
        for (volatile int i = 0; i < 30; i++);
    }
    return -1;
}

static void escape_stream_mode(void) {
    wait_ms(1100);
    flush_uart();
    send_esp("+++");
    wait_ms(1100);
    flush_uart();
}

static int prepare_esp(void) {
    flush_uart();

    // Check if module is already in AT command mode
    send_esp("AT\r\n");
    if (wait_for_ok(500) != 1) {
        printf("Notice: Module not responding to AT. Attempting stream escape...\n");
        escape_stream_mode();
        send_esp("AT\r\n");
        if (wait_for_ok(1500) != 1) {
            printf("Error: ESP8266 module not responding on UART1 (115200 baud).\n");
            return 0;
        }
        printf("Notice: Recovered module from active stream mode.\n");
        send_esp("AT+CIPCLOSE\r\n");
        wait_ms(200);
        flush_uart();
        send_esp("AT+CIPMODE=0\r\n");
        wait_ms(100);
        flush_uart();
    }

    // Disable local echo
    send_esp("ATE0\r\n");
    wait_for_ok(500);
    flush_uart();

    // Single connection mode
    send_esp("AT+CIPMUX=0\r\n");
    if (wait_for_ok(1000) != 1) {
        printf("Error: Failed to set single-connection mode (CIPMUX=0).\n");
        return 0;
    }
    flush_uart();

    // Enable transparent transmission mode
    send_esp("AT+CIPMODE=1\r\n");
    if (wait_for_ok(1000) != 1) {
        printf("Error: Failed to enable transparent mode (CIPMODE=1).\n");
        return 0;
    }
    flush_uart();

    return 1;
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        printf("Usage: openstream <host_or_ip> <port>\n");
        printf("Example: openstream 192.168.1.50 65432\n");
        printf("         openstream server.local 65432\n");
        return 1;
    }

    char host[BUFFER_SIZE];
    strncpy(host, argv[1], sizeof(host) - 1);
    host[sizeof(host) - 1] = '\0';

    int port = atoi(argv[2]);
    if (port <= 0 || port > 65535) {
        printf("Error: Invalid port '%s' (must be 1-65535).\n", argv[2]);
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
        printf("Error: Failed to open UART1 (interface locked).\n");
        return 1;
    }

    if (!prepare_esp()) {
        flush_uart();
        mos_uclose();
        return 1;
    }

    char cmd[BUFFER_SIZE];
    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%d\r\n", host, port);
    printf("Connecting to %s:%d...\n", host, port);
    send_esp(cmd);

    int conn_res = wait_for_connect(10000);
    if (conn_res <= 0) {
        printf("Error: Connection to %s:%d failed.\n", host, port);
        send_esp("AT+CIPCLOSE\r\n");
        wait_ms(100);
        send_esp("AT+CIPMODE=0\r\n");
        flush_uart();
        mos_uclose();
        return 1;
    }

    // Enter transparent transmission mode
    send_esp("AT+CIPSEND\r\n");
    if (wait_for_prompt(3000) != 1) {
        printf("Error: Failed to enter transparent streaming mode (no '>' prompt).\n");
        escape_stream_mode();
        send_esp("AT+CIPCLOSE\r\n");
        wait_ms(100);
        send_esp("AT+CIPMODE=0\r\n");
        flush_uart();
        mos_uclose();
        return 1;
    }

    // Wait briefly and flush any residual prompt characters
    wait_ms(50);
    flush_uart();

    // Close UART1 in MOS so MOS interrupt handler is detached
    mos_uclose();

    printf("Streaming mode active on UART1 (115200 8-N-1).\n");
    printf("Link established. Ready for TRS-OS.\n");
    return 0;
}
