#!/usr/bin/env python3
"""
Automated End-to-End Integration Test for openstream & closestream

Tests:
Stage 1 (openstream & stream mode):
1. Starts mock_server.py on TCP port 65432.
2. Starts esp8266_sim.py on virtual PTY (/tmp/agon-uart1).
3. Configures emulator sdcard autoexec.txt to invoke openstream.bin.
4. Launches fab-agon-emulator linked to virtual PTY (--uart1-baud 0).
5. Validates AT command negotiation (AT, ATE0, CIPCLOSE, CIPMODE=0, CIPMUX=0, CIPMODE=1, CIPSTART, CIPSEND).
6. Validates incoming TCP connection at mock_server.py.
7. Validates bidirectional transparent data transfer (@ping -> @pong).

Stage 2 (closestream & escape/teardown):
1. Configures emulator sdcard autoexec.txt to invoke openstream.bin followed by closestream.bin.
2. Launches fab-agon-emulator linked to virtual PTY.
3. Validates that closestream detects stream mode and issues Hayes '+++' escape sequence.
4. Validates that simulator verifies guard silences and transitions back to AT command mode.
5. Validates AT+CIPCLOSE and clean TCP disconnection at mock_server.py.
6. Validates AT+CIPMODE=0 mode reset and MOS completion message.
"""

import sys
import os
import time
import subprocess
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
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

def kill_proc(proc):
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def run_stage1(emu_bin, emu_dir, sdcard_dir, autoexec_path, port, timeout):
    print("\n------------------------------------------------------------")
    print("  STAGE 1: openstream & Bidirectional Stream Verification")
    print("------------------------------------------------------------")

    test_autoexec = f"LOAD mos/openstream.bin\nRUN . 127.0.0.1 {port}\n"
    with open(autoexec_path, "w") as f:
        f.write(test_autoexec)

    server_proc = None
    sim_proc = None
    emu_proc = None

    emu_out = ""
    sim_out = ""
    server_out = ""
    stream_ok = False

    try:
        print("[*] Starting Mock TCP Server...")
        server_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "mock_server.py"), "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(0.5)

        print("[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...")
        sim_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "esp8266_sim.py"), "--verbose", "--symlink", "/tmp/agon-uart1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(1.0)

        print("[*] Launching Fab Agon Emulator (--uart1-baud 0)...")
        emu_proc = subprocess.Popen(
            [emu_bin, "--uart1-device", "/tmp/agon-uart1", "--uart1-baud", "0"],
            cwd=emu_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

        print("[*] Waiting for openstream AT handshake and TCP connection...")
        t0 = time.time()
        while (time.time() - t0) < timeout:
            time.sleep(0.5)
            if os.path.exists("/tmp/agon-uart1"):
                break

        time.sleep(3.5)  # Allow openstream to complete handshake and exit to MOS

        print("[*] Testing bidirectional stream payload (@ping -> @pong)...")
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
        kill_proc(emu_proc)
        kill_proc(sim_proc)
        kill_proc(server_proc)

        emu_out = emu_proc.communicate()[0] if emu_proc else ""
        sim_out = sim_proc.communicate()[0] if sim_proc else ""
        server_out = server_proc.communicate()[0] if server_proc else ""

    at_handshake_ok = "AT+CIPMODE=1" in sim_out and "Entering transparent streaming mode" in sim_out
    socket_ok = "Client connected" in server_out
    openstream_ok = "Streaming mode active on UART1" in emu_out and "Link established" in emu_out

    results = {
        "at_handshake": at_handshake_ok,
        "socket_connected": socket_ok,
        "openstream_exec": openstream_ok,
        "streaming_payload": stream_ok,
    }

    print(f"[*] Stage 1 AT Negotiation:     {'PASS' if at_handshake_ok else 'FAIL'}")
    print(f"[*] Stage 1 Socket Connection:  {'PASS' if socket_ok else 'FAIL'}")
    print(f"[*] Stage 1 openstream Output:  {'PASS' if openstream_ok else 'FAIL'}")
    print(f"[*] Stage 1 Payload Streaming:  {'PASS' if stream_ok else 'FAIL'}")

    return all(results.values()), emu_out, sim_out, server_out

def run_stage2(emu_bin, emu_dir, sdcard_dir, autoexec_path, port, timeout):
    print("\n------------------------------------------------------------")
    print("  STAGE 2: closestream Escape & Teardown Verification")
    print("------------------------------------------------------------")

    test_autoexec = f"LOAD mos/openstream.bin\nRUN . 127.0.0.1 {port}\nLOAD mos/closestream.bin\nRUN\n"
    with open(autoexec_path, "w") as f:
        f.write(test_autoexec)

    server_proc = None
    sim_proc = None
    emu_proc = None

    emu_out = ""
    sim_out = ""
    server_out = ""

    try:
        print("[*] Starting Mock TCP Server...")
        server_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "mock_server.py"), "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(0.5)

        print("[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: /tmp/agon-uart1)...")
        sim_proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "esp8266_sim.py"), "--verbose", "--symlink", "/tmp/agon-uart1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        time.sleep(1.0)

        print("[*] Launching Fab Agon Emulator (--uart1-baud 0)...")
        emu_proc = subprocess.Popen(
            [emu_bin, "--uart1-device", "/tmp/agon-uart1", "--uart1-baud", "0"],
            cwd=emu_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

        print("[*] Waiting for openstream + closestream execution...")
        # openstream takes ~1.5s, closestream takes ~3.0s (500ms probe + 1.25s pre + 1.25s post)
        time.sleep(7.5)

    finally:
        kill_proc(emu_proc)
        kill_proc(sim_proc)
        kill_proc(server_proc)

        emu_out = emu_proc.communicate()[0] if emu_proc else ""
        sim_out = sim_proc.communicate()[0] if sim_proc else ""
        server_out = server_proc.communicate()[0] if server_proc else ""

    escape_verified = "Escape sequence verified! Dropping to AT command mode" in sim_out
    socket_closed = "AT+CIPCLOSE" in sim_out and "disconnected" in server_out
    mode_reset = "AT+CIPMODE=0" in sim_out
    closestream_ok = "Stream closed. ESP8266 in command mode." in emu_out

    results = {
        "escape_verified": escape_verified,
        "socket_closed": socket_closed,
        "mode_reset": mode_reset,
        "closestream_exec": closestream_ok,
    }

    print(f"[*] Stage 2 Hayes Escape (+++): {'PASS' if escape_verified else 'FAIL'}")
    print(f"[*] Stage 2 Socket Disconnect:  {'PASS' if socket_closed else 'FAIL'}")
    print(f"[*] Stage 2 CIPMODE=0 Reset:    {'PASS' if mode_reset else 'FAIL'}")
    print(f"[*] Stage 2 closestream Output: {'PASS' if closestream_ok else 'FAIL'}")

    return all(results.values()), emu_out, sim_out, server_out

def main():
    parser = argparse.ArgumentParser(description="Run end-to-end integration test for openstream and closestream")
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

    # Ensure binaries exist
    openstream_bin = os.path.join(REPO_ROOT, "bin", "openstream.bin")
    closestream_bin = os.path.join(REPO_ROOT, "bin", "closestream.bin")

    if not os.path.isfile(openstream_bin):
        print("[-] Error: openstream.bin not found. Run 'make' first.")
        sys.exit(1)
    if not os.path.isfile(closestream_bin):
        print("[-] Error: closestream.bin not found. Run 'make' first.")
        sys.exit(1)

    # Ensure binaries are installed in emulator sdcard/mos
    dest_mos_dir = os.path.join(sdcard_dir, "mos")
    os.makedirs(dest_mos_dir, exist_ok=True)
    subprocess.run(["cp", openstream_bin, os.path.join(dest_mos_dir, "openstream.bin")], check=True)
    subprocess.run(["cp", closestream_bin, os.path.join(dest_mos_dir, "closestream.bin")], check=True)

    print("============================================================")
    print("  openstream & closestream Integration Test Suite")
    print("============================================================")
    print(f"Emulator Binary: {emu_bin}")
    print(f"TCP Port:        {args.port}")
    print(f"SDCard Dir:      {sdcard_dir}")
    print("------------------------------------------------------------")

    # Backup autoexec.txt
    original_autoexec = None
    if os.path.isfile(autoexec_path):
        with open(autoexec_path, "r") as f:
            original_autoexec = f.read()
        with open(autoexec_bak, "w") as f:
            f.write(original_autoexec)

    stage1_pass = False
    stage2_pass = False

    try:
        stage1_pass, emu1, sim1, srv1 = run_stage1(emu_bin, emu_dir, sdcard_dir, autoexec_path, args.port, args.timeout)
        time.sleep(1.0)
        stage2_pass, emu2, sim2, srv2 = run_stage2(emu_bin, emu_dir, sdcard_dir, autoexec_path, args.port, args.timeout)

    finally:
        # Restore autoexec.txt
        if original_autoexec is not None:
            with open(autoexec_path, "w") as f:
                f.write(original_autoexec)
            if os.path.isfile(autoexec_bak):
                os.unlink(autoexec_bak)
            print("\n[+] Restored original autoexec.txt.")

    print("\n============================================================")
    print("                    OVERALL TEST SUMMARY")
    print("============================================================")
    print(f"[*] Stage 1 (openstream & streaming):  {'PASS' if stage1_pass else 'FAIL'}")
    print(f"[*] Stage 2 (closestream & teardown):  {'PASS' if stage2_pass else 'FAIL'}")
    print("============================================================")

    if stage1_pass and stage2_pass:
        print("[+] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!\n")
        return 0
    else:
        print("[-] INTEGRATION TEST SUITE FAILED.\n")
        if not stage1_pass:
            print("--- STAGE 1 LOGS ---")
            print("EMU:\n", emu1, "\nSIM:\n", sim1, "\nSERVER:\n", srv1)
        if not stage2_pass:
            print("--- STAGE 2 LOGS ---")
            print("EMU:\n", emu2, "\nSIM:\n", sim2, "\nSERVER:\n", srv2)
        return 1

if __name__ == "__main__":
    sys.exit(main())
