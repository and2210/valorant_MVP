from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = PROJECT_ROOT / "launch.pyw"
DESKTOP = Path.home() / "Desktop"
SHORTCUT_PATH = DESKTOP / "Radiante Daily.lnk"


def get_pythonw_path() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "pythonw.exe":
        return executable

    candidate = executable.with_name("pythonw.exe")
    if candidate.exists():
        return candidate

    return executable


def main() -> None:
    if not LAUNCHER.exists():
        raise SystemExit(f"Launcher not found: {LAUNCHER}")

    pythonw_path = get_pythonw_path()
    powershell_script = f"""
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut('{SHORTCUT_PATH}')
$shortcut.TargetPath = '{pythonw_path}'
$shortcut.Arguments = '\"{LAUNCHER}\"'
$shortcut.WorkingDirectory = '{PROJECT_ROOT}'
$shortcut.IconLocation = '{pythonw_path},0'
$shortcut.Description = 'Launch Radiante Daily silently'
$shortcut.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
        check=True,
    )
    print(f"Desktop shortcut created: {SHORTCUT_PATH}")


if __name__ == "__main__":
    main()
