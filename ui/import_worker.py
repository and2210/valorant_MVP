from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot


SECRET_PATTERNS = [
    re.compile(r"HDEV-[A-Za-z0-9-]+"),
    re.compile(r"(HENRIK_API_KEY\s*=\s*)[^\s#]+"),
]


def safe_error_message(error: Exception) -> str:
    message = str(error) or type(error).__name__
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("(HENRIK"):
            message = pattern.sub(r"\1***", message)
        else:
            message = pattern.sub("***", message)
    return message


class TrackerImportWorker(QObject):
    progress = Signal(str, float, str)
    status = Signal(str, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        kind: str,
        import_callable: Callable[..., Any],
        import_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.kind = kind
        self.import_callable = import_callable
        self.import_kwargs = dict(import_kwargs or {})

    @Slot()
    def run(self) -> None:
        label = "Ranked" if self.kind == "ranked" else "Tracker"
        try:
            self.status.emit(self.kind, f"{label}: importando")
            kwargs = dict(self.import_kwargs)
            kwargs["progress_callback"] = self._on_progress
            result = self.import_callable(**kwargs)
        except Exception as error:
            self.failed.emit(self.kind, safe_error_message(error))
            return

        self.finished.emit(self.kind, result)

    def _on_progress(self, progress: dict[str, Any]) -> None:
        label = "Ranked" if self.kind == "ranked" else "Tracker"
        try:
            percent = float(progress.get("percent", 0.0))
        except (TypeError, ValueError):
            percent = 0.0
        self.progress.emit(self.kind, percent, f"{label}: importando")
