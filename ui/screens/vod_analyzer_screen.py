from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QInputDialog, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.config import load_config, save_config
from core.vod_analyzer.models import VodSession
from core.vod_analyzer.pipeline import VodPipeline
from ui.vod_calibration_dialog import OverlayCalibrationDialog


class VodWorker(QThread):
    progress = Signal(int, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, action, parent=None) -> None:
        super().__init__(parent)
        self.action = action

    def run(self) -> None:
        try:
            self.result.emit(self.action(lambda value, text: self.progress.emit(value, text)))
        except Exception as exc:
            self.failed.emit(str(exc))


class VodAnalyzerScreen(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.sessions: list[VodSession] = []
        self.worker: VodWorker | None = None
        self.pipeline: VodPipeline | None = None
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("VOD Analyzer — processamento local e somente leitura"))
        root_row = QHBoxLayout()
        self.root_edit = QLineEdit()
        browse = QPushButton("Selecionar raiz")
        browse.clicked.connect(self.select_root)
        self.mode_filter = QComboBox()
        self.mode_filter.addItems(["Todos", "DM", "Ranked"])
        self.mode_filter.currentIndexChanged.connect(self.refresh_table)
        root_row.addWidget(self.root_edit, stretch=1)
        root_row.addWidget(browse)
        root_row.addWidget(self.mode_filter)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("Inspecionar")
        self.calibrate_button = QPushButton("Calibrar overlay")
        self.analyze_button = QPushButton("Analisar localmente")
        self.marker_button = QPushButton("Adicionar marcador")
        self.voice_button = QPushButton("Transcrever voz")
        self.evidence_button = QPushButton("Gerar evidências")
        self.export_button = QPushButton("Exportar pacote GPT")
        self.open_button = QPushButton("Abrir relatório")
        self.cancel_button = QPushButton("Cancelar")
        self.scan_button.clicked.connect(self.scan)
        self.calibrate_button.clicked.connect(self.calibrate)
        self.analyze_button.clicked.connect(lambda: self.analyze(True))
        self.marker_button.clicked.connect(self.add_marker)
        self.voice_button.clicked.connect(self.transcribe_voice)
        self.evidence_button.clicked.connect(lambda: self.analyze(True))
        self.export_button.clicked.connect(lambda: self.analyze(True))
        self.open_button.clicked.connect(self.open_report)
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.scan_button, self.calibrate_button, self.marker_button, self.voice_button, self.analyze_button, self.evidence_button, self.export_button, self.open_button, self.cancel_button):
            actions.addWidget(button)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Sessão", "Modo", "Partes", "Duração", "Status", "Confiança", "Inconsistências"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.progress = QProgressBar()
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumHeight(150)
        layout.addLayout(root_row)
        layout.addLayout(actions)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.progress)
        layout.addWidget(self.logs)

    def _load_settings(self) -> None:
        config = load_config()
        settings = dict(config.vod_analyzer or {})
        self.root_edit.setText(str(settings.get("root") or ""))

    def _save_settings(self, root: Path, calibration: Path | None = None) -> None:
        config = load_config()
        settings = dict(config.vod_analyzer or {})
        settings["root"] = str(root)
        if calibration:
            settings["calibration"] = str(calibration)
        config.vod_analyzer = settings
        save_config(config)

    def select_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Raiz dos VODs", self.root_edit.text())
        if selected:
            self.root_edit.setText(selected)
            self._save_settings(Path(selected))

    def _make_pipeline(self) -> VodPipeline:
        root = Path(self.root_edit.text().strip())
        if not root.is_dir():
            raise ValueError("Selecione uma pasta raiz válida.")
        config = load_config()
        settings = dict(config.vod_analyzer or {})
        return VodPipeline(root, ffmpeg=str(settings.get("ffmpeg") or "ffmpeg"), ffprobe=str(settings.get("ffprobe") or "ffprobe"))

    def scan(self) -> None:
        try:
            self.pipeline = self._make_pipeline()
        except Exception as exc:
            QMessageBox.warning(self, "Raiz inválida", str(exc))
            return
        self._run(lambda progress: self.pipeline.scan(progress), self._scan_complete)

    def _scan_complete(self, sessions: object) -> None:
        self.sessions = list(sessions)
        self.refresh_table()
        self.logs.appendPlainText(f"{len(self.sessions)} sessão(ões) detectada(s).")

    def refresh_table(self) -> None:
        selected_mode = self.mode_filter.currentText().lower()
        visible = [s for s in self.sessions if selected_mode == "todos" or s.mode == selected_mode]
        self.table.setRowCount(len(visible))
        for row, session in enumerate(visible):
            self.table.setItem(row, 0, QTableWidgetItem(session.session_id))
            self.table.setItem(row, 1, QTableWidgetItem(session.mode.upper()))
            self.table.setItem(row, 2, QTableWidgetItem(str(len(session.files))))
            self.table.setItem(row, 3, QTableWidgetItem(f"{session.duration_seconds:.1f}s"))
            status = "Pronto" if all(item.stable and not item.probe_error for item in session.files) else "Revisão necessária"
            self.table.setItem(row, 4, QTableWidgetItem(status))
            self.table.setItem(row, 5, QTableWidgetItem(f"{session.confidence:.0%}"))
            self.table.setItem(row, 6, QTableWidgetItem("; ".join(session.warnings)))
            self.table.item(row, 0).setData(256, session.session_id)
        self.table.resizeColumnsToContents()

    def selected_session(self) -> VodSession | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        session_id = self.table.item(row, 0).data(256)
        return next((session for session in self.sessions if session.session_id == session_id), None)

    def calibrate(self) -> None:
        session = self.selected_session()
        if not session:
            QMessageBox.information(self, "Selecione uma sessão", "Inspecione e selecione uma sessão primeiro.")
            return
        try:
            pipeline = self._make_pipeline()
            dialog = OverlayCalibrationDialog(pipeline.root, session.files[0].path, pipeline.ffmpeg, self)
            if dialog.exec():
                self._save_settings(pipeline.root, dialog.calibration_path)
                self.logs.appendPlainText(f"Calibração salva: {dialog.calibration_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Calibração", str(exc))

    def analyze(self, include_evidence: bool) -> None:
        session = self.selected_session()
        if not session:
            QMessageBox.information(self, "Selecione uma sessão", "Selecione uma sessão para analisar.")
            return
        try:
            self.pipeline = self._make_pipeline()
            settings = dict(load_config().vod_analyzer or {})
            calibration = Path(str(settings.get("calibration") or ""))
            if not calibration.is_file():
                raise ValueError("Calibre o overlay antes da análise.")
            maximum = int(settings.get("maximum_images", 40))
        except Exception as exc:
            QMessageBox.warning(self, "Configuração incompleta", str(exc))
            return
        self._run(
            lambda progress: self.pipeline.analyze(session, calibration, include_evidence=include_evidence, maximum_images=maximum, progress=progress),
            lambda path: self.logs.appendPlainText(f"Relatório pronto: {path}"),
        )

    def add_marker(self) -> None:
        session = self.selected_session()
        if not session:
            QMessageBox.information(self, "Selecione uma sessão", "Selecione uma sessão para marcar.")
            return
        part_labels = [f"Parte {index}: {item.path.name}" for index, item in enumerate(session.files, 1)]
        part_label, ok = QInputDialog.getItem(self, "Parte do vídeo", "Arquivo:", part_labels, 0, False)
        if not ok:
            return
        part_index = part_labels.index(part_label) + 1
        maximum_ms = max(round(session.files[part_index - 1].duration_seconds * 1000), 0)
        timestamp_ms, ok = QInputDialog.getInt(
            self, "Timestamp local", "Tempo local na parte (milissegundos):",
            0, 0, maximum_ms,
        )
        if not ok:
            return
        marker_types = ["manual_note", "round_start", "round_end", "possible_duel_review"]
        marker_type, ok = QInputDialog.getItem(self, "Tipo de marcador", "Tipo:", marker_types, 0, False)
        if not ok:
            return
        text, ok = QInputDialog.getText(self, "Observação", "Texto objetivo (opcional):")
        if not ok:
            return
        try:
            pipeline = self._make_pipeline()
            marker = pipeline.add_manual_marker(
                session, marker_type=marker_type, part_index=part_index,
                local_timestamp_ms=timestamp_ms, text=text,
            )
            self.logs.appendPlainText(f"Marcador salvo: {marker['marker_type']} @ parte {part_index} / {timestamp_ms} ms")
        except Exception as exc:
            QMessageBox.critical(self, "Marcador", str(exc))

    def transcribe_voice(self) -> None:
        session = self.selected_session()
        if not session:
            QMessageBox.information(self, "Selecione uma sessão", "Selecione uma sessão para transcrever.")
            return
        confirmation = QMessageBox.question(
            self, "Transcrição local",
            "O áudio será extraído para o cache local e transcrito no computador. O primeiro uso pode baixar o modelo Whisper. Continuar?",
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.pipeline = self._make_pipeline()
        except Exception as exc:
            QMessageBox.critical(self, "Transcrição", str(exc))
            return
        self._run(
            lambda progress: self.pipeline.transcribe_markers(session, progress=progress),
            lambda markers: self.logs.appendPlainText(f"{len(markers)} marcações de voz persistidas; execute a análise para atualizar a linha do tempo."),
        )

    def open_report(self) -> None:
        session = self.selected_session()
        if not session:
            return
        root = Path(self.root_edit.text())
        path = root / "Relatorios" / session.session_id
        if path.is_dir():
            os.startfile(path)

    def cancel(self) -> None:
        if self.pipeline:
            self.pipeline.cancel()
            self.logs.appendPlainText("Cancelamento solicitado.")

    def _run(self, action, on_result) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Processamento ativo", "Aguarde ou cancele a tarefa atual.")
            return
        self.progress.setValue(0)
        self.worker = VodWorker(action, self)
        self.worker.progress.connect(lambda value, text: (self.progress.setValue(value), self.logs.appendPlainText(text)))
        self.worker.result.connect(on_result)
        self.worker.failed.connect(lambda message: QMessageBox.critical(self, "VOD Analyzer", message))
        self.worker.start()
