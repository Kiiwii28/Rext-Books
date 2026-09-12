"""Production entry point for the packaged .exe.

``app.py``'s own ``__main__`` block stays a plain dev server (Flask's debug
reloader, which spawns a subprocess of itself — fine on the command line,
but breaks once frozen). This is what actually gets built into the .exe: it
starts the real server quietly (no debug, no reloader, no console output)
and opens the user's browser to it.

Safe to double-click more than once: if the app is already running, it just
opens another tab instead of trying (and failing) to bind the port again.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import requests

import app as appmod
import config

HOST = "127.0.0.1"
# Deliberately NOT 5000 — that's the dev server's port (python app.py). Using
# a different one means a packaged copy left running in the background (this
# launches with no console window, so there's nothing to notice) can never
# silently squat on the same port as the dev server and serve stale content
# under it without anyone realizing.
PORT = 5001
URL = f"http://{HOST}:{PORT}"


def _ensure_desktop_shortcut() -> None:
    """Drop a "Rextbooks" shortcut on the Desktop the first time this runs.

    Built here (not baked in ahead of time) so the paths are always correct
    for wherever this folder actually ended up — the whole thing can be
    copied, renamed, moved to another machine, anything, and it still works.
    Best-effort: any failure here should never stop the app from starting.
    """
    if sys.platform != "win32":
        return
    try:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        target = pyw if pyw.exists() else Path(sys.executable)
        launcher = (config.BASE_DIR / "launcher.py").resolve()
        icon = config.BASE_DIR / "app.ico"
        # Let PowerShell resolve the real Desktop path itself — %USERPROFILE%\Desktop
        # isn't always right (OneDrive folder redirection moves it), and this also
        # sidesteps a stray POSIX-style $HOME some shells (Git Bash, etc.) leave
        # behind in the environment, which would otherwise send Path.home() astray.
        ps = (
            "$desktop = [Environment]::GetFolderPath('Desktop');"
            "$lnk = Join-Path $desktop 'Rextbooks.lnk';"
            "if (-not (Test-Path $lnk)) {{"
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);"
            "$s.TargetPath = '{target}';"
            "$s.Arguments = '\"{launcher}\"';"
            "$s.WorkingDirectory = '{cwd}';"
            "$s.IconLocation = '{icon}';"
            "$s.Save() }}"
        ).format(target=target, launcher=launcher, cwd=config.BASE_DIR, icon=icon)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass   # no desktop icon is a minor inconvenience, not worth failing the launch over


def _already_running() -> bool:
    try:
        return requests.get(f"{URL}/health", timeout=1.5).ok
    except requests.RequestException:
        return False


def _wait_for_server_then_open() -> None:
    for _ in range(100):   # ~10s
        try:
            with socket.create_connection((HOST, PORT), timeout=0.25):
                break
        except OSError:
            time.sleep(0.1)
    webbrowser.open(URL)


def _report_failure(detail: str) -> None:
    try:
        (config.BASE_DIR / "error.log").write_text(detail, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Rextbooks couldn't start. Details were saved to error.log,\n"
                "next to the app, if you need to share them for help.",
                "Rextbooks",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass


def main() -> None:
    try:
        if _already_running():
            webbrowser.open(URL)
            return
        _ensure_desktop_shortcut()
        threading.Thread(target=_wait_for_server_then_open, daemon=True).start()
        appmod.app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)
    except Exception:
        _report_failure(traceback.format_exc())


if __name__ == "__main__":
    main()
