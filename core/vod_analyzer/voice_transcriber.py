from __future__ import annotations

import math
import subprocess
import unicodedata
from collections.abc import Callable
from pathlib import Path

from .markers import MarkerStore
from .models import VodSession
from .paths import ensure_within


def extract_audio(video: Path, target: Path, ffmpeg: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target
    command = [
        ffmpeg, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(target),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=180, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr.decode(errors="replace") or "Audio extraction failed")[:1000])
    return target


def transcribe_voice_markers(
    root: Path,
    session: VodSession,
    *,
    ffmpeg: str,
    model_name: str = "small",
    language: str = "pt",
    marker_terms: list[str] | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required for local voice markers") from exc
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    store = MarkerStore(root, session.session_id)
    existing = store.load()
    # Retain manual markers; replace generated voice markers to keep reruns idempotent.
    retained = [item for item in existing if item.get("source") != "voice_transcription"]
    previous_voice = [item for item in existing if item.get("source") == "voice_transcription"]
    generated: list[dict] = []
    for index, item in enumerate(session.files, 1):
        if cancelled and cancelled():
            return previous_voice
        audio = ensure_within(root, root / "Cache" / "audio" / session.session_id / f"part_{index:02d}.wav")
        extract_audio(item.path, audio, ffmpeg)
        if progress:
            progress(round((index - 1) * 100 / max(len(session.files), 1)), f"Transcrevendo áudio: {item.path.name}")
        segments, _info = model.transcribe(str(audio), language=language, vad_filter=True, beam_size=1)
        for segment in segments:
            if cancelled and cancelled():
                return previous_voice
            text = str(segment.text or "").strip()
            if not text or not is_voice_marker(text, marker_terms):
                continue
            confidence = max(0.0, min(math.exp(float(segment.avg_logprob or -10.0)), 1.0))
            marker = {
                "marker_id": f"voice-{index}-{round(float(segment.start) * 1000)}",
                "marker_type": "voice_marker",
                "part_index": index,
                "local_timestamp_ms": round(float(segment.start) * 1000),
                "end_local_timestamp_ms": round(float(segment.end) * 1000),
                "text": text,
                "source": "voice_transcription",
                "confidence": confidence,
            }
            generated.append(marker)
    store.save(retained + generated)
    if progress:
        progress(100, f"{len(generated)} marcações de voz geradas")
    return generated


def is_voice_marker(text: str, marker_terms: list[str] | None) -> bool:
    if marker_terms is None or marker_terms == []:
        return True
    normalized_text = _normalize(text)
    return any(_normalize(term) in normalized_text for term in marker_terms if term.strip())


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))
