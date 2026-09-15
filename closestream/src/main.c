/*
 * closestream - Close transparent TCP stream on MOD-WIFI-ESP8266 for Agon Light 2
 *
 * Usage: closestream
 *
 * Escapes transparent transmission mode (via Hayes '+++' escape sequence),
 * terminates active TCP connections (AT+CIPCLOSE), and resets the ESP8266
 * back to standard command mode (CIPMODE=0).
 */

#include "esp8266.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(void) {
    log_msg("Usage: closestream\n"
            "Closes active transparent stream on UART1 and returns ESP8266 to command mode.\n");
}

int main(int argc, char *argv[]) {
    if (argc > 1) {
        if (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "/?") == 0) {
            usage();
            return 0;
        }
        usage();
        return 1;
    }

    if (!init_uart1()) {
        log_msg("Error: Failed to open UART1 (interface locked).\n");
        return 1;
    }

    log_msg("Closing stream and restoring ESP8266 command mode...\n");
    if (!restore_command_mode()) {
        flush_uart();
        mos_uclose();
        log_msg("Error: Failed to restore ESP8266 to command mode.\n");
        return 1;
    }

    flush_uart();
    mos_uclose();

    log_msg("Stream closed. ESP8266 in command mode.\n");
    return 0;
}
