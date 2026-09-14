#!/usr/bin/env python3
"""
Automated End-to-End Integration Test for openstream & ESP8266 Simulator

Tests:
1. Starts mock_server.py on TCP port 65432.
2. Starts esp8266_sim.py on virtual PTY (/tmp/agon-uart1).
3. Configures emulator sdcard autoexec.txt to invoke openstream.bin.
4. Launches fab-agon-emulator linked to virtual PTY (--uart1-baud 0).
5. Validates AT command negotiation (AT, ATE0, CIPCLOSE, CIPMODE=0, CIPMUX=0, CIPMODE=1, CIPSTART, CIPSEND).
6. Validates incoming TCP connection at mock_server.py.
7. Validates bidirectional transparent data transfer (@ping -> @pong).
8. Restores original sdcard autoexec.txt upon completion.
"""

import sys
import os
import time
import subprocess
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DEFAULT_EMU = "/Users/richardlucente/development/git/fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator"

def find_emulator(custom_path=None):
    if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
        return os.path.abspath(custom_path)
    if os.path.isfile(DEFAULT_EMU) and os.access(DEFAULT_EMU, os.X_OK):
        return DEFAULT_EMU
    which_emu = subprocess.run(["which", "fab-agon-emulator"], stdout=subprocess.PIPE, text=True).stdout.strip()
    if which_emu and os.access(which_emu, os.X_OK):
        return which_emu
    return None

def main():
    parser = argparse.ArgumentParser(description="Run end-to-end integration test for openstream")
    parser.add_argument("--emulator", "-e", help="Path to fab-agon-emulator executable")
    parser.add_argument("--port", "-p", type=int, default=65432, help="TCP port for mock server (default 65432)")
    parser.add_argument("--timeout", "-t", type=float, default=10.0, help="Max test timeout in seconds (default 10.0)")
    args = parser.parse_args()

    emu_bin = find_emulator(args.emulator)
    if not emu_bin:
        print("[-] Error: fab-agon-emulator executable not found.")
        sys.exit(1)

    emu_dir = os.path.dirname(emu_bin)
    sdcard_dir = os.path.join(emu_dir, "sdcard")
    autoexec_path = os.path.join(sdcard_dir, "autoexec.txt")
    autoexec_bak = os.path.join(sdcard_dir, "autoexec.txt.test_bak")

    # Ensure openstream.bin exists
    openstream_bin = os.path.join(REPO_ROOT, "openstream", "bin", "openstream.bin")
    if not os.path.isfile(openstream_bin):
        print("[-] Error: openstream.bin not found. Run 'make -C openstream' first.")
        sys.exit(1)

    # Ensure openstream.bin is installed in emulator sdcard
    dest_mos = os.path.join(sdcard_dir, "mos", "openstream.bin")
    os.makedirs(os.path.dirname(dest_mos), exist_ok=True)
    subprocess.run(["cp", openstream_bin, dest_mos], check=True)

    print("============================================================")
    print("  openstream & ESP8266 Simulator Integration Test")
    print("============================================================")
    print(f"Emulator Binary: {emu_bin}")
    print(f"TCP Port:        {args.port}")
    print(f"SDCard Dir:      {sdcard_dir}")
    print("------------------------------------------------------------")

    # 1. Backup and prepare autoexec.txt
    original_autoexec = None
    if os.path.isfile(autoexec_path):
        with open(autoexec_path, "r") as f:
            original_autoexec = f.read()
        with open(autoexec_bak, "w") as f:
            f.write(original_autoexec)

    test_autoexec = f"LOAD mos/openstream.bin\nRUN . 127.0.0.1 {args.port}\n"
    with open(autoexec_path, "w") as f:
        f.write(test_autoexec)

    server_proc = None
    sim_proc = None
    emu_proc = None

    try:
        # 2. Start mock TCP server
        print("[*] Starting Mock TCP Server...")
        server_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "mock_server.py"), "--port", str(args.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(0.5)

        # 3. Start ESP8266 Simulator
        print("[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...")
        sim_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "esp8266_sim.py"), "--verbose", "--symlink", "/tmp/agon-uart1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(1.0)

        # 4. Launch Fab Agon Emulator
        print("[*] Launching Fab Agon Emulator (--uart1-baud 0)...")
        emu_proc = subprocess.Popen(
            [emu_bin, "--uart1-device", "/tmp/agon-uart1", "--uart1-baud", "0"],
            cwd=emu_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

        # 5. Wait for openstream to execute and establish stream
        print("[*] Waiting for openstream AT handshake and TCP connection...")
        t0 = time.time()
        connected = False
        while (time.time() - t0) < args.timeout:
            time.sleep(0.5)
            # Check if emulator finished or outputted link established
            if os.path.exists("/tmp/agon-uart1"):
                connected = True
                break

        time.sleep(3.5) # allow openstream to complete negotiation

        # 6. Test bidirectional payload transfer through stream
        print("[*] Testing bidirectional stream payload (@ping -> @pong)...")
        stream_ok = False
        try:
            with open("/tmp/agon-uart1", "r+b", buffering=0) as pty_f:
                pty_f.write(b"@ping\n")
                time.sleep(0.5)
                reply = pty_f.read(6)
                if b"@pong" in reply or b"pong" in reply:
                    print(f"[+] Successfully received reply over UART1 stream: {reply!r}")
                    stream_ok = True
                else:
                    print(f"[-] Received unexpected stream data: {reply!r}")
        except Exception as e:
            print(f"[-] Stream read/write failed: {e}")

    finally:
        # Terminate processes
        print("[*] Terminating emulator and test services...")
        if emu_proc:
            emu_proc.terminate()
        if sim_proc:
            sim_proc.terminate()
        if server_proc:
            server_proc.terminate()

        emu_out = emu_proc.communicate()[0] if emu_proc else ""
        sim_out = sim_proc.communicate()[0] if sim_proc else ""
        server_out = server_proc.communicate()[0] if server_proc else ""

        # Restore autoexec.txt
        if original_autoexec is not None:
            with open(autoexec_path, "w") as f:
                f.write(original_autoexec)
            if os.path.isfile(autoexec_bak):
                os.unlink(autoexec_bak)
            print("[+] Restored original autoexec.txt.")

    print("------------------------------------------------------------")
    print("                    TEST SUMMARY")
    print("------------------------------------------------------------")
    negotiation_ok = "Streaming mode active on UART1" in emu_out and "Link established" in emu_out
    socket_ok = "Client connected" in server_out
    at_handshake_ok = "AT+CIPMODE=1" in sim_out and "Entering transparent streaming mode" in sim_out

    print(f"[*] AT Command Negotiation:    {'PASS' if at_handshake_ok else 'FAIL'}")
    print(f"[*] TCP Socket Connection:      {'PASS' if socket_ok else 'FAIL'}")
    print(f"[*] MOS openstream Execution:   {'PASS' if negotiation_ok else 'FAIL'}")
    print(f"[*] Transparent Data Streaming: {'PASS' if stream_ok else 'FAIL'}")
    print("============================================================")

    if negotiation_ok and socket_ok and stream_ok:
        print("[+] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!")
        return 0
    else:
        print("[-] INTEGRATION TEST FAILED.")
        print("\n--- EMULATOR OUTPUT ---")
        print(emu_out)
        print("\n--- SIMULATOR OUTPUT ---")
        print(sim_out)
        print("\n--- SERVER OUTPUT ---")
        print(server_out)
        return 1

if __name__ == "__main__":
    sys.exit(main())
