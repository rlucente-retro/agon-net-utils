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

#include "esp8266.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int usage(void) {
    log_msg("Usage: openstream <host_or_ip> <port>\n"
            "  <host_or_ip>  Remote server hostname or IPv4 address\n"
            "  <port>        TCP port number (1-65535)\n"
            "Example: openstream 192.168.1.50 65432\n"
            "         openstream server.local 65432\n");
    return 1;
}

// Parses and validates TCP port number (1-65535). Returns 0 on invalid input.
static uint16_t parse_port(const char *s) {
    if (*s == '\0') {
        return 0;
    }
    uint24_t port = 0;
    while (*s) {
        if (*s < '0' || *s > '9') {
            return 0;
        }
        port = port * 10 + (uint24_t)(*s++ - '0');
        if (port > 65535) {
            return 0;
        }
    }
    return (uint16_t)port;
}

static int prepare_esp(void) {
    if (!restore_command_mode()) {
        return 0;
    }

    // Configure single-connection mode (required for transparent streaming)
    send_esp("AT+CIPMUX=0\r\n");
    if (wait_for_ok(1000) != 1) {
        log_msg("Error: Failed to set single-connection mode (CIPMUX=0).\n");
        return 0;
    }
    flush_uart();

    // Enable transparent transmission mode
    send_esp("AT+CIPMODE=1\r\n");
    if (wait_for_ok(1000) != 1) {
        log_msg("Error: Failed to enable transparent mode (CIPMODE=1).\n");
        return 0;
    }
    flush_uart();

    return 1;
}

int main(int argc, char *argv[]) {
    uint16_t port;
    if (argc < 3 || (port = parse_port(argv[2])) == 0) {
        return usage();
    }

    char host[BUFFER_SIZE];
    strncpy(host, argv[1], sizeof(host) - 1);
    host[sizeof(host) - 1] = '\0';

    if (!init_uart1()) {
        log_msg("Error: Failed to open UART1 (interface locked).\n");
        return 1;
    }

    if (!prepare_esp()) {
        flush_uart();
        mos_uclose();
        return 1;
    }

    char cmd[BUFFER_SIZE];
    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%u\r\n", host, port);
    log_msg("Connecting to %s:%u...\n", host, port);
    send_esp(cmd);

    int conn_res = wait_for_connect(10000);
    if (conn_res <= 0) {
        log_msg("Error: Connection to %s:%u failed.\n", host, port);
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
        log_msg("Error: Failed to enter transparent streaming mode (no '>' prompt).\n");
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

    log_msg("Streaming mode active on UART1 (115200 8-N-1).\n");
    log_msg("Link established. Ready for TRS-OS.\n");
    return 0;
}
