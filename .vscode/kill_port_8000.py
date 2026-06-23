import os
import platform
import signal
import subprocess

PORT = 8000

def windows_pids():
    cmd = (
        f"Get-NetTCPConnection -LocalPort {PORT} "
        "-State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
    )
    return {int(x.strip()) for x in r.stdout.splitlines() if x.strip().isdigit()}

def unix_pids():
    r = subprocess.run(
        ["sh", "-lc", f"lsof -ti tcp:{PORT} -sTCP:LISTEN"],
        capture_output=True,
        text=True,
    )
    return {int(x.strip()) for x in r.stdout.splitlines() if x.strip().isdigit()}

try:
    is_windows = platform.system().lower().startswith("win")
    pids = windows_pids() if is_windows else unix_pids()

    for pid in pids:
        if is_windows:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)

    print("port_8000_ready")
except Exception as e:
    print(f"port_8000_ready: {e}")