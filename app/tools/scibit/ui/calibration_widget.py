"""CalibrationWidget — shell + orchestrator for the calibration flow.

Layout (the widget owns the fixed structure)
--------------------------------------------
::

    ┌─────────────────────────────────────────────────────────┐
    │  Title bar  (stage sets the text via set_title)         │
    ├──────────────────────────────┬──────────────────────────┤
    │                              │  ┌─ Operator ────────────┐│
    │                              │  │ [combo]               ││
    │   Image panel                │  └───────────────────────┘│
    │   (stage drives content      │  ┌─ Parameters ───────────┐│
    │    and overlays)             │  │ key: [editor]          ││
    │                              │  │ key: [editor]          ││
    │                              │  └───────────────────────┘│
    │                              │  ┌─ Result ───────────────┐│
    │                              │  │ Text:       …          ││
    │                              │  │ Confidence: …          ││
    │                              │  └───────────────────────┘│
    │                              │  (stretch)                 │
    │                              │  [◄ Prev][extras…][Next ►] │
    └──────────────────────────────┴──────────────────────────┘

The widget owns navigation state and the standard UI shell.  Each
:class:`~app.tools.scibit.core.stage.Stage` declares its operators,
parameters, ROI mode, and extra buttons through its
:class:`~app.tools.scibit.core.stage.StageUIDescriptor` and drives the
dynamic content (title text, image, overlays, result panel) through the
:class:`~app.tools.scibit.core.calibration.CalibrationView` Protocol
that this widget satisfies structurally.

There is no separate controller class — the widget routes its Qt
events to the current stage's calibration hooks
(``present``, ``confirm_calibration``, ``on_action``, ``on_roi_drawn``,
``on_scene_selection``).  Stages opt into each hook by defining the
method; the widget guards every call with ``hasattr``.

Entry point: :meth:`start_calibration`.  Exit: emits either
``calibration_complete(session)`` when the final stage is confirmed or
``calibration_cancelled()`` when the host stops the run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.tools.scibit.core.calibration import CalibrationContext
from app.tools.scibit.core.stage import ParamSpec, StageUIDescriptor
from app.tools.scibit.core.types import BoundingBox
from app.tools.scibit.ui._image_utils import ndarray_to_pixmap

if TYPE_CHECKING:
    from app.tools.scibit.config.config import PipelineOptions
    from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
    from app.tools.scibit.core.pipeline import Pipeline
    from app.tools.scibit.core.stage import Stage

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graphics view with rubber-band ROI selection
# ---------------------------------------------------------------------------


class _RoiGraphicsView(QGraphicsView):
    """QGraphicsView subclass that supports rubber-band ROI selection.

    When ROI selection is active (via :meth:`enable_roi_selection`), the
    user can click and drag to define a rectangle.  On mouse release the
    :attr:`roi_drawn` signal is emitted with the mode tag and the rectangle
    in scene (image) coordinates.
    """

    roi_drawn = Signal(str, object)  # (mode: str, rect: (x, y, w, h))

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self._roi_mode: str | None = None
        self._roi_start: QPointF | None = None
        self._rubber_band: QGraphicsRectItem | None = None
        self._pan_start: QPoint | None = None
        self._needs_fit: bool = False

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(255, 255, 255))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    # ------------------------------------------------------------------
    # ROI control
    # ------------------------------------------------------------------

    def enable_roi_selection(self, mode: str) -> None:
        self._roi_mode = mode
        self.setCursor(Qt.CursorShape.CrossCursor)

    def disable_roi_selection(self) -> None:
        self._roi_mode = None
        self.unsetCursor()
        self._remove_rubber_band()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self._roi_mode and event.button() == Qt.MouseButton.LeftButton:
            self._roi_start = self.mapToScene(event.pos())
            self._remove_rubber_band()
            self._rubber_band = QGraphicsRectItem(QRectF(self._roi_start, QSizeF(0, 0)))
            pen = QPen(QColor(255, 100, 0), 1, Qt.PenStyle.DashLine)
            self._rubber_band.setPen(pen)
            self._rubber_band.setBrush(Qt.BrushStyle.NoBrush)
            self._rubber_band.setZValue(200)
            self.scene().addItem(self._rubber_band)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._roi_mode and self._roi_start is not None and self._rubber_band:
            end = self.mapToScene(event.pos())
            self._rubber_band.setRect(QRectF(self._roi_start, end).normalized())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            if self._roi_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        if (
            self._roi_mode
            and self._roi_start is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            end = self.mapToScene(event.pos())
            rect = QRectF(self._roi_start, end).normalized()
            self._roi_start = None
            if rect.width() > 2 and rect.height() > 2:
                self.roi_drawn.emit(
                    self._roi_mode,
                    (int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())),
                )
        else:
            super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Zoom / resize
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._needs_fit = False
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def fit_all(self) -> None:
        """Fit the full scene rect (including any overflow items) into view."""
        rect = self.scene().itemsBoundingRect() if self.scene() else None
        if rect and rect.isValid():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._needs_fit:
            self.fit_all()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _remove_rubber_band(self) -> None:
        if self._rubber_band is not None:
            if self.scene():
                self.scene().removeItem(self._rubber_band)
            self._rubber_band = None


# ---------------------------------------------------------------------------
# CalibrationWidget
# ---------------------------------------------------------------------------


class CalibrationWidget(QWidget):
    """Shell + orchestrator for the calibration flow.

    Constructed by :class:`~app.tools.scibit.tool.Scibit`.  The host calls
    :meth:`start_calibration` once the pipeline is built and the image
    list is ready.  The widget then drives the stage sequence; the host
    listens for :attr:`calibration_complete` or
    :attr:`calibration_cancelled` to know when to move on.

    Parameters
    ----------
    parent : QWidget | None
        Optional Qt parent.
    """

    # External signals (host listens to these).
    calibration_complete = Signal(object)  # CalibrationSession
    calibration_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[QGraphicsRectItem] = []
        self._overlay_rects: dict[QGraphicsRectItem, BoundingBox] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._original_pixmap: QPixmap | None = None
        self._preview_rotation: float = 0.0
        self._preview_invert: bool = False
        self._preview_scale: float = 1.0
        self._pixmap_item: QGraphicsPixmapItem | None = None

        # Navigation state — populated by start_calibration().
        self._stages: list[Stage] = []
        self._current_idx: int = 0
        self._ctx: CalibrationContext | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # ── Title bar ───────────────────────────────────────────────
        self._title_label = QLabel("Calibration")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        root.addWidget(self._title_label)

        # ── Main splitter ───────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Left: image / overlay view
        self._scene = QGraphicsScene(self)
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._view = _RoiGraphicsView(self._scene, self)
        self._view.roi_drawn.connect(self._on_roi_drawn)
        splitter.addWidget(self._view)

        # Right: controls panel
        right = QWidget()
        right.setMinimumWidth(240)
        right.setMaximumWidth(360)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # ── Operator combo (hidden until a stage with operators arrives)
        self._dyn_operator_group = QGroupBox("Operator")
        self._dyn_operator_group.setVisible(False)
        dyn_op_layout = QVBoxLayout(self._dyn_operator_group)
        self._dyn_operator_combo = QComboBox()
        self._dyn_operator_combo.currentIndexChanged.connect(self._on_dyn_operator_combo_changed)
        dyn_op_layout.addWidget(self._dyn_operator_combo)
        right_layout.addWidget(self._dyn_operator_group)

        # ── Parameter form (rebuilt from the active stage's descriptor)
        self._dyn_params_group = QGroupBox("Parameters")
        self._dyn_params_group.setVisible(False)
        self._dyn_params_form = QFormLayout(self._dyn_params_group)
        self._dyn_params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._dyn_param_widgets: dict[str, QWidget] = {}
        right_layout.addWidget(self._dyn_params_group)

        # ── Result panel (text + confidence, generic across stages) ─
        self._result_group = QGroupBox("Result")
        self._result_group.setVisible(False)
        result_form = QFormLayout(self._result_group)
        result_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._result_text_label = QLabel()
        self._result_text_label.setWordWrap(True)
        result_form.addRow("Text:", self._result_text_label)
        self._result_confidence_label = QLabel()
        result_form.addRow("Confidence:", self._result_confidence_label)
        right_layout.addWidget(self._result_group)

        right_layout.addStretch()

        # ── Button bar ──────────────────────────────────────────────
        btn_container = QWidget()
        self._btn_layout = QHBoxLayout(btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(btn_container)

        splitter.addWidget(right)
        splitter.setSizes([700, 280])

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start_calibration(
        self,
        pipeline: Pipeline,
        image_paths: list[Path],
        options: PipelineOptions,
        preset_registry: IdentifierPatternPresetRegistry,
    ) -> None:
        """Begin a calibration run.

        Builds the :class:`CalibrationContext`, resets to the first stage,
        and renders it.  The host listens to
        :attr:`calibration_complete` / :attr:`calibration_cancelled` to
        know when the run finishes.
        """
        self._stages = pipeline.get_stages()
        self._current_idx = 0
        self._ctx = CalibrationContext(
            pipeline=pipeline,
            options=options,
            preset_registry=preset_registry,
            image_paths=list(image_paths),
        )
        self._show_current_stage()

    # ------------------------------------------------------------------
    # CalibrationView Protocol — title bar
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Replace the title bar text."""
        self._title_label.setText(text)

    # ------------------------------------------------------------------
    # CalibrationView Protocol — image panel
    # ------------------------------------------------------------------

    def load_image(self, path: Path) -> None:
        """Load an image from disk and display it in the preview pane.

        Applies the current Stage-0 preview state (rotation, inversion,
        scale) to the loaded pixmap so newly loaded images respect the
        already-confirmed transform values.
        """
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            _log.warning("Could not load image for display: %s", path)
            return
        self._original_pixmap = pixmap
        self._set_pixmap(pixmap)
        self._apply_stage0_transform()

    def set_preview_image(self, image: NDArray[np.uint8]) -> None:
        """Display a NumPy image array (used for pipeline stage previews)."""
        self._original_pixmap = None
        self._set_pixmap(ndarray_to_pixmap(image))

    def _set_pixmap(self, pixmap: QPixmap) -> None:
        """Replace the scene content with *pixmap*, clearing all overlays."""
        self._scene.clear()
        self._overlays = []
        self._overlay_rects = {}
        self._view._rubber_band = None
        self._view._roi_start = None
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(0, 0, pixmap.width(), pixmap.height()))
        self._view._needs_fit = True
        QTimer.singleShot(0, self._view.fit_all)

    def _apply_stage0_transform(self) -> None:
        """Apply rotation, inversion, and scale to the raw loaded image via Qt.

        Only active while displaying the original image (Stage 0). Has no
        effect once set_preview_image() replaces it with a processed array.
        """
        if self._original_pixmap is None or self._pixmap_item is None:
            return
        pixmap = self._original_pixmap
        if self._preview_invert:
            img = pixmap.toImage()
            img.invertPixels()
            pixmap = QPixmap.fromImage(img)
        if self._preview_scale < 1.0:
            sw = max(1, round(pixmap.width() * self._preview_scale))
            sh = max(1, round(pixmap.height() * self._preview_scale))
            pixmap = pixmap.scaled(
                sw,
                sh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._pixmap_item.setPixmap(pixmap)
        self._pixmap_item.setTransformOriginPoint(pixmap.width() / 2.0, pixmap.height() / 2.0)
        self._pixmap_item.setRotation(self._preview_rotation)
        self._scene.setSceneRect(self._scene.itemsBoundingRect())

    # ------------------------------------------------------------------
    # CalibrationView Protocol — overlays
    # ------------------------------------------------------------------

    def show_rect_overlay(
        self,
        rect: BoundingBox,
        color: tuple[int, int, int],
        width: int = 2,
        *,
        selectable: bool = False,
    ) -> None:
        """Draw a coloured bounding-box overlay on the image.

        When *selectable* is True, the item responds to mouse clicks and the
        widget emits the picked rect to the active stage's
        :meth:`on_scene_selection` hook.
        """
        x, y, w, h = rect
        r, g, b = color
        item = QGraphicsRectItem(QRectF(x, y, w, h))
        item.setPen(QPen(QColor(r, g, b), width))
        item.setBrush(Qt.BrushStyle.NoBrush)
        item.setZValue(10)
        if selectable:
            from PySide6.QtWidgets import QGraphicsItem

            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._overlay_rects[item] = rect
        self._scene.addItem(item)
        self._overlays.append(item)

    def show_rects_overlay(
        self,
        rects: list[BoundingBox],
        color: tuple[int, int, int],
        width: int = 2,
        *,
        selectable: bool = False,
    ) -> None:
        """Draw multiple bounding-box overlays in the same colour."""
        for rect in rects:
            self.show_rect_overlay(rect, color, width, selectable=selectable)

    def clear_overlays(self) -> None:
        """Remove all overlay items from the scene."""
        for item in self._overlays:
            self._scene.removeItem(item)
        self._overlays.clear()
        self._overlay_rects.clear()

    # ------------------------------------------------------------------
    # CalibrationView Protocol — ROI drawing mode
    # ------------------------------------------------------------------

    def start_roi_selection(self, mode: str) -> None:
        """Enable rubber-band ROI drawing with the given mode tag."""
        self._view.enable_roi_selection(mode)

    def stop_roi_selection(self) -> None:
        """Disable rubber-band ROI drawing."""
        self._view.disable_roi_selection()

    # ------------------------------------------------------------------
    # CalibrationView Protocol — result panel
    # ------------------------------------------------------------------

    def show_text_result(self, text: str, confidence: float = 0.0) -> None:
        """Reveal the result panel showing *text* and *confidence*."""
        self._result_text_label.setText(text if text else "—")
        self._result_confidence_label.setText(f"{confidence:.1f} %")
        self._result_group.setVisible(True)

    def hide_text_result(self) -> None:
        """Hide the result panel."""
        self._result_group.setVisible(False)

    # ------------------------------------------------------------------
    # CalibrationView Protocol — error display
    # ------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        """Display a modal error dialog."""
        QMessageBox.critical(self, "Error", message)

    # ------------------------------------------------------------------
    # Navigation — stage transitions
    # ------------------------------------------------------------------

    @property
    def _current_stage(self) -> Stage | None:
        if not self._stages or not (0 <= self._current_idx < len(self._stages)):
            return None
        return self._stages[self._current_idx]

    def _show_current_stage(self) -> None:
        """Render the shell for the active stage and hand off to its hook.

        Builds the parameter form / operator combo / button bar from the
        stage's UI descriptor, then calls the stage's ``present`` hook so
        it can populate the dynamic display.
        """
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        descriptor = stage.get_ui_descriptor()
        # Force first stage to never offer a Previous button regardless of
        # the descriptor's default (defensive — stage 0 already overrides).
        if self._current_idx == 0:
            descriptor.has_previous = False

        # Standard layout
        self._render_shell(descriptor)
        self._set_default_title(stage)
        self.clear_overlays()
        self.hide_text_result()

        # Stage-specific dynamic content
        if hasattr(stage, "present"):
            stage.present(self, self._ctx)

    def _refresh_current_stage(self) -> None:
        """Rebuild the shell and re-present without changing stage index.

        Called when the assigned operator changes — the parameter form
        depends on the operator, so the descriptor must be re-fetched.
        """
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        descriptor = stage.get_ui_descriptor()
        if self._current_idx == 0:
            descriptor.has_previous = False
        self._render_shell(descriptor)
        self.clear_overlays()
        self.hide_text_result()
        if hasattr(stage, "present"):
            stage.present(self, self._ctx)

    def _re_present(self) -> None:
        """Re-run the active stage's ``present`` hook without rebuilding the shell.

        Used after a parameter value changes — the parameter editors
        themselves are stable, only the stage's dynamic display needs to
        update, so we skip rebuilding the form / operator combo / button bar.
        """
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        self.clear_overlays()
        self.hide_text_result()
        if hasattr(stage, "present"):
            stage.present(self, self._ctx)

    def _set_default_title(self, stage: Stage) -> None:
        """Compose and apply the default title for *stage*.

        Stages may override via :meth:`set_title` from inside their
        ``present`` hook.
        """
        total = len(self._stages)
        self.set_title(f"Step {self._current_idx + 1}/{total}: {stage.display_name}")

    # ------------------------------------------------------------------
    # Shell rebuild — operator combo, parameter form, ROI mode, buttons
    # ------------------------------------------------------------------

    def _render_shell(self, descriptor: StageUIDescriptor) -> None:
        """Rebuild the right-side panel and button bar from *descriptor*."""
        self._set_navigation_buttons(descriptor)
        self._set_dyn_operator_combo(
            descriptor.available_operators,
            descriptor.selected_operator,
        )
        self._build_param_form(descriptor.parameters, descriptor.parameter_values)
        self._sync_stage0_preview(descriptor.parameter_values)
        self._configure_roi_mode(descriptor)

    def _sync_stage0_preview(self, values: dict[str, Any]) -> None:
        """Update preview-transform state from descriptor parameter_values."""
        if "rotation_degrees" in values:
            try:
                self._preview_rotation = float(values["rotation_degrees"])
            except (TypeError, ValueError):
                self._preview_rotation = 0.0
        if "invert_colors" in values:
            self._preview_invert = bool(values["invert_colors"])
        if "downscale_factor" in values:
            try:
                pct = int(values["downscale_factor"])
            except (TypeError, ValueError):
                pct = 100
            self._preview_scale = max(10, min(100, pct)) / 100.0
        self._apply_stage0_transform()

    def _set_navigation_buttons(self, descriptor: StageUIDescriptor) -> None:
        """Build the action button bar from descriptor navigation state."""
        specs: list[dict] = []
        if descriptor.has_previous:
            specs.append(
                {
                    "label": descriptor.previous_label,
                    "action": "previous",
                }
            )
        for extra in descriptor.extra_buttons:
            specs.append(dict(extra))
        if descriptor.has_confirm:
            specs.append(
                {
                    "label": descriptor.confirm_label,
                    "action": "confirm",
                    "default": True,
                }
            )
        self._set_buttons(specs)

    def _set_buttons(self, specs: list[dict]) -> None:
        """Rebuild the action button bar from *specs*.

        Each spec dict must have ``"label"`` (str) and ``"action"`` (str),
        and optionally ``"default": True`` for the primary button.
        """
        while self._btn_layout.count():
            item = self._btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        for spec in specs:
            label = spec.get("label", "")
            action = spec.get("action", "")
            btn = QPushButton(label)
            if spec.get("default"):
                btn.setDefault(True)
            btn.clicked.connect(lambda _checked=False, a=action: self._on_button_clicked(a))
            self._btn_layout.addWidget(btn)
            if action:
                self._buttons[action] = btn

    def _set_dyn_operator_combo(
        self,
        operators: list[tuple[str, str]],
        selected: str,
    ) -> None:
        """Populate the operator combo and reveal it.

        *operators* is a list of ``(display_name, operator_key)`` tuples.
        Hidden when the list is empty (built-in stages with no operator).
        """
        self._dyn_operator_combo.blockSignals(True)
        self._dyn_operator_combo.clear()
        for display, key in operators:
            self._dyn_operator_combo.addItem(display, key)
        if selected:
            for i in range(self._dyn_operator_combo.count()):
                if self._dyn_operator_combo.itemData(i) == selected:
                    self._dyn_operator_combo.setCurrentIndex(i)
                    break
        self._dyn_operator_combo.blockSignals(False)
        self._dyn_operator_group.setVisible(bool(operators))

    def _build_param_form(
        self,
        specs: list[ParamSpec],
        values: dict[str, Any],
    ) -> None:
        """Clear and rebuild the dynamic parameter form from *specs*."""
        self._clear_dyn_param_form()
        for spec in specs:
            if spec.type == "group":
                group_box = self._build_group_widget(spec, values)
                self._dyn_params_form.addRow(group_box)
                self._dyn_param_widgets[spec.key] = group_box
            else:
                value = values.get(spec.key, spec.default)
                widget = self._create_widget_for_spec(spec, value)
                self._dyn_params_form.addRow(spec.label + ":", widget)
                self._dyn_param_widgets[spec.key] = widget
        self._dyn_params_group.setVisible(bool(specs))

    def _clear_dyn_param_form(self) -> None:
        while self._dyn_params_form.rowCount():
            self._dyn_params_form.removeRow(0)
        self._dyn_param_widgets.clear()

    def _create_widget_for_spec(self, spec: ParamSpec, value: Any) -> QWidget:
        if spec.type == "choice":
            return self._build_choice_widget(spec, value)
        if spec.type == "int":
            return self._build_int_widget(spec, value)
        if spec.type == "float":
            return self._build_float_widget(spec, value)
        if spec.type == "bool":
            return self._build_bool_widget(spec, value)
        return QLabel(str(value))

    def _build_choice_widget(self, spec: ParamSpec, value: Any) -> QComboBox:
        combo = QComboBox()
        for display, val in spec.options or []:
            combo.addItem(display, val)
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        if spec.tooltip:
            combo.setToolTip(spec.tooltip)
        key = spec.key
        combo.currentIndexChanged.connect(
            lambda _i, k=key, c=combo: self._on_dyn_param_changed(k, c.currentData())
        )
        return combo

    def _build_int_widget(self, spec: ParamSpec, value: Any) -> QSpinBox:
        spin = QSpinBox()
        if spec.min is not None:
            spin.setMinimum(int(spec.min))
        else:
            spin.setMinimum(-1_000_000)
        if spec.max is not None:
            spin.setMaximum(int(spec.max))
        else:
            spin.setMaximum(1_000_000)
        if spec.step:
            spin.setSingleStep(int(spec.step))
        if spec.suffix:
            spin.setSuffix(spec.suffix)
        if spec.tooltip:
            spin.setToolTip(spec.tooltip)
        spin.setValue(int(value) if value is not None else 0)
        key = spec.key
        spin.valueChanged.connect(lambda v, k=key: self._on_dyn_param_changed(k, int(v)))
        return spin

    def _build_float_widget(self, spec: ParamSpec, value: Any) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        if spec.min is not None:
            spin.setMinimum(float(spec.min))
        else:
            spin.setMinimum(-1e9)
        if spec.max is not None:
            spin.setMaximum(float(spec.max))
        else:
            spin.setMaximum(1e9)
        if spec.step:
            spin.setSingleStep(float(spec.step))
        if spec.suffix:
            spin.setSuffix(spec.suffix)
        if spec.tooltip:
            spin.setToolTip(spec.tooltip)
        spin.setDecimals(2)
        spin.setValue(float(value) if value is not None else 0.0)
        key = spec.key
        spin.valueChanged.connect(lambda v, k=key: self._on_dyn_param_changed(k, float(v)))
        return spin

    def _build_group_widget(
        self,
        spec: ParamSpec,
        values: dict[str, Any],
    ) -> QGroupBox:
        """Build a checkable QGroupBox containing nested parameter rows."""
        group = QGroupBox(spec.label)
        group.setCheckable(True)
        enabled = bool(values.get(spec.enable_key, False))
        group.setChecked(enabled)
        if spec.tooltip:
            group.setToolTip(spec.tooltip)

        inner = QFormLayout(group)
        inner.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        inner.setContentsMargins(8, 4, 4, 4)

        child_widgets: list[QWidget] = []
        for child in spec.children:
            child_value = values.get(child.key, child.default)
            child_widget = self._create_widget_for_spec(child, child_value)
            child_widget.setEnabled(enabled)
            inner.addRow(child.label + ":", child_widget)
            self._dyn_param_widgets[child.key] = child_widget
            child_widgets.append(child_widget)

        enable_key = spec.enable_key

        def _on_toggled(checked: bool) -> None:
            for w in child_widgets:
                w.setEnabled(checked)
            self._on_dyn_param_changed(enable_key, bool(checked))

        group.toggled.connect(_on_toggled)
        return group

    def _build_bool_widget(self, spec: ParamSpec, value: Any) -> QCheckBox:
        cb = QCheckBox()
        cb.setChecked(bool(value))
        if spec.tooltip:
            cb.setToolTip(spec.tooltip)
        key = spec.key
        cb.toggled.connect(lambda v, k=key: self._on_dyn_param_changed(k, bool(v)))
        return cb

    def _configure_roi_mode(self, descriptor: StageUIDescriptor) -> None:
        """Activate or clear ROI-drawing mode based on *descriptor*."""
        if descriptor.enable_roi_drawing and descriptor.roi_mode:
            self.start_roi_selection(descriptor.roi_mode)
        else:
            self.stop_roi_selection()

    # ------------------------------------------------------------------
    # Internal event routing — connects Qt signals to stage hooks
    # ------------------------------------------------------------------

    def _on_button_clicked(self, action: str) -> None:
        """Dispatch a button-bar click.

        - ``"confirm"`` → call the stage's ``confirm_calibration``; advance
          on success, or emit ``calibration_complete`` after the last stage.
        - ``"previous"`` → step back one stage.
        - ``"cancel"`` → emit ``calibration_cancelled``.
        - anything else → routed to the active stage's ``on_action``.
        """
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return

        if action == "confirm":
            ok = True
            if hasattr(stage, "confirm_calibration"):
                ok = bool(stage.confirm_calibration(self, self._ctx))
            if not ok:
                return
            self._advance()
            return

        if action == "previous":
            if self._current_idx > 0:
                self._current_idx -= 1
                self._show_current_stage()
            return

        if action == "cancel":
            self.calibration_cancelled.emit()
            return

        # Stage-specific action.
        if hasattr(stage, "on_action"):
            stage.on_action(self, self._ctx, action)

    def _advance(self) -> None:
        """Move to the next stage, or finish if the active stage was the last."""
        self._current_idx += 1
        if self._current_idx >= len(self._stages):
            self._finish()
        else:
            self._show_current_stage()

    def _finish(self) -> None:
        """Emit calibration_complete with the populated session."""
        if self._ctx is None or self._ctx.session is None:
            self.calibration_cancelled.emit()
            return
        self._ctx.session.clear_calibration_scratch()
        self.calibration_complete.emit(self._ctx.session)

    def _on_dyn_operator_combo_changed(self, index: int) -> None:
        """Operator selection changed — swap operator and re-render the stage."""
        if index < 0:
            return
        key = self._dyn_operator_combo.itemData(index)
        if not key:
            return
        stage = self._current_stage
        if stage is None:
            return
        from app.tools.scibit.core.registry import OperatorRegistry

        op_cls = OperatorRegistry().resolve_operator_class(str(key))
        if op_cls is None or op_cls is stage.assigned_operator_class:
            return
        stage.assigned_operator_class = op_cls
        self._refresh_current_stage()

    def _on_dyn_param_changed(self, key: str, value: Any) -> None:
        """Update the active stage and re-present after a parameter editor changes.

        Stage 0 preview transforms (rotation / invert / downscale) are
        applied to the displayed pixmap directly so the user sees them
        live; the stage's persisted value matches the editor.
        """
        # Live Stage-0 preview transforms.
        if key == "rotation_degrees":
            self._preview_rotation = float(value)
            self._apply_stage0_transform()
        elif key == "invert_colors":
            self._preview_invert = bool(value)
            self._apply_stage0_transform()
        elif key == "downscale_factor":
            try:
                pct = int(value)
            except (TypeError, ValueError):
                pct = 100
            self._preview_scale = max(10, min(100, pct)) / 100.0
            self._apply_stage0_transform()

        # Persist to the stage and re-present.
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        stage.parameters[key] = value
        self._re_present()

    def _on_roi_drawn(self, mode: str, rect: object) -> None:
        """Forward an ROI drawing event to the active stage."""
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        try:
            x, y, w, h = rect  # type: ignore[misc]
            bbox: BoundingBox = (int(x), int(y), int(w), int(h))
        except (TypeError, ValueError):
            _log.warning("Ignoring malformed ROI rect: %r", rect)
            return
        if hasattr(stage, "on_roi_drawn"):
            stage.on_roi_drawn(self, self._ctx, mode, bbox)

    def _on_scene_selection_changed(self) -> None:
        """Forward a scene-overlay click to the active stage.

        Resolves the selected ``QGraphicsRectItem`` back to the rect
        tuple it was registered with via :meth:`show_rect_overlay`, then
        invokes the stage's ``on_scene_selection`` hook with the rect as
        a typed :class:`BoundingBox`.
        """
        stage = self._current_stage
        if stage is None or self._ctx is None:
            return
        for item in self._scene.selectedItems():
            rect = self._overlay_rects.get(item)
            if rect is not None:
                if hasattr(stage, "on_scene_selection"):
                    stage.on_scene_selection(self, self._ctx, rect)
                return
