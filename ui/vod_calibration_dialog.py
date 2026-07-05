from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.vod_analyzer.frame_extractor import extract_frame
from core.vod_analyzer.models import Region
from core.vod_analyzer.overlay_calibration import save_calibration


class FrameSelector(QLabel):
    region_changed = Signal(str, object)

    def __init__(self) -> None:
        super().__init__("Carregue o frame solto para marcar A, D e LMB.")
        self.setMinimumSize(640, 360)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#111827;border:1px solid #374151;")
        self.frame = None
        self.active_key = "A"
        self.regions: dict[str, Region] = {}
        self.start: QPoint | None = None

    def set_frame(self, frame) -> None:
        self.frame = frame
        self._refresh()

    def _image_rect(self) -> QRect:
        if self.frame is None:
            return QRect()
        height, width = self.frame.shape[:2]
        scaled = QRect(0, 0, width, height)
        scaled.setSize(scaled.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio))
        scaled.moveCenter(self.rect().center())
        return scaled

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.frame is not None and event.button() == Qt.MouseButton.LeftButton and self._image_rect().contains(event.position().toPoint()):
            self.start = event.position().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.start is None or self.frame is None:
            return
        display_rect = QRect(self.start, event.position().toPoint()).normalized().intersected(self._image_rect())
        self.start = None
        if display_rect.width() < 3 or display_rect.height() < 3:
            return
        image_rect = self._image_rect()
        frame_height, frame_width = self.frame.shape[:2]
        scale_x, scale_y = frame_width / image_rect.width(), frame_height / image_rect.height()
        region = Region(
            round((display_rect.x() - image_rect.x()) * scale_x),
            round((display_rect.y() - image_rect.y()) * scale_y),
            max(round(display_rect.width() * scale_x), 1),
            max(round(display_rect.height() * scale_y), 1),
        )
        self.regions[self.active_key] = region
        self.region_changed.emit(self.active_key, region)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self.frame is None:
            return
        import cv2
        frame = self.frame.copy()
        colors = {"A": (34, 197, 94), "D": (59, 130, 246), "LMB": (239, 68, 68)}
        for key, region in self.regions.items():
            cv2.rectangle(frame, (region.x, region.y), (region.x + region.width, region.y + region.height), colors[key], 2)
            cv2.putText(frame, key, (region.x, max(region.y - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[key], 2)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(image).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class OverlayCalibrationDialog(QDialog):
    def __init__(self, root: Path, video: Path, ffmpeg: str = "ffmpeg", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root, self.video, self.ffmpeg = root, video, ffmpeg
        self.setWindowTitle("Calibrar overlay A / D / LMB")
        self.resize(900, 680)
        root_layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit("obs_1280x720")
        self.released_time = self._time_spin()
        self.a_time = self._time_spin()
        self.d_time = self._time_spin()
        self.lmb_time = self._time_spin()
        form.addRow("Nome do layout", self.name)
        form.addRow("Frame com tudo solto (s)", self.released_time)
        form.addRow("Frame com A pressionado (s)", self.a_time)
        form.addRow("Frame com D pressionado (s)", self.d_time)
        form.addRow("Frame com LMB pressionado (s)", self.lmb_time)
        controls = QHBoxLayout()
        self.key = QComboBox()
        self.key.addItems(["A", "D", "LMB"])
        load_button = QPushButton("Carregar frame solto")
        load_button.clicked.connect(self.load_released)
        controls.addWidget(QLabel("Região que será marcada:"))
        controls.addWidget(self.key)
        controls.addWidget(load_button)
        controls.addStretch(1)
        self.selector = FrameSelector()
        self.key.currentTextChanged.connect(lambda value: setattr(self.selector, "active_key", value))
        self.status = QLabel("Arraste um retângulo sobre cada indicador no frame solto.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root_layout.addLayout(form)
        root_layout.addLayout(controls)
        root_layout.addWidget(self.selector, stretch=1)
        root_layout.addWidget(self.status)
        root_layout.addWidget(buttons)

    @staticmethod
    def _time_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 99_999)
        spin.setDecimals(3)
        spin.setSuffix(" s")
        return spin

    def load_released(self) -> None:
        try:
            self.selector.set_frame(extract_frame(self.video, self.released_time.value(), self.ffmpeg))
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao extrair frame", str(exc))

    def save(self) -> None:
        if self.selector.frame is None or set(self.selector.regions) != {"A", "D", "LMB"}:
            QMessageBox.warning(self, "Calibração incompleta", "Carregue o frame e marque A, D e LMB.")
            return
        try:
            pressed = {
                "A": extract_frame(self.video, self.a_time.value(), self.ffmpeg),
                "D": extract_frame(self.video, self.d_time.value(), self.ffmpeg),
                "LMB": extract_frame(self.video, self.lmb_time.value(), self.ffmpeg),
            }
            self.calibration_path = save_calibration(
                self.root, self.name.text(), self.selector.frame, pressed, self.selector.regions,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Falha na calibração", str(exc))
            return
        self.accept()
