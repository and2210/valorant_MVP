from datetime import datetime, timedelta
from pathlib import Path

from core.vod_analyzer.models import MediaInfo
from core.vod_analyzer.session_grouper import group_sessions


def media(path: str, file_id: str, minute: int = 0) -> MediaInfo:
    created = (datetime(2026, 7, 5, 12, 0) + timedelta(minutes=minute)).astimezone().isoformat()
    return MediaInfo(Path(path), file_id, 100, created, created, duration_seconds=900, fps=30)


def test_ranked_parts_are_ordered_and_missing_part_reported() -> None:
    sessions = group_sessions([
        media("Entrada/Ranked/Ranked_01/Ranked_01_Parte-03.mp4", "c", 30),
        media("Entrada/Ranked/Ranked_01/Ranked_01_Parte-01.mp4", "a", 0),
    ])
    session = sessions[0]
    assert [item.path.name for item in session.files] == ["Ranked_01_Parte-01.mp4", "Ranked_01_Parte-03.mp4"]
    assert any("Parte-02" in warning for warning in session.warnings)


def test_duplicate_identifier_is_reported() -> None:
    sessions = group_sessions([
        media("Entrada/DM/one.mp4", "same"),
        media("Entrada/DM/two.mp4", "same", 1),
    ])
    assert all(any("duplicata" in warning.lower() for warning in session.warnings) for session in sessions)


def test_dm_chronological_numbering() -> None:
    sessions = group_sessions([
        media("Entrada/DM/DM_02.mp4", "b", 2),
        media("Entrada/DM/DM_01.mp4", "a", 1),
    ])
    assert [session.session_id for session in sessions] == ["DM_2026-07-05_01", "DM_2026-07-05_02"]
