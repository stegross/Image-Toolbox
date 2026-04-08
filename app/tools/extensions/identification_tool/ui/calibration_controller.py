"""Pipeline-specific calibration controllers.

Each controller owns the calibration state machine for one pipeline.
:class:`CalibrationWidget` is a dumb surface; controllers drive it.

To add a new pipeline:
  1. Write a new controller class inheriting AbstractCalibrationController.
  2. Implement ``start()`` — connect to widget signals, set up step 1.
  3. Return an instance from ``YourPipeline.create_calibration_controller()``.
  No changes to CalibrationWidget are needed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRectF
from PySide6.QtGui import QColor

from app.tools.extensions.identification_tool.pipeline.base import (
    AbstractCalibrationController,
    CalibrationData,
)


# ---------------------------------------------------------------------------
# Pipeline 1 controller
# ---------------------------------------------------------------------------


class Pipeline1CalibrationController(AbstractCalibrationController):
    """Drives the 5-step chip-shape calibration for Pipeline 1.

    Steps
    -----
    1. Chip boundary detection (automatic)
    2. User confirms / retries / draws chip boundary manually
    3. Text-region detection inside chip (automatic)
    4. User selects identifier region (click or draw)
    5. OCR on selected region → user confirms text
    """

    def __init__(self, pipeline, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    # ------------------------------------------------------------------
    # AbstractCalibrationController
    # ------------------------------------------------------------------

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        # Connect pipeline signals
        self._pipeline.chip_detected.connect(self._on_chip_detected)
        self._pipeline.chip_detection_failed.connect(self._on_chip_detection_failed)
        self._pipeline.text_regions_detected.connect(self._on_text_regions_detected)
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)

        # Connect widget signals
        widget.roi_drawn.connect(self._on_roi_drawn)
        widget.ocr_confirmed.connect(self._on_ocr_confirmed)

        self._step1()

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _image_path(self) -> Path:
        return self._image_paths[self._image_index]

    def _skip_spec(self) -> list[tuple[str, str]]:
        if self._image_index < len(self._image_paths) - 1:
            return [("skip_calib", "Skip Image")]
        return []

    def _connect_cancel(self) -> None:
        btn = self._widget.button("cancel")
        if btn:
            btn.clicked.connect(self.calibration_cancelled)

    def _connect_skip(self) -> None:
        btn = self._widget.button("skip_calib")
        if btn:
            btn.clicked.connect(self._on_skip)

    def _step1(self) -> None:
        self._widget.load_image(self._image_path())
        self._widget.set_step(1, 5, "Detecting chip boundary…")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.start_calibration(self._image_path())

    def _on_skip(self) -> None:
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._widget.clear_overlays()
        self._pipeline._stopped = False
        self._step1()

    # ------------------------------------------------------------------
    # Pipeline signal handlers
    # ------------------------------------------------------------------

    def _on_chip_detected(self, polygon: list[tuple[float, float]], confidence: float) -> None:  # noqa: ARG002
        self._widget.set_step(2, 5, "Confirm chip boundary")
        self._widget.clear_overlays()
        self._widget.show_rect_overlay(self._polygon_to_qrectf(polygon), QColor(0, 200, 0), width=8)
        self._widget.set_buttons([
            ("confirm", "Confirm"),
            ("reject_retry", "Retry"),
            ("reject_manual", "Draw Manually"),
            ("cancel", "Cancel"),
        ])
        self._widget.button("confirm").clicked.connect(self._on_confirm_chip)
        self._widget.button("reject_retry").clicked.connect(self._on_retry_chip)
        self._widget.button("reject_manual").clicked.connect(self._on_manual_chip)
        self._connect_cancel()

    def _on_chip_detection_failed(self, reason: str) -> None:
        self._widget.set_step(1, 5, f"Detection failed: {reason}")
        self._widget.set_buttons(self._skip_spec() + [
            ("retry", "Retry"),
            ("manual", "Draw Manually"),
            ("cancel", "Cancel"),
        ])
        self._widget.button("retry").clicked.connect(lambda: self._pipeline.confirm_chip(False))
        self._widget.button("manual").clicked.connect(self._on_manual_chip)
        self._connect_cancel()
        self._connect_skip()

    def _on_confirm_chip(self) -> None:
        self._widget.set_step(3, 5, "Detecting text regions…")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()
        self._pipeline.confirm_chip(True)

    def _on_retry_chip(self) -> None:
        self._widget.set_step(1, 5, "Detecting chip boundary…")
        self._widget.clear_overlays()
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.confirm_chip(False)

    def _on_manual_chip(self) -> None:
        self._widget.set_step(2, 5, "Draw chip boundary manually")
        self._widget.clear_overlays()
        self._widget.start_roi_selection("chip")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()

    def _on_text_regions_detected(self, rects: list[QRectF]) -> None:
        self._widget.set_step(4, 5, "Select the identifier region")
        self._widget.clear_overlays()
        items = self._widget.show_rects_overlay(rects, QColor(255, 0, 255), width=8)
        self._widget.set_buttons([("manual_id", "Draw Manually"), ("cancel", "Cancel")])
        self._widget.button("manual_id").clicked.connect(self._on_manual_identifier)
        self._connect_cancel()
        # Allow clicking an overlay rect to select it
        for item in items:
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        self._widget.scene_selection_changed.connect(self._on_scene_selection_changed)

    def _on_scene_selection_changed(self) -> None:
        selected = self._widget.selected_scene_items()
        if not selected:
            return
        item = selected[0]
        rect = item.rect() if hasattr(item, "rect") else item.boundingRect()
        self._widget.scene_selection_changed.disconnect(self._on_scene_selection_changed)
        self._widget.set_step(5, 5, "Running OCR…")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()
        self._pipeline.set_identifier_bbox(rect)

    def _on_manual_identifier(self) -> None:
        self._widget.set_step(4, 5, "Draw the identifier region")
        self._widget.start_roi_selection("identifier")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()

    def _on_roi_drawn(self, mode: str, rect: QRectF) -> None:
        self._widget.clear_overlays()
        if mode == "chip":
            polygon = [
                (rect.x(), rect.y()), (rect.right(), rect.y()),
                (rect.right(), rect.bottom()), (rect.x(), rect.bottom()),
            ]
            self._widget.show_rect_overlay(rect, QColor(0, 120, 255), width=8)
            self._pipeline.confirm_chip(False, polygon)
        elif mode == "identifier":
            self._widget.show_rect_overlay(rect, QColor(0, 120, 255), width=8)
            self._widget.set_step(5, 5, "Running OCR…")
            self._widget.set_buttons([("cancel", "Cancel")])
            self._connect_cancel()
            self._pipeline.set_identifier_bbox(rect)

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(5, 5, f"Confirm OCR result (confidence: {confidence:.0%})")
        self._widget.show_ocr_panel(text)
        self._widget.set_buttons([])

    def _on_ocr_confirmed(self, text: str) -> None:
        self._widget.hide_ocr_panel()
        self._pipeline.confirm_ocr_result(text)

    def _on_calibration_complete(self, data: CalibrationData) -> None:
        self.calibration_complete.emit(data)

    def _on_calibration_error(self, message: str) -> None:
        self._widget.show_error(message)
        self.calibration_cancelled.emit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _polygon_to_qrectf(polygon: list[tuple[float, float]]) -> QRectF:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        x, y = min(xs), min(ys)
        return QRectF(x, y, max(xs) - x, max(ys) - y)


# ---------------------------------------------------------------------------
# Pipeline 2 controller
# ---------------------------------------------------------------------------


class Pipeline2CalibrationController(AbstractCalibrationController):
    """Drives the 4-step ROI-selection calibration for Pipeline 2.

    Steps
    -----
    1. User draws ROI around identifier
    2. Text detection snaps to precise boundary (automatic)
    3. User confirms / redraws snapped region
    4. OCR on snapped region → user confirms text
    """

    def __init__(self, pipeline, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    # ------------------------------------------------------------------
    # AbstractCalibrationController
    # ------------------------------------------------------------------

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        self._pipeline.roi_confirmed.connect(self._on_roi_confirmed)
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)

        widget.roi_drawn.connect(self._on_roi_drawn)
        widget.ocr_confirmed.connect(self._on_ocr_confirmed)

        self._step1()

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _image_path(self) -> Path:
        return self._image_paths[self._image_index]

    def _skip_spec(self) -> list[tuple[str, str]]:
        if self._image_index < len(self._image_paths) - 1:
            return [("skip_calib", "Skip Image")]
        return []

    def _connect_cancel(self) -> None:
        btn = self._widget.button("cancel")
        if btn:
            btn.clicked.connect(self.calibration_cancelled)

    def _connect_skip(self) -> None:
        btn = self._widget.button("skip_calib")
        if btn:
            btn.clicked.connect(self._on_skip)

    def _step1(self) -> None:
        self._widget.load_image(self._image_path())
        self._widget.set_step(1, 4, "Draw ROI around the identifier")
        self._widget.start_roi_selection("roi")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.start_calibration(self._image_path())

    def _on_skip(self) -> None:
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._widget.clear_overlays()
        self._pipeline._stopped = False
        self._step1()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_roi_drawn(self, mode: str, rect: QRectF) -> None:  # noqa: ARG002
        self._widget.stop_roi_selection()
        self._widget.clear_overlays()
        self._widget.show_rect_overlay(rect, QColor(0, 120, 255), width=8)
        self._widget.set_step(2, 4, "Snapping to text boundary…")
        self._widget.set_buttons([("cancel", "Cancel")])
        self._connect_cancel()
        self._pipeline.set_roi(rect)

    def _on_roi_confirmed(self, snapped: QRectF) -> None:
        self._widget.set_step(3, 4, "Confirm identifier region")
        self._widget.clear_overlays()
        self._widget.show_rect_overlay(snapped, QColor(0, 200, 0), width=8)
        self._widget.set_buttons([
            ("confirm", "Confirm"),
            ("redraw", "Redraw"),
            ("cancel", "Cancel"),
        ])
        self._widget.button("confirm").clicked.connect(lambda: self._pipeline.confirm_roi(True))
        self._widget.button("redraw").clicked.connect(self._on_redraw)
        self._connect_cancel()

    def _on_redraw(self) -> None:
        self._widget.clear_overlays()
        self._widget.start_roi_selection("roi")
        self._widget.set_step(1, 4, "Draw ROI around the identifier")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(4, 4, f"Confirm OCR result (confidence: {confidence:.0%})")
        self._widget.show_ocr_panel(text)
        self._widget.set_buttons([])

    def _on_ocr_confirmed(self, text: str) -> None:
        self._widget.hide_ocr_panel()
        self._pipeline.confirm_ocr_result(text)

    def _on_calibration_complete(self, data: CalibrationData) -> None:
        self.calibration_complete.emit(data)

    def _on_calibration_error(self, message: str) -> None:
        self._widget.show_error(message)
        self.calibration_cancelled.emit()


# ---------------------------------------------------------------------------
# Pipeline X controller — copy this block when adding a new pipeline
# ---------------------------------------------------------------------------


class PipelineXCalibrationController(AbstractCalibrationController):
    """Drives calibration for Pipeline X.

    Implement one _stepN() method per user-facing calibration step.
    Each step sets the step indicator, updates the buttons, and either
    starts an automatic background operation or waits for user input.

    Widget API available in every method
    -------------------------------------
    self._widget.load_image(path)
    self._widget.set_step(current, total, description)
    self._widget.set_buttons([(name, label), ...])
    self._widget.button(name) -> QPushButton | None
    self._widget.start_roi_selection(mode)   # activates rubber-band
    self._widget.stop_roi_selection()
    self._widget.show_rect_overlay(rect, color, width) -> item
    self._widget.show_rects_overlay(rects, color, width) -> [items]
    self._widget.clear_overlays()
    self._widget.show_ocr_panel(text)        # shows editable OCR confirm row
    self._widget.hide_ocr_panel()
    self._widget.show_error(message)         # modal error dialog
    self._widget.selected_scene_items()      # items clicked by user

    Widget signals to connect in start()
    -------------------------------------
    self._widget.roi_drawn          -> Signal(mode: str, rect: QRectF)
    self._widget.ocr_confirmed      -> Signal(text: str)
    self._widget.scene_selection_changed -> Signal()

    Convenience helpers (copy from Pipeline1/2 controller as needed)
    -----------------------------------------------------------------
    _image_path()  — current image
    _skip_spec()   — Skip Image button spec when images remain
    _connect_cancel() / _connect_skip()
    """

    def __init__(self, pipeline, parent=None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._widget = None
        self._image_paths: list[Path] = []
        self._image_index: int = 0

    # ------------------------------------------------------------------
    # Required: AbstractCalibrationController
    # ------------------------------------------------------------------

    def start(self, widget, image_paths: list[Path]) -> None:
        self._widget = widget
        self._image_paths = image_paths
        self._image_index = 0

        # 1. Connect pipeline signals you care about:
        self._pipeline.ocr_result_ready.connect(self._on_ocr_result_ready)
        self._pipeline.calibration_complete.connect(self._on_calibration_complete)
        self._pipeline.calibration_error.connect(self._on_calibration_error)
        # Add more: chip_detected, text_regions_detected, roi_confirmed, …

        # 2. Connect widget signals you need:
        self._widget.ocr_confirmed.connect(self._on_ocr_confirmed)
        # self._widget.roi_drawn.connect(self._on_roi_drawn)
        # self._widget.scene_selection_changed.connect(self._on_scene_selection_changed)

        # 3. Kick off step 1:
        self._step1()

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _step1(self) -> None:
        """TODO: describe what this step does."""
        self._widget.load_image(self._image_path())
        self._widget.set_step(1, 2, "TODO: step description")
        self._widget.set_buttons(self._skip_spec() + [("cancel", "Cancel")])
        self._connect_cancel()
        self._connect_skip()
        self._pipeline.start_calibration(self._image_path())

    # def _step2(self) -> None: ...

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_ocr_result_ready(self, text: str, confidence: float) -> None:
        self._widget.set_step(2, 2, f"Confirm OCR result (confidence: {confidence:.0%})")
        self._widget.show_ocr_panel(text)
        self._widget.set_buttons([])

    def _on_ocr_confirmed(self, text: str) -> None:
        self._widget.hide_ocr_panel()
        self._pipeline.confirm_ocr_result(text)

    def _on_calibration_complete(self, data: CalibrationData) -> None:
        self.calibration_complete.emit(data)

    def _on_calibration_error(self, message: str) -> None:
        self._widget.show_error(message)
        self.calibration_cancelled.emit()

    # ------------------------------------------------------------------
    # Helpers (same pattern as Pipeline1/2 controllers)
    # ------------------------------------------------------------------

    def _image_path(self) -> Path:
        return self._image_paths[self._image_index]

    def _skip_spec(self) -> list[tuple[str, str]]:
        if self._image_index < len(self._image_paths) - 1:
            return [("skip_calib", "Skip Image")]
        return []

    def _connect_cancel(self) -> None:
        btn = self._widget.button("cancel")
        if btn:
            btn.clicked.connect(self.calibration_cancelled)

    def _connect_skip(self) -> None:
        btn = self._widget.button("skip_calib")
        if btn:
            btn.clicked.connect(self._on_skip)

    def _on_skip(self) -> None:
        if self._image_index >= len(self._image_paths) - 1:
            return
        self._image_index += 1
        self._widget.clear_overlays()
        self._pipeline._stopped = False
        self._step1()
