/*
 * esp8266.h - Common MOD-WIFI-ESP8266 utility functions for Agon family
 */

#ifndef _ESP8266_H
#define _ESP8266_H

#include <stdint.h>
#include <agon/mos.h>

#define BUFFER_SIZE 128

// MOS sysvar_time centisecond tick conversion (rounding up)
#define MS_TO_TICKS(ms) (((uint24_t)(ms) + 9) / 10)

// System timer ticks from MOS sysvars
uint24_t get_ticks(void);

// Formatted logging with dual output (MOS screen + eZ80 debug port 0x30)
void log_msg(const char *fmt, ...);

// Centisecond-accurate busy wait using MOS system timer
void wait_ms(uint24_t ms);

// Initialize UART1 to 115200 8-N-1 and attach MOS driver. Returns 1 on success, 0 on failure.
int init_uart1(void);

// Transmit string to UART1 via mos_uputc()
void send_esp(const char *cmd);

// Drain UART1 until a continuous 50ms silence interval occurs
void flush_uart(void);

// Response scanning core engine with timeout
int wait_for_response(const char *success_token, int exact_match,
                      char prompt_char, int check_closed, uint24_t timeout_ms);

// Helper: Scan UART1 for "OK" (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (-1)
static inline int wait_for_ok(uint24_t timeout_ms) {
    return wait_for_response("OK", 1, 0, 0, timeout_ms);
}

// Helper: Scan UART1 for TCP connection result:
// Returns 1 on success (CONNECT or ALREADY CONNECTED), 0 on failure, -1 on timeout
static inline int wait_for_connect(uint24_t timeout_ms) {
    return wait_for_response("CONNECT", 0, 0, 1, timeout_ms);
}

// Helper: Scan UART1 for '>' prompt from AT+CIPSEND (returns 1), "ERROR"/"FAIL" (returns 0), or timeout (-1)
static inline int wait_for_prompt(uint24_t timeout_ms) {
    return wait_for_response(NULL, 0, '>', 0, timeout_ms);
}

// Hayes escape sequence: 1.1s silence + "+++" + 1.1s silence
void escape_stream_mode(void);

// Recovers module to AT command mode: probes AT, escapes stream if needed, disables echo,
// closes active connections, and resets CIPMODE=0. Returns 1 on success, 0 on failure.
int restore_command_mode(void);

#endif // _ESP8266_H
