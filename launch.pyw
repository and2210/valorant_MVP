from __future__ import annotations

import os
import runpy
import subprocess
import sys
import traceback
from pathlib import Path


APP_VERSION = "v0.21.12"
PROJECT_ROOT = Path(__file__).resolve().parent
APP_FILE = PROJECT_ROOT / "app.py"
LOG_FILE = PROJECT_ROOT / "launch_error.log"


def show_message(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def write_error_log(message: str) -> None:
    try:
        LOG_FILE.write_text(message, encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    if not APP_FILE.exists():
        message = (
            f"Radiante Daily {APP_VERSION} could not find app.py.\n\n"
            f"Expected path:\n{APP_FILE}"
        )
        write_error_log(message)
        show_message("Radiante Daily", message)
        return

    preferred = (
        Path(os.environ["LOCALAPPDATA"])
        / "RadianteDaily"
        / ".venv"
        / "Scripts"
        / "pythonw.exe"
    )
    fallback = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    candidates = [path for path in (preferred, fallback) if path.is_file()]
    current_python = Path(sys.executable).resolve()

    if not any(current_python == path.resolve() for path in candidates):
        if candidates:
            try:
                subprocess.Popen([str(candidates[0]), str(Path(__file__).resolve())], cwd=PROJECT_ROOT)
            except OSError as error:
                message = f"Radiante Daily {APP_VERSION} could not start its local environment.\n\n{error}"
                write_error_log(message)
                show_message("Radiante Daily", message)
            return

        message = (
            f"Radiante Daily {APP_VERSION} needs a local Python environment.\n\n"
            "Create it at:\n"
            f"{preferred.parent.parent}\n\n"
            "Then install requirements.txt. Global Python is not used as a dependency fallback."
        )
        write_error_log(message)
        show_message("Radiante Daily", message)
        return

    try:
        os.chdir(PROJECT_ROOT)
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        sys.argv = [str(APP_FILE), "--gui"]
        runpy.run_path(str(APP_FILE), run_name="__main__")
    except Exception as error:
        details = (
            f"Radiante Daily {APP_VERSION} failed to launch.\n\n"
            f"Project root: {PROJECT_ROOT}\n"
            f"Python: {sys.executable}\n\n"
            f"{type(error).__name__}: {error}\n\n"
            f"{traceback.format_exc()}"
        )
        write_error_log(details)
        show_message("Radiante Daily", f"Launch failed.\n\nA log was saved to:\n{LOG_FILE}")


if __name__ == "__main__":
    main()
