#!/usr/bin/env python3
"""
Lightweight Mock TCP Server for Testing openstream and TRS-OS Network Handshake

Listens on TCP port 65432 (default).
Waits for the client to initiate communication with '@ping\n'.
Responds with '@pong\n' and logs subsequent commands.
"""

import socket
import sys
import argparse

def run_server(port=65432, host="0.0.0.0"):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)

    print(f"[*] Mock TCP server listening on {host}:{port}", flush=True)
    print(f"[*] Waiting for client connection (e.g. from openstream / TRS-OS)...", flush=True)

    try:
        while True:
            conn, addr = server.accept()
            print(f"[+] Client connected from {addr[0]}:{addr[1]}", flush=True)
            print(f"[*] Silent mode: Waiting for client '@ping'...", flush=True)

            buffer = bytearray()
            while True:
                data = conn.recv(1024)
                if not data:
                    print(f"[-] Client {addr[0]}:{addr[1]} disconnected.", flush=True)
                    break

                buffer.extend(data)
                print(f"[RX] Received {len(data)} bytes: {data!r}", flush=True)

                # Check for TRS-OS @ping initiation
                if b"@ping" in buffer:
                    print(f"[TX] Replying with '@pong\\n'...", flush=True)
                    conn.sendall(b"@pong\n")
                    # Clear processed ping
                    idx = buffer.find(b"@ping")
                    buffer = buffer[idx + 5:]

    except KeyboardInterrupt:
        print("\nShutting down server.", flush=True)
    finally:
        server.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock TCP Server for TRS-OS network testing")
    parser.add_argument("--port", "-p", type=int, default=65432, help="Port to listen on (default 65432)")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind to (default 0.0.0.0)")
    args = parser.parse_args()

    run_server(port=args.port, host=args.host)
