"""Image Viewer base tool (REQ-HS-021)."""

from __future__ import annotations

import datetime
import enum
import logging
from abc import ABCMeta
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QIcon, QImageReader, QKeySequence, QPainter, QPixmap, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.plugin.base import IBaseToolPlugin

_logger = logging.getLogger("vi_toolbox.tools.image_viewer")

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif",
})

_ARROW_HOVER_MARGIN = 60  # px from left/right edge that triggers arrow visibility

_THUMB_SIZE = QSize(64, 48)
_THUMB_ROW_HEIGHT = 56

_CONFIG_KEY_COLUMNS = "image_list_columns"
_CONFIG_KEY_LIST_VISIBLE = "image_list_visible"
_DEFAULT_COLUMNS: list[str] = ["Thumbnail", "Name", "Date Modified"]


# ---------------------------------------------------------------------------
# Image list: column types
# ---------------------------------------------------------------------------


class _ColumnType(enum.Enum):
    THUMBNAIL = "Thumbnail"
    NAME = "Name"
    DATE_MODIFIED = "Date Modified"
    FILE_SIZE = "Size"
    RESOLUTION = "Resolution"
    FORMAT = "Format"


_ALL_COLUMNS: tuple[_ColumnType, ...] = tuple(_ColumnType)


# ---------------------------------------------------------------------------
# Async image info loader (thumbnail + resolution)
# ---------------------------------------------------------------------------


class _ImageInfoSignals(QObject):
    """Qt signals for :class:`_ImageInfoLoader` (must live on the main thread)."""

    # (row, path_str, thumbnail_pixmap, resolution_str)
    loaded = Signal(int, str, QPixmap, str)


class _ImageInfoLoader(QRunnable):
    """Background worker that reads a thumbnail and image resolution.

    Results are delivered via :attr:`signals` using a queued connection so
    they are applied safely on the main thread.
    """

    def __init__(self, row: int, path: Path) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = _ImageInfoSignals()
        self._row = row
        self._path = path

    def run(self) -> None:  # noqa: N802
        reader = QImageReader(str(self._path))
        orig = reader.size()
        res_str = f"{orig.width()} × {orig.height()}" if orig.isValid() else "—"
        reader.setScaledSize(_THUMB_SIZE)
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self.signals.loaded.emit(self._row, str(self._path), pixmap, res_str)


# ---------------------------------------------------------------------------
# Image list model
# ---------------------------------------------------------------------------


class _ImageListModel(QAbstractTableModel):
    """Table model backed by a list of image paths with configurable columns."""

    def __init__(self, columns: list[_ColumnType], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._images: list[Path] = []
        self._columns: list[_ColumnType] = list(columns)
        self._thumbnails: dict[int, QPixmap] = {}
        self._resolutions: dict[int, str] = {}
        self._stat_cache: dict[int, tuple[int, float]] = {}  # (size_bytes, mtime)

    # --- QAbstractTableModel interface ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._images)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._columns)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._columns):
                return self._columns[section].value
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # noqa: N802
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if not (0 <= row < len(self._images) and 0 <= col < len(self._columns)):
            return None
        path = self._images[row]
        col_type = self._columns[col]

        if col_type == _ColumnType.THUMBNAIL:
            if role == Qt.ItemDataRole.DecorationRole:
                px = self._thumbnails.get(row)
                if px and not px.isNull():
                    return QIcon(px)
            return None

        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if col_type == _ColumnType.NAME:
            return path.name

        if col_type in (_ColumnType.DATE_MODIFIED, _ColumnType.FILE_SIZE):
            if row not in self._stat_cache:
                try:
                    st = path.stat()
                    self._stat_cache[row] = (st.st_size, st.st_mtime)
                except OSError:
                    self._stat_cache[row] = (0, 0.0)
            sz, mt = self._stat_cache[row]
            if col_type == _ColumnType.DATE_MODIFIED:
                return datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M") if mt else "—"
            return f"{sz / (1024 * 1024):.1f} MB" if sz >= 1024 * 1024 else f"{sz / 1024:.1f} KB"

        if col_type == _ColumnType.FORMAT:
            return path.suffix.upper().lstrip(".")

        if col_type == _ColumnType.RESOLUTION:
            return self._resolutions.get(row, "…")

        return None

    # --- Mutation ---

    def set_images(self, images: list[Path]) -> None:
        """Replace the image list and clear all cached data."""
        self.beginResetModel()
        self._images = list(images)
        self._thumbnails.clear()
        self._resolutions.clear()
        self._stat_cache.clear()
        self.endResetModel()

    def set_columns(self, columns: list[_ColumnType]) -> None:
        """Replace the visible column set."""
        self.beginResetModel()
        self._columns = list(columns)
        self.endResetModel()

    def column_type_at(self, col: int) -> _ColumnType | None:
        """Return the :class:`_ColumnType` for column *col*, or ``None``."""
        return self._columns[col] if 0 <= col < len(self._columns) else None

    def receive_info(self, row: int, path_str: str, thumbnail: QPixmap, resolution: str) -> None:
        """Apply async-loaded thumbnail and resolution (called from main thread via queued signal)."""
        if row >= len(self._images) or str(self._images[row]) != path_str:
            return  # stale result — folder changed while loading
        self._thumbnails[row] = thumbnail
        self._resolutions[row] = resolution
        for c, ct in enumerate(self._columns):
            if ct == _ColumnType.THUMBNAIL:
                idx = self.index(row, c)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
            elif ct == _ColumnType.RESOLUTION:
                idx = self.index(row, c)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])


# ---------------------------------------------------------------------------
# Image list panel
# ---------------------------------------------------------------------------


class _ImageListPanel(QWidget):
    """Scrollable table listing all images in the current folder.

    Signals
    -------
    image_selected
        Emitted when the user clicks a row; carries the row index.
    """

    image_selected = Signal(int)

    def __init__(self, config_manager: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self._syncing = False

        columns = self._load_columns_config()
        self._model = _ImageListModel(columns, self)

        self._view = QTableView(self)
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setShowGrid(False)
        self._view.setIconSize(_THUMB_SIZE)
        self._view.verticalHeader().setVisible(False)
        self._view.verticalHeader().setDefaultSectionSize(_THUMB_ROW_HEIGHT)
        hdr = self._view.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._on_header_context_menu)

        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self.setMinimumWidth(120)

    # --- Public interface ---

    def set_images(self, images: list[Path]) -> None:
        """Populate the list with *images* and start async info loading."""
        self._model.set_images(images)
        QThreadPool.globalInstance().clear()  # cancel queued (not running) jobs from prior batch
        for row, path in enumerate(images):
            loader = _ImageInfoLoader(row, path)
            loader.signals.loaded.connect(self._model.receive_info)
            QThreadPool.globalInstance().start(loader)

    def set_current_index(self, index: int) -> None:
        """Sync selection to *index* without emitting :attr:`image_selected`."""
        self._syncing = True
        try:
            if 0 <= index < self._model.rowCount():
                self._view.selectRow(index)
                self._view.scrollTo(
                    self._model.index(index, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
        finally:
            self._syncing = False

    def clear(self) -> None:
        """Remove all entries from the list."""
        self._model.set_images([])

    # --- Config ---

    def _load_columns_config(self) -> list[_ColumnType]:
        cfg = self._config_manager.get_tool_config("Image Viewer")
        names: list[str] = cfg.get(_CONFIG_KEY_COLUMNS, _DEFAULT_COLUMNS)
        name_map = {ct.value: ct for ct in _ColumnType}
        result = [name_map[n] for n in names if n in name_map]
        return result or [_ColumnType.NAME]

    def _save_columns_config(self) -> None:
        cfg = self._config_manager.get_tool_config("Image Viewer")
        cfg[_CONFIG_KEY_COLUMNS] = [ct.value for ct in self._model._columns]
        self._config_manager.set_tool_config("Image Viewer", cfg)
        self._config_manager.save("Image Viewer")

    # --- Slots ---

    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        rows = self._view.selectionModel().selectedRows()
        if rows:
            self.image_selected.emit(rows[0].row())

    def _on_header_context_menu(self, pos: object) -> None:
        menu = QMenu(self)
        current = set(self._model._columns)
        for col_type in _ALL_COLUMNS:
            act = menu.addAction(col_type.value)
            act.setCheckable(True)
            act.setChecked(col_type in current)
        action = menu.exec(self._view.horizontalHeader().mapToGlobal(pos))
        if action is None:
            return
        toggled = next((ct for ct in _ALL_COLUMNS if ct.value == action.text()), None)
        if toggled is None:
            return
        new_cols = list(self._model._columns)
        if toggled in current:
            if len(new_cols) <= 1:
                return  # always keep at least one column
            new_cols.remove(toggled)
        else:
            new_cols.append(toggled)
        self._model.set_columns(new_cols)
        self._save_columns_config()


# ---------------------------------------------------------------------------
# Pan / zoom graphics view
# ---------------------------------------------------------------------------


class _PanZoomView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom and click-drag pan."""

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

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Zoom in/out on scroll wheel."""
        factor = self._ZOOM_FACTOR if event.angleDelta().y() > 0 else 1.0 / self._ZOOM_FACTOR
        self.scale(factor, factor)


# ---------------------------------------------------------------------------
# Image area: graphics view + overlay labels + navigation arrows
# ---------------------------------------------------------------------------


class _ImageArea(QWidget):
    """Container widget hosting the pan/zoom view with HUD overlays and nav arrows.

    The folder path and current filename are rendered as semi-transparent
    overlays in the top-left corner.  Left/right navigation arrow buttons
    appear when the cursor is within :data:`_ARROW_HOVER_MARGIN` pixels of
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

        self._view = _PanZoomView(self._scene, self)

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

    def _fit_pixmap(self) -> None:
        """Fit the current pixmap to the viewport (no-op if no pixmap loaded)."""
        if not self._pixmap_item.pixmap().isNull():
            self._view.resetTransform()
            self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

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
        """Enable or suppress navigation arrows (disable for single-image folders)."""
        self._arrows_enabled = enabled
        if not enabled:
            self._left_btn.hide()
            self._right_btn.hide()

    def clear(self) -> None:
        """Remove the displayed image and hide all overlays."""
        self._pixmap_item.setPixmap(QPixmap())
        self._folder_label.hide()
        self._filename_label.hide()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._view.setGeometry(self.rect())
        self._fit_pixmap()
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
        """Hide navigation arrows when the cursor leaves the entire widget."""
        super().leaveEvent(event)
        self._left_btn.hide()
        self._right_btn.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._view.viewport():
            if event.type() == QEvent.Type.MouseMove and self._arrows_enabled:
                x = event.position().x()
                vw = self._view.viewport().width()
                self._left_btn.setVisible(x < _ARROW_HOVER_MARGIN)
                self._right_btn.setVisible(x > vw - _ARROW_HOVER_MARGIN)
        return super().eventFilter(watched, event)


# ---------------------------------------------------------------------------
# Collapsible metadata panel
# ---------------------------------------------------------------------------


class _MetadataPanel(QWidget):
    """Collapsible panel showing per-image metadata with a rename action.

    Signals
    -------
    rename_requested
        Emitted when the user clicks the Rename button.
    """

    rename_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toggle button
        self._toggle_btn = QPushButton("▶   Metadata")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet("QPushButton { text-align: left; padding: 4px 6px; }")
        self._toggle_btn.toggled.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        # Content frame (hidden by default)
        self._content = QFrame(self)
        self._content.setFrameShape(QFrame.Shape.StyledPanel)
        self._content.setVisible(False)

        form = QFormLayout(self._content)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Filename row: value label + Rename button
        fn_row = QWidget()
        fn_layout = QHBoxLayout(fn_row)
        fn_layout.setContentsMargins(0, 0, 0, 0)
        fn_layout.setSpacing(6)
        self._filename_val = QLabel()
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setFixedWidth(70)
        self._rename_btn.clicked.connect(self.rename_requested)
        fn_layout.addWidget(self._filename_val)
        fn_layout.addWidget(self._rename_btn)
        fn_layout.addStretch()
        form.addRow("Filename:", fn_row)

        self._resolution_val = QLabel()
        form.addRow("Resolution:", self._resolution_val)

        self._size_val = QLabel()
        form.addRow("File Size:", self._size_val)

        self._format_val = QLabel()
        form.addRow("Format:", self._format_val)

        layout.addWidget(self._content)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update_metadata(self, path: Path) -> None:
        """Populate all rows from *path*."""
        self._filename_val.setText(path.name)

        reader = QImageReader(str(path))
        size = reader.size()
        self._resolution_val.setText(
            f"{size.width()} × {size.height()} px" if size.isValid() else "—"
        )

        try:
            raw = path.stat().st_size
            self._size_val.setText(
                f"{raw / (1024 * 1024):.1f} MB" if raw >= 1024 * 1024 else f"{raw / 1024:.1f} KB"
            )
        except OSError:
            self._size_val.setText("—")

        fmt = reader.format().data().decode(errors="replace").upper()
        self._format_val.setText(fmt or "—")

    def clear(self) -> None:
        """Reset all value labels to a placeholder dash."""
        for val in (self._filename_val, self._resolution_val, self._size_val, self._format_val):
            val.setText("—")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_toggle(self, checked: bool) -> None:
        self._toggle_btn.setText("▼   Metadata" if checked else "▶   Metadata")
        self._content.setVisible(checked)


# ---------------------------------------------------------------------------
# Widget metaclass (resolves PySide6 / ABCMeta conflict)
# ---------------------------------------------------------------------------


class _ImageViewerMeta(type(QWidget), ABCMeta):
    pass


# ---------------------------------------------------------------------------
# ImageViewer
# ---------------------------------------------------------------------------


class ImageViewer(QWidget, IBaseToolPlugin, metaclass=_ImageViewerMeta):
    """Zoomable image viewer with folder navigation and metadata panel (REQ-HS-021).

    Can be opened standalone or driven externally by any tool that calls
    :meth:`open_from_path` with a file or folder path.

    Parameters
    ----------
    config_manager : ConfigManager
        Application-wide config manager used to persist UI preferences
        (visible list columns, panel visibility).
    parent : QWidget | None
        Optional parent widget.
    """

    name: ClassVar[str] = "Image Viewer"
    description: ClassVar[str] = "Browse and inspect images from a folder."
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    logger_name: ClassVar[str] = "vi_toolbox.tools.image_viewer"
    auto_open_on_startup: ClassVar[bool] = False
    allow_multiple_instances: ClassVar[bool] = True
    closable: ClassVar[bool] = True
    handled_path_extensions: ClassVar[frozenset[str]] = _SUPPORTED_EXTENSIONS
    handles_folders: ClassVar[bool] = True

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._config_manager = config_manager
        self._folder: Path | None = None
        self._images: list[Path] = []
        self._current_index: int = -1
        # Falls back to the module-level logger until _assign_instance_id is called.
        self._logger = _logger

        self._setup_ui()

    # ------------------------------------------------------------------
    # IBaseToolPlugin interface
    # ------------------------------------------------------------------

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return *self* as the dock widget content.

        Parameters
        ----------
        parent : QWidget | None
            Optional parent to re-assign.

        Returns
        -------
        QWidget
            This widget instance.
        """
        self.setParent(parent)
        return self

    def _assign_instance_id(self, instance_id: int) -> None:
        """Set up a per-instance logger so multiple viewers are distinguishable.

        Parameters
        ----------
        instance_id : int
            Positive integer assigned by MainWindow; ``0`` is never used for
            ImageViewer since ``allow_multiple_instances`` is ``True``.
        """
        super()._assign_instance_id(instance_id)
        self._logger = logging.getLogger(f"{self.logger_name}.{instance_id}")

    def accepts_path(self, path: Path) -> bool:
        """Return ``True`` for image files and directories.

        Parameters
        ----------
        path : Path
            File or directory to test.

        Returns
        -------
        bool
            ``True`` if *path* is a directory or a supported image format.
        """
        if path.is_dir():
            return True
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def open_from_path(self, path: Path) -> None:
        """Load an image file or folder into the viewer.

        Parameters
        ----------
        path : Path
            If a file, only that single image is shown (no folder navigation).
            If a directory, all images in the folder are loaded with navigation.
        """
        if path.is_file():
            self._load_single(path)
        elif path.is_dir():
            self._load_folder(path)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Top bar: list toggle + read-only folder path + browse button
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self._list_toggle_btn = QPushButton("☰")
        self._list_toggle_btn.setFixedWidth(30)
        self._list_toggle_btn.setCheckable(True)
        self._list_toggle_btn.setToolTip("Toggle image list panel")
        self._list_toggle_btn.toggled.connect(self._on_list_toggle)
        top_bar.addWidget(self._list_toggle_btn)

        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("No folder selected")
        top_bar.addWidget(self._folder_edit, stretch=1)

        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedWidth(80)
        self._browse_btn.clicked.connect(self._on_browse)
        top_bar.addWidget(self._browse_btn)
        layout.addLayout(top_bar)

        # Content: horizontal splitter — image list panel (left) + image area (right)
        self._content_splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self._image_list_panel = _ImageListPanel(self._config_manager, self)
        self._image_list_panel.image_selected.connect(self._on_list_image_selected)
        self._content_splitter.addWidget(self._image_list_panel)

        self._image_area = _ImageArea(self)
        self._image_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_area.navigate_left.connect(self._navigate_left)
        self._image_area.navigate_right.connect(self._navigate_right)
        self._content_splitter.addWidget(self._image_area)

        self._content_splitter.setStretchFactor(0, 0)
        self._content_splitter.setStretchFactor(1, 1)
        layout.addWidget(self._content_splitter, stretch=1)

        # Restore list panel visibility from config
        cfg = self._config_manager.get_tool_config("Image Viewer")
        list_visible: bool = cfg.get(_CONFIG_KEY_LIST_VISIBLE, False)
        self._image_list_panel.setVisible(list_visible)
        self._list_toggle_btn.setChecked(list_visible)

        # Metadata panel
        self._metadata_panel = _MetadataPanel(self)
        self._metadata_panel.rename_requested.connect(self._on_rename)
        layout.addWidget(self._metadata_panel)

        # Arrow-key navigation works regardless of which child widget has focus.
        for key, slot in (
            (Qt.Key.Key_Left, self._navigate_left),
            (Qt.Key.Key_Right, self._navigate_right),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    # ------------------------------------------------------------------
    # Image loading & navigation
    # ------------------------------------------------------------------

    def _load_single(self, path: Path) -> None:
        """Display *path* as a standalone image — no folder navigation."""
        self._folder = path.parent
        self._images = [path]
        self._current_index = 0
        self._image_area.set_arrows_enabled(False)
        self._folder_edit.setText(str(self._folder))
        self._image_list_panel.set_images(self._images)
        self._show_current()

    def _load_folder(self, folder: Path, initial_file: Path | None = None) -> None:
        self._folder = folder
        self._images = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
        )

        self._image_list_panel.set_images(self._images)

        if not self._images:
            self._folder_edit.setText(str(folder))
            self._image_area.clear()
            self._metadata_panel.clear()
            self._image_area.set_arrows_enabled(False)
            self._logger.debug("No supported images found in: %s", folder)
            return

        if initial_file and initial_file in self._images:
            self._current_index = self._images.index(initial_file)
        else:
            self._current_index = 0

        self._image_area.set_arrows_enabled(len(self._images) > 1)
        self._show_current()

    def _show_current(self) -> None:
        if not self._images or self._current_index < 0:
            return
        path = self._images[self._current_index]
        # Qt's default allocation limit rejects large uncompressed images; disable it.
        QImageReader.setAllocationLimit(0)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._logger.warning("Failed to load image: %s", path)
            return

        self._folder_edit.setText(str(self._folder))
        self._image_area.set_pixmap(pixmap)
        self._image_area.set_folder_text(str(self._folder))
        self._image_area.set_filename_text(path.name)
        self._metadata_panel.update_metadata(path)
        self._image_list_panel.set_current_index(self._current_index)
        self._logger.debug(
            "Showing image %d/%d: %s", self._current_index + 1, len(self._images), path.name
        )

    def _navigate_left(self) -> None:
        if self._images:
            self._current_index = (self._current_index - 1) % len(self._images)
            self._show_current()

    def _navigate_right(self) -> None:
        if self._images:
            self._current_index = (self._current_index + 1) % len(self._images)
            self._show_current()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_list_toggle(self, checked: bool) -> None:
        self._image_list_panel.setVisible(checked)
        if checked and self._content_splitter.sizes()[0] == 0:
            total = sum(self._content_splitter.sizes())
            self._content_splitter.setSizes([250, max(0, total - 250)])
        cfg = self._config_manager.get_tool_config("Image Viewer")
        cfg[_CONFIG_KEY_LIST_VISIBLE] = checked
        self._config_manager.set_tool_config("Image Viewer", cfg)
        self._config_manager.save("Image Viewer")

    def _on_list_image_selected(self, row: int) -> None:
        if 0 <= row < len(self._images):
            self._current_index = row
            self._show_current()

    def _on_browse(self) -> None:
        menu = QMenu(self)
        act_file = menu.addAction("Open File…")
        act_folder = menu.addAction("Open Folder…")
        pos = self._browse_btn.mapToGlobal(self._browse_btn.rect().bottomLeft())
        action = menu.exec(pos)

        if action is act_file:
            exts = " ".join(f"*{e}" for e in sorted(_SUPPORTED_EXTENSIONS))
            path_str, _ = QFileDialog.getOpenFileName(
                self, "Open Image", str(self._folder or ""), f"Images ({exts})"
            )
            if path_str:
                self._load_single(Path(path_str))
        elif action is act_folder:
            folder_str = QFileDialog.getExistingDirectory(
                self, "Open Folder", str(self._folder or "")
            )
            if folder_str:
                self.open_from_path(Path(folder_str))

    def _on_rename(self) -> None:
        if not self._images or self._current_index < 0:
            return
        current = self._images[self._current_index]

        new_stem, ok = QInputDialog.getText(
            self,
            "Rename Image",
            "New filename (without extension):",
            text=current.stem,
        )
        if not ok or not new_stem.strip() or new_stem.strip() == current.stem:
            return

        new_stem = new_stem.strip()
        new_name = new_stem + current.suffix
        new_path = current.parent / new_name

        reply = QMessageBox.question(
            self,
            "Confirm Rename",
            f"Rename\n\n  {current.name}\n\nto\n\n  {new_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            current.rename(new_path)
            self._images[self._current_index] = new_path
            self._show_current()
            self._logger.debug("Renamed '%s' → '%s'", current.name, new_name)
        except OSError as exc:
            self._logger.error("Failed to rename '%s': %s", current, exc)
            QMessageBox.warning(self, "Rename Failed", f"Could not rename file:\n\n{exc}")
