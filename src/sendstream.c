/*
 * sendstream - Send a string over active transparent TCP stream on UART1
 *
 * Usage: sendstream <message>
 *
 * Transmits <message> over UART1 to remote TCP host and prints any response
 * received within the timeout period. Leaves the stream open upon exit.
 */

#include "esp8266.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define INITIAL_TIMEOUT_MS   2000   // Max wait for first response byte (2.0s)
#define INTERBYTE_TIMEOUT_MS  200   // Max silence after last received byte (200ms)
#define MAX_PAYLOAD_SIZE      256

static int usage(void) {
    log_msg("Usage: sendstream <message>\n"
            "  <message>  String to send over active stream\n"
            "Example: sendstream @ping\n");
    return 1;
}

// Unescapes \n, \r, \t, and \\ sequences
static void unescape_string(char *dst, const char *src, size_t max_len) {
    size_t d = 0;
    while (*src && d < max_len - 1) {
        if (*src == '\\' && *(src + 1)) {
            src++;
            switch (*src) {
                case 'n': dst[d++] = '\n'; break;
                case 'r': dst[d++] = '\r'; break;
                case 't': dst[d++] = '\t'; break;
                case '\\': dst[d++] = '\\'; break;
                default:
                    dst[d++] = '\\';
                    if (d < max_len - 1) {
                        dst[d++] = *src;
                    }
                    break;
            }
            src++;
        } else {
            dst[d++] = *src++;
        }
    }
    dst[d] = '\0';
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        return usage();
    }

    // Concatenate all arguments into a single buffer separated by spaces
    char raw_buf[MAX_PAYLOAD_SIZE];
    raw_buf[0] = '\0';
    for (int i = 1; i < argc; i++) {
        if (i > 1) {
            strncat(raw_buf, " ", sizeof(raw_buf) - strlen(raw_buf) - 1);
        }
        strncat(raw_buf, argv[i], sizeof(raw_buf) - strlen(raw_buf) - 1);
    }

    char payload[MAX_PAYLOAD_SIZE + 2];
    unescape_string(payload, raw_buf, sizeof(payload) - 2);

    // Append newline if payload does not already end in \n or \r
    size_t len = strlen(payload);
    if (len == 0 || (payload[len - 1] != '\n' && payload[len - 1] != '\r')) {
        payload[len++] = '\n';
        payload[len] = '\0';
    }

    if (!init_uart1()) {
        log_msg("Error: Failed to open UART1 (interface locked).\n");
        return 1;
    }

    // Drain any stale bytes before transmission
    flush_uart();

    // Transmit payload
    send_esp(payload);

    // Wait for response and print received characters
    uint24_t timeout_ticks = MS_TO_TICKS(INITIAL_TIMEOUT_MS);
    uint24_t start_tick = get_ticks();
    uint24_t bytes_received = 0;
    char last_char = 0;

    while ((uint24_t)(get_ticks() - start_tick) < timeout_ticks) {
        int c = mos_ugetc_nb();
        if (c >= 0) {
            bytes_received++;
            last_char = (char)c;
            putchar(last_char);
            debug_putc(last_char);

            // Once data starts arriving, switch to inter-byte timeout
            start_tick = get_ticks();
            timeout_ticks = MS_TO_TICKS(INTERBYTE_TIMEOUT_MS);
        }
    }

    if (bytes_received == 0) {
        log_msg("(No response received within %u ms)\n", INITIAL_TIMEOUT_MS);
    } else if (last_char != '\n') {
        putchar('\n');
        debug_putc('\n');
    }

    // Detach MOS UART interrupt handler so UART1 remains free
    mos_uclose();
    return (bytes_received > 0) ? 0 : 1;
}
