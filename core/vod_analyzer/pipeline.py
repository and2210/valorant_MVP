from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Event
from typing import Callable

from .evidence_builder import build_evidence
from .metrics import calculate_metrics
from .markers import MarkerStore
from .models import OverlayEvent, VodSession
from .overlay_detector import detect_overlay_events
from .paths import create_vod_structure, ensure_within, resolve_media_tool, safe_name
from .report_builder import (
    build_gpt_payload, build_manifest, objective_summary, write_events_csv,
    write_json_atomic, write_json_once, write_text_atomic,
)
from .scanner import scan_videos
from .session_grouper import group_sessions
from .timeline import correlate_timeline, create_analysis_windows
from .voice_transcriber import transcribe_voice_markers


Progress = Callable[[int, str], None]


class VodPipeline:
    def __init__(self, root: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.root = root.resolve()
        self.ffmpeg = resolve_media_tool(ffmpeg, "ffmpeg")
        self.ffprobe = resolve_media_tool(ffprobe, "ffprobe")
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def scan(self, progress: Progress | None = None) -> list[VodSession]:
        create_vod_structure(self.root)
        items = scan_videos(
            self.root, ffprobe=self.ffprobe,
            progress=(lambda current, total, name: progress(int(current * 100 / max(total, 1)), name)) if progress else None,
            cancelled=self.cancel_event.is_set,
        )
        return group_sessions(items)

    def inspect(self, session: VodSession, *, dry_run: bool = False) -> Path:
        report_dir = self._report_dir(session)
        if dry_run:
            return report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        manifest = report_dir / "manifest.json"
        if not manifest.exists():
            write_json_once(self.root, manifest, build_manifest(self.root, session))
        inconsistencies = report_dir / "inconsistencies.json"
        if not inconsistencies.exists():
            write_json_once(self.root, inconsistencies, {"warnings": session.warnings})
        return report_dir

    def analyze(
        self,
        session: VodSession,
        calibration_file: Path,
        *,
        include_evidence: bool = True,
        maximum_images: int = 40,
        progress: Progress | None = None,
    ) -> Path:
        if any(not item.stable or item.probe_error for item in session.files):
            raise RuntimeError("Session contains unstable or invalid files; analysis refused.")
        report_dir = self.inspect(session)
        checkpoint = report_dir / "processing_state.json"
        if checkpoint.exists():
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            if state.get("status") == "complete" and (report_dir / "timeline.json").exists():
                return report_dir
        log_path = ensure_within(self.root, report_dir / "processing.log")
        logger = _session_logger(session.session_id, log_path)
        logger.info("Starting local read-only analysis")
        all_events: list[OverlayEvent] = []
        overlay_by_part: list[tuple[int, OverlayEvent]] = []
        offset_ms = 0
        for index, item in enumerate(session.files, 1):
            if self.cancel_event.is_set():
                _write_state(checkpoint, "cancelled", len(all_events))
                logger.warning("Analysis cancelled")
                return report_dir
            if progress:
                progress(int((index - 1) * 70 / len(session.files)), f"Detectando overlay: {item.path.name}")
            events = detect_overlay_events(self.root, item.path, calibration_file, self.cancel_event.is_set)
            overlay_by_part.extend((index, event) for event in events)
            for event in events:
                all_events.append(OverlayEvent(
                    timestamp_ms=event.timestamp_ms + offset_ms,
                    event=event.event,
                    state=event.state,
                    confidence=event.confidence,
                    uncertain=event.uncertain,
                ))
            offset_ms += round(item.duration_seconds * 1000)
            _write_state(checkpoint, "running", len(all_events))
        fps = session.files[0].fps if session.files else 30.0
        metrics = calculate_metrics(all_events, fps)
        markers = MarkerStore(self.root, session.session_id).load()
        timeline = correlate_timeline(session, overlay_by_part, markers)
        windows = [window.to_dict() for window in create_analysis_windows(
            timeline,
            before_ms=int(self._setting("frame_window_before_ms", 3000)),
            after_ms=int(self._setting("frame_window_after_ms", 2000)),
        )]
        events_path = report_dir / "overlay_events.csv"
        if not events_path.exists():
            write_events_csv(self.root, events_path, all_events)
        metrics_path = report_dir / "mechanical_metrics.json"
        if not metrics_path.exists():
            write_json_once(self.root, metrics_path, metrics)
        timeline_path = report_dir / "timeline.json"
        write_json_atomic(self.root, timeline_path, timeline)
        windows_path = report_dir / "analysis_windows.json"
        write_json_atomic(self.root, windows_path, {"schema_version": 1, "windows": windows})
        evidence: list[str] = []
        if include_evidence and session.files and session.mode == "dm" and not self.cancel_event.is_set():
            existing_evidence = sorted((report_dir / "evidence").glob("*.jpg")) if (report_dir / "evidence").exists() else []
            existing_sheet = report_dir / "contact_sheet_01.jpg"
            if existing_evidence or existing_sheet.exists():
                evidence = [str(path.relative_to(report_dir)).replace("\\", "/") for path in existing_evidence]
                if existing_sheet.exists():
                    evidence.append(existing_sheet.name)
            else:
                if progress:
                    progress(80, "Extraindo evidências selecionadas")
                evidence = build_evidence(
                    self.root, session.files[0].path, all_events, report_dir,
                    ffmpeg=self.ffmpeg, maximum_images=maximum_images,
                )
        summary_path = report_dir / "objective_summary.md"
        write_text_atomic(self.root, summary_path, objective_summary(session, metrics, evidence, timeline, windows))
        payload_path = report_dir / "gpt_payload.json"
        write_json_atomic(self.root, payload_path, build_gpt_payload(session, metrics, evidence, timeline, windows))
        _write_state(checkpoint, "complete", len(all_events))
        logger.info("Analysis complete with %d overlay events", len(all_events))
        if progress:
            progress(100, "Análise local concluída")
        return report_dir

    def add_manual_marker(
        self, session: VodSession, *, marker_type: str, part_index: int,
        local_timestamp_ms: int, text: str = "",
    ) -> dict:
        # Conversion validation prevents markers outside a part.
        from .timeline import build_part_spans, local_to_global
        local_to_global(build_part_spans(session), part_index, local_timestamp_ms)
        marker = MarkerStore(self.root, session.session_id).add(
            marker_type=marker_type, part_index=part_index,
            local_timestamp_ms=local_timestamp_ms, text=text,
        )
        self._invalidate_timeline(session)
        return marker

    def transcribe_markers(
        self, session: VodSession, *, progress: Progress | None = None,
    ) -> list[dict]:
        markers = transcribe_voice_markers(
            self.root, session, ffmpeg=self.ffmpeg,
            model_name=str(self._setting("voice_model", "small")),
            language=str(self._setting("voice_language", "pt")),
            marker_terms=list(self._setting("voice_marker_terms", ["analisar", "analisa", "por que", "marcar", "marca"])),
            cancelled=self.cancel_event.is_set, progress=progress,
        )
        self._invalidate_timeline(session)
        return markers

    def _report_dir(self, session: VodSession) -> Path:
        return ensure_within(self.root, self.root / "Relatorios" / safe_name(session.session_id))

    def _invalidate_timeline(self, session: VodSession) -> None:
        checkpoint = self._report_dir(session) / "processing_state.json"
        if checkpoint.exists():
            _write_state(checkpoint, "timeline_pending", 0)

    @staticmethod
    def _setting(_name: str, default):
        # Pipeline remains usable without importing the application config layer.
        from core.config import load_config
        return dict(load_config().vod_analyzer or {}).get(_name, default)


def _write_state(path: Path, status: str, event_count: int) -> None:
    path.write_text(json.dumps({"status": status, "event_count": event_count}, indent=2), encoding="utf-8")


def _session_logger(name: str, path: Path) -> logging.Logger:
    logger = logging.getLogger(f"vod_analyzer.{safe_name(name)}")
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == path for handler in logger.handlers):
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
