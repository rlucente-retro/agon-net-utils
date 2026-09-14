#!/usr/bin/env python3
"""
MOD-WIFI-ESP8266 Coprocessor Simulator for Fab Agon Emulator

Emulates the Espressif ESP-AT v1.7.x firmware running on an Olimex MOD-WIFI-ESP8266
module connected to UART1 of the Olimex Agon Light 2.

Creates a virtual serial pseudo-terminal (PTY) that can be linked to:
    fab-agon-emulator --uart1-device <pty_path> --uart1-baud 115200

Features:
- Full AT command parser for standard Agon network utilities (netman, ping, openstream).
- Handles transparent streaming mode (AT+CIPMODE=1 & AT+CIPSEND -> '>').
- Bridges transparent UART1 stream directly to remote TCP server (e.g. TRS-NET.py).
- Implements strict Hayes '+++' escape sequence detection with 1.0s guard times.
- Detects socket disconnects and returns cleanly to command mode.
"""

import sys
import os
import pty
import tty
import termios
import select
import socket
import time
import argparse
import subprocess
import signal

MODE_COMMAND = 0
MODE_STREAM = 1

class ESP8266Simulator:
    def __init__(self, symlink=None, verbose=False, simulated_ip="192.168.1.100"):
        self.verbose = verbose
        self.simulated_ip = simulated_ip
        self.symlink = symlink
        self.mode = MODE_COMMAND

        # AT State
        self.echo = True
        self.cwmode = 1           # Station mode
        self.cipmux = 0           # Single connection mode
        self.cipmode = 0          # 0 = Normal mode, 1 = Transparent streaming
        self.tcp_sock = None
        self.tcp_host = None
        self.tcp_port = None

        # Command buffer
        self.cmd_buffer = bytearray()

        # Escape sequence detector for transparent mode
        self.last_char_time = 0.0
        self.escape_buf = bytearray()
        self.escape_candidate = False
        self.escape_candidate_time = 0.0

        # Create PTY
        self.master_fd, self.slave_fd = pty.openpty()
        self.slave_name = os.ttyname(self.slave_fd)

        # Set raw mode on PTY
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)

        # Create symlink if requested
        if self.symlink:
            try:
                if os.path.islink(self.symlink) or os.path.exists(self.symlink):
                    os.unlink(self.symlink)
                os.symlink(self.slave_name, self.symlink)
            except Exception as e:
                print(f"[!] Warning: Could not create symlink {self.symlink}: {e}")

    def log(self, msg):
        if self.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def write_pty(self, data: bytes):
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            self.log(f"PTY write error: {e}")

    def send_response(self, text: str):
        data = text.encode("ascii", errors="replace")
        self.write_pty(data)

    def handle_command(self, cmd_bytes: bytes):
        cmd = cmd_bytes.decode("ascii", errors="replace").strip()
        if not cmd:
            return

        self.log(f"AT CMD: '{cmd}'")
        u_cmd = cmd.upper()

        if u_cmd == "AT":
            self.send_response("\r\nOK\r\n")

        elif u_cmd == "ATE0":
            self.echo = False
            self.send_response("\r\nOK\r\n")

        elif u_cmd == "ATE1":
            self.echo = True
            self.send_response("\r\nOK\r\n")

        elif u_cmd.startswith("AT+GMR"):
            resp = (
                "\r\nAT version:1.7.4.0-sim\r\n"
                "SDK version:3.0.4\r\n"
                "compile time:Sep 14 2026 12:00:00\r\n"
                "Bin version(Wroom-02):1.7.4\r\n\r\nOK\r\n"
            )
            self.send_response(resp)

        elif u_cmd.startswith("AT+RST"):
            self.close_socket()
            self.mode = MODE_COMMAND
            self.cipmode = 0
            self.send_response("\r\nOK\r\nready\r\n")

        elif u_cmd.startswith("AT+CWMODE"):
            # e.g. AT+CWMODE=1 or AT+CWMODE_DEF=1 or AT+CWMODE?
            if "?" in u_cmd:
                self.send_response(f"\r\n+CWMODE:{self.cwmode}\r\n\r\nOK\r\n")
            else:
                try:
                    val = int(cmd.split("=")[1].strip())
                    self.cwmode = val
                    self.send_response("\r\nOK\r\n")
                except Exception:
                    self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CWJAP"):
            # e.g. AT+CWJAP_DEF="SSID","PASS" or AT+CWJAP?
            if "?" in u_cmd:
                self.send_response('\r\n+CWJAP:"SimulatedAP","xx:xx:xx:xx:xx:xx",1,-50\r\n\r\nOK\r\n')
            else:
                self.send_response("\r\nWIFI CONNECTED\r\nWIFI GOT IP\r\n\r\nOK\r\n")

        elif u_cmd.startswith("AT+CWDHCP"):
            self.send_response("\r\nOK\r\n")

        elif u_cmd.startswith("AT+CIPSTA?") or u_cmd.startswith("AT+CIPSTA_") or u_cmd == "AT+CIPSTA":
            # Query IP address
            resp = (
                f'\r\n+CIPSTA_CUR:ip:"{self.simulated_ip}"\r\n'
                f'+CIPSTA_CUR:gateway:"192.168.1.1"\r\n'
                f'+CIPSTA_CUR:netmask:"255.255.255.0"\r\n\r\nOK\r\n'
            )
            self.send_response(resp)

        elif u_cmd.startswith("AT+CIPMUX"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CIPMUX:{self.cipmux}\r\n\r\nOK\r\n")
            else:
                if self.tcp_sock:
                    self.send_response("\r\nlink is builded\r\n\r\nERROR\r\n")
                else:
                    try:
                        val = int(cmd.split("=")[1].strip())
                        self.cipmux = val
                        self.send_response("\r\nOK\r\n")
                    except Exception:
                        self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPMODE"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CIPMODE:{self.cipmode}\r\n\r\nOK\r\n")
            else:
                try:
                    val = int(cmd.split("=")[1].strip())
                    self.cipmode = val
                    self.send_response("\r\nOK\r\n")
                except Exception:
                    self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPSTART="):
            # e.g. AT+CIPSTART="TCP","192.168.1.50",65432
            self.handle_cipstart(cmd)

        elif u_cmd.startswith("AT+CIPSEND"):
            if self.cipmode == 1:
                if self.tcp_sock:
                    self.log("Entering transparent streaming mode...")
                    self.mode = MODE_STREAM
                    self.escape_buf.clear()
                    self.escape_candidate = False
                    self.last_char_time = time.time()
                    # Official ESP-AT response: \r\nOK\r\n\r\n> 
                    self.send_response("\r\nOK\r\n\r\n> ")
                else:
                    self.send_response("\r\nERROR\r\n")
            else:
                # Normal packet send not fully modeled (returns OK for simple len)
                self.send_response("\r\nOK\r\n> ")

        elif u_cmd.startswith("AT+CIPCLOSE"):
            if self.tcp_sock:
                self.close_socket()
                self.send_response("\r\nCLOSED\r\n\r\nOK\r\n")
            else:
                self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+PING="):
            # e.g. AT+PING="192.168.1.50"
            host = cmd.split("=")[1].strip().strip('"')
            try:
                t0 = time.time()
                addr = socket.gethostbyname(host)
                elapsed_ms = max(1, int((time.time() - t0) * 1000))
                self.send_response(f"\r\n+{elapsed_ms}\r\n\r\nOK\r\n")
            except Exception:
                self.send_response("\r\n+timeout\r\n\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPDOMAIN="):
            host = cmd.split("=")[1].strip().strip('"')
            try:
                ip = socket.gethostbyname(host)
                self.send_response(f'\r\n+CIPDOMAIN:"{ip}"\r\n\r\nOK\r\n')
            except Exception:
                self.send_response("\r\nDNS Fail\r\n\r\nERROR\r\n")

        else:
            self.log(f"Unhandled command '{cmd}', returning OK")
            self.send_response("\r\nOK\r\n")

    def handle_cipstart(self, cmd: str):
        # Format: AT+CIPSTART="TCP","host",port
        if self.tcp_sock:
            self.send_response("\r\nALREADY CONNECTED\r\n\r\nERROR\r\n")
            return

        parts = cmd[len("AT+CIPSTART="):].strip().split(",")
        if len(parts) < 3:
            self.send_response("\r\nERROR\r\n")
            return

        conn_type = parts[0].strip().strip('"').upper()
        host = parts[1].strip().strip('"')
        try:
            port = int(parts[2].strip())
        except ValueError:
            self.send_response("\r\nERROR\r\n")
            return

        if conn_type != "TCP":
            self.log(f"Unsupported connection type: {conn_type}")
            self.send_response("\r\nERROR\r\n")
            return

        self.log(f"Attempting TCP connection to {host}:{port}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            sock.setblocking(False)
            self.tcp_sock = sock
            self.tcp_host = host
            self.tcp_port = port
            self.log(f"TCP connection established to {host}:{port}")
            self.send_response("\r\nCONNECT\r\n\r\nOK\r\n")
        except Exception as e:
            self.log(f"TCP connection failed: {e}")
            self.send_response("\r\nCLOSED\r\n\r\nCONNECT FAIL\r\n\r\nERROR\r\n")

    def close_socket(self):
        if self.tcp_sock:
            try:
                self.tcp_sock.close()
            except Exception:
                pass
            self.tcp_sock = None
            self.tcp_host = None
            self.tcp_port = None
            self.log("TCP socket closed")

    def process_master_input(self, data: bytes):
        now = time.time()

        if self.mode == MODE_COMMAND:
            for b in data:
                if self.echo:
                    self.write_pty(bytes([b]))
                if b in (ord('\r'), ord('\n')):
                    if self.cmd_buffer:
                        self.handle_command(self.cmd_buffer)
                        self.cmd_buffer.clear()
                else:
                    self.cmd_buffer.append(b)
            return

        # MODE_STREAM: Transparent passthrough with Hayes +++ detection
        # Hayes requirements:
        # 1. >= 1.0s silence before +++
        # 2. Exactly +++ with no other chars
        # 3. >= 1.0s silence after +++
        silence_before = (now - self.last_char_time) >= 1.0
        self.last_char_time = now

        for b in data:
            char = bytes([b])
            if silence_before and char == b'+' and len(self.escape_buf) < 3:
                self.escape_buf.append(b)
                if len(self.escape_buf) == 3:
                    self.escape_candidate = True
                    self.escape_candidate_time = now
                    self.log("Candidate +++ escape detected, waiting for post-guard silence...")
                continue

            # Non-escape byte or interrupted sequence
            if self.escape_buf:
                # Sequence broken before reaching 3 '+' or extra chars arrived
                self.forward_to_socket(bytes(self.escape_buf))
                self.escape_buf.clear()
                self.escape_candidate = False

            silence_before = False
            self.forward_to_socket(char)

    def check_escape_timeout(self):
        if self.mode == MODE_STREAM and self.escape_candidate:
            now = time.time()
            if (now - self.escape_candidate_time) >= 1.0:
                # Post-guard silence verified! Transition back to command mode
                self.log("+++ Escape sequence verified! Dropping to AT command mode.")
                self.mode = MODE_COMMAND
                self.escape_buf.clear()
                self.escape_candidate = False
                # Do NOT emit OK on escape; wait for next AT command

    def forward_to_socket(self, data: bytes):
        if self.tcp_sock:
            try:
                self.tcp_sock.sendall(data)
            except Exception as e:
                self.log(f"Socket send error: {e}")
                self.handle_remote_disconnect()

    def handle_remote_disconnect(self):
        self.log("Remote server disconnected")
        self.close_socket()
        if self.mode == MODE_STREAM:
            self.mode = MODE_COMMAND
            self.write_pty(b"\r\nCLOSED\r\n")

    def run(self):
        print(f"============================================================")
        print(f"  MOD-WIFI-ESP8266 Simulator (ESP-AT v1.7.4.0)")
        print(f"============================================================")
        print(f"  PTY Device: {self.slave_name}")
        if self.symlink:
            print(f"  Symlink:    {self.symlink}")
        print(f"  Baud Rate:  115200 (8-N-1)")
        print(f"\nTo launch Fab Agon Emulator with this bridge:")
        print(f"  fab-agon-emulator --uart1-device {self.slave_name} --uart1-baud 115200\n")
        print(f"Press Ctrl+C to exit.")
        print(f"============================================================\n", flush=True)

        try:
            while True:
                rlist = [self.master_fd]
                if self.tcp_sock:
                    rlist.append(self.tcp_sock)

                # Poll with 50ms timeout to service escape timers
                readable, _, _ = select.select(rlist, [], [], 0.05)

                self.check_escape_timeout()

                for fd in readable:
                    if fd == self.master_fd:
                        try:
                            data = os.read(self.master_fd, 1024)
                            if not data:
                                break
                            self.process_master_input(data)
                        except OSError as e:
                            self.log(f"Master PTY read error: {e}")
                            break

                    elif self.tcp_sock and fd == self.tcp_sock:
                        try:
                            net_data = self.tcp_sock.recv(2048)
                            if not net_data:
                                self.handle_remote_disconnect()
                            else:
                                if self.mode == MODE_STREAM:
                                    self.write_pty(net_data)
                        except (BlockingIOError, InterruptedError):
                            pass
                        except Exception as e:
                            self.log(f"Socket recv error: {e}")
                            self.handle_remote_disconnect()

        except KeyboardInterrupt:
            print("\nShutting down ESP8266 simulator...")
        finally:
            self.close_socket()
            try:
                os.close(self.master_fd)
                os.close(self.slave_fd)
            except Exception:
                pass
            if self.symlink and os.path.islink(self.symlink):
                try:
                    os.unlink(self.symlink)
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="MOD-WIFI-ESP8266 Coprocessor Simulator for Agon Light 2")
    parser.add_argument("--symlink", default="/tmp/agon-uart1", help="Symlink path for PTY (default: /tmp/agon-uart1)")
    parser.add_argument("--ip", default="192.168.1.100", help="Simulated local IP address")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--launch", help="Path to fab-agon-emulator binary to automatically start")
    args = parser.parse_args()

    sim = ESP8266Simulator(symlink=args.symlink, verbose=args.verbose, simulated_ip=args.ip)

    if args.launch:
        cmd = [args.launch, "--uart1-device", sim.slave_name, "--uart1-baud", "115200"]
        print(f"Launching emulator: {' '.join(cmd)}")
        emu_proc = subprocess.Popen(cmd)

        def sig_handler(sig, frame):
            emu_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, sig_handler)

    sim.run()

if __name__ == "__main__":
    main()
