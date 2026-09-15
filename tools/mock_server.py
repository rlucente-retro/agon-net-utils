#!/usr/bin/env python3
"""
Lightweight Mock TCP Server for Testing openstream and TRS-OS Network Handshake

Listens on TCP port 65432 (default).
Waits for the client to initiate communication with '@ping\n'.
Responds with '@pong\n' and logs subsequent commands.
"""

from __future__ import annotations

import argparse
import socket
import sys


def run_server(port: int = 65432, host: str = "0.0.0.0") -> None:
    """Run the mock TCP test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)

        print(f"[*] Mock TCP server listening on {host}:{port}", flush=True)
        print("[*] Waiting for client connection (e.g. from openstream / TRS-OS)...", flush=True)

        try:
            while True:
                conn, (client_host, client_port) = server.accept()
                with conn:
                    print(f"[+] Client connected from {client_host}:{client_port}", flush=True)
                    print("[*] Silent mode: Waiting for client '@ping'...", flush=True)

                    buffer = bytearray()
                    while True:
                        data = conn.recv(1024)
                        if not data:
                            print(f"[-] Client {client_host}:{client_port} disconnected.", flush=True)
                            break

                        buffer.extend(data)
                        print(f"[RX] Received {len(data)} bytes: {data!r}", flush=True)

                        # Check for TRS-OS @ping initiation
                        if b"@ping" in buffer:
                            print("[TX] Replying with '@pong\\n'...", flush=True)
                            conn.sendall(b"@pong\n")
                            # In-place clear of processed ping to avoid reallocation
                            idx = buffer.find(b"@ping")
                            del buffer[: idx + 5]

        except KeyboardInterrupt:
            print("\nShutting down server.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock TCP Server for TRS-OS network testing")
    parser.add_argument("--port", "-p", type=int, default=65432, help="Port to listen on (default 65432)")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind to (default 0.0.0.0)")
    args = parser.parse_args(argv)

    run_server(port=args.port, host=args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
