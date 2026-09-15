/*
 * esp8266.c - Common MOD-WIFI-ESP8266 utility functions for Agon family
 */

#include "esp8266.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <ctype.h>

static volatile uint8_t *sysvars = NULL;

uint24_t get_ticks(void) {
    if (sysvars == NULL) {
        sysvars = (volatile uint8_t *)mos_sysvars();
    }
    return *(volatile uint24_t *)(sysvars + 0x00);
}

// Writes character directly to eZ80 debug port 0x30 (echoed to host stdout by emulator)
void debug_putc(char c) {
    __asm__ volatile (
        "out0 (0x30), a\n\t"
        :
        : "a" (c)
    );
}

static void debug_print(const char *s) {
    while (*s) {
        debug_putc(*s++);
    }
}

void log_msg(const char *fmt, ...) {
    char buf[BUFFER_SIZE];
    va_list args;

    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    printf("%s", buf);
    debug_print(buf);
}

void wait_ms(uint24_t ms) {
    uint24_t ticks = MS_TO_TICKS(ms);
    uint24_t start = get_ticks();
    while ((uint24_t)(get_ticks() - start) < ticks) {
        // busy wait on system timer
    }
}

int init_uart1(void) {
    if (sysvars == NULL) {
        sysvars = (volatile uint8_t *)mos_sysvars();
    }

    UART settings;
    settings.baudRate = 115200;
    settings.dataBits = 8;
    settings.stopBits = 1;
    settings.parity = 0;
    settings.flowcontrol = 0;
    settings.eir = 0;

    return (mos_uopen(&settings) == 0);
}

void send_esp(const char *cmd) {
    while (*cmd) {
        mos_uputc(*cmd++);
    }
}

void flush_uart(void) {
    uint24_t start = get_ticks();
    while ((uint24_t)(get_ticks() - start) < MS_TO_TICKS(50)) {
        if (mos_ugetc_nb() >= 0) {
            start = get_ticks();
        }
    }
}

int wait_for_response(const char *success_token, int exact_match,
                      char prompt_char, int check_closed, uint24_t timeout_ms) {
    uint24_t timeout_ticks = MS_TO_TICKS(timeout_ms);
    uint24_t start_tick = get_ticks();
    char line[BUFFER_SIZE];
    uint8_t len = 0;

    while ((uint24_t)(get_ticks() - start_tick) < timeout_ticks) {
        int c = mos_ugetc_nb();
        if (c < 0) {
            continue;
        }

        // Check for immediate un-delimited prompt character (e.g. '>')
        if (prompt_char && c == prompt_char) {
            return 1;
        }

        switch (c) {
        case '\r':
            break;

        case '\n':
            if (len == 0) {
                break;
            }
            line[len] = '\0';
            len = 0;

            // Check failure conditions first
            if (strstr(line, "FAIL") != NULL || strstr(line, "ERROR") != NULL) {
                return 0;
            }
            if (check_closed && strstr(line, "CLOSED") != NULL) {
                return 0;
            }

            // Check success condition
            if (success_token) {
                if (exact_match ? (strcmp(line, success_token) == 0)
                                : (strstr(line, success_token) != NULL)) {
                    return 1;
                }
            }
            break;

        default:
            if (len < (BUFFER_SIZE - 1)) {
                line[len++] = (char)toupper(c);
            }
            break;
        }
    }
    return -1; // timeout
}

void escape_stream_mode(void) {
    // 1.25s pre-guard silence (125 centiseconds)
    wait_ms(1250);
    flush_uart();
    // Raw +++ escape string without CRLF
    send_esp("+++");
    // 1.25s post-guard silence (125 centiseconds)
    wait_ms(1250);
    flush_uart();
}

int restore_command_mode(void) {
    flush_uart();

    // 1. Probe if module is in AT command mode
    send_esp("AT\r\n");
    if (wait_for_ok(500) != 1) {
        log_msg("Notice: Module not responding. Attempting stream escape...\n");
        escape_stream_mode();
        send_esp("AT\r\n");
        if (wait_for_ok(1500) != 1) {
            log_msg("Error: ESP8266 module not responding on UART1 (115200 baud).\n");
            return 0;
        }
        log_msg("Notice: Recovered module to command mode.\n");
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
        log_msg("Error: Failed to reset CIPMODE=0.\n");
        return 0;
    }
    flush_uart();

    return 1;
}
