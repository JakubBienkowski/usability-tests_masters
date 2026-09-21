import ctypes
import os
import subprocess
import sys


SDK_DIR = r"C:\Program Files (x86)\Visual Interaction\myGaze SDK\bin\x64"
DLL_PATH = os.path.join(SDK_DIR, "myGazeAPI.dll")
TIMEOUT_SECONDS = 8


def call_sdk(function_name):
    try:
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(SDK_DIR)
        print(f"stage: loading {DLL_PATH}", flush=True)
        api = ctypes.WinDLL(DLL_PATH)
        function = getattr(api, function_name)
        function.restype = ctypes.c_int
        print(f"stage: calling {function_name}", flush=True)
        result = function()
        print(f"result: {result}", flush=True)
        return 0
    except BaseException as exc:
        print(f"error: {type(exc).__name__}: {exc}", flush=True)
        return 1


def run_guarded(function_name):
    command = [sys.executable, os.path.abspath(__file__), "--worker", function_name]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        status = f"EXIT_{result.returncode}"
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        status = "TIMEOUT"
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = stdout + stderr

    print(f"\n[{function_name}] {status}")
    print(output.rstrip() or "  no output")
    return status, output


def main():
    if not os.path.isfile(DLL_PATH):
        print(f"Missing SDK DLL: {DLL_PATH}")
        return 2

    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return call_sdk(sys.argv[2])

    functions = sys.argv[1:] or ["iV_Connect", "iV_Start"]
    for function_name in functions:
        run_guarded(function_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
