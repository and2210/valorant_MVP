import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from core.vod_analyzer.models import MediaInfo, VodSession
from core.vod_analyzer.paths import ensure_within
from core.vod_analyzer.report_builder import build_gpt_payload, build_manifest, objective_summary, write_json_once
from core.vod_analyzer.scanner import is_file_stable
from core.vod_analyzer.pipeline import VodPipeline


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "vods"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_within(root, tmp_path / "outside.json")


def test_recent_file_is_not_stable(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"partial")
    assert is_file_stable(video, minimum_age_seconds=30) is False


def test_write_once_prevents_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    write_json_once(tmp_path, target, {"first": True})
    with pytest.raises(FileExistsError):
        write_json_once(tmp_path, target, {"second": True})
    assert json.loads(target.read_text())["first"] is True


def test_manifest_serialization_uses_relative_path(tmp_path: Path) -> None:
    video = tmp_path / "Entrada" / "DM" / "one.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    now = datetime.now().astimezone().isoformat()
    item = MediaInfo(video, "abc", 1, now, now, duration_seconds=10)
    payload = build_manifest(tmp_path, VodSession("one", "dm", [item]))
    assert payload["files"][0]["path"] == str(Path("Entrada/DM/one.mp4"))
    assert payload["originals_modified"] is False


def test_complete_checkpoint_resumes_without_reprocessing(tmp_path: Path) -> None:
    video = tmp_path / "Entrada" / "DM" / "one.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"original")
    now = datetime.now().astimezone().isoformat()
    item = MediaInfo(video, "abc", 8, now, now, duration_seconds=10, fps=30)
    session = VodSession("one", "dm", [item])
    report = tmp_path / "Relatorios" / "one"
    report.mkdir(parents=True)
    (report / "processing_state.json").write_text('{"status":"complete","event_count":4}')
    (report / "timeline.json").write_text('{"schema_version":1,"events":[]}', encoding="utf-8")
    result = VodPipeline(tmp_path).analyze(session, tmp_path / "missing-calibration.json")
    assert result == report
    assert video.read_bytes() == b"original"


def test_reports_include_objective_timeline_layers() -> None:
    now = datetime.now().astimezone().isoformat()
    item = MediaInfo(Path("one.mp4"), "abc", 1, now, now, duration_seconds=10)
    session = VodSession("one", "dm", [item])
    timeline = {
        "events": [
            {"evidence_class": "fact"},
            {"evidence_class": "inference"},
            {"evidence_class": "uncertainty"},
        ]
    }
    windows = [{"window_id": "window-1"}]
    summary = objective_summary(session, {"event_count": 0}, [], timeline, windows)
    payload = build_gpt_payload(session, {}, [], timeline, windows)
    assert "Eventos factuais: 1" in summary
    assert payload["timeline"] is timeline
    assert payload["frame_analysis_windows"] == windows
    assert payload["interpretation_layers"]["recommendations"] == []
