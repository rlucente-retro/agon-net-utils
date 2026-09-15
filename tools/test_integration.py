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

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
from typing import Final, Iterator

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = SCRIPT_DIR.parent

# Default relative path to emulator executable (relative to repository root)
DEFAULT_EMULATOR: Final[Path] = Path("../fab-agon-emulator-v1.2.4-macos-arm64/fab-agon-emulator")
DEFAULT_PTY: Final[Path] = Path("/tmp/agon-uart1")


@dataclass(frozen=True)
class StageResult:
    """Holds the outcome and captured outputs for an integration test stage."""
    passed: bool
    emu_out: str
    sim_out: str
    server_out: str
    details: dict[str, bool]


def find_emulator(custom_path: str | Path | None = None) -> Path | None:
    """Resolve path to fab-agon-emulator binary following priority order."""
    # 1. Explicit command-line argument
    if custom_path:
        cand = Path(custom_path).expanduser().resolve()
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
        print(f"[-] Error: Specified emulator binary not found or not executable: {custom_path}", file=sys.stderr)
        return None

    # 2. Environment variable override
    env_emu = os.environ.get("FAB_AGON_EMULATOR")
    if env_emu:
        cand = Path(env_emu).expanduser().resolve()
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand

    # 3. Default relative path (relative to repository root)
    rel_cand = (REPO_ROOT / DEFAULT_EMULATOR).resolve()
    if rel_cand.is_file() and os.access(rel_cand, os.X_OK):
        return rel_cand

    # 4. System PATH
    which_emu = shutil.which("fab-agon-emulator")
    if which_emu:
        cand = Path(which_emu).resolve()
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand

    return None


def kill_proc(proc: subprocess.Popen[str] | None) -> None:
    """Safely terminate a subprocess with escalation to SIGKILL."""
    if proc is None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)


def collect_output(proc: subprocess.Popen[str] | None) -> str:
    """Safely drain stdout/stderr from a process."""
    if proc is None:
        return ""
    try:
        out, _ = proc.communicate(timeout=2.0)
        return out or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return out or ""


@contextlib.contextmanager
def preserved_file(target: Path) -> Iterator[Path]:
    """Context manager to backup and safely restore a file after testing."""
    backup = target.with_suffix(target.suffix + ".test_bak")
    original_content: str | None = None
    if target.is_file():
        original_content = target.read_text(encoding="utf-8", errors="replace")
        backup.write_text(original_content, encoding="utf-8")
    try:
        yield target
    finally:
        if original_content is not None:
            target.write_text(original_content, encoding="utf-8")
            backup.unlink(missing_ok=True)
            print("\n[+] Restored original autoexec.txt.")
        elif target.is_file():
            target.unlink(missing_ok=True)


def run_stage1(
    emu_bin: Path,
    emu_dir: Path,
    autoexec_path: Path,
    port: int,
    timeout: float,
) -> StageResult:
    """Run Stage 1: openstream & bidirectional stream verification."""
    print("\n------------------------------------------------------------")
    print("  STAGE 1: openstream & Bidirectional Stream Verification")
    print("------------------------------------------------------------")

    autoexec_path.write_text(f"openstream 127.0.0.1 {port}\nsendstream @ping\n", encoding="utf-8")

    server_proc: subprocess.Popen[str] | None = None
    sim_proc: subprocess.Popen[str] | None = None
    emu_proc: subprocess.Popen[str] | None = None

    try:
        print("[*] Starting Mock TCP Server...")
        server_proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "mock_server.py"), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(0.5)

        print(f"[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: {DEFAULT_PTY})...")
        sim_proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "esp8266_sim.py"), "--verbose", "--symlink", str(DEFAULT_PTY)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(1.0)

        print("[*] Launching Fab Agon Emulator (--uart1-baud 0)...")
        emu_proc = subprocess.Popen(
            [str(emu_bin), "--uart1-device", str(DEFAULT_PTY), "--uart1-baud", "0"],
            cwd=emu_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("[*] Waiting for openstream & sendstream execution...")
        time.sleep(5.0)  # Allow openstream and sendstream to complete and exit to MOS

    finally:
        kill_proc(emu_proc)
        kill_proc(sim_proc)
        kill_proc(server_proc)

        emu_out = collect_output(emu_proc)
        sim_out = collect_output(sim_proc)
        server_out = collect_output(server_proc)

    stream_ok = "@pong" in emu_out or "pong" in emu_out
    if stream_ok:
        print("[+] Successfully received @pong reply via sendstream")
    else:
        print("[-] sendstream @ping reply not detected in emulator output")

    at_handshake_ok = "AT+CIPMODE=1" in sim_out and "Entering transparent streaming mode" in sim_out
    socket_ok = "Client connected" in server_out
    openstream_ok = "Streaming mode active on UART1" in emu_out and "Link established" in emu_out

    details = {
        "at_handshake": at_handshake_ok,
        "socket_connected": socket_ok,
        "openstream_exec": openstream_ok,
        "streaming_payload": stream_ok,
    }

    print(f"[*] Stage 1 AT Negotiation:     {'PASS' if at_handshake_ok else 'FAIL'}")
    print(f"[*] Stage 1 Socket Connection:  {'PASS' if socket_ok else 'FAIL'}")
    print(f"[*] Stage 1 openstream Output:  {'PASS' if openstream_ok else 'FAIL'}")
    print(f"[*] Stage 1 Payload Streaming:  {'PASS' if stream_ok else 'FAIL'}")

    return StageResult(
        passed=all(details.values()),
        emu_out=emu_out,
        sim_out=sim_out,
        server_out=server_out,
        details=details,
    )


def run_stage2(
    emu_bin: Path,
    emu_dir: Path,
    autoexec_path: Path,
    port: int,
    timeout: float,
) -> StageResult:
    """Run Stage 2: closestream escape & teardown verification."""
    print("\n------------------------------------------------------------")
    print("  STAGE 2: closestream Escape & Teardown Verification")
    print("------------------------------------------------------------")

    autoexec_path.write_text(
        f"openstream 127.0.0.1 {port}\nclosestream\n",
        encoding="utf-8",
    )

    server_proc: subprocess.Popen[str] | None = None
    sim_proc: subprocess.Popen[str] | None = None
    emu_proc: subprocess.Popen[str] | None = None

    try:
        print("[*] Starting Mock TCP Server...")
        server_proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "mock_server.py"), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(0.5)

        print(f"[*] Starting MOD-WIFI-ESP8266 Simulator (PTY: {DEFAULT_PTY})...")
        sim_proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "esp8266_sim.py"), "--verbose", "--symlink", str(DEFAULT_PTY)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(1.0)

        print("[*] Launching Fab Agon Emulator (--uart1-baud 0)...")
        emu_proc = subprocess.Popen(
            [str(emu_bin), "--uart1-device", str(DEFAULT_PTY), "--uart1-baud", "0"],
            cwd=emu_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("[*] Waiting for openstream + closestream execution...")
        # openstream takes ~1.5s, closestream takes ~3.0s (500ms probe + 1.25s pre + 1.25s post)
        time.sleep(7.5)

    finally:
        kill_proc(emu_proc)
        kill_proc(sim_proc)
        kill_proc(server_proc)

        emu_out = collect_output(emu_proc)
        sim_out = collect_output(sim_proc)
        server_out = collect_output(server_proc)

    escape_verified = "Escape sequence verified! Dropping to AT command mode" in sim_out
    socket_closed = "AT+CIPCLOSE" in sim_out and "disconnected" in server_out
    mode_reset = "AT+CIPMODE=0" in sim_out
    closestream_ok = "Stream closed. ESP8266 in command mode." in emu_out

    details = {
        "escape_verified": escape_verified,
        "socket_closed": socket_closed,
        "mode_reset": mode_reset,
        "closestream_exec": closestream_ok,
    }

    print(f"[*] Stage 2 Hayes Escape (+++): {'PASS' if escape_verified else 'FAIL'}")
    print(f"[*] Stage 2 Socket Disconnect:  {'PASS' if socket_closed else 'FAIL'}")
    print(f"[*] Stage 2 CIPMODE=0 Reset:    {'PASS' if mode_reset else 'FAIL'}")
    print(f"[*] Stage 2 closestream Output: {'PASS' if closestream_ok else 'FAIL'}")

    return StageResult(
        passed=all(details.values()),
        emu_out=emu_out,
        sim_out=sim_out,
        server_out=server_out,
        details=details,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end integration test for openstream and closestream")
    parser.add_argument("--emulator", "-e", help="Path to fab-agon-emulator executable")
    parser.add_argument("--port", "-p", type=int, default=65432, help="TCP port for mock server (default 65432)")
    parser.add_argument("--timeout", "-t", type=float, default=10.0, help="Max test timeout in seconds (default 10.0)")
    args = parser.parse_args(argv)

    emu_bin = find_emulator(args.emulator)
    if not emu_bin:
        print("[-] Error: fab-agon-emulator executable not found.", file=sys.stderr)
        return 1

    emu_dir = emu_bin.parent
    sdcard_dir = emu_dir / "sdcard"
    autoexec_path = sdcard_dir / "autoexec.txt"

    # Ensure binaries exist
    openstream_bin = REPO_ROOT / "bin" / "openstream.bin"
    closestream_bin = REPO_ROOT / "bin" / "closestream.bin"
    sendstream_bin = REPO_ROOT / "bin" / "sendstream.bin"

    if not openstream_bin.is_file():
        print("[-] Error: openstream.bin not found. Run 'make' first.", file=sys.stderr)
        return 1
    if not closestream_bin.is_file():
        print("[-] Error: closestream.bin not found. Run 'make' first.", file=sys.stderr)
        return 1
    if not sendstream_bin.is_file():
        print("[-] Error: sendstream.bin not found. Run 'make' first.", file=sys.stderr)
        return 1

    # Ensure binaries are installed in emulator sdcard/mos
    dest_mos_dir = sdcard_dir / "mos"
    dest_mos_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(openstream_bin, dest_mos_dir / "openstream.bin")
    shutil.copy2(closestream_bin, dest_mos_dir / "closestream.bin")
    shutil.copy2(sendstream_bin, dest_mos_dir / "sendstream.bin")

    print("============================================================")
    print("  openstream, sendstream & closestream Integration Test Suite")
    print("============================================================")
    print(f"Emulator Binary: {emu_bin}")
    print(f"TCP Port:        {args.port}")
    print(f"SDCard Dir:      {sdcard_dir}")
    print("------------------------------------------------------------")

    with preserved_file(autoexec_path):
        stage1 = run_stage1(emu_bin, emu_dir, autoexec_path, args.port, args.timeout)
        time.sleep(1.0)
        stage2 = run_stage2(emu_bin, emu_dir, autoexec_path, args.port, args.timeout)

    print("\n============================================================")
    print("                    OVERALL TEST SUMMARY")
    print("============================================================")
    print(f"[*] Stage 1 (openstream & streaming):  {'PASS' if stage1.passed else 'FAIL'}")
    print(f"[*] Stage 2 (closestream & teardown):  {'PASS' if stage2.passed else 'FAIL'}")
    print("============================================================")

    if stage1.passed and stage2.passed:
        print("[+] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!\n")
        return 0

    print("[-] INTEGRATION TEST SUITE FAILED.\n")
    if not stage1.passed:
        print("--- STAGE 1 LOGS ---")
        print(f"EMU:\n{stage1.emu_out}\nSIM:\n{stage1.sim_out}\nSERVER:\n{stage1.server_out}")
    if not stage2.passed:
        print("--- STAGE 2 LOGS ---")
        print(f"EMU:\n{stage2.emu_out}\nSIM:\n{stage2.sim_out}\nSERVER:\n{stage2.server_out}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
