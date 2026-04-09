"""Shared pan/zoom image display widgets used by multiple tools."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QPushButton,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Pixels from left/right edge of the viewport that trigger arrow visibility.
ARROW_HOVER_MARGIN = 60


# ---------------------------------------------------------------------------
# Pan / zoom graphics view
# ---------------------------------------------------------------------------


class PanZoomView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom and click-drag pan.

    Parameters
    ----------
    scene : QGraphicsScene
        The scene to display.
    parent : QWidget | None
        Optional parent widget.
    """

    _ZOOM_FACTOR = 1.15

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit_item: QGraphicsPixmapItem | None = None

    def set_fit_item(self, item: QGraphicsPixmapItem) -> None:
        """Register the pixmap item to auto-fit whenever the view is resized."""
        self._fit_item = item

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Re-fit the registered item after Qt has updated the viewport size."""
        super().resizeEvent(event)
        if self._fit_item and not self._fit_item.pixmap().isNull():
            self.fitInView(self._fit_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Zoom in/out on scroll wheel."""
        factor = self._ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / self._ZOOM_FACTOR
        self.scale(factor, factor)


# ---------------------------------------------------------------------------
# Image area: graphics view + overlay labels + navigation arrows
# ---------------------------------------------------------------------------


class ImageArea(QWidget):
    """Container hosting a pan/zoom view with HUD overlays and nav arrows.

    The folder path and current filename are rendered as semi-transparent
    overlays in the top-left corner.  Left/right navigation arrow buttons
    appear when the cursor is within :data:`ARROW_HOVER_MARGIN` pixels of
    the respective edge.

    Signals
    -------
    navigate_left
        Emitted when the left arrow is clicked.
    navigate_right
        Emitted when the right arrow is clicked.
    """

    navigate_left = Signal()
    navigate_right = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        self._view = self._create_view()
        self._view.set_fit_item(self._pixmap_item)

        # Layout manages view geometry — avoids manual setGeometry timing issues.
        _layout = QVBoxLayout(self)
        _layout.setContentsMargins(0, 0, 0, 0)
        _layout.setSpacing(0)
        _layout.addWidget(self._view)

        # HUD overlay labels (children of this widget, drawn on top of the view)
        self._folder_label = self._make_overlay_label()
        self._filename_label = self._make_overlay_label()

        # Navigation arrow buttons
        self._left_btn = self._make_arrow_button("❮")
        self._right_btn = self._make_arrow_button("❯")
        self._left_btn.hide()
        self._right_btn.hide()
        self._left_btn.clicked.connect(self.navigate_left)
        self._right_btn.clicked.connect(self.navigate_right)

        self._arrows_enabled = False

        # Enable mouse tracking on the viewport to detect edge hover
        self._view.viewport().setMouseTracking(True)
        self._view.viewport().installEventFilter(self)

    # ------------------------------------------------------------------
    # Factory — subclasses may override to inject a custom view
    # ------------------------------------------------------------------

    def _create_view(self) -> PanZoomView:
        """Create the underlying graphics view.

        Override in subclasses to return a specialised :class:`PanZoomView`.
        """
        return PanZoomView(self._scene, self)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    def _make_overlay_label(self) -> QLabel:
        label = QLabel(self)
        label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 145); color: white;"
            " padding: 2px 6px; border-radius: 3px;"
        )
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.hide()
        return label

    def _make_arrow_button(self, text: str) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(0, 0, 0, 120); color: white;"
            "  font-size: 22px; border: none; border-radius: 4px; padding: 8px 6px;"
            "}"
            "QPushButton:hover { background-color: rgba(0, 0, 0, 210); }"
        )
        btn.setFixedWidth(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Display *pixmap* and fit it to the current viewport."""
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._fit_pixmap()

    def set_folder_text(self, text: str) -> None:
        """Update the folder path overlay."""
        self._folder_label.setText(text)
        self._folder_label.adjustSize()
        self._folder_label.show()
        self._reposition_overlays()

    def set_filename_text(self, text: str) -> None:
        """Update the filename overlay."""
        self._filename_label.setText(text)
        self._filename_label.adjustSize()
        self._filename_label.show()
        self._reposition_overlays()

    def set_arrows_enabled(self, enabled: bool) -> None:
        """Enable or suppress navigation arrows."""
        self._arrows_enabled = enabled
        if not enabled:
            self._left_btn.hide()
            self._right_btn.hide()

    def clear(self) -> None:
        """Remove the displayed image and hide all overlays."""
        self._pixmap_item.setPixmap(QPixmap())
        self._folder_label.hide()
        self._filename_label.hide()
        self.clear_overlays()

    def add_overlay_item(self, item: QGraphicsItem) -> None:
        """Add a graphics item as an overlay on the scene."""
        self._scene.addItem(item)

    def clear_overlays(self) -> None:
        """Remove all overlay graphics items (keeps the pixmap item)."""
        for item in list(self._scene.items()):
            if item is not self._pixmap_item:
                self._scene.removeItem(item)

    def scene(self) -> QGraphicsScene:
        """Return the underlying :class:`QGraphicsScene`."""
        return self._scene

    def view(self) -> PanZoomView:
        """Return the underlying :class:`PanZoomView`."""
        return self._view

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _fit_pixmap(self) -> None:
        if not self._pixmap_item.pixmap().isNull():
            self._view.resetTransform()
            self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_overlays()

    def _reposition_overlays(self) -> None:
        margin = 8
        y = margin
        for label in (self._folder_label, self._filename_label):
            if label.isVisible():
                label.move(margin, y)
                y += label.height() + 2

        btn_h = 60
        arrow_y = max(0, (self.height() - btn_h) // 2)
        self._left_btn.setFixedHeight(btn_h)
        self._right_btn.setFixedHeight(btn_h)
        self._left_btn.move(8, arrow_y)
        self._right_btn.move(self.width() - self._right_btn.width() - 8, arrow_y)

    # ------------------------------------------------------------------
    # Viewport event filter (mouse tracking for arrows)
    # ------------------------------------------------------------------

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._left_btn.hide()
        self._right_btn.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._view.viewport():
            if event.type() == QEvent.Type.MouseMove and self._arrows_enabled:
                x = event.position().x()
                vw = self._view.viewport().width()
                self._left_btn.setVisible(x < ARROW_HOVER_MARGIN)
                self._right_btn.setVisible(x > vw - ARROW_HOVER_MARGIN)
        return super().eventFilter(watched, event)
