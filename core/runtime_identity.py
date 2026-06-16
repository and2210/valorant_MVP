from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _safe_resolve(path: str | Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _run_git(args: list[str], project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    value = (result.stdout or "").strip()
    return value or None


def _is_python_inside(expected_venv: Path, python_executable: Path) -> bool:
    expected_root = _safe_resolve(expected_venv)
    current_python = _safe_resolve(python_executable)
    return expected_root == current_python or expected_root in current_python.parents


@dataclass(slots=True)
class RuntimeIdentity:
    app_version: str
    git_branch: str | None
    git_short_commit: str | None
    project_root: Path
    current_working_directory: Path
    python_executable: Path
    expected_venv: Path
    is_expected_venv: bool
    launch_entry_file: Path
    process_pid: int
    warnings: list[str]

    def as_text(self) -> str:
        git_branch = self.git_branch or "unavailable"
        git_short_commit = self.git_short_commit or "unavailable"
        return "\n".join(
            [
                f"App version: {self.app_version}",
                f"Git branch: {git_branch}",
                f"Git short commit: {git_short_commit}",
                f"Project root: {self.project_root}",
                f"Current working directory: {self.current_working_directory}",
                f"Python executable: {self.python_executable}",
                f"Expected venv path: {self.expected_venv}",
                f"Python matches expected venv: {'Yes' if self.is_expected_venv else 'No'}",
                f"Launch entry file: {self.launch_entry_file}",
                f"Process PID: {self.process_pid}",
            ]
        )


def collect_runtime_identity(
    *,
    app_version: str,
    project_root: Path,
    launch_entry_file: str | Path,
) -> RuntimeIdentity:
    resolved_project_root = _safe_resolve(project_root)
    launch_path = _safe_resolve(launch_entry_file)
    current_working_directory = _safe_resolve(Path.cwd())
    python_executable = _safe_resolve(sys.executable)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        expected_venv = _safe_resolve(Path(local_app_data) / "RadianteDaily" / ".venv")
    else:
        expected_venv = Path("%LOCALAPPDATA%") / "RadianteDaily" / ".venv"
    git_branch = _run_git(["branch", "--show-current"], resolved_project_root)
    git_short_commit = _run_git(["rev-parse", "--short", "HEAD"], resolved_project_root)
    is_expected_venv = bool(local_app_data) and _is_python_inside(expected_venv, python_executable)

    warnings: list[str] = []
    if not is_expected_venv:
        warnings.append("Python is not running from %LOCALAPPDATA%\\RadianteDaily\\.venv.")
    if git_branch is None or git_short_commit is None:
        warnings.append("Git branch or commit could not be detected.")
    elif git_branch != "main":
        warnings.append(f"Git branch is {git_branch}, not main.")
    if current_working_directory != resolved_project_root:
        warnings.append("Current working directory differs from the project root.")

    return RuntimeIdentity(
        app_version=app_version,
        git_branch=git_branch,
        git_short_commit=git_short_commit,
        project_root=resolved_project_root,
        current_working_directory=current_working_directory,
        python_executable=python_executable,
        expected_venv=expected_venv,
        is_expected_venv=is_expected_venv,
        launch_entry_file=launch_path,
        process_pid=os.getpid(),
        warnings=warnings,
    )
