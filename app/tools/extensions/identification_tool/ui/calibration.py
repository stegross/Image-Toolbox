"""Calibration phase widget — drives the first-image reference setup."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.tools._shared.image_widgets import ImageArea, PanZoomView
from app.tools.extensions.identification_tool.pipeline.base import (
    AbstractPipeline,
    CalibrationData,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.calibration")

# ---------------------------------------------------------------------------
# ROI-selectable image area
# ---------------------------------------------------------------------------


class _RoiSelectView(PanZoomView):
    """Pan/zoom view extended with rubber-band ROI selection.

    When :meth:`start_roi_selection` is active, clicking and dragging
    draws a rubber band.  On mouse release the selected rectangle is
    reported via :attr:`roi_drawn`.

    Signals
    -------
    roi_drawn
        ``(rect: QRectF)`` — rectangle in scene coordinates.
    """

    roi_drawn = Signal(QRectF)

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self._selecting = False
        self._origin: QPoint | None = None
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)

    def start_roi_selection(self) -> None:
        """Switch to rubber-band draw mode (disables pan/drag)."""
        self._selecting = True
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def stop_roi_selection(self) -> None:
        """Restore normal pan/drag mode."""
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
                self.roi_drawn.emit(scene_rect)
        else:
            super().mouseReleaseEvent(event)


class _OverlayImageArea(ImageArea):
    """ImageArea subclass that uses :class:`_RoiSelectView` and exposes overlay helpers."""

    roi_drawn = Signal(QRectF)

    def _create_view(self) -> PanZoomView:
        view = _RoiSelectView(self._scene, self)
        view.roi_drawn.connect(self.roi_drawn)
        return view

    def start_roi_selection(self) -> None:
        self._view.start_roi_selection()  # type: ignore[attr-defined]

    def stop_roi_selection(self) -> None:
        self._view.stop_roi_selection()  # type: ignore[attr-defined]

    def show_rect_overlay(self, rect: QRectF, color: QColor | None = None, width: int = 8) -> QGraphicsRectItem:
        """Draw a rectangle overlay on the scene and return the item."""
        pen = QPen(color or QColor(255, 0, 255))
        pen.setWidth(width)
        item = QGraphicsRectItem(rect)
        item.setPen(pen)
        self._scene.addItem(item)
        return item

    def show_rects_overlay(self, rects: list[QRectF], color: QColor | None = None, width: int = 8) -> list[QGraphicsRectItem]:
        """Draw multiple rectangle overlays."""
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
        """Replace button bar contents.

        Parameters
        ----------
        specs : list[tuple[str, str]]
            List of ``(object_name, label)`` pairs.
        """
        # Remove existing buttons
        for btn in self._buttons.values():
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()
        # Add new ones
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
        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.clicked.connect(self._on_confirm)
        layout.addWidget(self._confirm_btn)
        self.hide()

    def show_result(self, text: str) -> None:
        self._edit.setText(text)
        self.show()

    def _on_confirm(self) -> None:
        text = self._edit.text().strip()
        if text:
            self.confirmed.emit(text)


# ---------------------------------------------------------------------------
# CalibrationWidget — drives the pipeline state machine
# ---------------------------------------------------------------------------


class CalibrationWidget(QWidget):
    """Guides the user through the calibration phase of the selected pipeline.

    Signals
    -------
    calibration_complete
        ``(data: CalibrationData)`` — emitted when all calibration steps pass.
    calibration_cancelled
        Emitted when the user cancels.
    """

    calibration_complete = Signal(object)  # CalibrationData
    calibration_cancelled = Signal()

    def __init__(
        self,
        pipeline: AbstractPipeline,
        image_paths: list[Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._image_paths = image_paths
        self._image_index = 0
        self._image_path = image_paths[0]
        self._detected_rects: list[QRectF] = []
        self._overlay_items: list[QGraphicsRectItem] = []

        self._setup_ui()
        self._connect_pipeline_signals()
        self._start()

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
        self._image_area.roi_drawn.connect(self._on_roi_drawn)
        layout.addWidget(self._image_area, stretch=1)

        self._ocr_panel = _OcrConfirmPanel(self)
        self._ocr_panel.confirmed.connect(self._on_ocr_confirmed)
        layout.addWidget(self._ocr_panel)

        self._button_bar = _ButtonBar(self)
        layout.addWidget(self._button_bar)

        self._load_current_image()

    def _connect_pipeline_signals(self) -> None:
        self._pipeline.chip_detected.connect(self._on_chip_detected)
        self._pipeline.chip_detection_failed.connect(self._on_chip_detection_failed)
        self._pipeline.text_regions_detected.connect(self._on_text_regions_detected)
        self._pipeline.roi_confirmed.connect(self._on_roi_confirmed)
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)

    # ------------------------------------------------------------------
    # Pipeline state driver
    # ------------------------------------------------------------------

    def _load_current_image(self) -> None:
        from PySide6.QtGui import QPixmap
        self._image_path = self._image_paths[self._image_index]
        pixmap = QPixmap(str(self._image_path))
        if not pixmap.isNull():
            self._image_area.set_pixmap(pixmap)
            self._image_area.set_filename_text(
                f"{self._image_path.name}  ({self._image_index + 1}/{len(self._image_paths)})"
            )

    def _start(self) -> None:
        from app.tools.extensions.identification_tool.pipeline.pipeline2 import Pipeline2

        if isinstance(self._pipeline, Pipeline2):
            self._step_indicator.set_step(1, 4, "Draw ROI around the identifier")
            self._image_area.start_roi_selection()
            self._set_buttons([("cancel", "Cancel")])
        else:
            self._step_indicator.set_step(1, 5, "Detecting chip boundary…")
            self._set_buttons([("cancel", "Cancel")])
            self._pipeline.start_calibration(self._image_path)

        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    def _on_skip_image(self) -> None:
        """Skip current calibration image and try the next one."""
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._image_area.clear_overlays()
        self._load_current_image()
        self._pipeline._stopped = False
        self._start()

    # --- Pipeline 1 callbacks ---

    def _on_chip_detected(self, polygon: list[tuple[float, float]], confidence: float) -> None:
        self._step_indicator.set_step(2, 5, "Confirm chip boundary")
        self._image_area.clear_overlays()
        rect = self._polygon_to_qrectf(polygon)
        self._image_area.show_rect_overlay(rect, QColor(0, 200, 0))
        # Store polygon for confirm_chip
        self._last_polygon = polygon
        self._set_buttons([
            ("confirm", "Confirm"),
            ("reject_retry", "Retry"),
            ("reject_manual", "Draw Manually"),
            ("cancel", "Cancel"),
        ])
        self._button_bar.button("confirm").clicked.connect(self._on_confirm_chip)
        self._button_bar.button("reject_retry").clicked.connect(self._on_retry_chip)
        self._button_bar.button("reject_manual").clicked.connect(self._on_manual_chip)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        # Store chip bbox in pipeline
        from app.tools.extensions.identification_tool.pipeline.pipeline1 import Pipeline1
        if isinstance(self._pipeline, Pipeline1):
            self._pipeline._store_chip_bbox(polygon)

    def _on_chip_detection_failed(self, reason: str) -> None:
        self._step_indicator.set_step(1, 5, f"Detection failed: {reason}")
        self._set_buttons([
            ("retry", "Retry"),
            ("manual", "Draw Manually"),
            ("cancel", "Cancel"),
        ])
        self._button_bar.button("retry").clicked.connect(
            lambda: self._pipeline.confirm_chip(False)
        )
        self._button_bar.button("manual").clicked.connect(self._on_manual_chip)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    def _on_confirm_chip(self) -> None:
        self._step_indicator.set_step(3, 5, "Detecting text regions…")
        self._set_buttons([("cancel", "Cancel")])
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        self._pipeline.confirm_chip(True)

    def _on_retry_chip(self) -> None:
        self._step_indicator.set_step(1, 5, "Detecting chip boundary…")
        self._image_area.clear_overlays()
        self._set_buttons([("cancel", "Cancel")])
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        self._pipeline.confirm_chip(False)

    def _on_manual_chip(self) -> None:
        self._step_indicator.set_step(2, 5, "Draw chip boundary manually")
        self._image_area.clear_overlays()
        self._image_area.start_roi_selection()
        # On roi_drawn -> treat it as the chip boundary
        self._roi_mode = "chip"
        self._set_buttons([("cancel", "Cancel")])
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    def _on_text_regions_detected(self, rects: list[QRectF]) -> None:
        self._detected_rects = rects
        self._step_indicator.set_step(4, 5, "Select the identifier region")
        self._image_area.clear_overlays()
        self._overlay_items = self._image_area.show_rects_overlay(rects, QColor(255, 0, 255))
        info = QLabel("Click a highlighted region, or draw manually.", self)
        self._set_buttons([("manual_id", "Draw Manually"), ("cancel", "Cancel")], skip=False)
        self._button_bar.button("manual_id").clicked.connect(self._on_manual_identifier)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        self._roi_mode = "identifier_click"
        # Allow clicking on an overlay to select it
        for i, item in enumerate(self._overlay_items):
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        self._image_area.scene().selectionChanged.connect(self._on_scene_selection_changed)

    def _on_scene_selection_changed(self) -> None:
        selected = self._image_area.scene().selectedItems()
        if not selected:
            return
        item = selected[0]
        rect = item.rect() if hasattr(item, "rect") else item.boundingRect()
        self._image_area.scene().selectionChanged.disconnect(self._on_scene_selection_changed)
        self._step_indicator.set_step(5, 5, "Running OCR…")
        self._set_buttons([("cancel", "Cancel")], skip=False)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        from app.tools.extensions.identification_tool.pipeline.pipeline1 import Pipeline1
        if isinstance(self._pipeline, Pipeline1):
            self._pipeline.set_identifier_bbox(rect)

    def _on_manual_identifier(self) -> None:
        self._image_area.start_roi_selection()
        self._roi_mode = "identifier"
        self._step_indicator.set_step(4, 5, "Draw the identifier region")
        self._set_buttons([("cancel", "Cancel")], skip=False)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    # --- Pipeline 2 callbacks ---

    def _on_roi_drawn(self, rect: QRectF) -> None:
        mode = getattr(self, "_roi_mode", "roi")
        self._image_area.stop_roi_selection()
        self._image_area.clear_overlays()
        self._image_area.show_rect_overlay(rect, QColor(0, 120, 255))

        if mode == "chip":
            polygon = [
                (rect.x(), rect.y()), (rect.right(), rect.y()),
                (rect.right(), rect.bottom()), (rect.x(), rect.bottom()),
            ]
            self._pipeline.confirm_chip(False, polygon)
        elif mode == "identifier":
            from app.tools.extensions.identification_tool.pipeline.pipeline1 import Pipeline1
            if isinstance(self._pipeline, Pipeline1):
                self._pipeline.set_identifier_bbox(rect)
                self._step_indicator.set_step(5, 5, "Running OCR…")
                self._set_buttons([("cancel", "Cancel")], skip=False)
                self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
        else:
            # Pipeline 2 ROI
            self._step_indicator.set_step(2, 4, "Snapping to text boundary…")
            self._set_buttons([("cancel", "Cancel")])
            self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)
            self._pipeline.set_roi(rect)

    def _on_roi_confirmed(self, snapped: QRectF) -> None:
        self._step_indicator.set_step(3, 4, "Confirm identifier region")
        self._image_area.clear_overlays()
        self._image_area.show_rect_overlay(snapped, QColor(0, 200, 0))
        self._last_snapped = snapped
        self._set_buttons([
            ("confirm", "Confirm"),
            ("redraw", "Redraw"),
            ("cancel", "Cancel"),
        ])
        self._button_bar.button("confirm").clicked.connect(
            lambda: self._pipeline.confirm_roi(True)
        )
        self._button_bar.button("redraw").clicked.connect(self._on_redraw_roi)
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    def _on_redraw_roi(self) -> None:
        self._image_area.clear_overlays()
        self._image_area.start_roi_selection()
        self._roi_mode = "roi"
        self._step_indicator.set_step(1, 4, "Draw ROI around the identifier")
        self._set_buttons([("cancel", "Cancel")])
        self._button_bar.button("cancel").clicked.connect(self.calibration_cancelled)

    # --- Shared OCR confirmation ---

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._step_indicator.set_step(
            5 if not hasattr(self, "_roi_mode") else 4,
            5 if not hasattr(self, "_roi_mode") else 4,
            f"Confirm OCR result (confidence: {confidence:.0%})",
        )
        self._ocr_panel.show_result(text)
        self._set_buttons([], skip=False)  # confirm comes from the OCR panel button

    def _on_ocr_confirmed(self, text: str) -> None:
        self._ocr_panel.hide()
        self._pipeline.confirm_ocr_result(text)

    def _on_calibration_complete(self, data: CalibrationData) -> None:
        self.calibration_complete.emit(data)

    def _on_calibration_error(self, message: str) -> None:
        QMessageBox.critical(self, "Calibration Error", message)
        self.calibration_cancelled.emit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _skip_spec(self) -> list[tuple[str, str]]:
        """Return a Skip Image button spec when more images are available."""
        return [("skip_calib", "Skip Image")] if self._image_index < len(self._image_paths) - 1 else []

    def _set_buttons(self, specs: list[tuple[str, str]], skip: bool = True) -> None:
        prefix = self._skip_spec() if skip else []
        self._button_bar.set_buttons(prefix + specs)
        skip_btn = self._button_bar.button("skip_calib")
        if skip_btn:
            skip_btn.clicked.connect(self._on_skip_image)

    @staticmethod
    def _polygon_to_qrectf(polygon: list[tuple[float, float]]) -> QRectF:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        x, y = min(xs), min(ys)
        return QRectF(x, y, max(xs) - x, max(ys) - y)
