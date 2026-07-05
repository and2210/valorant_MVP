from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppModule:
    name: str
    status: str
    description: str


FUTURE_MODULES: tuple[AppModule, ...] = (
    AppModule(
        name="Tracker/Henrik Import",
        status="Not installed",
        description="External match import is reserved for the future modules phase.",
    ),
    AppModule(
        name="Match Analysis",
        status="Installed (local MVP)",
        description="VOD Analyzer processes local recordings and exports objective evidence packages.",
    ),
    AppModule(
        name="Coach/Analyst",
        status="Not installed",
        description="Coaching summaries and analyst views are planned as optional extensions.",
    ),
)
