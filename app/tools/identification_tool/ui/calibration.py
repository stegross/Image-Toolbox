"""Calibration phase widget — a dumb UI surface driven by a CalibrationController."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.tools._shared.image_widgets import ImageArea, PanZoomView
from app.tools.identification_tool.pipeline.base import (
    AbstractCalibrationController,
    CalibrationData,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.calibration")


# ---------------------------------------------------------------------------
# ROI-selectable view
# ---------------------------------------------------------------------------


class _RoiSelectView(PanZoomView):
    """PanZoomView extended with rubber-band ROI selection."""

    # Emits (mode, scene_rect) when user finishes drawing
    roi_drawn = Signal(str, QRectF)

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self._selecting = False
        self._roi_mode: str = ""
        self._origin: QPoint | None = None
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)

    def start_roi_selection(self, mode: str) -> None:
        self._roi_mode = mode
        self._selecting = True
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def stop_roi_selection(self) -> None:
        self._selecting = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.unsetCursor()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._rubber_band.setGeometry(QRect(self._origin, self._origin))
            self._rubber_band.show()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._selecting and self._origin is not None:
            self._rubber_band.setGeometry(
                QRect(self._origin, event.position().toPoint()).normalized()
            )
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._selecting and self._origin is not None and event.button() == Qt.MouseButton.LeftButton:
            self._rubber_band.hide()
            viewport_rect = QRect(self._origin, event.position().toPoint()).normalized()
            scene_rect = self.mapToScene(viewport_rect).boundingRect()
            self._origin = None
            if scene_rect.width() > 2 and scene_rect.height() > 2:
                self.roi_drawn.emit(self._roi_mode, scene_rect)
        else:
            super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Overlay image area
# ---------------------------------------------------------------------------


class _OverlayImageArea(ImageArea):
    """ImageArea that uses _RoiSelectView and exposes overlay/ROI helpers."""

    roi_drawn = Signal(str, QRectF)

    def _create_view(self) -> PanZoomView:
        view = _RoiSelectView(self._scene, self)
        view.roi_drawn.connect(self.roi_drawn)
        return view

    def start_roi_selection(self, mode: str) -> None:
        self._view.start_roi_selection(mode)  # type: ignore[attr-defined]

    def stop_roi_selection(self) -> None:
        self._view.stop_roi_selection()  # type: ignore[attr-defined]

    def show_rect_overlay(self, rect: QRectF, color: QColor | None = None, width: int = 8) -> QGraphicsRectItem:
        pen = QPen(color or QColor(255, 0, 255))
        pen.setWidth(width)
        item = QGraphicsRectItem(rect)
        item.setPen(pen)
        self._scene.addItem(item)
        return item

    def show_rects_overlay(self, rects: list[QRectF], color: QColor | None = None, width: int = 8) -> list[QGraphicsRectItem]:
        return [self.show_rect_overlay(r, color, width) for r in rects]


# ---------------------------------------------------------------------------
# Step indicator
# ---------------------------------------------------------------------------


class _StepIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._label = QLabel()
        self._label.setStyleSheet("font-weight: bold; color: #555;")
        layout.addWidget(self._label)
        layout.addStretch()

    def set_step(self, current: int, total: int, description: str) -> None:
        self._label.setText(f"Step {current}/{total}: {description}")

    def set_message(self, text: str) -> None:
        self._label.setText(text)


# ---------------------------------------------------------------------------
# Button bar
# ---------------------------------------------------------------------------


class _ButtonBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.addStretch()
        self._buttons: dict[str, QPushButton] = {}

    def set_buttons(self, specs: list[tuple[str, str]]) -> None:
        for btn in self._buttons.values():
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()
        for name, label in specs:
            btn = QPushButton(label)
            self._buttons[name] = btn
            self._layout.addWidget(btn)

    def button(self, name: str) -> QPushButton | None:
        return self._buttons.get(name)


# ---------------------------------------------------------------------------
# OCR confirmation panel
# ---------------------------------------------------------------------------


class _OcrConfirmPanel(QWidget):
    confirmed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Recognised identifier:"))
        self._edit = QLineEdit()
        layout.addWidget(self._edit, stretch=1)
        btn = QPushButton("Confirm")
        btn.clicked.connect(self._on_confirm)
        layout.addWidget(btn)
        self.hide()

    def show_result(self, text: str) -> None:
        self._edit.setText(text)
        self.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _on_confirm(self) -> None:
        text = self._edit.text().strip()
        if text:
            self.confirmed.emit(text)


# ---------------------------------------------------------------------------
# Rotation panel
# ---------------------------------------------------------------------------


class _RotationPanel(QWidget):
    """Slider-based rotation control shown as the first calibration step."""

    rotation_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        # Row 1: label + slider + value display
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Rotation:"))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(-180, 180)
        self._slider.setValue(0)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(90)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(10)
        row1.addWidget(self._slider, stretch=1)
        self._value_label = QLabel("0°")
        self._value_label.setMinimumWidth(44)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row1.addWidget(self._value_label)
        outer.addLayout(row1)

        # Row 2: tick labels at -180°, -90°, 0°, 90°, 180°
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(0)
        for text in ("-180°", "-90°", "0°", "90°", "180°"):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888; font-size: 10px;")
            row2.addWidget(lbl, stretch=1)
        outer.addLayout(row2)

        self._slider.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, value: int) -> None:
        self._value_label.setText(f"{value:+d}°" if value != 0 else "0°")
        self.rotation_changed.emit(value)

    def degrees(self) -> int:
        return self._slider.value()


# ---------------------------------------------------------------------------
# CalibrationWidget — dumb UI surface
# ---------------------------------------------------------------------------


class CalibrationWidget(QWidget):
    """Dumb UI surface for the calibration phase.

    Always starts with a universal rotation step (slider, live preview).
    After the user confirms the rotation, the pipeline-specific controller
    takes over.

    Controller-facing API
    ---------------------
    load_image(path)
    set_step(current, total, description)
    set_buttons(specs)           — [(name, label), ...]
    button(name) -> QPushButton
    start_roi_selection(mode)
    stop_roi_selection()
    show_rect_overlay(rect, color, width) -> item
    show_rects_overlay(rects, color, width) -> [items]
    clear_overlays()
    show_ocr_panel(text)
    hide_ocr_panel()
    show_error(message)
    selected_scene_items() -> list

    Signals for controllers
    -----------------------
    roi_drawn(mode: str, rect: QRectF)
    ocr_confirmed(text: str)
    scene_selection_changed()

    Outer signals
    -------------
    calibration_complete(CalibrationData)
    calibration_cancelled()
    """

    calibration_complete = Signal(object)   # CalibrationData
    calibration_cancelled = Signal()

    # Forwarded from internal widgets
    roi_drawn = Signal(str, QRectF)
    ocr_confirmed = Signal(str)
    scene_selection_changed = Signal()

    def __init__(
        self,
        pipeline,
        image_paths: list[Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._image_paths = image_paths
        self._rotation_degrees: float = 0.0
        self._original_pixmap: QPixmap | None = None

        self._setup_ui()

        self._controller: AbstractCalibrationController = pipeline.create_calibration_controller()
        self._controller.calibration_complete.connect(self._on_controller_complete)
        self._controller.calibration_cancelled.connect(self.calibration_cancelled)

        self._start_rotation_step()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._step_indicator = _StepIndicator(self)
        layout.addWidget(self._step_indicator)

        self._image_area = _OverlayImageArea(self)
        self._image_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_area.roi_drawn.connect(self.roi_drawn)
        self._image_area.scene().selectionChanged.connect(self.scene_selection_changed)
        layout.addWidget(self._image_area, stretch=1)

        self._rotation_panel = _RotationPanel(self)
        layout.addWidget(self._rotation_panel)

        self._ocr_panel = _OcrConfirmPanel(self)
        self._ocr_panel.confirmed.connect(self.ocr_confirmed)
        layout.addWidget(self._ocr_panel)

        self._button_bar = _ButtonBar(self)
        layout.addWidget(self._button_bar)

    # ------------------------------------------------------------------
    # Rotation step
    # ------------------------------------------------------------------

    def _start_rotation_step(self) -> None:
        if self._image_paths:
            path = self._image_paths[0]
            self._original_pixmap = QPixmap(str(path))
            if not self._original_pixmap.isNull():
                self._image_area.set_pixmap(
                    self._apply_display_transforms(self._original_pixmap, 0)
                )
                self._image_area.set_filename_text(path.name)

        self._step_indicator.set_message("Rotation — set the orientation applied to all images")
        self._rotation_panel.show()
        self._rotation_panel.rotation_changed.connect(self._on_rotation_preview)

        self._button_bar.set_buttons([("confirm_rotation", "Confirm Rotation")])
        btn = self._button_bar.button("confirm_rotation")
        if btn:
            btn.clicked.connect(self._on_rotation_confirmed)

    def _apply_display_transforms(self, pixmap: QPixmap, degrees: float | None = None) -> QPixmap:
        """Return *pixmap* with rotation and color-inversion applied for display."""
        angle = degrees if degrees is not None else self._rotation_degrees
        if angle != 0:
            pixmap = pixmap.transformed(
                QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation
            )
        if self._pipeline.invert_colors:
            img = pixmap.toImage()
            img.invertPixels()
            pixmap = QPixmap.fromImage(img)
        return pixmap

    def _on_rotation_preview(self, degrees: int) -> None:
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        self._image_area.set_pixmap(
            self._apply_display_transforms(self._original_pixmap, degrees)
        )

    def _on_rotation_confirmed(self) -> None:
        self._rotation_degrees = float(self._rotation_panel.degrees())
        self._rotation_panel.rotation_changed.disconnect(self._on_rotation_preview)
        self._rotation_panel.hide()
        self._pipeline.set_rotation(self._rotation_degrees)
        self._controller.start(self, self._image_paths)

    def _on_controller_complete(self, data: CalibrationData) -> None:
        data.rotation_degrees = self._rotation_degrees
        data.invert_colors = self._pipeline.invert_colors
        self.calibration_complete.emit(data)

    # ------------------------------------------------------------------
    # Controller-facing API
    # ------------------------------------------------------------------

    def load_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._image_area.set_pixmap(self._apply_display_transforms(pixmap))
            self._image_area.set_filename_text(path.name)

    def set_step(self, current: int, total: int, description: str) -> None:
        self._step_indicator.set_step(current, total, description)

    def set_buttons(self, specs: list[tuple[str, str]]) -> None:
        self._button_bar.set_buttons(specs)

    def button(self, name: str) -> QPushButton | None:
        return self._button_bar.button(name)

    def start_roi_selection(self, mode: str) -> None:
        self._image_area.start_roi_selection(mode)

    def stop_roi_selection(self) -> None:
        self._image_area.stop_roi_selection()

    def show_rect_overlay(self, rect: QRectF, color: QColor | None = None, width: int = 8) -> QGraphicsRectItem:
        return self._image_area.show_rect_overlay(rect, color, width)

    def show_rects_overlay(self, rects: list[QRectF], color: QColor | None = None, width: int = 8) -> list[QGraphicsRectItem]:
        return self._image_area.show_rects_overlay(rects, color, width)

    def clear_overlays(self) -> None:
        self._image_area.clear_overlays()

    def show_ocr_panel(self, text: str) -> None:
        self._ocr_panel.show_result(text)

    def hide_ocr_panel(self) -> None:
        self._ocr_panel.hide()

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Calibration Error", message)

    def selected_scene_items(self) -> list:
        return self._image_area.scene().selectedItems()
