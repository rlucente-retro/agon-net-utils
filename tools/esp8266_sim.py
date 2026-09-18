#!/usr/bin/env python3
"""
MOD-WIFI-ESP8266 Coprocessor Simulator for Fab Agon Emulator

Emulates the Espressif ESP-AT v1.7.x firmware running on a MOD-WIFI-ESP8266
module connected to UART1 of the Agon family (Agon Light, Agon Light 2, etc.).

Creates a virtual serial pseudo-terminal (PTY) that can be linked to:
    fab-agon-emulator --uart1-device <pty_path> --uart1-baud 0

Features:
- Full AT command parser for standard Agon network utilities (netman, ping, openstream).
- Handles transparent streaming mode (AT+CIPMODE=1 & AT+CIPSEND -> '>').
- Bridges transparent UART1 stream directly to remote TCP server (e.g. TRS-NET.py).
- Implements strict Hayes '+++' escape sequence detection with guard times.
- Detects socket disconnects and returns cleanly to command mode.
"""

from __future__ import annotations

import argparse
import contextlib
import enum
import os
from pathlib import Path
import pty
import select
import socket
import subprocess
import sys
import time
from typing import Final
import tty


class OperatingMode(enum.IntEnum):
    COMMAND = 0
    STREAM = 1


# Backwards compatibility aliases
MODE_COMMAND: Final[OperatingMode] = OperatingMode.COMMAND
MODE_STREAM: Final[OperatingMode] = OperatingMode.STREAM

DEFAULT_SYMLINK: Final[Path] = Path("/tmp/agon-uart1")
DEFAULT_IP: Final[str] = "192.168.1.100"
GUARD_TIME: Final[float] = 0.9
INTER_CHAR_TIMEOUT: Final[float] = 1.0


class ESP8266Simulator:
    """Simulates an ESP8266 running ESP-AT firmware over a Unix pseudo-terminal (PTY)."""

    def __init__(
        self,
        symlink: str | Path | None = None,
        verbose: bool = False,
        simulated_ip: str = DEFAULT_IP,
    ) -> None:
        self.verbose = verbose
        self.simulated_ip = simulated_ip
        self.symlink = Path(symlink) if symlink else None
        self.mode = OperatingMode.COMMAND

        # AT State
        self.echo = True
        self.cwmode = 1           # Station mode
        self.cipmux = 0           # Single connection mode
        self.cipmode = 0          # 0 = Normal mode, 1 = Transparent streaming
        self.tcp_sock: socket.socket | None = None
        self.tcp_host: str | None = None
        self.tcp_port: int | None = None

        # UART configuration: <baudrate>, <databits>, <stopbits>, <parity>, <flow_control>
        self.uart_cur = {
            "baudrate": 115200,
            "databits": 8,
            "stopbits": 1,
            "parity": 0,
            "flow_control": 0,
        }
        self.uart_def = {
            "baudrate": 115200,
            "databits": 8,
            "stopbits": 1,
            "parity": 0,
            "flow_control": 0,
        }

        # Command buffer
        self.cmd_buffer = bytearray()
        self.last_was_cr = False

        # Escape sequence detector for transparent mode
        self.last_char_time = 0.0
        self.escape_buf = bytearray()
        self.escape_candidate = False
        self.escape_candidate_time = 0.0

        # Create PTY
        self.master_fd: int | None
        self.slave_fd: int | None
        self.master_fd, self.slave_fd = pty.openpty()
        self.slave_name = os.ttyname(self.slave_fd)

        # Set raw mode on PTY
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)

        # Create symlink if requested
        if self.symlink:
            with contextlib.suppress(OSError):
                self.symlink.unlink(missing_ok=True)
            try:
                self.symlink.symlink_to(self.slave_name)
            except OSError as e:
                print(f"[!] Warning: Could not create symlink {self.symlink}: {e}", file=sys.stderr)

    def __enter__(self) -> ESP8266Simulator:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Close sockets, file descriptors, and clean up symlinks."""
        self.close_socket()
        if self.master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.master_fd)
            self.master_fd = None
        if self.slave_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.slave_fd)
            self.slave_fd = None
        if self.symlink:
            with contextlib.suppress(OSError):
                self.symlink.unlink(missing_ok=True)

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def write_pty(self, data: bytes) -> None:
        if self.master_fd is None:
            return
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            self.log(f"PTY write error: {e}")

    def send_response(self, text: str) -> None:
        self.write_pty(text.encode("ascii", errors="replace"))

    def handle_command(self, cmd_bytes: bytes) -> None:
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
            self.mode = OperatingMode.COMMAND
            self.cipmode = 0
            self.uart_cur = dict(self.uart_def)
            self.send_response("\r\nOK\r\nready\r\n")

        elif u_cmd.startswith("AT+RESTORE"):
            self.close_socket()
            self.mode = OperatingMode.COMMAND
            self.cipmode = 0
            self.cipmux = 0
            self.cwmode = 1
            self.uart_def = {
                "baudrate": 115200,
                "databits": 8,
                "stopbits": 1,
                "parity": 0,
                "flow_control": 0,
            }
            self.uart_cur = dict(self.uart_def)
            self.send_response("\r\nOK\r\nready\r\n")

        elif u_cmd.startswith("AT+CWMODE"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CWMODE:{self.cwmode}\r\n\r\nOK\r\n")
            else:
                try:
                    self.cwmode = int(cmd.partition("=")[2].strip())
                    self.send_response("\r\nOK\r\n")
                except ValueError:
                    self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CWJAP"):
            if "?" in u_cmd:
                self.send_response('\r\n+CWJAP:"SimulatedAP","xx:xx:xx:xx:xx:xx",1,-50\r\n\r\nOK\r\n')
            else:
                self.send_response("\r\nWIFI CONNECTED\r\nWIFI GOT IP\r\n\r\nOK\r\n")

        elif u_cmd.startswith("AT+CWDHCP"):
            self.send_response("\r\nOK\r\n")

        elif u_cmd.startswith("AT+CIPSTA?") or u_cmd.startswith("AT+CIPSTA_") or u_cmd == "AT+CIPSTA":
            resp = (
                f'\r\n+CIPSTA_CUR:ip:"{self.simulated_ip}"\r\n'
                f'+CIPSTA_CUR:gateway:"192.168.1.1"\r\n'
                f'+CIPSTA_CUR:netmask:"255.255.255.0"\r\n\r\nOK\r\n'
            )
            self.send_response(resp)

        elif u_cmd.startswith("AT+CIPMUX"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CIPMUX:{self.cipmux}\r\n\r\nOK\r\n")
            elif self.tcp_sock:
                self.send_response("\r\nlink is builded\r\n\r\nERROR\r\n")
            else:
                try:
                    self.cipmux = int(cmd.partition("=")[2].strip())
                    self.send_response("\r\nOK\r\n")
                except ValueError:
                    self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPMODE"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CIPMODE:{self.cipmode}\r\n\r\nOK\r\n")
            else:
                try:
                    self.cipmode = int(cmd.partition("=")[2].strip())
                    self.send_response("\r\nOK\r\n")
                except ValueError:
                    self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPSTART="):
            self.handle_cipstart(cmd)

        elif u_cmd.startswith("AT+CIPSEND"):
            if self.cipmode == 1:
                if self.tcp_sock:
                    self.log("Entering transparent streaming mode...")
                    self.mode = OperatingMode.STREAM
                    self.escape_buf.clear()
                    self.escape_candidate = False
                    self.last_char_time = time.time()
                    # Official ESP-AT response: \r\nOK\r\n\r\n>
                    self.send_response("\r\nOK\r\n\r\n> ")
                else:
                    self.send_response("\r\nERROR\r\n")
            else:
                self.send_response("\r\nOK\r\n> ")

        elif u_cmd.startswith("AT+CIPCLOSE"):
            if self.tcp_sock:
                self.close_socket()
                self.send_response("\r\nCLOSED\r\n\r\nOK\r\n")
            else:
                self.send_response("\r\nERROR\r\n")

        elif u_cmd.startswith("AT+PING="):
            host = cmd.partition("=")[2].strip().strip('"')
            try:
                t0 = time.time()
                _ = socket.gethostbyname(host)
                elapsed_ms = max(1, int((time.time() - t0) * 1000))
                self.send_response(f"\r\n+{elapsed_ms}\r\n\r\nOK\r\n")
            except OSError:
                self.send_response("\r\n+timeout\r\n\r\nERROR\r\n")

        elif u_cmd.startswith("AT+CIPDOMAIN="):
            host = cmd.partition("=")[2].strip().strip('"')
            try:
                ip = socket.gethostbyname(host)
                self.send_response(f'\r\n+CIPDOMAIN:"{ip}"\r\n\r\nOK\r\n')
            except OSError:
                self.send_response("\r\nDNS Fail\r\n\r\nERROR\r\n")

        elif (
            u_cmd.startswith("AT+UART_CUR")
            or u_cmd.startswith("AT+UART_DEF")
            or u_cmd.startswith("AT+UART")
            or u_cmd.startswith("AT+CIOBAUD")
        ):
            self.handle_uart_cmd(cmd, u_cmd)

        else:
            self.log(f"Unhandled command '{cmd}', returning OK")
            self.send_response("\r\nOK\r\n")

    def handle_uart_cmd(self, cmd: str, u_cmd: str) -> None:
        """Handle AT+UART_CUR, AT+UART_DEF, AT+UART, and legacy AT+CIOBAUD commands."""
        # Check for legacy AT+CIOBAUD
        if u_cmd.startswith("AT+CIOBAUD"):
            if "?" in u_cmd:
                self.send_response(f"\r\n+CIOBAUD:{self.uart_cur['baudrate']}\r\n\r\nOK\r\n")
            elif "=" in cmd:
                try:
                    baud = int(cmd.partition("=")[2].strip())
                    if baud <= 0:
                        raise ValueError
                    self.uart_cur["baudrate"] = baud
                    self.send_response("\r\nOK\r\n")
                except ValueError:
                    self.send_response("\r\nERROR\r\n")
            else:
                self.send_response("\r\nERROR\r\n")
            return

        # Determine target command prefix: AT+UART_DEF, AT+UART_CUR, or legacy AT+UART
        is_def = u_cmd.startswith("AT+UART_DEF")
        is_cur = u_cmd.startswith("AT+UART_CUR")
        tag = "+UART_DEF" if is_def else ("+UART_CUR" if is_cur else "+UART")

        # Test command: AT+UART...=?
        if "=?" in u_cmd:
            self.send_response("\r\nOK\r\n")
            return

        # Query command: AT+UART...?
        if "?" in u_cmd:
            cfg = self.uart_def if is_def else self.uart_cur
            resp = (
                f"\r\n{tag}:{cfg['baudrate']},{cfg['databits']},"
                f"{cfg['stopbits']},{cfg['parity']},{cfg['flow_control']}\r\n\r\nOK\r\n"
            )
            self.send_response(resp)
            return

        # Set command: AT+UART...=<baudrate>,<databits>,<stopbits>,<parity>,<flow_control>
        if "=" in cmd:
            params_str = cmd.partition("=")[2].strip()
            parts = [p.strip() for p in params_str.split(",")]
            if len(parts) != 5:
                self.send_response("\r\nERROR\r\n")
                return

            try:
                baud = int(parts[0])
                databits = int(parts[1])
                stopbits = int(parts[2])
                parity = int(parts[3])
                flow = int(parts[4])
            except ValueError:
                self.send_response("\r\nERROR\r\n")
                return

            # Validate parameters according to Espressif ESP8266 AT specification:
            # baudrate: positive integer (typically 110 to 5000000)
            # databits: 5 (5-bit), 6 (6-bit), 7 (7-bit), 8 (8-bit)
            # stopbits: 1 (1-bit), 2 (1.5-bit), 3 (2-bit)
            # parity: 0 (None), 1 (Odd), 2 (Even)
            # flow_control: 0 (Disabled), 1 (RTS), 2 (CTS), 3 (RTS & CTS)
            if (
                baud <= 0
                or databits not in (5, 6, 7, 8)
                or stopbits not in (1, 2, 3)
                or parity not in (0, 1, 2)
                or flow not in (0, 1, 2, 3)
            ):
                self.send_response("\r\nERROR\r\n")
                return

            new_cfg = {
                "baudrate": baud,
                "databits": databits,
                "stopbits": stopbits,
                "parity": parity,
                "flow_control": flow,
            }

            if is_def:
                self.uart_def = new_cfg
                self.uart_cur = dict(new_cfg)
                self.log(f"UART_DEF configured: {baud},{databits},{stopbits},{parity},{flow}")
            else:
                self.uart_cur = new_cfg
                self.log(f"UART_CUR configured: {baud},{databits},{stopbits},{parity},{flow}")

            self.send_response("\r\nOK\r\n")
            return

        # Malformed command (neither '?' nor '=')
        self.send_response("\r\nERROR\r\n")

    def handle_cipstart(self, cmd: str) -> None:
        if self.tcp_sock:
            self.send_response("\r\nALREADY CONNECTED\r\n\r\nERROR\r\n")
            return

        _, _, params = cmd.partition("=")
        parts = [p.strip().strip('"') for p in params.split(",")]
        if len(parts) < 3:
            self.send_response("\r\nERROR\r\n")
            return

        conn_type, host, port_str = parts[0].upper(), parts[1], parts[2]
        try:
            port = int(port_str)
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
        except socket.gaierror as e:
            self.log(f"DNS lookup failed for '{host}': {e}")
            self.send_response("\r\nDNS Fail\r\n\r\nERROR\r\n")
        except OSError as e:
            self.log(f"TCP connection failed: {e}")
            self.send_response("\r\nCLOSED\r\n\r\nCONNECT FAIL\r\n\r\nERROR\r\n")

    def close_socket(self) -> None:
        if self.tcp_sock:
            with contextlib.suppress(OSError):
                self.tcp_sock.close()
            self.tcp_sock = None
            self.tcp_host = None
            self.tcp_port = None
            self.log("TCP socket closed")

    def process_master_input(self, data: bytes) -> None:
        if self.mode == OperatingMode.COMMAND:
            for b in data:
                if self.echo:
                    self.write_pty(bytes([b]))
                if b == ord("\r"):
                    self.last_was_cr = True
                    if self.cmd_buffer:
                        self.handle_command(self.cmd_buffer)
                        self.cmd_buffer.clear()
                elif b == ord("\n"):
                    if self.last_was_cr:
                        self.last_was_cr = False
                        continue
                    self.last_was_cr = False
                    if self.cmd_buffer:
                        self.handle_command(self.cmd_buffer)
                        self.cmd_buffer.clear()
                else:
                    self.last_was_cr = False
                    self.cmd_buffer.append(b)
            return

        # OperatingMode.STREAM: Transparent passthrough with Hayes +++ detection
        # Consume any trailing newline from the command that entered stream mode
        if self.last_was_cr and len(data) > 0 and data[0] == ord("\n"):
            self.last_was_cr = False
            data = data[1:]
            if not data:
                return
        self.last_was_cr = False

        for b in data:
            char = bytes([b])
            now = time.time()

            # If in candidate state (3 '+' received) and a character arrived before guard time:
            if self.escape_candidate:
                self.log(
                    f"Escape candidate broken by byte {char!r} after {now - self.escape_candidate_time:.3f}s "
                    f"(needed {GUARD_TIME}s)"
                )
                self.escape_candidate = False
                self.forward_to_socket(bytes(self.escape_buf))
                self.escape_buf.clear()
                self.last_char_time = now
                self.forward_to_socket(char)
                continue

            if char == b"+":
                if len(self.escape_buf) == 0:
                    if (now - self.last_char_time) >= GUARD_TIME:
                        self.escape_buf.append(b)
                        self.last_char_time = now
                        continue
                    else:
                        self.last_char_time = now
                        self.forward_to_socket(char)
                        continue
                elif len(self.escape_buf) < 3:
                    if (now - self.last_char_time) < INTER_CHAR_TIMEOUT:
                        self.escape_buf.append(b)
                        self.last_char_time = now
                        if len(self.escape_buf) == 3:
                            self.escape_candidate = True
                            self.escape_candidate_time = now
                            self.log("Candidate +++ escape detected, waiting for post-guard silence...")
                        continue
                    else:
                        self.forward_to_socket(bytes(self.escape_buf))
                        self.escape_buf.clear()
                        self.escape_buf.append(b)
                        self.last_char_time = now
                        continue

            if self.escape_buf:
                self.forward_to_socket(bytes(self.escape_buf))
                self.escape_buf.clear()
                self.escape_candidate = False

            self.last_char_time = now
            self.forward_to_socket(char)

    def check_escape_timeout(self) -> None:
        now = time.time()
        if self.mode == OperatingMode.STREAM:
            if self.escape_candidate:
                if (now - self.escape_candidate_time) >= GUARD_TIME:
                    self.log("+++ Escape sequence verified! Dropping to AT command mode.")
                    self.mode = OperatingMode.COMMAND
                    self.escape_buf.clear()
                    self.escape_candidate = False
            elif self.escape_buf and len(self.escape_buf) < 3:
                if (now - self.last_char_time) >= GUARD_TIME:
                    self.forward_to_socket(bytes(self.escape_buf))
                    self.escape_buf.clear()

    def forward_to_socket(self, data: bytes) -> None:
        if self.tcp_sock:
            try:
                self.tcp_sock.sendall(data)
            except OSError as e:
                self.log(f"Socket send error: {e}")
                self.handle_remote_disconnect()

    def handle_remote_disconnect(self) -> None:
        self.log("Remote server disconnected")
        self.close_socket()
        if self.mode == OperatingMode.STREAM:
            self.mode = OperatingMode.COMMAND
            self.write_pty(b"\r\nCLOSED\r\n")

    def run(self) -> None:
        """Run the main event loop bridging PTY and TCP socket."""
        print("=" * 60)
        print("  MOD-WIFI-ESP8266 Simulator (ESP-AT v1.7.4.0)")
        print("=" * 60)
        print(f"  PTY Device: {self.slave_name}")
        if self.symlink:
            print(f"  Symlink:    {self.symlink}")
        print("  Baud Rate:  115200 (8-N-1)")
        print("\nTo launch Fab Agon Emulator with this bridge:")
        print(f"  fab-agon-emulator --uart1-device {self.slave_name} --uart1-baud 0\n")
        print("Press Ctrl+C to exit.")
        print("=" * 60 + "\n", flush=True)

        try:
            while True:
                if self.master_fd is None:
                    break
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
                                return
                            self.process_master_input(data)
                        except OSError as e:
                            self.log(f"Master PTY read error: {e}")
                            return

                    elif self.tcp_sock and fd == self.tcp_sock:
                        try:
                            net_data = self.tcp_sock.recv(2048)
                            if not net_data:
                                self.handle_remote_disconnect()
                            elif self.mode == OperatingMode.STREAM:
                                self.write_pty(net_data)
                        except (BlockingIOError, InterruptedError):
                            pass
                        except OSError as e:
                            self.log(f"Socket recv error: {e}")
                            self.handle_remote_disconnect()

        except KeyboardInterrupt:
            print("\nShutting down ESP8266 simulator...")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MOD-WIFI-ESP8266 Coprocessor Simulator for Agon family")
    parser.add_argument("--symlink", default=str(DEFAULT_SYMLINK), help="Symlink path for PTY (default: /tmp/agon-uart1)")
    parser.add_argument("--ip", default=DEFAULT_IP, help="Simulated local IP address")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--launch", help="Path to fab-agon-emulator binary to automatically start")
    args = parser.parse_args(argv)

    with ESP8266Simulator(symlink=args.symlink, verbose=args.verbose, simulated_ip=args.ip) as sim:
        emu_proc: subprocess.Popen[str] | None = None
        if args.launch:
            launch_path = Path(args.launch).resolve()
            cmd = [str(launch_path), "--uart1-device", sim.slave_name, "--uart1-baud", "0"]
            emu_cwd = launch_path.parent
            print(f"Launching emulator: {' '.join(cmd)} (cwd: {emu_cwd})")
            emu_proc = subprocess.Popen(cmd, cwd=emu_cwd)

        try:
            sim.run()
        finally:
            if emu_proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    emu_proc.terminate()
                    try:
                        emu_proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        emu_proc.kill()
                        emu_proc.wait(timeout=1.0)

    return 0


if __name__ == "__main__":
    sys.exit(main())
