from __future__ import annotations

import compileall
import os
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    required = [ROOT / "core", ROOT / "ui", ROOT / "tools", ROOT / "launch.pyw"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("health check: missing required paths")
        for path in missing:
            print(path)
        return 1

    external_venv = Path(os.environ["LOCALAPPDATA"]) / "RadianteDaily" / ".venv"
    print(f"external venv: {external_venv}")
    print(f"external venv exists: {external_venv.is_dir()}")

    for directory in ("core", "ui", "tools"):
        if not compileall.compile_dir(ROOT / directory, quiet=1):
            return 1
    py_compile.compile(str(ROOT / "launch.pyw"), doraise=True)
    py_compile.compile(str(ROOT / "app.py"), doraise=True)
    print("health check: safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
