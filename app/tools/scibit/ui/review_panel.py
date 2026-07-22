"""ReviewPanel — manual review sub-widget for individual batch results.

Shown on the right side of :class:`~app.tools.scibit.ui.ResultsWidget`'s
horizontal splitter when the user double-clicks a reviewable item.

Design:

- Image preview (top, expandable).
- Info label: filename / OCR text / confidence.
- Editable identifier field: auto-focused and fully selected on load so
  the user can immediately type a correction.
- Action buttons: Prev / Skip / Rename·Confirm / Next.

Key UX rules (spec Section 3.10):

- **Enter** in the text field → confirm (same as clicking Rename·Confirm).
- **Left/Right arrow** keys navigate the review queue when the text field
  has all its text selected (or when the text field does not have focus).
- Navigation emits :attr:`navigate` so :class:`ResultsWidget` can update
  the queue pointer and reload the panel.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.tools.scibit.core.pipeline import _preprocess_image
from app.tools.scibit.ui._image_utils import ndarray_to_pixmap

_log = logging.getLogger(__name__)


class _ZoomableImageView(QGraphicsView):
    """Read-only image view with mouse-wheel zoom and click-drag panning.

    A new image is fit into the viewport on load; the user can then scroll
    to zoom (anchored under the cursor) and drag to pan.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._needs_fit = False
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(0x1E, 0x1E, 0x1E))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Display *pixmap*, reset any prior zoom, and fit it into the view."""
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(0, 0, pixmap.width(), pixmap.height()))
        self.resetTransform()
        self._needs_fit = True
        QTimer.singleShot(0, self._fit)

    def show_message(self, text: str) -> None:
        """Clear the view and show a centred placeholder *text*."""
        self._scene.clear()
        self._pixmap_item = None
        self.resetTransform()
        item = self._scene.addText(text)
        item.setDefaultTextColor(QColor(200, 200, 200))
        self._scene.setSceneRect(item.boundingRect())

    def _fit(self) -> None:
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._needs_fit = False
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._needs_fit:
            self._fit()


class _IdentifierLineEdit(QLineEdit):
    """QLineEdit that converts Left/Right into queue navigation when fully selected.

    Emits :attr:`navigate_requested` instead of moving the cursor when all
    text is selected — a signal that the user wants to step through the
    review queue rather than edit the field.
    """

    navigate_requested = Signal(int)  # delta: -1 or +1

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if not event.modifiers() and self.text() and self.selectedText() == self.text():
                delta = -1 if event.key() == Qt.Key.Key_Left else 1
                self.navigate_requested.emit(delta)
                return
        super().keyPressEvent(event)


class ReviewPanel(QWidget):
    """Manual-review panel for a single batch result (spec Section 3.10).

    Parameters
    ----------
    parent : QWidget | None
        Optional Qt parent.

    Signals
    -------
    rename_applied(image_path: Path, new_identifier: str)
        Emitted when the user confirms (Enter or button).  The caller is
        responsible for performing the file copy and updating the list item.
    skipped(image_path: Path)
        Emitted when the user clicks Skip.
    navigate(delta: int)
        Emitted to request queue navigation.  ``delta`` is ``-1`` (Prev) or
        ``+1`` (Next).
    """

    rename_applied = Signal(object, str)  # (Path, new_identifier)
    skipped = Signal(object)  # Path
    navigate = Signal(int)  # delta: -1 or +1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_path: Path | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_result(
        self,
        image_path: Path,
        filename: str,
        ocr_text: str,
        confidence: float,
        *,
        has_prev: bool,
        has_next: bool,
        rotation_degrees: float = 0.0,
        invert_colors: bool = False,
        downscale_factor: float = 1.0,
    ) -> None:
        """Populate the panel with *result* data and focus the text field.

        Parameters
        ----------
        image_path : Path
            Full path to the original image file.
        filename : str
            Original filename shown in the info label.
        ocr_text : str
            Recognised identifier string (pre-fills the edit field).
        confidence : float
            OCR confidence (0–100) shown in the info label.
        has_prev : bool
            Whether a previous item exists in the review queue.
        has_next : bool
            Whether a next item exists in the review queue.
        rotation_degrees : float
            Stage-0 rotation (degrees) applied to the preview so it matches
            what the pipeline processed.
        invert_colors : bool
            Stage-0 colour inversion applied to the preview.
        downscale_factor : float
            Stage-0 downscale fraction (``1.0`` disables downscaling).
        """
        self._current_path = image_path

        # Image preview — apply Stage-0 transforms (rotation, invert,
        # downscale) so the reviewer sees exactly what the pipeline did.
        if image_path.exists():
            try:
                processed = _preprocess_image(
                    image_path,
                    rotation_degrees,
                    invert_colors,
                    downscale_factor,
                )
                self._preview.set_pixmap(ndarray_to_pixmap(processed))
            except Exception as exc:
                _log.warning("Could not render preview for '%s': %s", image_path, exc)
                self._preview.show_message("(preview unavailable)")
        else:
            self._preview.show_message("(image not found)")

        # Info label
        self._info_label.setText(
            f"<b>{filename}</b><br>"
            f"OCR: {ocr_text or '(empty)'} &nbsp;|&nbsp; "
            f"Confidence: {confidence:.1f}&thinsp;%"
        )

        # Text field — auto-focus + select all
        self._text_edit.setText(ocr_text or "")
        self._text_edit.selectAll()
        self._text_edit.setFocus()

        # Navigation buttons
        self._prev_btn.setEnabled(has_prev)
        self._next_btn.setEnabled(has_next)

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Image preview — zoomable / pannable view
        self._preview = _ZoomableImageView()
        self._preview.setMinimumHeight(180)
        layout.addWidget(self._preview, 1)

        # Info label
        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._info_label)

        # Identifier edit row
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Identifier:"))
        self._text_edit = _IdentifierLineEdit()
        self._text_edit.returnPressed.connect(self._on_confirm)
        self._text_edit.navigate_requested.connect(self.navigate)
        edit_row.addWidget(self._text_edit, 1)
        layout.addLayout(edit_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self._prev_btn = QPushButton("← Prev")
        self._skip_btn = QPushButton("Skip")
        self._confirm_btn = QPushButton("Rename / Confirm")
        self._confirm_btn.setDefault(True)
        self._next_btn = QPushButton("Next →")

        self._prev_btn.clicked.connect(lambda: self.navigate.emit(-1))
        self._skip_btn.clicked.connect(self._on_skip)
        self._confirm_btn.clicked.connect(self._on_confirm)
        self._next_btn.clicked.connect(lambda: self.navigate.emit(1))

        for btn in (self._prev_btn, self._skip_btn, self._confirm_btn, self._next_btn):
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_confirm(self) -> None:
        if self._current_path is None:
            return
        new_identifier = self._text_edit.text().strip()
        self.rename_applied.emit(self._current_path, new_identifier)

    def _on_skip(self) -> None:
        if self._current_path is None:
            return
        self.skipped.emit(self._current_path)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Navigate queue with Left/Right when text field is not focused."""
        if not self._text_edit.hasFocus():
            if event.key() == Qt.Key.Key_Left:
                self.navigate.emit(-1)
                return
            if event.key() == Qt.Key.Key_Right:
                self.navigate.emit(1)
                return
        super().keyPressEvent(event)
