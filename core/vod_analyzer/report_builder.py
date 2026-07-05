from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from .models import OverlayEvent, VodSession
from .paths import ensure_within


def write_json_once(root: Path, path: Path, payload: Any) -> Path:
    path = ensure_within(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def write_json_atomic(root: Path, path: Path, payload: Any) -> Path:
    path = ensure_within(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def write_text_atomic(root: Path, path: Path, text: str) -> Path:
    path = ensure_within(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def build_manifest(root: Path, session: VodSession) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "mode": session.mode,
        "duration_seconds": round(session.duration_seconds, 3),
        "confidence": session.confidence,
        "warnings": session.warnings,
        "files": [item.to_dict(root) for item in session.files],
        "originals_modified": False,
    }


def write_events_csv(root: Path, path: Path, events: list[OverlayEvent]) -> Path:
    path = ensure_within(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_ms", "event", "state", "confidence", "uncertain"])
        writer.writeheader()
        for event in events:
            writer.writerow(event.to_dict())
    return path


def objective_summary(
    session: VodSession, metrics: dict[str, Any], evidence: list[str],
    timeline: dict[str, Any] | None = None, windows: list[dict[str, Any]] | None = None,
) -> str:
    timeline = timeline or {}
    timeline_events = timeline.get("events") or []
    fact_count = sum(event.get("evidence_class") == "fact" for event in timeline_events)
    inference_count = sum(event.get("evidence_class") == "inference" for event in timeline_events)
    uncertainty_count = sum(event.get("evidence_class") == "uncertainty" for event in timeline_events)
    resolution = metrics.get("temporal_resolution_ms")
    lines = [
        f"# VOD Analyzer — {session.session_id}", "",
        "## Fatos extraídos", "",
        f"- Modo: {session.mode}",
        f"- Partes: {len(session.files)}",
        f"- Duração total: {session.duration_seconds:.2f} s",
        f"- Eventos do overlay: {metrics.get('event_count', 0)}",
        f"- Sobreposições objetivas A/D + LMB: {metrics.get('movement_fire_overlap_count', 0)}",
        f"- Ativações prolongadas de LMB (>=500 ms): {metrics.get('long_lmb_count', 0)}",
        f"- Alternâncias A/D: {metrics.get('ad_alternation_count', 0)}",
        f"- Eventos incertos: {metrics.get('uncertain_event_count', 0)}", "",
        "## Linha do tempo unificada", "",
        f"- Eventos factuais: {fact_count}",
        f"- Inferências sinalizadas: {inference_count}",
        f"- Registros incertos: {uncertainty_count}",
        f"- Janelas selecionadas para análise frame a frame: {len(windows or [])}",
        "- Arquivo estruturado: `timeline.json`",
        "- Plano de janelas: `analysis_windows.json`", "",
        "## Limitações", "",
        f"- Resolução temporal aproximada: {resolution} ms." if resolution else "- FPS indisponível; resolução temporal não determinada.",
        "- A sobreposição entre movimento e disparo é um fato observado, não uma classificação automática de erro.",
        "- O sistema não infere intenção, qualidade competitiva ou estado psicológico.",
    ]
    if session.warnings:
        lines.extend(["", "## Inconsistências", "", *[f"- {warning}" for warning in session.warnings]])
    if evidence:
        lines.extend(["", "## Evidências", "", *[f"- `{item}`" for item in evidence]])
    return "\n".join(lines) + "\n"


def build_gpt_payload(
    session: VodSession, metrics: dict[str, Any], evidence: list[str],
    timeline: dict[str, Any] | None = None, windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "session": {"id": session.session_id, "mode": session.mode},
        "map": None,
        "agent": None,
        "parts": [item.path.name for item in session.files],
        "duration_seconds": round(session.duration_seconds, 3),
        "overlay_metrics": metrics,
        "important_events": [],
        "rounds": [],
        "images": evidence,
        "timeline": timeline or {},
        "frame_analysis_windows": windows or [],
        "interpretation_layers": {
            "facts": "timeline events with evidence_class=fact",
            "inferences": "timeline events with evidence_class=inference",
            "uncertainties": "timeline events with evidence_class=uncertainty",
            "recommendations": [],
        },
        "limitations": [
            "Local overlay detection only.",
            "No intent or competitive outcome inferred.",
            "Uncertain events require manual review.",
        ],
        "confidence": session.confidence,
        "api_sent": False,
    }
